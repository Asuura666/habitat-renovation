"""Nouvelle tentative à l'enregistrement d'un bon Telegram (incident du
07/10/2026, demande d'Ilane) : si aucune connexion ne se libère à temps
(`sqlalchemy.exc.TimeoutError`, rien n'a encore été écrit), l'enregistrement
est retenté avant d'abandonner."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import exc as sa_exc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ingest import depot_telegram
from app.modules.ingest.depot_telegram import _MESSAGE_ECHEC_AGENT, traiter_fichier
from app.modules.ingest.models import Document
from app.modules.ingest.tests.test_service import (
    CHAT_SUPERVISION_INVENTE,
    MessagerieFactice,
    _creer_utilisateur,
    _deposant_depuis,
    _entrant,
    _ocr_avec_numero_bl,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


class _SessionsQuiEchouent:
    """Fabrique de sessions dont les `echecs` premiers appels lèvent la même
    erreur que le pool épuisé du 07/10/2026."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], echecs: int) -> None:
        self._sessions = sessions
        self._echecs = echecs
        self.appels = 0

    def __call__(self) -> AsyncSession:
        self.appels += 1
        if self._echecs > 0:
            self._echecs -= 1
            raise sa_exc.TimeoutError("pool épuisé (factice)")
        return self._sessions()


@pytest.fixture(autouse=True)
def _sans_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(depot_telegram, "_PAUSES_ENREGISTREMENT_S", (0.0, 0.0))


async def test_enregistrement_reussit_apres_deux_echecs(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9301)
    messagerie = MessagerieFactice()
    sessions = _SessionsQuiEchouent(sessions_test, echecs=2)

    await traiter_fichier(
        _entrant(update_id=301),
        messagerie,
        sessions,  # type: ignore[arg-type]
        tmp_path,
        _ocr_avec_numero_bl,
        _deposant_depuis(utilisateur),
        CHAT_SUPERVISION_INVENTE,
    )

    documents = (await db_session.execute(select(Document))).scalars().all()
    assert len(documents) == 1
    assert messagerie.reponses[0][2].startswith("Reçu")
    assert len(list(tmp_path.glob("*.jpg"))) == 1


async def test_enregistrement_abandonne_apres_trois_echecs(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9302)
    messagerie = MessagerieFactice()
    sessions = _SessionsQuiEchouent(sessions_test, echecs=3)

    await traiter_fichier(
        _entrant(update_id=302),
        messagerie,
        sessions,  # type: ignore[arg-type]
        tmp_path,
        _ocr_avec_numero_bl,
        _deposant_depuis(utilisateur),
        CHAT_SUPERVISION_INVENTE,
    )

    assert sessions.appels == 3
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert [texte for _, _, texte, _ in messagerie.reponses] == [_MESSAGE_ECHEC_AGENT]
    assert list(tmp_path.glob("*.jpg")) == []
