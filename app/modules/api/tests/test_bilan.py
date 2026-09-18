"""Tests de `GET /api/bilan/...` (L5-T3) : autorisation, filtres, formes
particulières -- voir `app/modules/ingest/tests/test_bilan.py` pour les
scénarios métier détaillés des quatre montants (L5-D3, déjà commité, non
modifié ici).

Ce fichier ne teste que les routeurs (couche d'entrée, L2-D3) : droits
d'accès, transmission des filtres `mois`/`agence`, validation 422 d'un mois
mal formé, absence de 404 sur un chantier/fournisseur inconnu, forme JSON
des montants (chaînes, jamais un nombre) et des lignes à identifiant nul.

Même schéma que `test_anomalies.py`/`test_referentiels.py` : `FastAPI`
isolé, `app.state.sessions` branché sur `bl_test`, IP dédiées (`10.84.0.x`)
pour ne jamais partager le quota `slowapi` du login avec un autre fichier de
test. `GET /api/bilan/agences` n'est pas testée ici : la route n'est pas
exposée par ce module (voir le docstring d'`api/bilan.py`).
"""

from __future__ import annotations

import itertools
import json
import re
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
    Chantier,
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
# Aides d'application/requête (mêmes idiomes que `test_anomalies.py`)
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
    transport = ASGITransport(app=app_test, client=("10.0.7.1", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get(chemin, params=params)


# --------------------------------------------------------------------------
# Aides de construction (données inventées) -- copie réduite de celles
# d'`app/modules/ingest/tests/test_bilan.py`, ce fichier ne pouvant pas
# importer un paquet `tests` frère (même raison que `test_anomalies.py`).
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur API Bilan"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_chantier(
    db_session: AsyncSession,
    *,
    nom: str = "Chantier API Bilan",
    agence: str | None = None,
) -> Chantier:
    chantier = Chantier(nom_canonique=nom, agence=agence)
    db_session.add(chantier)
    await db_session.commit()
    await db_session.refresh(chantier)
    return chantier


async def _creer_facture(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur | None,
    numero: str = "F0001",
    date_doc: date | None = date(2026, 7, 15),
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero=numero,
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
        date_doc=date_doc,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_bloc(
    db_session: AsyncSession,
    *,
    facture: Document,
    numero_bl: str | None = "L0001",
    chantier_id: uuid.UUID | None = None,
    statut_rapprochement: str | None = "recu",
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=0,
        numero_bl=numero_bl,
        chantier_id=chantier_id,
        statut_rapprochement=statut_rapprochement,
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


async def _scenario_simple(
    db_session: AsyncSession,
    *,
    agence: str | None = None,
    date_doc: date | None = date(2026, 7, 15),
    montant_ht: Decimal = Decimal("100.00"),
    fournisseur: Fournisseur | None = None,
) -> tuple[Chantier, Fournisseur, BlocFacture]:
    """Un chantier, un fournisseur, une facture avec un bloc et une ligne
    (données inventées) -- le scénario minimal réutilisé par la plupart des
    tests de ce fichier."""
    chantier = await _creer_chantier(db_session, agence=agence)
    if fournisseur is None:
        fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, date_doc=date_doc
    )
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(db_session, document=facture, bloc=bloc, montant_ht=montant_ht)
    return chantier, fournisseur, bloc


def _trouver(
    lignes: list[dict[str, object]], cle: str, valeur: object
) -> dict[str, object]:
    """La première ligne dont `cle == valeur` -- lève si absente (aide de
    lisibilité pour les assertions ci-dessous)."""
    for ligne in lignes:
        if ligne[cle] == valeur:
            return ligne
    raise AssertionError(f"aucune ligne avec {cle}={valeur!r}")


# --------------------------------------------------------------------------
# Droits (401/403/200) -- une route sur les quatre exposées par ce module
# --------------------------------------------------------------------------


async def test_get_bilan_chantiers_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(app_test, "/api/bilan/chantiers", cookie=None)

    assert reponse.status_code == 401


async def test_get_bilan_chantiers_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.bilan1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.bilan1@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/chantiers", cookie=cookie)

    assert reponse.status_code == 403


async def test_get_bilan_chantiers_admin_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _scenario_simple(db_session)
    await _creer_utilisateur(
        db_session, email="admin.bilan1@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bilan1@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/chantiers", cookie=cookie)

    assert reponse.status_code == 200
    assert len(reponse.json()) == 1


async def test_get_bilan_fournisseurs_du_chantier_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test, f"/api/bilan/chantiers/{uuid.uuid4()}/fournisseurs", cookie=None
    )

    assert reponse.status_code == 401


async def test_get_bilan_fournisseurs_du_chantier_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.bilan2@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.bilan2@example.invalid")

    reponse = await _requete(
        app_test, f"/api/bilan/chantiers/{uuid.uuid4()}/fournisseurs", cookie=cookie
    )

    assert reponse.status_code == 403


async def test_get_bilan_fournisseurs_du_chantier_admin_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chantier, fournisseur, _bloc = await _scenario_simple(db_session)
    await _creer_utilisateur(
        db_session, email="admin.bilan2@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bilan2@example.invalid")

    reponse = await _requete(
        app_test, f"/api/bilan/chantiers/{chantier.id}/fournisseurs", cookie=cookie
    )

    assert reponse.status_code == 200
    lignes = reponse.json()
    assert len(lignes) == 1
    assert lignes[0]["fournisseur_id"] == str(fournisseur.id)


async def test_get_bilan_fournisseurs_du_chantier_inconnu_liste_vide(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Décision du contrôleur : un chantier inconnu est une vue vide, pas
    une ressource absente -- 200, jamais 404."""
    await _creer_utilisateur(
        db_session, email="admin.bilan3@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bilan3@example.invalid")

    reponse = await _requete(
        app_test, f"/api/bilan/chantiers/{uuid.uuid4()}/fournisseurs", cookie=cookie
    )

    assert reponse.status_code == 200
    assert reponse.json() == []


async def test_get_bilan_bl_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test,
        f"/api/bilan/chantiers/{uuid.uuid4()}/fournisseurs/{uuid.uuid4()}/bl",
        cookie=None,
    )

    assert reponse.status_code == 401


async def test_get_bilan_bl_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.bilan3@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.bilan3@example.invalid")

    reponse = await _requete(
        app_test,
        f"/api/bilan/chantiers/{uuid.uuid4()}/fournisseurs/{uuid.uuid4()}/bl",
        cookie=cookie,
    )

    assert reponse.status_code == 403


async def test_get_bilan_bl_admin_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chantier, fournisseur, bloc = await _scenario_simple(db_session)
    await _creer_utilisateur(
        db_session, email="admin.bilan4@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bilan4@example.invalid")

    reponse = await _requete(
        app_test,
        f"/api/bilan/chantiers/{chantier.id}/fournisseurs/{fournisseur.id}/bl",
        cookie=cookie,
    )

    assert reponse.status_code == 200
    lignes = reponse.json()
    assert len(lignes) == 1
    assert lignes[0]["bloc_id"] == str(bloc.id)


async def test_get_bilan_fournisseurs_global_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(app_test, "/api/bilan/fournisseurs", cookie=None)

    assert reponse.status_code == 401


async def test_get_bilan_fournisseurs_global_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.bilan4@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.bilan4@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/fournisseurs", cookie=cookie)

    assert reponse.status_code == 403


async def test_get_bilan_fournisseurs_global_admin_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    _chantier, fournisseur, _bloc = await _scenario_simple(db_session)
    await _creer_utilisateur(
        db_session, email="admin.bilan5@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bilan5@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/fournisseurs", cookie=cookie)

    assert reponse.status_code == 200
    lignes = reponse.json()
    assert len(lignes) == 1
    assert lignes[0]["fournisseur_id"] == str(fournisseur.id)


# --------------------------------------------------------------------------
# Filtres `mois`/`agence`
# --------------------------------------------------------------------------


async def test_get_bilan_chantiers_filtre_mois_change_le_resultat(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chantier = await _creer_chantier(db_session)
    fournisseur = await _creer_fournisseur(db_session)
    facture_juillet = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-JUIL", date_doc=date(2026, 7, 15)
    )
    bloc_juillet = await _creer_bloc(
        db_session, facture=facture_juillet, chantier_id=chantier.id
    )
    await _creer_ligne(
        db_session,
        document=facture_juillet,
        bloc=bloc_juillet,
        montant_ht=Decimal("100.00"),
    )
    facture_aout = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-AOUT", date_doc=date(2026, 8, 3)
    )
    bloc_aout = await _creer_bloc(
        db_session, facture=facture_aout, chantier_id=chantier.id
    )
    await _creer_ligne(
        db_session, document=facture_aout, bloc=bloc_aout, montant_ht=Decimal("250.00")
    )
    await _creer_utilisateur(
        db_session, email="admin.bilan6@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bilan6@example.invalid")

    reponse_juillet = await _requete(
        app_test, "/api/bilan/chantiers", cookie=cookie, params={"mois": "2026-07-01"}
    )
    reponse_aout = await _requete(
        app_test, "/api/bilan/chantiers", cookie=cookie, params={"mois": "2026-08-01"}
    )

    assert reponse_juillet.status_code == 200
    assert reponse_aout.status_code == 200
    ligne_juillet = _trouver(reponse_juillet.json(), "chantier_id", str(chantier.id))
    ligne_aout = _trouver(reponse_aout.json(), "chantier_id", str(chantier.id))
    montants_juillet = ligne_juillet["montants"]
    montants_aout = ligne_aout["montants"]
    assert isinstance(montants_juillet, dict)
    assert isinstance(montants_aout, dict)
    assert montants_juillet["facture_ht"] == "100.00"
    assert montants_aout["facture_ht"] == "250.00"


async def test_get_bilan_chantiers_mois_malforme_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.bilan7@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bilan7@example.invalid")

    reponse = await _requete(
        app_test, "/api/bilan/chantiers", cookie=cookie, params={"mois": "pas-une-date"}
    )

    assert reponse.status_code == 422


async def test_get_bilan_chantiers_filtre_agence_change_le_resultat(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    chantier_nord, _f1, _b1 = await _scenario_simple(
        db_session, agence="Agence Nord Inventee", montant_ht=Decimal("100.00")
    )
    chantier_sud, _f2, _b2 = await _scenario_simple(
        db_session, agence="Agence Sud Inventee", montant_ht=Decimal("50.00")
    )
    await _creer_utilisateur(
        db_session, email="admin.bilan8@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bilan8@example.invalid")

    reponse_sans_filtre = await _requete(
        app_test, "/api/bilan/chantiers", cookie=cookie
    )
    reponse_nord = await _requete(
        app_test,
        "/api/bilan/chantiers",
        cookie=cookie,
        params={"agence": "Agence Nord Inventee"},
    )

    assert reponse_sans_filtre.status_code == 200
    assert reponse_nord.status_code == 200
    ids_sans_filtre = {ligne["chantier_id"] for ligne in reponse_sans_filtre.json()}
    ids_nord = {ligne["chantier_id"] for ligne in reponse_nord.json()}
    assert ids_sans_filtre == {str(chantier_nord.id), str(chantier_sud.id)}
    assert ids_nord == {str(chantier_nord.id)}


# --------------------------------------------------------------------------
# Forme JSON : montants en chaînes, ligne à identifiant nul
# --------------------------------------------------------------------------


async def test_get_bilan_chantiers_montants_sont_des_chaines_dans_le_json_brut(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _scenario_simple(db_session, montant_ht=Decimal("123.45"))
    await _creer_utilisateur(
        db_session, email="admin.bilan9@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bilan9@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/chantiers", cookie=cookie)

    assert reponse.status_code == 200
    # Lecture du JSON brut (pas seulement l'objet désérialisé, décision du
    # contrôleur) : un nombre bare (`123.45`) ne serait jamais entouré de
    # guillemets dans le texte de la réponse, contrairement à une chaîne.
    assert re.search(r'"facture_ht"\s*:\s*"123\.45"', reponse.text) is not None
    lignes_brutes = json.loads(reponse.text)
    montants = lignes_brutes[0]["montants"]
    for cle in ("facture_ht", "rapproche", "en_ecart", "non_justifie"):
        assert isinstance(montants[cle], str), (
            f"{cle} n'est pas une chaîne dans le JSON"
        )
    assert isinstance(montants["nb_anomalies_ouvertes"], int)


async def test_get_bilan_chantiers_ligne_chantier_non_resolu_serialisee(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Un bloc sans chantier résolu (`BlocFacture.chantier_id=None` et
    `Document.chantier_id=None`, jamais rempli pour une facture) doit
    apparaître dans une ligne `chantier_id=None`, pas disparaître ni faire
    échouer la sérialisation (point signalé explicitement par le
    contrôleur)."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=None)
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("42.00")
    )
    await _creer_utilisateur(
        db_session, email="admin.bilan10@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bilan10@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/chantiers", cookie=cookie)

    assert reponse.status_code == 200
    lignes = reponse.json()
    assert len(lignes) == 1
    ligne = lignes[0]
    assert ligne["chantier_id"] is None
    assert ligne["nom_canonique"] is None
    assert ligne["agence"] is None
    assert ligne["montants"]["facture_ht"] == "42.00"


async def test_get_bilan_fournisseurs_global_ligne_fournisseur_non_resolu_serialisee(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Même principe côté fournisseur : une facture sans `fournisseur_id`
    doit apparaître dans une ligne `fournisseur_id=None` de la vue inverse,
    jamais perdue."""
    facture = await _creer_facture(db_session, fournisseur=None, numero="F-SANS-FOURN")
    chantier = await _creer_chantier(db_session)
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("77.00")
    )
    await _creer_utilisateur(
        db_session, email="admin.bilan11@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bilan11@example.invalid")

    reponse = await _requete(app_test, "/api/bilan/fournisseurs", cookie=cookie)

    assert reponse.status_code == 200
    lignes = reponse.json()
    assert len(lignes) == 1
    ligne = lignes[0]
    assert ligne["fournisseur_id"] is None
    assert ligne["nom"] is None
    assert ligne["montants"]["facture_ht"] == "77.00"
