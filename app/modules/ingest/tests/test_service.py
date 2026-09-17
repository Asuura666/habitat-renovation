"""Tests unitaires de `app/modules/ingest/service.py` (base de test réelle,
`docs_dir` temporaire, fausse `Messagerie`). Toutes les valeurs (identifiants,
noms) sont inventées."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ingest import service as ingest_service
from app.modules.ingest.models import Document, TelegramUpdate, Utilisateur
from app.modules.ingest.service import (
    Deposant,
    enregistrer_update,
    signaler_expediteur_inconnu,
    traiter_fichier,
    utilisateur_rattache,
)
from app.modules.messaging.base import FichierEntrant, FichierTelecharge

pytestmark = [pytest.mark.anyio, pytest.mark.db]

NUMERO_BL_INVENTE = "L209900000123"
CHAT_SUPERVISION_INVENTE = 999999

_RE_LIGNE_SUPERVISION = re.compile(
    r"^Document n° (?P<numero_interne>\d+) · BL (?P<bl>.+) · fournisseur — · "
    r"chantier — · (?P<deposant>.+) · (?P<heure>\d{2}:\d{2}) · (?P<statut>\w+)$"
)


def _parse_ligne_supervision(texte: str) -> re.Match[str]:
    """Valide qu'une ligne de supervision respecte le format L2-D8, sans
    figer l'heure (dépendante de l'exécution)."""
    match = _RE_LIGNE_SUPERVISION.match(texte)
    assert match is not None, f"ligne de supervision inattendue : {texte!r}"
    return match


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
    document n'a pas pu être enregistré (téléchargement, écriture ou base en
    échec)."""
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

    def __init__(
        self,
        *,
        echoue_telechargement: bool = False,
        echoue_envoyer: bool = False,
        echoue_repondre: bool = False,
    ) -> None:
        self.echoue_telechargement = echoue_telechargement
        self.echoue_envoyer = echoue_envoyer
        self.echoue_repondre = echoue_repondre
        self.reponses: list[tuple[int, int, str]] = []
        self.supervisions: list[tuple[int, str]] = []

    async def telecharger(self, fichier: FichierEntrant) -> FichierTelecharge:
        if self.echoue_telechargement:
            raise RuntimeError("échec factice de téléchargement")
        return FichierTelecharge(contenu=b"contenu-invente-du-fichier", extension="jpg")

    async def repondre(self, chat_id: int, message_id: int, texte: str) -> None:
        if self.echoue_repondre:
            raise RuntimeError("échec factice de réponse")
        self.reponses.append((chat_id, message_id, texte))

    async def envoyer(self, chat_id: int, texte: str) -> None:
        if self.echoue_envoyer:
            raise RuntimeError("échec factice d'envoi de supervision")
        self.supervisions.append((chat_id, texte))


def _entrant(
    update_id: int = 1,
    expediteur_id: int | None = None,
    expediteur_nom: str | None = None,
) -> FichierEntrant:
    return FichierEntrant(
        update_id=update_id,
        chat_id=100 + update_id,
        message_id=200 + update_id,
        expediteur_id=expediteur_id,
        fichier_id="fichier-invente",
        mime_type=None,
        nom_fichier=None,
        compresse=True,
        expediteur_nom=expediteur_nom,
    )


