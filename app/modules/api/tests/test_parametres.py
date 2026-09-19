from __future__ import annotations

import itertools
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.config import get_settings
from app.modules.api import router as api_router
from app.modules.ingest.models import Journal, Utilisateur

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"
_IPS = itertools.count(1)


def _app_test(sessions: async_sessionmaker[AsyncSession], docs_dir: Path) -> FastAPI:
    app = FastAPI()
    app.state.sessions = sessions
    app.include_router(auth_router)
    app.include_router(api_router)
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"docs_dir": docs_dir}
    )
    return app


async def _creer_utilisateur(
    db_session: AsyncSession, *, email: str, role: str
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email,
        hashed_password=_PASSWORD_HELPER.hash(_MOT_DE_PASSE),
        role=role,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _login(app: FastAPI, email: str) -> str:
    ip = f"10.85.0.{next(_IPS)}"
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app, client=(ip, 12345)),
        base_url="http://test",
    ) as client:
        reponse = await client.post(
            "/api/auth/login",
            data={"username": email, "password": _MOT_DE_PASSE},
        )
    assert reponse.status_code == 204
    cookie = reponse.cookies.get(NOM_COOKIE)
    assert cookie is not None
    return cookie


async def test_get_parametres_est_reserve_a_admin(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.parametres@example.test", role="agent"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, agent.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get("/api/parametres")

    assert reponse.status_code == 403


async def test_put_parametre_admin_modifie_et_journalise(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.parametres@example.test", role="admin"
    )
    admin_id = admin.id
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        liste = await client.get("/api/parametres")
        modification = await client.put(
            "/api/parametres/seuil_prix_pct", json={"valeur": "6.5"}
        )

    assert liste.status_code == 200
    assert len(liste.json()) == 9
    assert modification.status_code == 200
    assert modification.json()["valeur"] == "6.5"

    db_session.expire_all()
    entree = (
        await db_session.execute(
            select(Journal).where(Journal.action == "parametre_modifie")
        )
    ).scalar_one()
    assert entree.utilisateur_id == admin_id


async def test_put_parametre_invalide_renvoie_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.parametres.invalide@example.test", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.put("/api/parametres/inconnue", json={"valeur": "6.5"})

    assert reponse.status_code == 422
    assert "Paramètre inconnu" in reponse.json()["detail"]
