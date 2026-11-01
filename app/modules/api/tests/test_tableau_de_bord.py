"""Tests de `GET /api/tableau-de-bord` (refonte front T2) : autorisation,
`mois` obligatoire, forme JSON -- voir `app/modules/ingest/tests/
test_tableau_de_bord.py` pour les scénarios métier détaillés des règles de
calcul (déjà commité, non modifié ici).

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3) : droits
d'accès, `mois` obligatoire (422 si absent, contrairement à `GET
/api/bilan/chantiers`), forme JSON des montants (chaînes, jamais un nombre)
et absence de 404 sur un mois sans donnée.

Même schéma que `test_bilan.py`/`test_anomalies.py` : `FastAPI` isolé,
`app.state.sessions` branché sur `bl_test_t2` (arbre de travail), IP dédiées
(`10.84.0.x`, même plage que `test_bilan.py` -- brief T2) pour ne jamais
partager le quota `slowapi` du login avec un autre fichier de test exécuté
au même instant.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import date
from decimal import Decimal
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
    return f"10.84.0.{next(_IPS)}"


# --------------------------------------------------------------------------
# Aides d'application/requête (mêmes idiomes que `test_bilan.py`)
# --------------------------------------------------------------------------


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
) -> None:
    utilisateur = Utilisateur(
        email=email,
        hashed_password=_PASSWORD_HELPER.hash(_MOT_DE_PASSE),
        role=role,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()


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
    chemin: str,
    *,
    cookie: str | None,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=("10.0.7.2", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get(chemin, params=params)


# --------------------------------------------------------------------------
# Aides de construction (données inventées) -- copie réduite de celles
# d'`app/modules/ingest/tests/test_tableau_de_bord.py`, ce fichier ne
# pouvant pas importer un paquet `tests` frère (même raison que
# `test_bilan.py`).
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur API Tableau"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_facture(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    numero: str = "F-API-TDB-1",
    date_doc: date | None = date(2026, 9, 15),
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero=numero,
        fournisseur_id=fournisseur.id,
        date_doc=date_doc,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_bloc(
    db_session: AsyncSession, *, facture: Document, numero_bl: str = "L0001"
) -> BlocFacture:
    # « Conforme » strict (décision d'Ilane du 29/09/2026) : le bon existe et
    # est validé.
    bon = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        date_doc=date(2020, 1, 1),
    )
    db_session.add(bon)
    await db_session.flush()
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=0,
        numero_bl=numero_bl,
        statut_rapprochement="recu",
        bl_document_id=bon.id,
    )
    db_session.add(bloc)
    await db_session.commit()
    await db_session.refresh(bloc)
    return bloc


async def _creer_ligne(
    db_session: AsyncSession,
    *,
    document: Document,
    bloc: BlocFacture,
    montant_ht: Decimal = Decimal("100.00"),
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        bloc_id=bloc.id,
        montant_ht=montant_ht,
        type_ligne="article",
        ordre=0,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _creer_bon(
    db_session: AsyncSession,
    *,
    total_ht: Decimal | None = Decimal("100.00"),
    date_doc: date | None = date(2026, 9, 15),
    statut: str = "recu",
) -> Document:
    """Un BL reçu -- voir docstring d'`ingest.tableau_de_bord` (décision
    d'Ilane du 25/09/2026, tuile « Montant des bons reçus »). Ce fichier ne
    teste que la forme JSON, le détail des scénarios de calcul vit dans
    `app/modules/ingest/tests/test_tableau_de_bord.py`."""
    document = Document(
        type="bl",
        source="telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        total_ht=total_ht,
        date_doc=date_doc,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _scenario_simple(db_session: AsyncSession) -> None:
    """Un fournisseur, une facture de septembre avec un bloc reçu (100,00 €,
    sans chantier ni anomalie) -- le scénario minimal réutilisé par la
    plupart des tests de ce fichier."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture)
    await _creer_ligne(db_session, document=facture, bloc=bloc)


# --------------------------------------------------------------------------
# Droits (401/403/200)
# --------------------------------------------------------------------------


async def test_get_tableau_de_bord_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test, "/api/tableau-de-bord", cookie=None, params={"mois": "2026-09-01"}
    )

    assert reponse.status_code == 401


async def test_get_tableau_de_bord_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.tdb1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.tdb1@example.invalid")

    reponse = await _requete(
        app_test,
        "/api/tableau-de-bord",
        cookie=cookie,
        params={"mois": "2026-09-01"},
    )

    assert reponse.status_code == 403


