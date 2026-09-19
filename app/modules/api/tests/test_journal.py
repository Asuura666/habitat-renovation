"""Tests de `GET /api/journal` (L5-T9) : autorisation, filtres, plafond de
pagination, forme JSON de la réponse — voir `ingest/journal.py`
(`app/modules/ingest/tests/test_journal.py`) pour les scénarios de lecture
détaillés (filtres combinés, tri, résolution de l'auteur). Ce fichier ne
teste que le routeur (couche d'entrée, L2-D3).

Même schéma que `test_anomalies.py`/`test_referentiels.py` : `FastAPI`
isolé, `app.state.sessions` branché sur `bl_test_wt` (arbre de travail), IP
dédiées (`10.84.0.x`) pour ne jamais partager le quota `slowapi` du login
avec un autre fichier de test.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta
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
from app.core.fuseau import FUSEAU_PARIS
from app.modules.api import router as api_router
from app.modules.ingest.models import Journal, Utilisateur

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"

_IPS = itertools.count(1)

_BASE_TEMPS = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _instant(decalage_s: int) -> datetime:
    return _BASE_TEMPS + timedelta(seconds=decalage_s)


def _ip_isolee() -> str:
    return f"10.84.0.{next(_IPS)}"


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
    db_session: AsyncSession, *, email: str, role: str, nom: str | None = "Nom Testeur"
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email,
        hashed_password=_PASSWORD_HELPER.hash(_MOT_DE_PASSE),
        role=role,
        nom=nom,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _creer_entree(
    db_session: AsyncSession,
    *,
    utilisateur_id: uuid.UUID | None = None,
    action: str = "document_valide",
    cible_table: str | None = "document",
    avant: dict[str, object] | None = None,
    apres: dict[str, object] | None = None,
    horodatage: datetime | None = None,
) -> Journal:
    entree = Journal(
        utilisateur_id=utilisateur_id,
        action=action,
        cible_table=cible_table,
        cible_id=str(uuid.uuid4()),
        avant=avant,
        apres=apres,
    )
    if horodatage is not None:
        entree.horodatage = horodatage
    db_session.add(entree)
    await db_session.commit()
    await db_session.refresh(entree)
    return entree


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
    app_test: FastAPI, chemin: str, *, cookie: str | None
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=("10.0.6.2", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get(chemin)


# --------------------------------------------------------------------------
# Droits
# --------------------------------------------------------------------------


async def test_get_journal_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(app_test, "/api/journal", cookie=None)

    assert reponse.status_code == 401


async def test_get_journal_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.journal1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(app_test, "/api/journal", cookie=cookie)

    assert reponse.status_code == 403


async def test_get_journal_admin_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.journal1@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "/api/journal", cookie=cookie)

    assert reponse.status_code == 200
    assert reponse.json() == []


# --------------------------------------------------------------------------
# Filtres
# --------------------------------------------------------------------------


async def test_get_journal_filtre_utilisateur_id(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.journal2@example.invalid", role="admin"
    )
    autre = await _creer_utilisateur(
        db_session, email="admin.journal2b@example.invalid", role="admin"
    )
    entree = await _creer_entree(db_session, utilisateur_id=admin.id)
    await _creer_entree(db_session, utilisateur_id=autre.id)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, f"/api/journal?utilisateur_id={admin.id}", cookie=cookie
    )

    assert reponse.status_code == 200
    ids = {ligne["id"] for ligne in reponse.json()}
    assert ids == {str(entree.id)}


async def test_get_journal_filtre_action(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.journal3@example.invalid", role="admin"
    )
    entree = await _creer_entree(db_session, action="chantier_cree")
    await _creer_entree(db_session, action="article_valide")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "/api/journal?action=chantier_cree", cookie=cookie
    )

    assert reponse.status_code == 200
    ids = {ligne["id"] for ligne in reponse.json()}
    assert ids == {str(entree.id)}


async def test_get_journal_filtre_cible_table(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.journal4@example.invalid", role="admin"
    )
    entree = await _creer_entree(db_session, cible_table="chantier")
    await _creer_entree(db_session, cible_table="article")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "/api/journal?cible_table=chantier", cookie=cookie
    )

    assert reponse.status_code == 200
    ids = {ligne["id"] for ligne in reponse.json()}
    assert ids == {str(entree.id)}


async def test_get_journal_filtre_periode_bornes_incluses(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Même vérification que `test_anomalies.py
    ::test_get_anomalies_filtre_periode_bornes_incluses` (Ruling R21) :
    bornes incluses (`>=`/`<=`) et conversion en journée **Europe/Paris**,
    pas en UTC — 2026-08-15 est en heure d'été (Europe/Paris = UTC+2)."""
    admin = await _creer_utilisateur(
        db_session, email="admin.journal5@example.invalid", role="admin"
    )
    minuit_paris = datetime(2026, 8, 15, 0, 0, 0, tzinfo=FUSEAU_PARIS)
    fin_journee_paris = datetime(2026, 8, 15, 23, 59, 59, 999999, tzinfo=FUSEAU_PARIS)

    sur_borne_basse = await _creer_entree(db_session, horodatage=minuit_paris)
    sur_borne_haute = await _creer_entree(db_session, horodatage=fin_journee_paris)
    juste_avant = await _creer_entree(
        db_session, horodatage=minuit_paris - timedelta(minutes=5)
    )
    juste_apres = await _creer_entree(
        db_session, horodatage=fin_journee_paris + timedelta(microseconds=1)
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "/api/journal?depuis=2026-08-15&jusqu_a=2026-08-15", cookie=cookie
    )

    assert reponse.status_code == 200
    ids = {ligne["id"] for ligne in reponse.json()}
    assert ids == {str(sur_borne_basse.id), str(sur_borne_haute.id)}
    assert str(juste_avant.id) not in ids
    assert str(juste_apres.id) not in ids


