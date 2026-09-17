"""Tests de `GET /api/documents` et `GET /api/documents/{id}/fichier`
(L2-T5) : autorisation, portée par rôle, forme JSON, 404.

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3) : les scénarios
métier détaillés (tri, `depuis`, `limite`, chemin hors `docs_dir`) vivent
dans `app/modules/ingest/tests/test_lecture.py`.

Même schéma que `test_factures.py`/`test_factures_lecture.py` : `FastAPI`
isolé, `app.state.sessions` branché sur `bl_test`, IP dédiées (`10.79.0.x`)
pour ne jamais partager le quota `slowapi` du login avec un autre fichier de
test.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.config import get_settings
from app.modules.api import router as api_router
from app.modules.ingest.models import Document, Journal, Utilisateur

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.79.0.{next(_IPS)}"


def _app_test(sessions: async_sessionmaker[AsyncSession], docs_dir: Path) -> FastAPI:
    app_test = FastAPI()
    app_test.state.sessions = sessions
    app_test.include_router(auth_router)
    app_test.include_router(api_router)

    def _settings_test() -> Any:
        return get_settings().model_copy(update={"docs_dir": docs_dir})

    app_test.dependency_overrides[get_settings] = _settings_test
    return app_test


async def _creer_utilisateur(
    db_session: AsyncSession, *, email: str, role: str, nom: str | None = None
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email,
        nom=nom,
        hashed_password=_PASSWORD_HELPER.hash(_MOT_DE_PASSE),
        role=role,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _login(app_test: FastAPI, *, email: str) -> str | None:
    transport = ASGITransport(app=app_test, client=(_ip_isolee(), 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.post(
            "/api/auth/login", data={"username": email, "password": _MOT_DE_PASSE}
        )
    assert reponse.status_code == 204
    return reponse.cookies.get(NOM_COOKIE)


async def _get(app_test: FastAPI, chemin: str, *, cookie: str | None) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=("10.0.2.1", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get(chemin)


async def _creer_document_bl(
    db_session: AsyncSession,
    *,
    numero: str,
    deposant: Utilisateur | None = None,
    fichier_path: str | None = None,
) -> Document:
    document = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path=fichier_path or "/var/docs/bl-lecture-invente.jpg",
        numero=numero,
        deposant_id=deposant.id if deposant is not None else None,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_journal_confirmation(
    db_session: AsyncSession, *, document: Document, action: str
) -> None:
    db_session.add(
        Journal(
            action=action,
            cible_table="document",
            cible_id=str(document.id),
        )
    )
    await db_session.commit()


# --------------------------------------------------------------------------
# GET /api/documents
# --------------------------------------------------------------------------


async def test_liste_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _get(app_test, "/api/documents", cookie=None)

    assert reponse.status_code == 401


async def test_liste_admin_voit_tous_les_documents(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.docliste@example.invalid", role="admin"
    )
    agent = await _creer_utilisateur(
        db_session,
        email="agent.docliste@example.invalid",
        role="agent",
        nom="Agent Testeur",
    )
    document = await _creer_document_bl(db_session, numero="L600", deposant=agent)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _get(app_test, "/api/documents", cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps) == 1
    ligne = corps[0]
    assert ligne["id"] == str(document.id)
    assert ligne["numero_interne"] == document.numero_interne
    assert ligne["type"] == "bl"
    assert ligne["numero"] == "L600"
    assert ligne["deposant"] == "Agent Testeur"
    assert ligne["confirme_par"] is None
    # Ruling L2-R8 (revue L2-T7, tour 1/5) : aucun clic -> `confirmation`
    # absente, jamais dérivée de `statut`.
    assert ligne["confirmation"] is None
    # L3-T8a : aucun fournisseur/chantier résolu sur ce document minimal.
    assert ligne["fournisseur"] is None
    assert ligne["chantier_brut"] is None
    assert set(ligne.keys()) == {
        "id",
        "numero_interne",
        "type",
        "numero",
        "statut",
        "deposant",
        "cree_le",
        "confirme_le",
        "confirme_par",
        "photo_compressee",
        "confirmation",
        "fournisseur",
        "chantier_brut",
    }


async def test_liste_confirmation_reflete_le_journal_pas_le_statut(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Ruling L2-R8 (revue L2-T7, tour 1/5) : `confirmation` vient du
    journal, jamais de `statut` — un document `a_verifier` (OCR sans numéro
    de BL détecté, ex. `traiter_fichier`) qui reçoit malgré tout « Quantités
    vérifiées » doit afficher `confirmation == "verifiee"`, pas « écart »."""
    admin = await _creer_utilisateur(
        db_session, email="admin.docconfirmation@example.invalid", role="admin"
    )
    document = Document(
        type="bl",
        source="telegram",
        statut="a_verifier",
        fichier_path="/var/docs/bl-a-verifier-invente.jpg",
        numero=None,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    await _creer_journal_confirmation(
        db_session, document=document, action="quantites_verifiees"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _get(app_test, "/api/documents", cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps) == 1
    assert corps[0]["statut"] == "a_verifier"
    assert corps[0]["confirmation"] == "verifiee"


async def test_liste_agent_ne_voit_que_ses_propres_documents(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent_1 = await _creer_utilisateur(
        db_session, email="agent1.docliste@example.invalid", role="agent"
    )
    agent_2 = await _creer_utilisateur(
        db_session, email="agent2.docliste@example.invalid", role="agent"
    )
    document_1 = await _creer_document_bl(db_session, numero="L610", deposant=agent_1)
    await _creer_document_bl(db_session, numero="L611", deposant=agent_2)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent_1.email)

    reponse = await _get(app_test, "/api/documents", cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert [ligne["id"] for ligne in corps] == [str(document_1.id)]


async def test_liste_limite_invalide_renvoie_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.doclimite@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _get(app_test, "/api/documents?limite=0", cookie=cookie)

    assert reponse.status_code == 422


# --------------------------------------------------------------------------
# GET /api/documents/{id}/fichier
# --------------------------------------------------------------------------


async def test_fichier_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _get(
        app_test,
        "/api/documents/00000000-0000-0000-0000-000000000000/fichier",
        cookie=None,
    )

    assert reponse.status_code == 401


async def test_fichier_dun_autre_agent_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chemin = tmp_path / "photo-autre-agent.jpg"
    chemin.write_bytes(b"contenu-invente")
    agent_1 = await _creer_utilisateur(
        db_session, email="agent1.docfichier@example.invalid", role="agent"
    )
    agent_2 = await _creer_utilisateur(
        db_session, email="agent2.docfichier@example.invalid", role="agent"
    )
    document = await _creer_document_bl(
        db_session, numero="L620", deposant=agent_1, fichier_path=str(chemin)
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent_2.email)

    reponse = await _get(
        app_test, f"/api/documents/{document.id}/fichier", cookie=cookie
    )

    assert reponse.status_code == 404


async def test_fichier_admin_voit_le_document_dun_agent(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chemin = tmp_path / "photo-admin.jpg"
    chemin.write_bytes(b"contenu-invente")
    admin = await _creer_utilisateur(
        db_session, email="admin.docfichier@example.invalid", role="admin"
    )
    agent = await _creer_utilisateur(
        db_session, email="agent.docfichierok@example.invalid", role="agent"
    )
    document = await _creer_document_bl(
        db_session, numero="L630", deposant=agent, fichier_path=str(chemin)
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _get(
        app_test, f"/api/documents/{document.id}/fichier", cookie=cookie
    )

    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "image/jpeg"
    assert reponse.content == b"contenu-invente"


async def test_fichier_son_propre_document_agent_ok(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chemin = tmp_path / "photo-soi.jpg"
    chemin.write_bytes(b"contenu-invente")
    agent = await _creer_utilisateur(
        db_session, email="agent.docfichiersoi@example.invalid", role="agent"
    )
    document = await _creer_document_bl(
        db_session, numero="L640", deposant=agent, fichier_path=str(chemin)
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _get(
        app_test, f"/api/documents/{document.id}/fichier", cookie=cookie
    )

    assert reponse.status_code == 200
