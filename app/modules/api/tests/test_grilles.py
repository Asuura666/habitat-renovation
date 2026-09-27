"""Tests de `POST/GET /api/grilles/...` (phase 3, tâche P4) : autorisation
(agent 403, anonyme 401), taille bornée (413), traduction des erreurs de
`ingest.grilles` en codes HTTP, contrôle d'origine sur les `POST`, en-tête
`Content-Disposition` du modèle.

Même harnais que `app/modules/api/tests/test_factures.py` (`FastAPI`
isolé, `ControleOrigineMiddleware`, cookies de session réels) -- les
scénarios métier détaillés (comparaison au prix en vigueur, historique
inaltérable, écriture disque) vivent dans
`app/modules/ingest/tests/test_grilles.py`, seul endroit autorisé à
importer `extract`/`normalize` (garde `tests/test_frontieres.py`)."""

from __future__ import annotations

import io
import itertools
import uuid
from pathlib import Path
from typing import Any

import httpx
import openpyxl
import pytest
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.config import get_settings
from app.core.origine import ControleOrigineMiddleware
from app.modules.api import router as api_router
from app.modules.ingest.models import Fournisseur, GrillePrix, Utilisateur

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.78.0.{next(_IPS)}"


def _classeur_grille(contenu: bytes | None = None) -> bytes:
    if contenu is not None:
        return contenu
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    assert feuille is not None
    feuille.title = "Grille"
    feuille.append(
        ("Référence", "Désignation", "Unité", "Prix unitaire HT (€)", "Remise %")
    )
    feuille.append(("REF-1", "Produit inventé", "sac", 5.5, None))
    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


def _app_test(sessions: async_sessionmaker[AsyncSession], docs_dir: Path) -> FastAPI:
    app_test = FastAPI()
    app_test.add_middleware(ControleOrigineMiddleware)
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


async def _creer_fournisseur(db_session: AsyncSession) -> Fournisseur:
    fournisseur = Fournisseur(nom=f"Fournisseur test {uuid.uuid4()}")
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


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
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=(_ip_isolee(), 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.request(methode, chemin, headers=headers or {}, **kwargs)


# --------------------------------------------------------------------------
# Autorisation (échantillon : une route GET, une route POST)
# --------------------------------------------------------------------------


async def test_modele_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(app_test, "GET", "/api/grilles/modele", cookie=None)

    assert reponse.status_code == 401


async def test_modele_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.grilles@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.grilles@example.invalid")

    reponse = await _requete(app_test, "GET", "/api/grilles/modele", cookie=cookie)

    assert reponse.status_code == 403


async def test_modele_admin_recoit_le_fichier_avec_content_disposition(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.modele@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.modele@example.invalid")

    reponse = await _requete(app_test, "GET", "/api/grilles/modele", cookie=cookie)

    assert reponse.status_code == 200
    assert (
        reponse.headers["content-disposition"]
        == 'attachment; filename="modele-grille-de-prix.xlsx"'
    )


async def test_enregistrer_prix_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{uuid.uuid4()}/prix",
        cookie=None,
        json={"designation": "Produit", "prix_ht": "5.00", "date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 401


async def test_enregistrer_prix_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.prix@example.invalid", role="agent"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.prix@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/prix",
        cookie=cookie,
        json={"designation": "Produit", "prix_ht": "5.00", "date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 403


# --------------------------------------------------------------------------
# Contrôle d'origine (un `POST`, un `GET`)
# --------------------------------------------------------------------------


async def test_enregistrer_prix_origine_etrangere_refusee_403(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{uuid.uuid4()}/prix",
        cookie=None,
        headers={"Origin": "https://evil.example"},
        json={"designation": "Produit", "prix_ht": "5.00", "date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 403
    assert reponse.json() == {"detail": "Origine refusée."}


# --------------------------------------------------------------------------
# 404 fournisseur inconnu
# --------------------------------------------------------------------------


async def test_grille_fournisseur_inconnu_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.404@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.404@example.invalid")

    reponse = await _requete(
        app_test, "GET", f"/api/grilles/fournisseurs/{uuid.uuid4()}", cookie=cookie
    )

    assert reponse.status_code == 404


async def test_historique_produit_inconnu_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.404hist@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.404hist@example.invalid")

    reponse = await _requete(
        app_test,
        "GET",
        f"/api/grilles/fournisseurs/{fournisseur.id}/produits/nom:jamais-vu/historique",
        cookie=cookie,
    )

    assert reponse.status_code == 404


# --------------------------------------------------------------------------
# Saisie : succès, 422 (prix invalide, prix inchangé)
# --------------------------------------------------------------------------


async def test_enregistrer_prix_succes_201(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.saisie@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.saisie@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/prix",
        cookie=cookie,
        json={
            "designation": "Produit saisi",
            "prix_ht": "9.90",
            "date_effet": "2026-01-01",
        },
    )

    assert reponse.status_code == 201
    assert reponse.json()["prix_net"] == "9.9000"


async def test_enregistrer_prix_negatif_renvoie_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.422saisie@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.422saisie@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/prix",
        cookie=cookie,
        json={"designation": "Produit", "prix_ht": "-1.00", "date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 422


# --------------------------------------------------------------------------
# Retrait : 404 produit inconnu
# --------------------------------------------------------------------------


async def test_retirer_produit_inconnu_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.retrait404@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.retrait404@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/retrait",
        cookie=cookie,
        json={"cle_produit": "nom:jamais-vu", "date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 404


# --------------------------------------------------------------------------
# Import : 413, 422 (fichier invalide), 201, aucune ligne valide -> 422
# --------------------------------------------------------------------------


async def test_import_apercu_fichier_trop_volumineux_413(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.413grille@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.413grille@example.invalid")
    contenu_trop_gros = b"PK\x03\x04" + b"0" * (5 * 1024 * 1024)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/import/apercu",
        cookie=cookie,
        files={
            "fichier": ("grille.xlsx", contenu_trop_gros, "application/octet-stream")
        },
        data={"date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 413


async def test_import_apercu_fichier_invalide_renvoie_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.422grille@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.422grille@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/import/apercu",
        cookie=cookie,
        files={"fichier": ("grille.xlsx", b"pas-un-xlsx", "application/octet-stream")},
        data={"date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 422


async def test_import_succes_201(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.import201@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.import201@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/import",
        cookie=cookie,
        files={
            "fichier": (
                "grille.xlsx",
                _classeur_grille(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 201
    assert reponse.json()["nb_nouveaux"] == 1


async def test_import_aucune_ligne_valide_renvoie_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.422vide@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.422vide@example.invalid")

    classeur = openpyxl.Workbook()
    feuille = classeur.active
    assert feuille is not None
    feuille.append(
        ("Référence", "Désignation", "Unité", "Prix unitaire HT (€)", "Remise %")
    )
    tampon = io.BytesIO()
    classeur.save(tampon)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/import",
        cookie=cookie,
        files={
            "fichier": (
                "grille.xlsx",
                tampon.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 422
    assert (await db_session.execute(select(GrillePrix))).scalars().all() == []