# --------------------------------------------------------------------------
# Validation (422)
# --------------------------------------------------------------------------


async def test_get_journal_utilisateur_id_malforme_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.journal6@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "/api/journal?utilisateur_id=pas-un-uuid", cookie=cookie
    )

    assert reponse.status_code == 422


async def test_get_journal_periode_malformee_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.journal6b@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "/api/journal?depuis=pas-une-date", cookie=cookie
    )

    assert reponse.status_code == 422


async def test_get_journal_limite_bornee(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.journal7@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    trop_basse = await _requete(app_test, "/api/journal?limite=0", cookie=cookie)
    trop_haute = await _requete(app_test, "/api/journal?limite=501", cookie=cookie)

    assert trop_basse.status_code == 422
    assert trop_haute.status_code == 422


# --------------------------------------------------------------------------
# Forme JSON
# --------------------------------------------------------------------------


async def test_get_journal_forme_json(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session,
        email="admin.journal8@example.invalid",
        role="admin",
        nom="Alice Admin",
    )
    entree = await _creer_entree(
        db_session,
        utilisateur_id=admin.id,
        action="document_valide",
        cible_table="document",
        avant={"statut": "a_verifier"},
        apres={"statut": "recu"},
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "/api/journal", cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()[0]
    assert corps["id"] == str(entree.id)
    assert corps["utilisateur_id"] == str(admin.id)
    assert corps["auteur"] == "Alice Admin"
    assert corps["action"] == "document_valide"
    assert corps["cible_table"] == "document"
    assert corps["avant"] == {"statut": "a_verifier"}
    assert corps["apres"] == {"statut": "recu"}
    assert corps["horodatage"] is not None


async def test_get_journal_entree_automatique_auteur_absent_dans_la_reponse(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Une décision automatique (`utilisateur_id = NULL`, convention du
    projet depuis le lot 1) apparaît dans la réponse avec `utilisateur_id`
    et `auteur` à `null` — jamais une valeur par défaut qui masquerait
    l'absence d'auteur humain."""
    admin = await _creer_utilisateur(
        db_session, email="admin.journal9@example.invalid", role="admin"
    )
    entree = await _creer_entree(
        db_session, utilisateur_id=None, action="anomalie_levee", cible_table="anomalie"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "/api/journal", cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()[0]
    assert corps["id"] == str(entree.id)
    assert corps["utilisateur_id"] is None
    assert corps["auteur"] is None


# --------------------------------------------------------------------------
# Schéma OpenAPI
# --------------------------------------------------------------------------


async def test_schemas_openapi_presents(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    schema = app_test.openapi()

    ok = (
        "/api/journal" in schema["paths"]
        and "JournalReponse" in schema["components"]["schemas"]
    )
    assert ok, "route et schéma JournalReponse absents de l'OpenAPI"
