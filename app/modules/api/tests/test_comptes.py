"""Tests de `GET/POST /api/comptes`, `PUT /api/comptes/{id}`, `PUT /api
/comptes/{id}/mot-de-passe`, `POST /api/comptes/{id}/retirer-acces` et
`POST /api/comptes/{id}/retablir-acces` (Task 10, spec §3) : autorisation,
codes HTTP, forme JSON, sessions coupées de bout en bout.

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3) : les scénarios
métier détaillés (unicité, garde-fous `DernierAdmin`/`ActionSurSoiInterdite`,
journal) vivent dans `app/core/tests/test_auth.py`, testés directement sur
les fonctions de `app.core.auth` (pas de route HTTP là-bas).

Même schéma que `test_parametres.py` : `FastAPI` isolé, `app.state.sessions`
branché sur `bl_test` (fixtures locales de `conftest.py`), IP dédiées
(`10.86.0.x`) pour ne jamais partager le quota `slowapi` du login avec un
autre fichier de test.
"""

from __future__ import annotations

import itertools
import uuid
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
_MOT_DE_PASSE_PROVISOIRE = "mot-de-passe-provisoire-invente-1234"
_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.86.0.{next(_IPS)}"


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
    db_session: AsyncSession,
    *,
    email: str,
    role: str,
    nom: str | None = None,
    telegram_user_id: int | None = None,
    mot_de_passe: str = _MOT_DE_PASSE,
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email,
        nom=nom,
        hashed_password=_PASSWORD_HELPER.hash(mot_de_passe),
        role=role,
        telegram_user_id=telegram_user_id,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _login(app: FastAPI, email: str, *, mot_de_passe: str = _MOT_DE_PASSE) -> str:
    """Connexion réussie : renvoie le cookie de session (échoue le test si
    ce n'est pas un 204, jamais un login refusé -- voir `_tenter_login` pour
    ce cas)."""
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app, client=(_ip_isolee(), 12345)),
        base_url="http://test",
    ) as client:
        reponse = await client.post(
            "/api/auth/login",
            data={"username": email, "password": mot_de_passe},
        )
    assert reponse.status_code == 204
    cookie = reponse.cookies.get(NOM_COOKIE)
    assert cookie is not None
    return cookie


async def _tenter_login(
    app: FastAPI, email: str, *, mot_de_passe: str = _MOT_DE_PASSE
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app, client=(_ip_isolee(), 12345)),
        base_url="http://test",
    ) as client:
        return await client.post(
            "/api/auth/login",
            data={"username": email, "password": mot_de_passe},
        )


# ---------------------------------------------------------------------------
# Autorisation
# ---------------------------------------------------------------------------


async def test_routes_comptes_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.comptes@example.invalid", role="agent"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, agent.email)
    cible_id = uuid.uuid4()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        liste = await client.get("/api/comptes")
        creation = await client.post(
            "/api/comptes",
            json={
                "email": "peu.importe@example.invalid",
                "nom": "Peu Importe",
                "role": "agent",
                "agence": None,
                "telegram_user_id": None,
                "mot_de_passe": _MOT_DE_PASSE_PROVISOIRE,
            },
        )
        modification = await client.put(
            f"/api/comptes/{cible_id}",
            json={
                "email": "peu.importe@example.invalid",
                "nom": "Peu Importe",
                "role": "agent",
                "agence": None,
                "telegram_user_id": None,
            },
        )
        mot_de_passe = await client.put(
            f"/api/comptes/{cible_id}/mot-de-passe",
            json={"mot_de_passe": _MOT_DE_PASSE_PROVISOIRE},
        )
        retrait = await client.post(f"/api/comptes/{cible_id}/retirer-acces")
        retablissement = await client.post(f"/api/comptes/{cible_id}/retablir-acces")

    assert [
        reponse.status_code
        for reponse in [
            liste,
            creation,
            modification,
            mot_de_passe,
            retrait,
            retablissement,
        ]
    ] == [403] * 6


# ---------------------------------------------------------------------------
# GET /api/comptes
# ---------------------------------------------------------------------------


async def test_get_comptes_liste_sans_empreinte(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.liste@example.invalid", role="admin", nom="Admin Liste"
    )
    await _creer_utilisateur(
        db_session, email="agent.liste@example.invalid", role="agent", nom="Agent Liste"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get("/api/comptes")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps) >= 2
    for compte in corps:
        # Garde-fou explicite (constat du brief) : ni le hash ni la colonne
        # brute `mdp_hash` ne doivent jamais apparaître dans une réponse.
        assert "hashed_password" not in compte
        assert "mdp_hash" not in compte
        assert set(compte.keys()) == {
            "id",
            "nom",
            "email",
            "role",
            "agence",
            "telegram_user_id",
            "actif",
            "cree_le",
        }


