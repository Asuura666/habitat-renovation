"""Tests de `GET /api/a-traiter` (L3-T8b) : autorisation, forme JSON.

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3) : les scénarios
métier détaillés (comptage des alias, sélection des articles, motifs) vivent
dans `app/modules/ingest/tests/test_a_traiter.py`.

Même schéma que `test_documents_detail.py` : `FastAPI` isolé, `app.state
.sessions` branché sur `bl_test`, IP dédiées (`10.81.0.x`) pour ne jamais
partager le quota `slowapi` du login avec un autre fichier de test.
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
from app.modules.ingest import commun
from app.modules.ingest.models import Document, Utilisateur

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.81.0.{next(_IPS)}"


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


async def _creer_document(
    db_session: AsyncSession, *, statut: str = "a_verifier"
) -> Document:
    document = Document(
        type="bl",
        source="telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


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
    app_test: FastAPI, methode: str, chemin: str, *, cookie: str | None
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=("10.0.4.1", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.request(methode, chemin)


async def test_a_traiter_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(app_test, "GET", "/api/a-traiter", cookie=None)

    assert reponse.status_code == 401


async def test_a_traiter_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.atraiter1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(app_test, "GET", "/api/a-traiter", cookie=cookie)

    assert reponse.status_code == 403


async def test_a_traiter_admin_renvoie_le_contenu(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.atraiter1@example.invalid", role="admin"
    )
    document = await _creer_document(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/a-traiter", cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()
    # `anomalies_hautes` ajouté en L4-T9 (L4-D18) : les scénarios détaillés
    # de cette section vivent dans `app/modules/api/tests/test_anomalies.py`.
    assert set(corps.keys()) == {"documents", "alias", "articles", "anomalies_hautes"}
    ids_documents = {d["id"] for d in corps["documents"]}
    assert str(document.id) in ids_documents


# --------------------------------------------------------------------------
# `GET /api/a-regler/compte` (revue finale de la refonte du front)
# --------------------------------------------------------------------------


async def test_compte_a_regler_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(app_test, "GET", "/api/a-regler/compte", cookie=None)

    assert reponse.status_code == 401


async def test_compte_a_regler_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.compte1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(app_test, "GET", "/api/a-regler/compte", cookie=cookie)

    assert reponse.status_code == 403


def _regler_drapeaux(
    monkeypatch: pytest.MonkeyPatch,
    *,
    prix_actif: bool,
    livre_non_facture_actif: bool = True,
) -> None:
    """Constat mineur 5 de la revue des contrôles de prix : `GET /api/
    a-regler/compte` traverse `ingest.commun.controle_prix_actif` (jamais la
    dépendance FastAPI de `get_settings`, court-circuitée pour ce module,
    voir son docstring) -- monkeypatcher `commun.get_settings` rend
    l'assertion déterministe, plutôt que de dépendre de l'absence de
    `CONTROLE_PRIX_ACTIF`/`CONTROLE_LIVRE_NON_FACTURE_ACTIF` dans le `.env`
    de test (qui pourrait changer sans casser ce test au bon endroit). Noms
    de paramètres différents des attributs posés (même idiome que
    `test_controle_prix._regler_controle_prix`) : un corps de classe qui
    réassigne un nom déjà lié dans la portée englobante le rendrait local à
    la classe avant même la lecture du membre de droite."""

    class _SettingsInventee:
        controle_prix_actif = prix_actif
        controle_livre_non_facture_actif = livre_non_facture_actif

    monkeypatch.setattr(commun, "get_settings", lambda: _SettingsInventee())


async def test_compte_a_regler_admin_compte_la_liste_de_l_ecran(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _regler_drapeaux(monkeypatch, prix_actif=False)
    admin = await _creer_utilisateur(
        db_session, email="admin.compte1@example.invalid", role="admin"
    )
    await _creer_document(db_session)
    await _creer_document(db_session, statut="recu")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/a-regler/compte", cookie=cookie)

    assert reponse.status_code == 200
    # Un seul document « à vérifier », aucune anomalie : 1 problème, 0 urgent.
    assert reponse.json() == {
        "nb_problemes": 1,
        "nb_urgents": 0,
        "controle_prix_actif": False,
        "controle_livre_non_facture_actif": True,
    }


async def test_compte_a_regler_reflete_controle_prix_actif_quand_vrai(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contre-épreuve du test ci-dessus : les deux valeurs du drapeau sont
    couvertes, aucune des deux par la seule absence d'une variable du
    `.env` de test."""
    _regler_drapeaux(monkeypatch, prix_actif=True)
    admin = await _creer_utilisateur(
        db_session, email="admin.compte2@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/a-regler/compte", cookie=cookie)

    assert reponse.status_code == 200
    assert reponse.json()["controle_prix_actif"] is True


async def test_compte_a_regler_reflete_controle_livre_non_facture_actif_quand_faux(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constat 1 de la relecture de l'évolution « R06 désactivée » :
    `controle_livre_non_facture_actif`, second drapeau indépendant de
    `controle_prix_actif`, exposé par le même point unique -- les deux
    valeurs sont couvertes, aucune des deux par la seule absence d'une
    variable du `.env` de test."""
    _regler_drapeaux(monkeypatch, prix_actif=True, livre_non_facture_actif=False)
    admin = await _creer_utilisateur(
        db_session, email="admin.compte3@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/a-regler/compte", cookie=cookie)

    assert reponse.status_code == 200
    assert reponse.json()["controle_livre_non_facture_actif"] is False
