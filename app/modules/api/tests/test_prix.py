"""Tests de `GET/POST /api/prix/...` (phase 3, tâche P8) : autorisation
(agent 403, anonyme 401), traduction des erreurs de `ingest.prix_bl` en
codes HTTP (409, 422), contrôle d'origine sur les `POST`.

Même harnais que `app/modules/api/tests/test_grilles.py` (`FastAPI` isolé,
`ControleOrigineMiddleware`, cookies de session réels) -- les scénarios
métier détaillés (regroupement, validation, recontrôle) vivent dans
`app/modules/ingest/tests/test_prix_page.py`, seul endroit autorisé à
importer `rules`/`normalize` (garde `tests/test_frontieres.py`)."""

from __future__ import annotations

import itertools
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.origine import ControleOrigineMiddleware
from app.modules.api import router as api_router
from app.modules.ingest.models import Document, Fournisseur, Ligne, Utilisateur
from app.modules.ingest.parametres import modifier_parametre
from app.modules.ingest.prix_bl import controler_prix_bl

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_MOT_DE_PASSE = "mot-de-passe-invente-1234"

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.79.0.{next(_IPS)}"


def _app_test(sessions: async_sessionmaker[AsyncSession]) -> FastAPI:
    app_test = FastAPI()
    app_test.add_middleware(ControleOrigineMiddleware)
    app_test.state.sessions = sessions
    app_test.include_router(auth_router)
    app_test.include_router(api_router)
    return app_test


async def _creer_utilisateur(
    db_session: AsyncSession, *, email: str, role: str
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email,
        hashed_password=PasswordHelper().hash(_MOT_DE_PASSE),
        role=role,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _creer_fournisseur(db_session: AsyncSession) -> Fournisseur:
    fournisseur = Fournisseur(nom=f"Fournisseur API prix {uuid.uuid4()}")
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_bon_en_alerte(
    db_session: AsyncSession, *, fournisseur: Fournisseur
) -> Ligne:
    """Un bon avec une ligne sans référence ni grille -> R22 (« absent de la
    grille »), sans dépendre du reste de la grille pour ce test d'API."""
    await modifier_parametre(db_session, "prix_controle_bl_actif", "1", auteur_id=None)
    document = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        numero=f"L-{uuid.uuid4()}",
        fournisseur_id=fournisseur.id,
        date_doc=date(2026, 6, 1),
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)

    ligne = Ligne(
        document_id=document.id,
        type_ligne="article",
        article_brut="Produit inventé pour l'API",
        pu_ht=Decimal("10.00"),
        ordre=0,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()
    return ligne


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
# Autorisation.
# --------------------------------------------------------------------------


async def test_alertes_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession],
) -> None:
    app_test = _app_test(sessions_test)

    reponse = await _requete(app_test, "GET", "/api/prix/alertes", cookie=None)

    assert reponse.status_code == 401


async def test_alertes_agent_renvoie_403(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.prix.api@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="agent.prix.api@example.invalid")

    reponse = await _requete(app_test, "GET", "/api/prix/alertes", cookie=cookie)

    assert reponse.status_code == 403


async def test_valider_agent_renvoie_403(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.prix.valider@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="agent.prix.valider@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        "/api/prix/valider",
        cookie=cookie,
        json={"anomalie_ids": [str(uuid.uuid4())], "ligne_id": str(uuid.uuid4())},
    )

    assert reponse.status_code == 403


# --------------------------------------------------------------------------
# Contrôle d'origine.
# --------------------------------------------------------------------------


async def test_valider_origine_etrangere_refusee_403(
    sessions_test: async_sessionmaker[AsyncSession],
) -> None:
    app_test = _app_test(sessions_test)

    reponse = await _requete(
        app_test,
        "POST",
        "/api/prix/valider",
        cookie=None,
        headers={"Origin": "https://evil.example"},
        json={"anomalie_ids": [str(uuid.uuid4())], "ligne_id": str(uuid.uuid4())},
    )

    assert reponse.status_code == 403
    assert reponse.json() == {"detail": "Origine refusée."}


# --------------------------------------------------------------------------
# Parcours complet : liste, valider (200), contester sans commentaire (422),
# 409 sur une alerte déjà réglée.
# --------------------------------------------------------------------------


async def test_liste_puis_ignorer_puis_409(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.prix.api@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_bon_en_alerte(db_session, fournisseur=fournisseur)

    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="admin.prix.api@example.invalid")

    reponse = await _requete(app_test, "GET", "/api/prix/alertes", cookie=cookie)
    assert reponse.status_code == 200
    produits = reponse.json()
    assert len(produits) == 1
    anomalie_ids = produits[0]["anomalie_ids"]

    reponse = await _requete(
        app_test,
        "POST",
        "/api/prix/ignorer",
        cookie=cookie,
        json={"anomalie_ids": anomalie_ids},
    )
    assert reponse.status_code == 200
    assert reponse.json() == {"nb_alertes_reglees": 1}

    # La même alerte, déjà réglée : 409, rien de modifié.
    reponse = await _requete(
        app_test,
        "POST",
        "/api/prix/contester",
        cookie=cookie,
        json={"anomalie_ids": anomalie_ids, "commentaire": "peu importe"},
    )
    assert reponse.status_code == 409

    # La liste est bien vide à présent.
    reponse = await _requete(app_test, "GET", "/api/prix/alertes", cookie=cookie)
    assert reponse.json() == []


async def test_contester_sans_commentaire_renvoie_422(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.prix.422@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_bon_en_alerte(db_session, fournisseur=fournisseur)

    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="admin.prix.422@example.invalid")

    reponse = await _requete(app_test, "GET", "/api/prix/alertes", cookie=cookie)
    anomalie_ids = reponse.json()[0]["anomalie_ids"]

    reponse = await _requete(
        app_test,
        "POST",
        "/api/prix/contester",
        cookie=cookie,
        json={"anomalie_ids": anomalie_ids, "commentaire": ""},
    )
    assert reponse.status_code == 422


async def test_valider_prix_200_puis_recontrole(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.prix.valider@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    ligne = await _creer_bon_en_alerte(db_session, fournisseur=fournisseur)

    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="admin.prix.valider@example.invalid")

    reponse = await _requete(app_test, "GET", "/api/prix/alertes", cookie=cookie)
    produit = reponse.json()[0]

    reponse = await _requete(
        app_test,
        "POST",
        "/api/prix/valider",
        cookie=cookie,
        json={"anomalie_ids": produit["anomalie_ids"], "ligne_id": str(ligne.id)},
    )
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["nb_alertes_reglees"] == 1
    assert corps["prix_net"] == "10.0000"

    reponse = await _requete(app_test, "POST", "/api/prix/recontrole", cookie=cookie)
    assert reponse.status_code == 200
    assert "nb_bons" in reponse.json()