# ---------------------------------------------------------------------------
# POST /api/comptes
# ---------------------------------------------------------------------------


async def test_post_comptes_cree_201_et_journalise(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.creation@example.invalid", role="admin"
    )
    admin_id = admin.id
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.post(
            "/api/comptes",
            json={
                "email": "nouveau.compte@example.invalid",
                "nom": "Nouveau Compte",
                "role": "agent",
                "agence": "Bordeaux",
                "telegram_user_id": 123123123,
                "mot_de_passe": _MOT_DE_PASSE_PROVISOIRE,
            },
        )

    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps["email"] == "nouveau.compte@example.invalid"
    assert corps["nom"] == "Nouveau Compte"
    assert corps["role"] == "agent"
    assert corps["agence"] == "Bordeaux"
    assert corps["telegram_user_id"] == 123123123
    assert corps["actif"] is True
    assert "hashed_password" not in corps
    assert "mdp_hash" not in corps

    db_session.expire_all()
    journal = (
        await db_session.execute(
            select(Journal)
            .where(Journal.action == "compte_cree")
            .where(Journal.cible_id == corps["id"])
        )
    ).scalar_one()
    assert journal.utilisateur_id == admin_id


async def test_post_comptes_email_deja_utilise_409(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.email409@example.invalid", role="admin"
    )
    await _creer_utilisateur(
        db_session, email="deja.pris@example.invalid", role="agent"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.post(
            "/api/comptes",
            json={
                "email": "deja.pris@example.invalid",
                "nom": "Peu Importe",
                "role": "agent",
                "agence": None,
                "telegram_user_id": None,
                "mot_de_passe": _MOT_DE_PASSE_PROVISOIRE,
            },
        )

    assert reponse.status_code == 409


async def test_post_comptes_telegram_deja_utilise_409(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.telegram409@example.invalid", role="admin"
    )
    await _creer_utilisateur(
        db_session,
        email="deja.telegram@example.invalid",
        role="agent",
        telegram_user_id=555444333,
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.post(
            "/api/comptes",
            json={
                "email": "nouveau.telegram@example.invalid",
                "nom": "Peu Importe",
                "role": "agent",
                "agence": None,
                "telegram_user_id": 555444333,
                "mot_de_passe": _MOT_DE_PASSE_PROVISOIRE,
            },
        )

    assert reponse.status_code == 409


async def test_post_comptes_mot_de_passe_court_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.mdpcourt422@example.invalid", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.post(
            "/api/comptes",
            json={
                "email": "mdp.court@example.invalid",
                "nom": "Peu Importe",
                "role": "agent",
                "agence": None,
                "telegram_user_id": None,
                "mot_de_passe": "court12345",
            },
        )

    assert reponse.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/comptes/{id}
# ---------------------------------------------------------------------------


async def test_put_comptes_modifie_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.modif200@example.invalid", role="admin"
    )
    cible = await _creer_utilisateur(
        db_session,
        email="cible.modif200@example.invalid",
        role="agent",
        nom="Ancien Nom",
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.put(
            f"/api/comptes/{cible.id}",
            json={
                "email": "cible.modif200.new@example.invalid",
                "nom": "Nouveau Nom",
                "role": "admin",
                "agence": "Lyon",
                "telegram_user_id": 999888777,
            },
        )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["email"] == "cible.modif200.new@example.invalid"
    assert corps["nom"] == "Nouveau Nom"
    assert corps["role"] == "admin"
    assert corps["agence"] == "Lyon"
    assert corps["telegram_user_id"] == 999888777


async def test_put_comptes_dernier_admin_downgrade_refuse_409(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Seul scénario où `DernierAdmin` est atteignable à travers les routes
    HTTP pour `modifier_compte` (constat du self-review, voir le rapport) :
    l'admin connecté est le seul admin actif et tente de se rétrograder
    lui-même -- `ActionSurSoiInterdite` ne s'applique qu'à `retirer_acces`,
    jamais à une modification de rôle."""
    seul_admin = await _creer_utilisateur(
        db_session,
        email="seul.admin.409@example.invalid",
        role="admin",
        nom="Seul Admin",
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, seul_admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.put(
            f"/api/comptes/{seul_admin.id}",
            json={
                "email": seul_admin.email,
                "nom": "Seul Admin",
                "role": "agent",
                "agence": None,
                "telegram_user_id": None,
            },
        )

    assert reponse.status_code == 409


async def test_put_comptes_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.introuvable404@example.invalid", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.put(
            f"/api/comptes/{uuid.uuid4()}",
            json={
                "email": "peu.importe@example.invalid",
                "nom": "Peu Importe",
                "role": "agent",
                "agence": None,
                "telegram_user_id": None,
            },
        )

    assert reponse.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/comptes/{id}/mot-de-passe
# ---------------------------------------------------------------------------


async def test_put_mot_de_passe_204_coupe_les_sessions(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.coupe.session@example.invalid", role="admin"
    )
    cible = await _creer_utilisateur(
        db_session, email="cible.coupe.session@example.invalid", role="agent"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie_admin = await _login(app, admin.email)
    cookie_cible = await _login(app, cible.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie_admin},
    ) as client:
        reponse = await client.put(
            f"/api/comptes/{cible.id}/mot-de-passe",
            json={"mot_de_passe": _MOT_DE_PASSE_PROVISOIRE},
        )

    assert reponse.status_code == 204

    # L'ancien cookie de la cible ne doit plus donner accès à rien (jeton
    # supprimé en base par `changer_mot_de_passe`, pas seulement un cookie
    # côté client encore valide).
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie_cible},
    ) as client:
        apres = await client.get("/api/moi")
    assert apres.status_code == 401

    # Le nouveau mot de passe fonctionne bien.
    nouveau_cookie = await _login(
        app, cible.email, mot_de_passe=_MOT_DE_PASSE_PROVISOIRE
    )
    assert nouveau_cookie is not None


async def test_put_mot_de_passe_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.mdp.introuvable404@example.invalid", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.put(
            f"/api/comptes/{uuid.uuid4()}/mot-de-passe",
            json={"mot_de_passe": _MOT_DE_PASSE_PROVISOIRE},
        )

    assert reponse.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/comptes/{id}/retirer-acces, POST /api/comptes/{id}/retablir-acces
# ---------------------------------------------------------------------------


async def test_post_retirer_acces_200_coupe_les_sessions_et_le_login(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.retire.http@example.invalid", role="admin"
    )
    cible = await _creer_utilisateur(
        db_session, email="cible.retire.http@example.invalid", role="agent"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie_admin = await _login(app, admin.email)
    cookie_cible = await _login(app, cible.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie_admin},
    ) as client:
        retrait = await client.post(f"/api/comptes/{cible.id}/retirer-acces")

    assert retrait.status_code == 200
    assert retrait.json()["actif"] is False

    # Ancien cookie coupé.
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie_cible},
    ) as client:
        apres = await client.get("/api/moi")
    assert apres.status_code == 401

    # Le compte désactivé ne peut plus se reconnecter.
    login_refuse = await _tenter_login(app, cible.email)
    assert login_refuse.status_code == 400


async def test_post_retirer_acces_sur_soi_meme_409(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.soi.http@example.invalid", role="admin"
    )
    # Un second admin actif, pour isoler `ActionSurSoiInterdite` du
    # garde-fou `DernierAdmin`.
    await _creer_utilisateur(
        db_session, email="admin.soi.http2@example.invalid", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.post(f"/api/comptes/{admin.id}/retirer-acces")

    assert reponse.status_code == 409


async def test_post_retirer_acces_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.retire.introuvable404@example.invalid", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.post(f"/api/comptes/{uuid.uuid4()}/retirer-acces")

    assert reponse.status_code == 404


async def test_post_retablir_acces_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.retablir.http@example.invalid", role="admin"
    )
    cible = await _creer_utilisateur(
        db_session, email="cible.retablir.http@example.invalid", role="agent"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        await client.post(f"/api/comptes/{cible.id}/retirer-acces")
        retablissement = await client.post(f"/api/comptes/{cible.id}/retablir-acces")

    assert retablissement.status_code == 200
    assert retablissement.json()["actif"] is True

    # Le compte rétabli peut de nouveau se connecter.
    nouveau_cookie = await _login(app, cible.email)
    assert nouveau_cookie is not None


async def test_post_retablir_acces_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.retablir.introuvable404@example.invalid", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.post(f"/api/comptes/{uuid.uuid4()}/retablir-acces")

    assert reponse.status_code == 404