async def _creer_utilisateur(
    db_session: AsyncSession,
    *,
    telegram_user_id: int,
    actif: bool = True,
    nom: str | None = "Agent Testeur",
    email: str | None = None,
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email or f"agent.{telegram_user_id}@example.invalid",
        role="agent",
        telegram_user_id=telegram_user_id,
        nom=nom,
        is_active=actif,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


def _deposant_depuis(utilisateur: Utilisateur) -> Deposant:
    return Deposant(
        id=utilisateur.id, nom_affichage=utilisateur.nom or utilisateur.email
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


# --------------------------------------------------------------------------
# `utilisateur_rattache` (L2-T2) : liste blanche, L2-D7. Contrairement à la
# décision D15 du lot 1 (tout `telegram_user_id` connu, actif ou non,
# remplissait `deposant_id`), un compte désactivé est désormais traité comme
# un expéditeur inconnu.
# --------------------------------------------------------------------------


async def test_utilisateur_rattache_actif_renvoie_le_deposant(
    db_session: AsyncSession,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=5001)

    resultat = await utilisateur_rattache(db_session, 5001)

    assert resultat == Deposant(id=utilisateur.id, nom_affichage="Agent Testeur")


async def test_utilisateur_rattache_inactif_traite_comme_inconnu(
    db_session: AsyncSession,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=5002, actif=False)

    assert await utilisateur_rattache(db_session, 5002) is None


async def test_utilisateur_rattache_telegram_user_id_inconnu_renvoie_none(
    db_session: AsyncSession,
) -> None:
    assert await utilisateur_rattache(db_session, 5_000_000) is None


async def test_utilisateur_rattache_telegram_user_id_none_renvoie_none(
    db_session: AsyncSession,
) -> None:
    assert await utilisateur_rattache(db_session, None) is None


async def test_utilisateur_rattache_sans_nom_utilise_lemail(
    db_session: AsyncSession,
) -> None:
    utilisateur = await _creer_utilisateur(
        db_session, telegram_user_id=5003, nom=None, email="sans-nom@example.invalid"
    )

    resultat = await utilisateur_rattache(db_session, 5003)

    assert resultat == Deposant(
        id=utilisateur.id, nom_affichage="sans-nom@example.invalid"
    )


# --------------------------------------------------------------------------
# `signaler_expediteur_inconnu` (L2-D7) : notification de supervision, sans
# écriture ni téléchargement.
# --------------------------------------------------------------------------


async def test_signaler_expediteur_inconnu_envoie_id_et_nom_en_supervision() -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=40, expediteur_id=777, expediteur_nom="Curieux")

    await signaler_expediteur_inconnu(entrant, messagerie, CHAT_SUPERVISION_INVENTE)

    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    assert "777" in texte
    assert "Curieux" in texte
    assert messagerie.reponses == []


async def test_signaler_expediteur_inconnu_sans_nom_ne_leve_pas() -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=41, expediteur_id=778, expediteur_nom=None)

    await signaler_expediteur_inconnu(entrant, messagerie, CHAT_SUPERVISION_INVENTE)

    assert len(messagerie.supervisions) == 1
    assert "778" in messagerie.supervisions[0][1]


async def test_signaler_expediteur_inconnu_echec_envoi_journalise_sans_lever(
    caplog: pytest.LogCaptureFixture,
) -> None:
    messagerie = MessagerieFactice(echoue_envoyer=True)
    entrant = _entrant(update_id=42, expediteur_id=779)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await signaler_expediteur_inconnu(entrant, messagerie, CHAT_SUPERVISION_INVENTE)

    assert messagerie.supervisions == []
    assert str(entrant.update_id) in caplog.text


# --------------------------------------------------------------------------
# `traiter_fichier` : `deposant` est désormais toujours renseigné (L2-T2),
# résolu par le routeur via `utilisateur_rattache` avant la mise en tâche de
# fond — plus jamais `NULL` (contrairement au lot 1, décision D15).
# --------------------------------------------------------------------------


async def test_traiter_fichier_ecrit_le_fichier_le_document_et_repond(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9010)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=10)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_avec_numero_bl,
        deposant,
        CHAT_SUPERVISION_INVENTE,
    )

    documents = (await db_session.execute(select(Document))).scalars().all()
    assert len(documents) == 1
    document = documents[0]
    assert document.type == "bl"
    assert document.source == "telegram"
    assert document.statut == "recu"
    assert document.telegram_message_id == entrant.message_id
    assert document.deposant_id == deposant.id
    assert document.numero == NUMERO_BL_INVENTE
    assert document.photo_compressee is True

    fichiers = list(tmp_path.glob("*.jpg"))
    assert len(fichiers) == 1
    assert not list(tmp_path.glob("*.tmp"))
    assert fichiers[0].read_bytes() == b"contenu-invente-du-fichier"
    assert document.fichier_path == str(fichiers[0])

    assert messagerie.reponses == [(entrant.chat_id, entrant.message_id, "reçu")]

    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    match = _parse_ligne_supervision(texte)
    assert match["numero_interne"] == str(document.numero_interne)
    assert match["bl"] == NUMERO_BL_INVENTE
    assert match["deposant"] == "Agent Testeur"
    assert match["statut"] == "recu"


async def test_traiter_fichier_photo_compressee_false_pour_un_document_envoye(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9011)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = FichierEntrant(
        update_id=16,
        chat_id=116,
        message_id=216,
        expediteur_id=9011,
        fichier_id="fichier-invente",
        mime_type="application/pdf",
        nom_fichier="bl-invente.pdf",
        compresse=False,
    )

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_avec_numero_bl,
        deposant,
        CHAT_SUPERVISION_INVENTE,
    )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.photo_compressee is False


