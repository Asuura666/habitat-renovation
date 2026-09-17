"""Tests unitaires de `app/modules/ingest/service.py` (base de test réelle,
`docs_dir` temporaire, fausse `Messagerie`). Toutes les valeurs (identifiants,
noms) sont inventées."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ingest import service as ingest_service
from app.modules.ingest.models import Document, TelegramUpdate, Utilisateur
from app.modules.ingest.service import enregistrer_update, traiter_fichier
from app.modules.messaging.base import FichierEntrant, FichierTelecharge

pytestmark = [pytest.mark.anyio, pytest.mark.db]


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

    await traiter_fichier(entrant, messagerie, sessions_test, tmp_path)

    documents = (await db_session.execute(select(Document))).scalars().all()
    assert len(documents) == 1
    document = documents[0]
    assert document.type == "bl"
    assert document.source == "telegram"
    assert document.statut == "recu"
    assert document.telegram_message_id == entrant.message_id
    assert document.deposant_id is None

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

    await traiter_fichier(entrant, messagerie, sessions_test, tmp_path)

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.deposant_id == utilisateur.id


async def test_traiter_fichier_deposant_null_si_utilisateur_inconnu(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=12, expediteur_id=999999)

    await traiter_fichier(entrant, messagerie, sessions_test, tmp_path)

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
        await traiter_fichier(entrant, messagerie, sessions_test, tmp_path)

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

    await traiter_fichier(entrant, messagerie, sessions_test, tmp_path)

    assert list(tmp_path.iterdir()) == []
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert messagerie.reponses == []
