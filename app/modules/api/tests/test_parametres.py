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
from app.modules.ingest import commun
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


# ---------------------------------------------------------------------------
# Fixe les deux drapeaux de contrôle plutôt que de dépendre de ceux du
# `.env` de test (même décision que `app/modules/ingest/tests/test_
# parametres.py`, ici à travers les routes HTTP) : `commun.get_settings`
# est monkeypatchée, jamais la dépendance FastAPI de `get_settings`
# (court-circuitée pour ce drapeau, voir `ingest.commun`) -- même idiome
# que `test_a_traiter.py::_regler_drapeaux`. Utilisée par tout le fichier,
# y compris `test_put_parametre_admin_modifie_et_journalise` ci-dessous,
# pour que le nombre de réglages exposés ne dépende jamais de l'état réel
# du `.env` local.
# ---------------------------------------------------------------------------


def _regler_controles(
    monkeypatch: pytest.MonkeyPatch,
    *,
    prix_actif: bool,
    livre_non_facture_actif: bool,
) -> None:
    class _SettingsInventee:
        controle_prix_actif = prix_actif
        controle_livre_non_facture_actif = livre_non_facture_actif

    monkeypatch.setattr(commun, "get_settings", lambda: _SettingsInventee())


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Les deux drapeaux sont fixés explicitement (`_regler_controles`),
    # jamais laissés à l'état du `.env` de test : le nombre de réglages
    # exposés ci-dessous ne doit dépendre que de ce que ce test règle.
    _regler_controles(monkeypatch, prix_actif=False, livre_non_facture_actif=False)
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
        # `tolerance_total_ht` : un des dix réglages qui n'appartiennent à
        # aucun des deux contrôles désactivables, avec `seuil_ressemblance_
        # chantier_pct` (avenant du 27/09/2026) (voir les tests de masquage
        # plus bas dans ce fichier) -- jamais masqué, quel que soit l'état
        # des deux drapeaux.
        modification = await client.put(
            "/api/parametres/tolerance_total_ht", json={"valeur": "6.5"}
        )

    assert liste.status_code == 200
    # Les deux contrôles étant désactivés ci-dessus, quatre des dix
    # réglages sont masqués -- voir les tests de masquage plus bas dans ce
    # fichier pour les deux drapeaux couverts indépendamment.
    assert len(liste.json()) == 6
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


async def test_get_parametres_masque_les_seuils_de_prix_quand_desactives(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _regler_controles(monkeypatch, prix_actif=False, livre_non_facture_actif=True)
    admin = await _creer_utilisateur(
        db_session, email="admin.parametres.masques@example.test", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get("/api/parametres")

    cles = {p["cle"] for p in reponse.json()}
    assert "seuil_prix_pct" not in cles
    assert "seuil_prix_fort_pct" not in cles
    assert "occurrences_prix_min" not in cles
    assert "delai_ligne_bl_non_facturee_j" in cles


async def test_get_parametres_toutes_les_cles_quand_les_deux_controles_actifs(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _regler_controles(monkeypatch, prix_actif=True, livre_non_facture_actif=True)
    admin = await _creer_utilisateur(
        db_session, email="admin.parametres.actifs@example.test", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get("/api/parametres")

    assert len(reponse.json()) == 10


async def test_put_parametre_masque_renvoie_422_comme_une_cle_inconnue(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _regler_controles(monkeypatch, prix_actif=False, livre_non_facture_actif=True)
    admin = await _creer_utilisateur(
        db_session, email="admin.parametres.put-masque@example.test", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.put(
            "/api/parametres/seuil_prix_pct", json={"valeur": "9"}
        )

    assert reponse.status_code == 422
    assert "Paramètre inconnu" in reponse.json()["detail"]


async def test_get_parametres_masque_le_seuil_r06_quand_desactive(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _regler_controles(monkeypatch, prix_actif=True, livre_non_facture_actif=False)
    admin = await _creer_utilisateur(
        db_session, email="admin.parametres.masque-r06@example.test", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get("/api/parametres")

    cles = {p["cle"] for p in reponse.json()}
    assert "delai_ligne_bl_non_facturee_j" not in cles
    assert "seuil_prix_pct" in cles
    assert "seuil_prix_fort_pct" in cles
    assert "occurrences_prix_min" in cles


async def test_put_delai_r06_masque_renvoie_422_comme_une_cle_inconnue(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _regler_controles(monkeypatch, prix_actif=True, livre_non_facture_actif=False)
    admin = await _creer_utilisateur(
        db_session, email="admin.parametres.put-masque-r06@example.test", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.put(
            "/api/parametres/delai_ligne_bl_non_facturee_j", json={"valeur": "30"}
        )

    assert reponse.status_code == 422
    assert "Paramètre inconnu" in reponse.json()["detail"]


async def test_valeur_masquee_reapparait_inchangee_a_la_reactivation(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _regler_controles(monkeypatch, prix_actif=True, livre_non_facture_actif=True)
    admin = await _creer_utilisateur(
        db_session, email="admin.parametres.reactivation@example.test", role="admin"
    )
    app = _app_test(sessions_test, tmp_path)
    cookie = await _login(app, admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        await client.put("/api/parametres/seuil_prix_pct", json={"valeur": "12"})

        _regler_controles(monkeypatch, prix_actif=False, livre_non_facture_actif=True)
        pendant_masquage = await client.get("/api/parametres")
        assert all(p["cle"] != "seuil_prix_pct" for p in pendant_masquage.json())

        _regler_controles(monkeypatch, prix_actif=True, livre_non_facture_actif=True)
        apres_reactivation = await client.get("/api/parametres")

    seuil = next(p for p in apres_reactivation.json() if p["cle"] == "seuil_prix_pct")
    assert seuil["valeur"] == "12"
