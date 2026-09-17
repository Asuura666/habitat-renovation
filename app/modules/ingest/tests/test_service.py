"""Tests unitaires de `app/modules/ingest/service.py` (base de test réelle,
`docs_dir` temporaire, fausse `Messagerie`). Toutes les valeurs (identifiants,
noms) sont inventées."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ingest import service as ingest_service
from app.modules.ingest.models import Document, TelegramUpdate, Utilisateur
from app.modules.ingest.service import enregistrer_update, traiter_fichier
from app.modules.messaging.base import FichierEntrant, FichierTelecharge

pytestmark = [pytest.mark.anyio, pytest.mark.db]

NUMERO_BL_INVENTE = "L209900000123"


async def _ocr_avec_numero_bl(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (T6b) : réponse portant un numéro de BL détectable, utilisé
    par les tests qui ne portent pas sur l'OCR lui-même (le document doit
    rester `recu`)."""
    return {"pages": [{"markdown": f"LIVRAISON N°{NUMERO_BL_INVENTE}"}]}


async def _ocr_sans_numero_bl(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (T6b) : réponse sans motif de numéro de BL reconnaissable."""
    return {"pages": [{"markdown": "texte inventé sans motif de BL"}]}


async def _ocr_en_echec(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (T6b) : simule un échec complet de l'appel OCR."""
    raise RuntimeError("échec factice de l'OCR")


async def _ocr_jamais_appele(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (T6b) : prouve que l'OCR n'est jamais appelé quand le
    document n'a pas pu être enregistré (téléchargement ou base en échec)."""
    raise AssertionError("l'OCR ne doit pas être appelé dans ce scénario")


async def _ocr_reponse_liste(contenu: bytes, mime: str) -> Any:
    """Faux OCR (correction tour 1/5) : réponse 200 mal formée, une liste au
    lieu d'un objet — `texte_ocr` appellerait `.get` sur une `list` et
    lèverait `AttributeError` sans la protection ajoutée dans
    `_executer_ocr`."""
    return ["pas", "un", "dict"]


async def _ocr_reponse_sans_pages(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (correction tour 1/5) : objet JSON valide mais sans clé
    `pages` du tout — traité comme une réponse mal formée (pas comme une
    réponse valide sans numéro détecté)."""
    return {"quelque_chose_dautre": True}


async def _ocr_reponse_pages_non_liste(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (correction tour 1/5) : `pages` présent mais pas une liste."""
    return {"pages": "pas une liste"}


class MessagerieFactice:
    """Fausse `Messagerie` (aucune dépendance réseau réelle)."""

    def __init__(self, *, echoue_telechargement: bool = False) -> None:
        self.echoue_telechargement = echoue_telechargement
        self.reponses: list[tuple[int, int, str]] = []

    async def telecharger(self, fichier: FichierEntrant) -> FichierTelecharge:
        if self.echoue_telechargement:
            raise RuntimeError("échec factice de téléchargement")
        return FichierTelecharge(contenu=b"contenu-invente-du-fichier", extension="jpg")

    async def repondre(self, chat_id: int, message_id: int, texte: str) -> None:
        self.reponses.append((chat_id, message_id, texte))


def _entrant(update_id: int = 1, expediteur_id: int | None = None) -> FichierEntrant:
    return FichierEntrant(
        update_id=update_id,
        chat_id=100 + update_id,
        message_id=200 + update_id,
        expediteur_id=expediteur_id,
        fichier_id="fichier-invente",
        mime_type=None,
        nom_fichier=None,
        compresse=True,
    )


async def test_enregistrer_update_nouveau_renvoie_true(
    db_session: AsyncSession,
) -> None:
    assert await enregistrer_update(db_session, 1) is True


async def test_enregistrer_update_deja_vu_renvoie_false(
    db_session: AsyncSession,
) -> None:
    assert await enregistrer_update(db_session, 2) is True
    assert await enregistrer_update(db_session, 2) is False

    updates = (
        (
            await db_session.execute(
                select(TelegramUpdate).where(TelegramUpdate.update_id == 2)
            )
        )
        .scalars()
        .all()
    )
    assert len(updates) == 1


async def test_enregistrer_update_concurrent_un_seul_gagne(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    """Dédoublonnage concurrent : deux requêtes simultanées pour le même
    `update_id` ne doivent jamais toutes les deux recevoir `True`."""

    async def _tenter() -> bool:
        async with sessions_test() as session:
            return await enregistrer_update(session, 777)

    resultats = await asyncio.gather(_tenter(), _tenter())

    assert sorted(resultats) == [False, True]
    updates = (
        (
            await db_session.execute(
                select(TelegramUpdate).where(TelegramUpdate.update_id == 777)
            )
        )
        .scalars()
        .all()
    )
    assert len(updates) == 1


async def test_traiter_fichier_ecrit_le_fichier_le_document_et_repond(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=10)

    await traiter_fichier(
        entrant, messagerie, sessions_test, tmp_path, _ocr_avec_numero_bl
    )

    documents = (await db_session.execute(select(Document))).scalars().all()
    assert len(documents) == 1
    document = documents[0]
    assert document.type == "bl"
    assert document.source == "telegram"
    assert document.statut == "recu"
    assert document.telegram_message_id == entrant.message_id
    assert document.deposant_id is None
    assert document.numero == NUMERO_BL_INVENTE

    fichiers = list(tmp_path.glob("*.jpg"))
    assert len(fichiers) == 1
    assert not list(tmp_path.glob("*.tmp"))
    assert fichiers[0].read_bytes() == b"contenu-invente-du-fichier"
    assert document.fichier_path == str(fichiers[0])

    assert messagerie.reponses == [(entrant.chat_id, entrant.message_id, "reçu")]


async def test_traiter_fichier_deposant_rempli_si_utilisateur_connu(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    utilisateur = Utilisateur(
        email="agent.invente@example.invalid", role="agent", telegram_user_id=4242
    )
    db_session.add(utilisateur)
    await db_session.commit()

    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=11, expediteur_id=4242)

    await traiter_fichier(
        entrant, messagerie, sessions_test, tmp_path, _ocr_avec_numero_bl
    )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.deposant_id == utilisateur.id


async def test_traiter_fichier_deposant_null_si_utilisateur_inconnu(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=12, expediteur_id=999999)

    await traiter_fichier(
        entrant, messagerie, sessions_test, tmp_path, _ocr_avec_numero_bl
    )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.deposant_id is None


async def test_traiter_fichier_echec_telechargement_necrit_rien(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    messagerie = MessagerieFactice(echoue_telechargement=True)
    entrant = _entrant(update_id=13)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant, messagerie, sessions_test, tmp_path, _ocr_jamais_appele
        )

    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []
    assert messagerie.reponses == []
    assert str(entrant.update_id) in caplog.text
    assert "contenu-invente-du-fichier" not in caplog.text


async def test_traiter_fichier_echec_base_supprime_le_fichier_ecrit(
    monkeypatch: pytest.MonkeyPatch,
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Simule un échec base après téléchargement/écriture réussis (FK vers
    un utilisateur inexistant) : aucun fichier ne doit rester."""

    async def _deposant_bidon(
        session: AsyncSession, telegram_user_id: int | None
    ) -> uuid.UUID:
        return uuid.uuid4()

    monkeypatch.setattr(ingest_service, "_resoudre_deposant", _deposant_bidon)

    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=14)

    await traiter_fichier(
        entrant, messagerie, sessions_test, tmp_path, _ocr_jamais_appele
    )

    assert list(tmp_path.iterdir()) == []
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert messagerie.reponses == []


# --------------------------------------------------------------------------
# OCR (T6b) : numéro détecté, non détecté, échec de l'appel OCR lui-même.
# Le dépôt du fichier est déjà acquis avant l'OCR (décision du contrôleur
# T6b) : dans les trois cas, le document existe et la réponse « reçu » part.
# --------------------------------------------------------------------------


async def test_traiter_fichier_numero_bl_detecte_remplit_numero_et_type(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=20)

    await traiter_fichier(
        entrant, messagerie, sessions_test, tmp_path, _ocr_avec_numero_bl
    )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.numero == NUMERO_BL_INVENTE
    assert document.type == "bl"
    assert document.statut == "recu"
    assert document.ocr_brut == {
        "pages": [{"markdown": f"LIVRAISON N°{NUMERO_BL_INVENTE}"}]
    }
    assert messagerie.reponses == [(entrant.chat_id, entrant.message_id, "reçu")]


async def test_traiter_fichier_numero_bl_non_detecte_statut_a_verifier(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=21)

    await traiter_fichier(
        entrant, messagerie, sessions_test, tmp_path, _ocr_sans_numero_bl
    )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.numero is None
    assert document.statut == "a_verifier"
    assert document.ocr_brut == {
        "pages": [{"markdown": "texte inventé sans motif de BL"}]
    }
    # Le dépôt reste acquis : la réponse « reçu » part malgré l'absence de
    # numéro détecté.
    assert messagerie.reponses == [(entrant.chat_id, entrant.message_id, "reçu")]


async def test_traiter_fichier_ocr_en_echec_document_garde_recu_sans_numero(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=22)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant, messagerie, sessions_test, tmp_path, _ocr_en_echec
        )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.statut == "recu"
    assert document.numero is None
    assert document.ocr_brut is None
    # Le dépôt est acquis quoi qu'il arrive : la réponse « reçu » part même
    # si l'OCR échoue complètement.
    assert messagerie.reponses == [(entrant.chat_id, entrant.message_id, "reçu")]
    assert str(entrant.update_id) in caplog.text
    assert "contenu-invente-du-fichier" not in caplog.text


# --------------------------------------------------------------------------
# Correction tour 1/5 : une réponse OCR 200 mal formée ne doit jamais faire
# remonter d'exception jusqu'à `traiter_fichier` (la réponse « reçu » doit
# toujours partir). Les trois formes constatées par le relecteur : liste au
# lieu d'un objet, objet sans `pages`, `pages` présent mais pas une liste.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ocr_factice",
    [_ocr_reponse_liste, _ocr_reponse_sans_pages, _ocr_reponse_pages_non_liste],
    ids=["reponse-liste", "objet-sans-pages", "pages-non-liste"],
)
async def test_traiter_fichier_reponse_ocr_malformee_document_garde_recu(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    ocr_factice: Any,
) -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=30)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(entrant, messagerie, sessions_test, tmp_path, ocr_factice)

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.statut == "recu"
    assert document.numero is None
    assert document.ocr_brut is None
    # Le dépôt est acquis quoi qu'il arrive, y compris pour une réponse OCR
    # mal formée : la réponse « reçu » part quand même.
    assert messagerie.reponses == [(entrant.chat_id, entrant.message_id, "reçu")]
    assert str(entrant.update_id) in caplog.text
    assert "contenu-invente-du-fichier" not in caplog.text