async def test_get_tableau_de_bord_admin_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _scenario_simple(db_session)
    await _creer_utilisateur(
        db_session, email="admin.tdb1@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.tdb1@example.invalid")

    reponse = await _requete(
        app_test,
        "/api/tableau-de-bord",
        cookie=cookie,
        params={"mois": "2026-09-01"},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["totaux"]["conforme"] == "100.00"
    assert corps["totaux"]["facture_a_verifier"] == "0"
    assert isinstance(corps["totaux"]["conforme"], str)
    assert len(corps["chantiers"]) == 1
    assert corps["chantiers"][0]["etat"] == "a_rattacher"
    assert corps["priorites"] == []
    # Revue finale de la refonte du front (SERVEUR-1/2/7, COUVERTURE-4/26) :
    # bons à réclamer comptés par le serveur, montants conforme/à vérifier
    # par chantier, mois toujours ramené au 1er, dernier mois facturé.
    assert corps["nb_bl_manquants"] == 0
    assert corps["mois"] == "2026-09-01"
    assert corps["dernier_mois_facture"] == "2026-09-01"
    montants = corps["chantiers"][0]["montants"]
    assert montants["conforme"] == "100.00"
    assert Decimal(montants["a_verifier"]) == Decimal("0")


async def test_get_tableau_de_bord_mois_ramene_au_premier_du_mois(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Revue finale (SERVEUR-7) : le docstring du routeur promettait un
    mois ramené au 1er -- c'est désormais vrai, le service le fait."""
    await _creer_utilisateur(
        db_session, email="admin.tdb4@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.tdb4@example.invalid")

    reponse = await _requete(
        app_test,
        "/api/tableau-de-bord",
        cookie=cookie,
        params={"mois": "2026-09-17"},
    )

    assert reponse.status_code == 200
    assert reponse.json()["mois"] == "2026-09-01"


async def test_get_tableau_de_bord_mois_absent_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.tdb2@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.tdb2@example.invalid")

    reponse = await _requete(app_test, "/api/tableau-de-bord", cookie=cookie)

    assert reponse.status_code == 422


async def test_get_tableau_de_bord_mois_vide_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _scenario_simple(db_session)
    await _creer_utilisateur(
        db_session, email="admin.tdb3@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.tdb3@example.invalid")

    reponse = await _requete(
        app_test,
        "/api/tableau-de-bord",
        cookie=cookie,
        params={"mois": "2026-08-01"},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["chantiers"] == []


async def test_get_tableau_de_bord_bons_recus_champs(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Décision d'Ilane du 25/09/2026 (tuile « Montant des bons reçus ») :
    l'API renvoie les trois champs, `montant_bons_recus` en chaîne comme
    les autres montants."""
    await _creer_bon(db_session, total_ht=Decimal("150.00"))
    await _creer_bon(db_session, total_ht=None)
    await _creer_utilisateur(
        db_session, email="admin.tdb5@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.tdb5@example.invalid")

    reponse = await _requete(
        app_test,
        "/api/tableau-de-bord",
        cookie=cookie,
        params={"mois": "2026-09-01"},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["nb_bons_recus"] == 2
    assert corps["montant_bons_recus"] == "150.00"
    assert isinstance(corps["montant_bons_recus"], str)
    assert corps["nb_bons_sans_montant"] == 1


async def test_get_tableau_de_bord_bons_du_mois_champs(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Lot 2, B6 : les bons « à vérifier » comptent dans le montant des bons
    du mois ; les nouveaux champs sont distincts des anciens."""
    await _creer_bon(db_session, total_ht=Decimal("150.00"))
    await _creer_bon(db_session, statut="a_verifier", total_ht=Decimal("50.00"))
    await _creer_bon(db_session, statut="a_verifier", total_ht=None)
    await _creer_utilisateur(
        db_session, email="admin.tdb6@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.tdb6@example.invalid")

    reponse = await _requete(
        app_test,
        "/api/tableau-de-bord",
        cookie=cookie,
        params={"mois": "2026-09-01"},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["nb_bons_mois"] == 3
    assert corps["montant_bons_mois"] == "200.00"
    assert isinstance(corps["montant_bons_mois"], str)
    assert corps["nb_bons_a_verifier"] == 2
    assert corps["nb_bons_mois_sans_montant"] == 1