async def test_traiter_fichier_echec_telechargement_signale_supervision_et_agent(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9012)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice(echoue_telechargement=True)
    entrant = _entrant(update_id=13)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant,
            messagerie,
            sessions_test,
            tmp_path,
            _ocr_jamais_appele,
            deposant,
            CHAT_SUPERVISION_INVENTE,
        )

    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []
    assert str(entrant.update_id) in caplog.text
    assert "contenu-invente-du-fichier" not in caplog.text

    # Ruling R22 : réponse d'échec à l'agent, sans détail technique.
    assert messagerie.reponses == [
        (entrant.chat_id, entrant.message_id, ingest_service._MESSAGE_ECHEC_AGENT)
    ]
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    assert "téléchargement" in texte
    assert "contenu-invente-du-fichier" not in texte


async def test_traiter_fichier_echec_ecriture_signale_supervision_et_agent(
    monkeypatch: pytest.MonkeyPatch,
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    def _ecriture_qui_echoue(*args: object, **kwargs: object) -> None:
        raise OSError("disque plein (factice)")

    monkeypatch.setattr(ingest_service, "_ecrire_atomique", _ecriture_qui_echoue)

    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9013)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=15)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_jamais_appele,
        deposant,
        CHAT_SUPERVISION_INVENTE,
    )

    assert list(tmp_path.iterdir()) == []
    assert (await db_session.execute(select(Document))).scalars().all() == []

    assert messagerie.reponses == [
        (entrant.chat_id, entrant.message_id, ingest_service._MESSAGE_ECHEC_AGENT)
    ]
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    assert "écriture" in texte
    assert "contenu-invente-du-fichier" not in texte


async def test_traiter_fichier_echec_base_supprime_le_fichier_ecrit(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Simule un échec base après téléchargement/écriture réussis (FK vers
    un utilisateur inexistant, `deposant.id` fantôme) : aucun fichier ne
    doit rester, l'agent est prévenu."""
    deposant_fantome = Deposant(id=uuid.uuid4(), nom_affichage="Fantôme")
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=14)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_jamais_appele,
        deposant_fantome,
        CHAT_SUPERVISION_INVENTE,
    )

    assert list(tmp_path.iterdir()) == []
    assert (await db_session.execute(select(Document))).scalars().all() == []

    assert messagerie.reponses == [
        (entrant.chat_id, entrant.message_id, ingest_service._MESSAGE_ECHEC_AGENT)
    ]
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    assert "insertion" in texte
    assert "contenu-invente-du-fichier" not in texte


async def test_traiter_fichier_echec_envoi_supervision_nempeche_pas_le_traitement(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un échec d'envoi du message de supervision est journalisé seulement
    (décision du contrôleur) : le document reste enregistré et la réponse
    « reçu » part quand même."""
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9014)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice(echoue_envoyer=True)
    entrant = _entrant(update_id=17)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant,
            messagerie,
            sessions_test,
            tmp_path,
            _ocr_avec_numero_bl,
            deposant,
            CHAT_SUPERVISION_INVENTE,
        )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.statut == "recu"
    assert messagerie.supervisions == []
    assert messagerie.reponses == [(entrant.chat_id, entrant.message_id, "reçu")]
    assert str(entrant.update_id) in caplog.text


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
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9020)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=20)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_avec_numero_bl,
        deposant,
        CHAT_SUPERVISION_INVENTE,
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
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9021)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=21)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_sans_numero_bl,
        deposant,
        CHAT_SUPERVISION_INVENTE,
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

    assert len(messagerie.supervisions) == 1
    match = _parse_ligne_supervision(messagerie.supervisions[0][1])
    assert match["bl"] == "non détecté"
    assert match["statut"] == "a_verifier"


async def test_traiter_fichier_ocr_en_echec_document_garde_recu_sans_numero(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9022)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=22)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant,
            messagerie,
            sessions_test,
            tmp_path,
            _ocr_en_echec,
            deposant,
            CHAT_SUPERVISION_INVENTE,
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

    assert len(messagerie.supervisions) == 1
    match = _parse_ligne_supervision(messagerie.supervisions[0][1])
    assert match["bl"] == "non détecté"
    assert match["statut"] == "recu"


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
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9030)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=30)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant,
            messagerie,
            sessions_test,
            tmp_path,
            ocr_factice,
            deposant,
            CHAT_SUPERVISION_INVENTE,
        )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.statut == "recu"
    assert document.numero is None
    assert document.ocr_brut is None
    # Le dépôt est acquis quoi qu'il arrive, y compris pour une réponse OCR
    # mal formée : la réponse « reçu » part quand même.
    assert messagerie.reponses == [(entrant.chat_id, entrant.message_id, "reçu")]
    assert str(entrant.update_id) in caplog.text
    assert "contenu-invente-du-fichier" not in caplog.text
