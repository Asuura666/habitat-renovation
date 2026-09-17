"""Tests de `GET /api/factures`, `GET /api/factures/{id}` et
`GET /api/factures/{id}/fichier` (L2-T5) : autorisation, forme JSON, 404.

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3) : les scénarios
métier détaillés (tri, somme des blocs, correspondance BL, chemin hors
`docs_dir`) vivent dans `app/modules/ingest/tests/test_lecture.py`, le seul
endroit autorisé à construire directement les objets ORM métier avec leurs
règles (`api` ne peut importer que `app.core` et `app.modules.ingest`).

Même schéma que `test_factures.py` : `FastAPI` isolé, `app.state.sessions`
branché sur `bl_test`, IP dédiées (`10.78.0.x`) pour ne jamais partager le
quota `slowapi` du login avec un autre fichier de test.
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
from app.modules.ingest.models import (
    BlocFacture,
    Document,
    Fournisseur,
    Ligne,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.78.0.{next(_IPS)}"


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


async def _login(app_test: FastAPI, *, email: str) -> str | None:
    transport = ASGITransport(app=app_test, client=(_ip_isolee(), 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.post(
            "/api/auth/login", data={"username": email, "password": _MOT_DE_PASSE}
        )
    assert reponse.status_code == 204
    return reponse.cookies.get(NOM_COOKIE)


async def _get(app_test: FastAPI, chemin: str, *, cookie: str | None) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=("10.0.1.1", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get(chemin)


async def _creer_facture_avec_bloc(
    db_session: AsyncSession,
    *,
    numero: str = "FAC-LECTURE-0001",
    fichier_path: str = "/var/docs/facture-lecture-invente.pdf",
) -> Document:
    fournisseur = Fournisseur(nom="Unikalo")
    db_session.add(fournisseur)
    await db_session.flush()

    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=fichier_path,
        fournisseur_id=fournisseur.id,
        numero=numero,
        total_ht=None,
    )
    db_session.add(document)
    await db_session.flush()

    bloc = BlocFacture(
        facture_id=document.id, ordre=0, numero_bl="L500", chantier_brut="CHANTIER"
    )
    db_session.add(bloc)
    await db_session.flush()

    db_session.add(
        Ligne(
            document_id=document.id,
            bloc_id=bloc.id,
            article_brut="Article inventé",
            type_ligne="article",
            ordre=0,
            montant_ht="12.50",
        )
    )
    await db_session.commit()
    await db_session.refresh(document)
    return document


# --------------------------------------------------------------------------
# GET /api/factures — liste
# --------------------------------------------------------------------------


async def test_liste_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _get(app_test, "/api/factures", cookie=None)

    assert reponse.status_code == 401


async def test_liste_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.liste@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.liste@example.invalid")

    reponse = await _get(app_test, "/api/factures", cookie=cookie)

    assert reponse.status_code == 403


async def test_liste_admin_renvoie_les_factures_avec_les_bons_champs(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.liste@example.invalid", role="admin"
    )
    document = await _creer_facture_avec_bloc(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.liste@example.invalid")

    reponse = await _get(app_test, "/api/factures", cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps) == 1
    facture = corps[0]
    assert facture["id"] == str(document.id)
    assert facture["numero"] == "FAC-LECTURE-0001"
    assert facture["fournisseur"] == "Unikalo"
    assert facture["nb_blocs"] == 1
    assert facture["nb_blocs_recus"] == 0
    assert set(facture.keys()) == {
        "id",
        "numero",
        "fournisseur",
        "date_doc",
        "total_ht",
        "nb_blocs",
        "nb_blocs_recus",
        "cree_le",
    }


# --------------------------------------------------------------------------
# GET /api/factures/{id} — détail
# --------------------------------------------------------------------------


async def test_detail_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _get(
        app_test, "/api/factures/00000000-0000-0000-0000-000000000000", cookie=None
    )

    assert reponse.status_code == 401


async def test_detail_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.detail@example.invalid", role="agent"
    )
    document = await _creer_facture_avec_bloc(db_session, numero="FAC-DETAIL-403")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.detail@example.invalid")

    reponse = await _get(app_test, f"/api/factures/{document.id}", cookie=cookie)

    assert reponse.status_code == 403


async def test_detail_id_absent_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.404detail@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.404detail@example.invalid")

    reponse = await _get(
        app_test, "/api/factures/00000000-0000-0000-0000-000000000000", cookie=cookie
    )

    assert reponse.status_code == 404


async def test_detail_admin_renvoie_len_tete_et_les_blocs(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.detail@example.invalid", role="admin"
    )
    document = await _creer_facture_avec_bloc(db_session, numero="FAC-DETAIL-OK")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.detail@example.invalid")

    reponse = await _get(app_test, f"/api/factures/{document.id}", cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["numero"] == "FAC-DETAIL-OK"
    assert len(corps["blocs"]) == 1
    bloc = corps["blocs"][0]
    assert bloc["numero_bl"] == "L500"
    assert bloc["bl_recu"] is False
    assert bloc["bl_document_id"] is None
    assert bloc["montant_ht"] == "12.50"
    assert len(bloc["lignes"]) == 1
    assert bloc["lignes"][0]["article_brut"] == "Article inventé"


# --------------------------------------------------------------------------
# GET /api/factures/{id}/fichier
# --------------------------------------------------------------------------


async def test_fichier_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.fichier@example.invalid", role="agent"
    )
    document = await _creer_facture_avec_bloc(db_session, numero="FAC-FICHIER-403")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.fichier@example.invalid")

    reponse = await _get(
        app_test, f"/api/factures/{document.id}/fichier", cookie=cookie
    )

    assert reponse.status_code == 403


async def test_fichier_id_absent_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.404fichier@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.404fichier@example.invalid")

    reponse = await _get(
        app_test,
        "/api/factures/00000000-0000-0000-0000-000000000000/fichier",
        cookie=cookie,
    )

    assert reponse.status_code == 404


async def test_fichier_admin_renvoie_le_pdf(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chemin = tmp_path / "facture-lecture.pdf"
    chemin.write_bytes(b"%PDF-1.4\ncontenu-invente")
    await _creer_utilisateur(
        db_session, email="admin.fichierok@example.invalid", role="admin"
    )
    document = await _creer_facture_avec_bloc(
        db_session, numero="FAC-FICHIER-OK", fichier_path=str(chemin)
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.fichierok@example.invalid")

    reponse = await _get(
        app_test, f"/api/factures/{document.id}/fichier", cookie=cookie
    )

    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "application/pdf"
    assert reponse.content == b"%PDF-1.4\ncontenu-invente"
