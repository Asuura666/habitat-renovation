"""Tests de `GET /api/ia/synthese`, `POST /api/ia/synthese/actions/{id}
/faite` et `POST /api/ia/synthese/actions/{id}/a-faire` (T4, phase 4 IA) :
autorisation, codes HTTP, forme JSON -- voir `app/modules/ingest/tests
/test_ia_synthese.py` pour les scénarios métier détaillés (sélection,
troncature, cochage, journal).

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3). Même schéma que
`test_comptes.py`/`test_bilan.py` : `FastAPI` isolé, `app.state.sessions`
branché sur `bl_test`, IP dédiées (`10.88.0.x`) pour ne jamais partager le
quota `slowapi` du login avec un autre fichier de test.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import date, timedelta
from pathlib import Path

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
from app.modules.ingest.models import (
    Document,
    Fournisseur,
    SyntheseAction,
    SyntheseCommentaires,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"
_LUNDI = date(2026, 9, 21)

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.88.0.{next(_IPS)}"


def _app_test(sessions: async_sessionmaker[AsyncSession], docs_dir: Path) -> FastAPI:
    app_test = FastAPI()
    app_test.state.sessions = sessions
    app_test.include_router(auth_router)
    app_test.include_router(api_router)

    def _settings_test() -> object:
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


async def _login(app_test: FastAPI, *, email: str) -> str:
    transport = ASGITransport(app=app_test, client=(_ip_isolee(), 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.post(
            "/api/auth/login", data={"username": email, "password": _MOT_DE_PASSE}
        )
    assert reponse.status_code == 204
    cookie = reponse.cookies.get(NOM_COOKIE)
    assert cookie is not None
    return cookie


async def _creer_synthese_avec_action(
    db_session: AsyncSession,
) -> tuple[SyntheseCommentaires, SyntheseAction, Document]:
    fournisseur = Fournisseur(nom="Fournisseur IA Invente")
    db_session.add(fournisseur)
    await db_session.flush()
    document = Document(
        type="bl",
        source="telegram",
        statut="a_verifier",
        fichier_path=f"bl-invente-ia-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id,
        numero="BL-IA-1",
    )
    db_session.add(document)
    await db_session.flush()
    synthese = SyntheseCommentaires(
        semaine_debut=_LUNDI,
        semaine_fin=_LUNDI + timedelta(days=6),
        statut="ok",
        resume="Résumé inventé pour les tests d'API.",
        nb_commentaires=1,
        modele="modele-invente",
    )
    db_session.add(synthese)
    await db_session.flush()
    action = SyntheseAction(
        synthese_id=synthese.id,
        ordre=1,
        texte="Action inventée pour les tests d'API.",
        commentaire_ids=[str(uuid.uuid4())],
        document_ids=[str(document.id)],
    )
    db_session.add(action)
    await db_session.commit()
    return synthese, action, document


# --------------------------------------------------------------------------
# Autorisation
# --------------------------------------------------------------------------


async def test_get_synthese_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)
    transport = ASGITransport(app=app_test, client=(_ip_isolee(), 12345))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.get("/api/ia/synthese")

    assert reponse.status_code == 401


async def test_routes_ia_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.ia@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)
    action_id = uuid.uuid4()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        liste = await client.get("/api/ia/synthese")
        faite = await client.post(f"/api/ia/synthese/actions/{action_id}/faite")
        a_faire = await client.post(f"/api/ia/synthese/actions/{action_id}/a-faire")

    assert [reponse.status_code for reponse in [liste, faite, a_faire]] == [403] * 3


# --------------------------------------------------------------------------
# GET /api/ia/synthese
# --------------------------------------------------------------------------


async def test_get_synthese_admin_200_forme_json(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.ia.get@example.invalid", role="admin"
    )
    synthese, action, document = await _creer_synthese_avec_action(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get("/api/ia/synthese")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["ia_active"] is False  # IA_ACTIVE absente en test -> éteinte
    assert corps["encore_a_faire"] == []
    assert corps["derniere"] is not None
    assert corps["derniere"]["id"] == str(synthese.id)
    assert corps["derniere"]["semaine_debut"] == _LUNDI.isoformat()
    assert corps["derniere"]["resume"] == "Résumé inventé pour les tests d'API."
    assert len(corps["derniere"]["actions"]) == 1
    action_json = corps["derniere"]["actions"][0]
    assert action_json["id"] == str(action.id)
    assert action_json["texte"] == "Action inventée pour les tests d'API."
    assert action_json["faite_le"] is None
    assert action_json["faite_par"] is None
    assert action_json["bons"] == [
        {"document_id": str(document.id), "numero": "BL-IA-1"}
    ]


async def test_get_synthese_admin_200_aucune_synthese(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.ia.vide@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get("/api/ia/synthese")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["derniere"] is None
    assert corps["encore_a_faire"] == []


# --------------------------------------------------------------------------
# POST /api/ia/synthese/actions/{id}/faite, .../a-faire
# --------------------------------------------------------------------------


async def test_post_action_faite_puis_a_faire_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session,
        email="admin.ia.cocher@example.invalid",
        role="admin",
        nom="Admin Cocher",
    )
    _synthese, action, _document = await _creer_synthese_avec_action(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        faite = await client.post(f"/api/ia/synthese/actions/{action.id}/faite")
        a_faire = await client.post(f"/api/ia/synthese/actions/{action.id}/a-faire")

    assert faite.status_code == 200
    corps_faite = faite.json()
    assert corps_faite["faite_le"] is not None
    assert corps_faite["faite_par"] == "Admin Cocher"

    assert a_faire.status_code == 200
    corps_a_faire = a_faire.json()
    assert corps_a_faire["faite_le"] is None
    assert corps_a_faire["faite_par"] is None


async def test_post_action_faite_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.ia.404@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        faite = await client.post(f"/api/ia/synthese/actions/{uuid.uuid4()}/faite")
        a_faire = await client.post(f"/api/ia/synthese/actions/{uuid.uuid4()}/a-faire")

    assert faite.status_code == 404
    assert a_faire.status_code == 404
