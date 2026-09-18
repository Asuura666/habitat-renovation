"""Tests de `GET /api/chantiers`, `POST /api/chantiers`, `GET
/api/fournisseurs`, `POST /api/alias-chantier/{id}/validation`, `POST
/api/articles/{id}/validation` (L3-T8b) et `GET /api/referentiels
/depots-par-agent`, `GET /api/referentiels/chantiers-silencieux`, `GET
/api/referentiels/agences` (L5-T7) : autorisation, codes HTTP, forme JSON.

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3) : les scénarios
métier détaillés vivent dans `app/modules/ingest/tests/test_referentiels.py`
(L3-T8b) et `app/modules/ingest/tests/test_referentiels_vue.py` (L5-T7).

Même schéma que `test_documents_detail.py` : `FastAPI` isolé, `app.state
.sessions` branché sur `bl_test_wt` (arbre de travail), IP dédiées
(`10.82.0.x`) pour ne jamais partager le quota `slowapi` du login avec un
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.config import get_settings
from app.modules.api import router as api_router
from app.modules.ingest.models import (
    Article,
    Chantier,
    ChantierAlias,
    Fournisseur,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.82.0.{next(_IPS)}"


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


async def _creer_fournisseur(db_session: AsyncSession, *, nom: str) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_chantier(
    db_session: AsyncSession, *, nom: str = "Chantier Existant"
) -> Chantier:
    chantier = Chantier(nom_canonique=nom)
    db_session.add(chantier)
    await db_session.commit()
    await db_session.refresh(chantier)
    return chantier


async def _creer_alias(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    libelle_brut: str = "maison test",
    chantier_id: uuid.UUID | None = None,
) -> ChantierAlias:
    alias = ChantierAlias(
        fournisseur_id=fournisseur.id,
        libelle_brut=libelle_brut,
        code_brut=None,
        chantier_id=chantier_id,
    )
    db_session.add(alias)
    await db_session.commit()
    await db_session.refresh(alias)
    return alias


async def _creer_article(
    db_session: AsyncSession, *, fournisseur: Fournisseur, code: str = "AB1234"
) -> Article:
    article = Article(fournisseur_id=fournisseur.id, code=code, valide=False)
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)
    return article


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


async def _requete(
    app_test: FastAPI,
    methode: str,
    chemin: str,
    *,
    cookie: str | None,
    json_body: object = None,
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=("10.0.5.1", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.request(methode, chemin, json=json_body)


# --------------------------------------------------------------------------
# GET/POST /api/chantiers
# --------------------------------------------------------------------------


async def test_chantiers_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.chantiers1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse_get = await _requete(app_test, "GET", "/api/chantiers", cookie=cookie)
    reponse_post = await _requete(
        app_test,
        "POST",
        "/api/chantiers",
        cookie=cookie,
        json_body={"nom_canonique": "Chantier Agent", "agence": None},
    )

    assert reponse_get.status_code == 403
    assert reponse_post.status_code == 403


async def test_get_chantiers_admin_liste(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.chantiers1@example.invalid", role="admin"
    )
    chantier = await _creer_chantier(db_session, nom="Chantier API")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/chantiers", cookie=cookie)

    assert reponse.status_code == 200
    ids = {c["id"] for c in reponse.json()}
    assert str(chantier.id) in ids


async def test_post_chantiers_cree_201(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.chantiers2@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        "/api/chantiers",
        cookie=cookie,
        json_body={"nom_canonique": "Chantier Créé API", "agence": "Agence Nord"},
    )

    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps["nom_canonique"] == "Chantier Créé API"
    assert corps["actif"] is True


async def test_post_chantiers_doublon_409_avec_original_id(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.chantiers3@example.invalid", role="admin"
    )
    existant = await _creer_chantier(db_session, nom="Chantier Doublon")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        "/api/chantiers",
        cookie=cookie,
        json_body={"nom_canonique": "CHANTIER DOUBLON", "agence": None},
    )

    assert reponse.status_code == 409
    assert reponse.json()["original_id"] == str(existant.id)


async def test_post_chantiers_nom_blanc_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.chantiers4@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        "/api/chantiers",
        cookie=cookie,
        json_body={"nom_canonique": "   ", "agence": None},
    )

    assert reponse.status_code == 422


# --------------------------------------------------------------------------
# GET /api/fournisseurs
# --------------------------------------------------------------------------


async def test_fournisseurs_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.fournisseurs1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(app_test, "GET", "/api/fournisseurs", cookie=cookie)

    assert reponse.status_code == 403


async def test_get_fournisseurs_admin_liste(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.fournisseurs1@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur API")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/fournisseurs", cookie=cookie)

    assert reponse.status_code == 200
    ids = {f["id"] for f in reponse.json()}
    assert str(fournisseur.id) in ids


# --------------------------------------------------------------------------
# POST /api/alias-chantier/{id}/validation
# --------------------------------------------------------------------------


async def test_validation_alias_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.alias1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/alias-chantier/{uuid.uuid4()}/validation",
        cookie=cookie,
        json_body={"chantier_id": str(uuid.uuid4())},
    )

    assert reponse.status_code == 403


async def test_validation_alias_ok(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.alias1@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Alias API")
    chantier = await _creer_chantier(db_session, nom="Chantier Alias API")
    alias = await _creer_alias(db_session, fournisseur=fournisseur)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/alias-chantier/{alias.id}/validation",
        cookie=cookie,
        json_body={"chantier_id": str(chantier.id)},
    )

    assert reponse.status_code == 200
    assert reponse.json() == {"nb_mis_a_jour": 0}


async def test_validation_alias_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.alias2@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/alias-chantier/{uuid.uuid4()}/validation",
        cookie=cookie,
        json_body={"chantier_id": str(uuid.uuid4())},
    )

    assert reponse.status_code == 404


async def test_validation_alias_chantier_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.alias3@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Alias API 2")
    alias = await _creer_alias(db_session, fournisseur=fournisseur)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/alias-chantier/{alias.id}/validation",
        cookie=cookie,
        json_body={"chantier_id": str(uuid.uuid4())},
    )

    assert reponse.status_code == 404


async def test_validation_alias_deja_valide_409(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.alias4@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Alias API 3")
    chantier = await _creer_chantier(db_session, nom="Chantier Alias API 3")
    alias = await _creer_alias(
        db_session, fournisseur=fournisseur, chantier_id=chantier.id
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/alias-chantier/{alias.id}/validation",
        cookie=cookie,
        json_body={"chantier_id": str(chantier.id)},
    )

    assert reponse.status_code == 409


# --------------------------------------------------------------------------
# POST /api/articles/{id}/validation
# --------------------------------------------------------------------------


async def test_validation_article_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.article1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/articles/{uuid.uuid4()}/validation",
        cookie=cookie,
        json_body={"unite_cdt": None, "unite_fact": None, "ratio": None},
    )

    assert reponse.status_code == 403


async def test_validation_article_ok_204(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.article1@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Article API")
    article = await _creer_article(db_session, fournisseur=fournisseur)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/articles/{article.id}/validation",
        cookie=cookie,
        json_body={"unite_cdt": "seau", "unite_fact": "kg", "ratio": "4.0000"},
    )

    assert reponse.status_code == 204


async def test_validation_article_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.article2@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/articles/{uuid.uuid4()}/validation",
        cookie=cookie,
        json_body={"unite_cdt": None, "unite_fact": None, "ratio": None},
    )

    assert reponse.status_code == 404


async def test_validation_article_ratio_negatif_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.article3@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Article API 2")
    article = await _creer_article(db_session, fournisseur=fournisseur)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/articles/{article.id}/validation",
        cookie=cookie,
        json_body={"unite_cdt": None, "unite_fact": None, "ratio": "-1"},
    )

    assert reponse.status_code == 422


# --------------------------------------------------------------------------
# GET /api/referentiels/depots-par-agent, /chantiers-silencieux, /agences
# (L5-T7) — voir `ingest/tests/test_referentiels_vue.py` pour les scénarios
# métier détaillés.
# --------------------------------------------------------------------------


async def test_depots_par_agent_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test, "GET", "/api/referentiels/depots-par-agent", cookie=None
    )

    assert reponse.status_code == 401


async def test_depots_par_agent_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.depots1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(
        app_test, "GET", "/api/referentiels/depots-par-agent", cookie=cookie
    )

    assert reponse.status_code == 403


async def test_depots_par_agent_admin_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.depots1@example.invalid", role="admin"
    )
    agent_sans_depot = await _creer_utilisateur(
        db_session, email="agent.depots2@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "GET", "/api/referentiels/depots-par-agent", cookie=cookie
    )

    assert reponse.status_code == 200
    lignes = {ligne["agent_id"]: ligne for ligne in reponse.json()}
    assert str(agent_sans_depot.id) in lignes
    assert lignes[str(agent_sans_depot.id)]["nombre_depots"] == 0
    # Tour de correction 1 bis : `role` traverse jusqu'à la réponse JSON.
    assert lignes[str(agent_sans_depot.id)]["role"] == "agent"


async def test_chantiers_silencieux_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test, "GET", "/api/referentiels/chantiers-silencieux", cookie=None
    )

    assert reponse.status_code == 401


async def test_chantiers_silencieux_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.silencieux1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(
        app_test, "GET", "/api/referentiels/chantiers-silencieux", cookie=cookie
    )

    assert reponse.status_code == 403


async def test_chantiers_silencieux_admin_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.silencieux1@example.invalid", role="admin"
    )
    chantier = await _creer_chantier(db_session, nom="Chantier Silencieux API")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "GET", "/api/referentiels/chantiers-silencieux", cookie=cookie
    )

    assert reponse.status_code == 200
    # Aucun dépôt jamais enregistré pour ce chantier tout neuf : il est
    # signalé (décision du contrôleur, voir `ingest.referentiels_vue
    # .chantiers_sans_depot`).
    ids = {ligne["chantier_id"] for ligne in reponse.json()}
    assert str(chantier.id) in ids


async def test_agences_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(app_test, "GET", "/api/referentiels/agences", cookie=None)

    assert reponse.status_code == 401


async def test_agences_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.agences1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(
        app_test, "GET", "/api/referentiels/agences", cookie=cookie
    )

    assert reponse.status_code == 403


async def test_agences_admin_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.agences1@example.invalid", role="admin"
    )
    await _creer_chantier(db_session, nom="Chantier Agence API")
    chantier_avec_agence = Chantier(
        nom_canonique="Chantier Avec Agence API", agence="Agence API Testeur"
    )
    db_session.add(chantier_avec_agence)
    await db_session.commit()
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "GET", "/api/referentiels/agences", cookie=cookie
    )

    assert reponse.status_code == 200
    assert reponse.json() == ["Agence API Testeur"]
