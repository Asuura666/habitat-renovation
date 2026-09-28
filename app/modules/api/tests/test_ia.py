"""Tests de `GET /api/ia/synthese`, `POST /api/ia/synthese/actions/{id}
/faite`, `POST /api/ia/synthese/actions/{id}/a-faire` (T4, phase 4 IA) et
`GET /api/ia/anomalies/{id}` (T6, même phase) : autorisation, codes HTTP,
forme JSON -- voir `app/modules/ingest/tests/test_ia_synthese.py` et
`app/modules/ingest/tests/test_ia_prix.py` pour les scénarios métier
détaillés (sélection, troncature, cochage, journal, empreinte, cache).

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3). Même schéma que
`test_comptes.py`/`test_bilan.py` : `FastAPI` isolé, `app.state.sessions`
branché sur `bl_test`, IP dédiées (`10.88.0.x`) pour ne jamais partager le
quota `slowapi` du login avec un autre fichier de test.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, date, datetime, timedelta
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
from app.modules.ingest import commun
from app.modules.ingest.ia_prix import cle_produit_internet, empreinte_detail
from app.modules.ingest.models import (
    Anomalie,
    Document,
    ExplicationAlerte,
    Fournisseur,
    PrixInternet,
    SyntheseAction,
    SyntheseCommentaires,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"
_LUNDI = date(2026, 9, 21)

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.88.0.{next(_IPS)}"


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
    db_session: AsyncSession, *, email: str, role: str, nom: str | None = None
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email,
        nom=nom,
        hashed_password=_PASSWORD_HELPER.hash(_MOT_DE_PASSE),
        role=role,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


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


async def _creer_synthese_avec_action(
    db_session: AsyncSession,
) -> tuple[SyntheseCommentaires, SyntheseAction, Document]:
    fournisseur = Fournisseur(nom="Fournisseur IA Invente")
    db_session.add(fournisseur)
    await db_session.flush()
    document = Document(
        type="bl",
        source="telegram",
        statut="a_verifier",
        fichier_path=f"bl-invente-ia-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id,
        numero="BL-IA-1",
    )
    db_session.add(document)
    await db_session.flush()
    synthese = SyntheseCommentaires(
        semaine_debut=_LUNDI,
        semaine_fin=_LUNDI + timedelta(days=6),
        statut="ok",
        resume="Résumé inventé pour les tests d'API.",
        nb_commentaires=1,
        modele="modele-invente",
    )
    db_session.add(synthese)
    await db_session.flush()
    action = SyntheseAction(
        synthese_id=synthese.id,
        ordre=1,
        texte="Action inventée pour les tests d'API.",
        commentaire_ids=[str(uuid.uuid4())],
        document_ids=[str(document.id)],
    )
    db_session.add(action)
    await db_session.commit()
    return synthese, action, document


_DETAIL_R22_INVENTE = {
    "produit": "Plaque std 13",
    "code": "PL13",
    "prix_bon": "7.90",
    "unite_bon": "u",
    "date_bon": "2026-09-21",
    "candidats": "—",
}


async def _creer_anomalie_prix(
    db_session: AsyncSession,
    *,
    regle: str = "R22",
    detail: dict[str, str] | None = None,
    fournisseur_nom: str = "Fournisseur IA Prix Invente",
) -> tuple[Anomalie, Fournisseur, Document]:
    """Anomalie de catégorie prix (`R22`, lot Prix, inventée -- pas encore
    fusionnée sur cette branche, cf. `ingest.tests.test_ia_prix`), avec son
    fournisseur et sa facture, pour tester `GET /api/ia/anomalies/{id}`."""
    detail_effectif = detail if detail is not None else dict(_DETAIL_R22_INVENTE)
    fournisseur = Fournisseur(nom=fournisseur_nom)
    db_session.add(fournisseur)
    await db_session.flush()
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"facture-invente-ia-avis-{uuid.uuid4()}.pdf",
        fournisseur_id=fournisseur.id,
        numero=f"FA-IA-AVIS-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(document)
    await db_session.flush()
    anomalie = Anomalie(
        regle=regle,
        gravite="moyenne",
        detail=detail_effectif,
        statut="ouverte",
        document_id=document.id,
    )
    db_session.add(anomalie)
    await db_session.commit()
    return anomalie, fournisseur, document


def _regler_controle_prix(monkeypatch: pytest.MonkeyPatch, *, actif: bool) -> None:
    """Force `ingest.commun.controle_prix_actif` pour le test courant (fix
    round 1, même idiome que `ingest.tests.test_controle_prix
    ._regler_controle_prix`/`api.tests.test_a_traiter._regler_drapeaux`) :
    monkeypatcher `commun.get_settings` rend l'assertion déterministe,
    plutôt que de dépendre de la valeur réelle de `CONTROLE_PRIX_ACTIF` dans
    le `.env` de test."""

    class _SettingsInventee:
        controle_prix_actif = actif
        controle_livre_non_facture_actif = True

    monkeypatch.setattr(commun, "get_settings", lambda: _SettingsInventee())


# --------------------------------------------------------------------------
# Autorisation
# --------------------------------------------------------------------------


async def test_get_synthese_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)
    transport = ASGITransport(app=app_test, client=(_ip_isolee(), 12345))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.get("/api/ia/synthese")

    assert reponse.status_code == 401


async def test_routes_ia_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.ia@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)
    action_id = uuid.uuid4()
    anomalie_id = uuid.uuid4()

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        liste = await client.get("/api/ia/synthese")
        faite = await client.post(f"/api/ia/synthese/actions/{action_id}/faite")
        a_faire = await client.post(f"/api/ia/synthese/actions/{action_id}/a-faire")
        avis = await client.get(f"/api/ia/anomalies/{anomalie_id}")

    assert [reponse.status_code for reponse in [liste, faite, a_faire, avis]] == [
        403
    ] * 4


async def test_get_avis_ia_anomalie_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)
    transport = ASGITransport(app=app_test, client=(_ip_isolee(), 12345))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.get(f"/api/ia/anomalies/{uuid.uuid4()}")

    assert reponse.status_code == 401


# --------------------------------------------------------------------------
# GET /api/ia/synthese
# --------------------------------------------------------------------------


async def test_get_synthese_admin_200_forme_json(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.ia.get@example.invalid", role="admin"
    )
    synthese, action, document = await _creer_synthese_avec_action(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get("/api/ia/synthese")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["ia_active"] is False  # IA_ACTIVE absente en test -> éteinte
    assert corps["encore_a_faire"] == []
    assert corps["derniere"] is not None
    assert corps["derniere"]["id"] == str(synthese.id)
    assert corps["derniere"]["semaine_debut"] == _LUNDI.isoformat()
    assert corps["derniere"]["resume"] == "Résumé inventé pour les tests d'API."
    assert len(corps["derniere"]["actions"]) == 1
    action_json = corps["derniere"]["actions"][0]
    assert action_json["id"] == str(action.id)
    assert action_json["texte"] == "Action inventée pour les tests d'API."
    assert action_json["faite_le"] is None
    assert action_json["faite_par"] is None
    assert action_json["bons"] == [
        {"document_id": str(document.id), "numero": "BL-IA-1"}
    ]


async def test_get_synthese_admin_200_aucune_synthese(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.ia.vide@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get("/api/ia/synthese")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["derniere"] is None
    assert corps["encore_a_faire"] == []


# --------------------------------------------------------------------------
# POST /api/ia/synthese/actions/{id}/faite, .../a-faire
# --------------------------------------------------------------------------


async def test_post_action_faite_puis_a_faire_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session,
        email="admin.ia.cocher@example.invalid",
        role="admin",
        nom="Admin Cocher",
    )
    _synthese, action, _document = await _creer_synthese_avec_action(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        faite = await client.post(f"/api/ia/synthese/actions/{action.id}/faite")
        a_faire = await client.post(f"/api/ia/synthese/actions/{action.id}/a-faire")

    assert faite.status_code == 200
    corps_faite = faite.json()
    assert corps_faite["faite_le"] is not None
    assert corps_faite["faite_par"] == "Admin Cocher"

    assert a_faire.status_code == 200
    corps_a_faire = a_faire.json()
    assert corps_a_faire["faite_le"] is None
    assert corps_a_faire["faite_par"] is None


async def test_post_action_faite_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.ia.404@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        faite = await client.post(f"/api/ia/synthese/actions/{uuid.uuid4()}/faite")
        a_faire = await client.post(f"/api/ia/synthese/actions/{uuid.uuid4()}/a-faire")

    assert faite.status_code == 404
    assert a_faire.status_code == 404


# --------------------------------------------------------------------------
# GET /api/ia/anomalies/{id} (T6, phase 4 IA)
# --------------------------------------------------------------------------


async def test_get_avis_ia_anomalie_admin_200_forme_json(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.ia.avis@example.invalid", role="admin"
    )
    anomalie, fournisseur, _document = await _creer_anomalie_prix(db_session)
    detail = _DETAIL_R22_INVENTE
    db_session.add(
        ExplicationAlerte(
            anomalie_id=anomalie.id,
            empreinte_detail=empreinte_detail(detail),
            statut="ok",
            texte="Ce produit n'est pas dans la grille tarifaire habituelle.",
            echecs=0,
            modele="modele-invente",
        )
    )
    cle = cle_produit_internet(fournisseur.id, detail["produit"], detail["code"])
    db_session.add(
        PrixInternet(
            fournisseur_id=fournisseur.id,
            cle=cle,
            designation=detail["produit"],
            code=detail["code"],
            statut="trouve",
            prix=Decimal("89.9000"),
            devise="EUR",
            taxes="TTC",
            unite="u",
            conditionnement="boîte de 10",
            produit_trouve="Plaque std 13",
            source_url="https://exemple.invalid/plaque-std-13",
            confiance="elevee",
            raison=None,
            modele="modele-invente",
            consulte_le=datetime.now(UTC),
        )
    )
    await db_session.commit()

    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get(f"/api/ia/anomalies/{anomalie.id}")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["ia_active"] is False  # IA_ACTIVE absente en test -> éteinte
    assert corps["explication"]["texte"] == (
        "Ce produit n'est pas dans la grille tarifaire habituelle."
    )
    assert corps["prix_internet"]["statut"] == "trouve"
    assert corps["prix_internet"]["prix"] == "89.9000"
    assert corps["prix_internet"]["taxes"] == "TTC"
    assert corps["prix_internet"]["unite"] == "u"
    assert corps["prix_internet"]["conditionnement"] == "boîte de 10"
    assert corps["prix_internet"]["produit_trouve"] == "Plaque std 13"
    assert (
        corps["prix_internet"]["source_url"] == "https://exemple.invalid/plaque-std-13"
    )
    assert corps["prix_internet"]["confiance"] == "elevee"


async def test_get_avis_ia_anomalie_admin_200_aucun_avis(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Anomalie sans `ExplicationAlerte` ni `PrixInternet` -- rien à afficher,
    jamais une erreur."""
    admin = await _creer_utilisateur(
        db_session, email="admin.ia.avis.vide@example.invalid", role="admin"
    )
    # R22 (jamais masquée, contrairement à R07/R08/R09 -- `CONTROLE_PRIX_ACTIF`
    # vaut son défaut réel `False` dans ce test, l'app de test n'écrasant pas
    # ce réglage) : aucune `ExplicationAlerte` ni `PrixInternet` en base pour
    # cette clé, donc rien à afficher, jamais une erreur.
    anomalie, _fournisseur, _document = await _creer_anomalie_prix(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get(f"/api/ia/anomalies/{anomalie.id}")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["explication"] is None
    assert corps["prix_internet"] is None


async def test_get_avis_ia_anomalie_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.ia.avis.404@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get(f"/api/ia/anomalies/{uuid.uuid4()}")

    assert reponse.status_code == 404


async def test_get_avis_ia_anomalie_regle_masquee_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix round 1 : une anomalie d'une règle désactivée côté serveur (R07
    avec `CONTROLE_PRIX_ACTIF` faux, décision d'Ilane du 24/09/2026) est
    masquée de tout le reste de l'application -- traitée comme introuvable
    par cette route aussi, même principe qu'`ingest.anomalies
    .traiter_anomalie`."""
    _regler_controle_prix(monkeypatch, actif=False)
    admin = await _creer_utilisateur(
        db_session, email="admin.ia.avis.masquee@example.invalid", role="admin"
    )
    anomalie, _fournisseur, _document = await _creer_anomalie_prix(
        db_session,
        regle="R07",
        detail={
            "article": "Sable 0/4",
            "code": "SAB04",
            "pu_facture": "12.50",
            "mediane": "10.00",
            "occurrences": "6",
            "ecart_pct": "25.00",
        },
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get(f"/api/ia/anomalies/{anomalie.id}")

    assert reponse.status_code == 404
