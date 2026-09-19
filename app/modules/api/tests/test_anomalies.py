"""Tests de `GET /api/anomalies` et `POST /api/anomalies/{id}/traitement`
(L4-T9) : autorisation, filtres, cycle de vie, et de la section
`anomalies_hautes` de `GET /api/a-traiter` (L4-D18).

Ce fichier ne teste que les routeurs (couche d'entrée, L2-D3) : les
scénarios métier détaillés (upsert, levée, règle des 90 jours) vivent dans
`app/modules/ingest/tests/test_anomalies.py` (L4-T8, déjà commité, non
modifié ici).

Même schéma que `test_a_traiter.py`/`test_referentiels.py` : `FastAPI`
isolé, `app.state.sessions` branché sur `bl_test_wt` (arbre de travail), IP
dédiées (`10.83.0.x`) pour ne jamais partager le quota `slowapi` du login
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
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Chantier,
    Document,
    Fournisseur,
    Utilisateur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"

_IPS = itertools.count(1)

_BASE_TEMPS = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _instant(decalage_s: int) -> datetime:
    """Horodatage déterministe, distinct par appel (voir
    `ingest.tests.test_lecture._instant`) : nécessaire pour les tests de tri
    (`anomalies_hautes`, filtres `depuis`/`jusqu_a`), `func.now()` étant
    identique pour toutes les lignes d'une même transaction."""
    return _BASE_TEMPS + timedelta(seconds=decalage_s)


def _ip_isolee() -> str:
    return f"10.83.0.{next(_IPS)}"


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


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur API Anomalies"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_chantier(
    db_session: AsyncSession, *, nom: str = "Chantier API Anomalies"
) -> Chantier:
    chantier = Chantier(nom_canonique=nom)
    db_session.add(chantier)
    await db_session.commit()
    await db_session.refresh(chantier)
    return chantier


async def _creer_document(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur | None = None,
    numero: str | None = None,
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero=numero,
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_bloc(
    db_session: AsyncSession,
    *,
    facture: Document,
    chantier_id: uuid.UUID | None = None,
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=0,
        numero_bl="L0001",
        chantier_id=chantier_id,
    )
    db_session.add(bloc)
    await db_session.commit()
    await db_session.refresh(bloc)
    return bloc


async def _creer_anomalie(
    db_session: AsyncSession,
    *,
    regle: str = "R10",
    gravite: str = "haute",
    statut: str = "ouverte",
    document_id: uuid.UUID | None = None,
    bloc_id: uuid.UUID | None = None,
    detail: dict[str, str] | None = None,
    created_at: datetime | None = None,
) -> Anomalie:
    """Identité `(regle, document_id, bloc_id, ligne_id)` garantie unique
    (index de la migration 0006) : quand l'appelant ne fixe ni `document_id`
    ni `bloc_id`, un document dédié est créé pour éviter deux anomalies de
    même règle à l'identité `(regle, None, None, None)`."""
    if document_id is None and bloc_id is None:
        document_id = (await _creer_document(db_session)).id
    anomalie = Anomalie(
        regle=regle,
        gravite=gravite,
        statut=statut,
        document_id=document_id,
        bloc_id=bloc_id,
        detail=detail if detail is not None else {"cle": "valeur-inventee"},
        created_at=created_at if created_at is not None else _instant(0),
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)
    return anomalie


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
    transport = ASGITransport(app=app_test, client=("10.0.6.1", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.request(methode, chemin, json=json_body)


# --------------------------------------------------------------------------
# Droits
# --------------------------------------------------------------------------


async def test_get_anomalies_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(app_test, "GET", "/api/anomalies", cookie=None)

    assert reponse.status_code == 401


async def test_post_traitement_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    """Écart de couverture signalé par la revue de la tâche : seul le 403
    agent était testé sur cette route, jamais le 401 anonyme."""
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/anomalies/{uuid.uuid4()}/traitement",
        cookie=None,
        json_body={"statut": "traitee", "commentaire": "Commentaire inventé."},
    )

    assert reponse.status_code == 401


async def test_get_anomalies_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.anomalies1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(app_test, "GET", "/api/anomalies", cookie=cookie)

    assert reponse.status_code == 403


async def test_post_traitement_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.anomalies2@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/anomalies/{uuid.uuid4()}/traitement",
        cookie=cookie,
        json_body={"statut": "traitee", "commentaire": "Commentaire inventé."},
    )

    assert reponse.status_code == 403


# --------------------------------------------------------------------------
# GET /api/anomalies — filtres
# --------------------------------------------------------------------------


async def test_get_anomalies_defaut_ne_montre_que_les_ouvertes(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies1@example.invalid", role="admin"
    )
    ouverte = await _creer_anomalie(db_session, statut="ouverte")
    await _creer_anomalie(db_session, statut="traitee")
    await _creer_anomalie(db_session, statut="ignoree")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/anomalies", cookie=cookie)

    assert reponse.status_code == 200
    ids = {a["id"] for a in reponse.json()}
    assert ids == {str(ouverte.id)}


async def test_get_anomalies_filtre_regle(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies2@example.invalid", role="admin"
    )
    r10 = await _creer_anomalie(db_session, regle="R10")
    await _creer_anomalie(db_session, regle="R12")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/anomalies?regle=R10", cookie=cookie)

    assert reponse.status_code == 200
    ids = {a["id"] for a in reponse.json()}
    assert ids == {str(r10.id)}


async def test_get_anomalies_regle_invalide_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Ruling R22 (revue finale du lot 4, Minor) : `regle` doit être validé
    par une énumération, comme `gravite`/`statut` — une faute de frappe
    (`R0O` au lieu de `R01`) doit renvoyer 422, pas 200 avec une liste vide.
    Couverture exacte de l'énumération face au moteur (`REGLES_FACTURE`/
    `REGLES_SUIVI`) vérifiée dans `tests/test_regle_anomalie_couverture.py`
    (ce fichier, sous `app/modules/api/`, ne peut pas importer `rules`,
    garde vérifiée par `tests/test_frontieres.py`)."""
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies2b@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/anomalies?regle=R0O", cookie=cookie)

    assert reponse.status_code == 422


async def test_get_anomalies_filtre_gravite(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies3@example.invalid", role="admin"
    )
    haute = await _creer_anomalie(db_session, gravite="haute")
    await _creer_anomalie(db_session, gravite="basse")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "GET", "/api/anomalies?gravite=haute", cookie=cookie
    )

    assert reponse.status_code == 200
    ids = {a["id"] for a in reponse.json()}
    assert ids == {str(haute.id)}


async def test_get_anomalies_filtre_statut_explicite(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies4@example.invalid", role="admin"
    )
    await _creer_anomalie(db_session, statut="ouverte")
    traitee = await _creer_anomalie(db_session, statut="traitee")
    ignoree = await _creer_anomalie(db_session, statut="ignoree")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse_ignoree = await _requete(
        app_test, "GET", "/api/anomalies?statut=ignoree", cookie=cookie
    )
    reponse_traitee = await _requete(
        app_test, "GET", "/api/anomalies?statut=traitee", cookie=cookie
    )

    assert reponse_ignoree.status_code == 200
    assert reponse_traitee.status_code == 200
    assert {a["id"] for a in reponse_ignoree.json()} == {str(ignoree.id)}
    assert {a["id"] for a in reponse_traitee.json()} == {str(traitee.id)}


async def test_get_anomalies_statut_toutes_retire_le_filtre(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Ruling R15 (fix round 1) : `statut=toutes` ne filtre plus par statut
    — l'admin doit pouvoir revoir ce qui a déjà été traité ou ignoré
    (CDC §4.6)."""
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies4b@example.invalid", role="admin"
    )
    ouverte = await _creer_anomalie(db_session, statut="ouverte")
    traitee = await _creer_anomalie(db_session, statut="traitee")
    ignoree = await _creer_anomalie(db_session, statut="ignoree")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "GET", "/api/anomalies?statut=toutes", cookie=cookie
    )

    assert reponse.status_code == 200
    ids = {a["id"] for a in reponse.json()}
    assert ids == {str(ouverte.id), str(traitee.id), str(ignoree.id)}


async def test_get_anomalies_statut_invalide_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies4c@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "GET", "/api/anomalies?statut=archivee", cookie=cookie
    )

    assert reponse.status_code == 422


async def test_get_anomalies_filtre_bloc_id(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies-bloc@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur)
    bloc_a = await _creer_bloc(db_session, facture=facture)
    bloc_b = await _creer_bloc(db_session, facture=facture)
    anomalie_a = await _creer_anomalie(db_session, bloc_id=bloc_a.id)
    await _creer_anomalie(db_session, bloc_id=bloc_b.id)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "GET", f"/api/anomalies?bloc_id={bloc_a.id}", cookie=cookie
    )

    assert reponse.status_code == 200
    ids = {a["id"] for a in reponse.json()}
    assert ids == {str(anomalie_a.id)}


async def test_get_anomalies_filtre_chantier_id(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies5@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    chantier_a = await _creer_chantier(db_session, nom="Chantier A")
    chantier_b = await _creer_chantier(db_session, nom="Chantier B")
    facture = await _creer_document(db_session, fournisseur=fournisseur)
    bloc_a = await _creer_bloc(db_session, facture=facture, chantier_id=chantier_a.id)
    bloc_b = await _creer_bloc(db_session, facture=facture, chantier_id=chantier_b.id)
    anomalie_a = await _creer_anomalie(db_session, bloc_id=bloc_a.id)
    await _creer_anomalie(db_session, bloc_id=bloc_b.id)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "GET", f"/api/anomalies?chantier_id={chantier_a.id}", cookie=cookie
    )

    assert reponse.status_code == 200
    ids = {a["id"] for a in reponse.json()}
    assert ids == {str(anomalie_a.id)}


async def test_get_anomalies_filtre_fournisseur_id(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies6@example.invalid", role="admin"
    )
    fournisseur_a = await _creer_fournisseur(db_session, nom="Fournisseur A")
    fournisseur_b = await _creer_fournisseur(db_session, nom="Fournisseur B")
    document_a = await _creer_document(db_session, fournisseur=fournisseur_a)
    document_b = await _creer_document(db_session, fournisseur=fournisseur_b)
    anomalie_a = await _creer_anomalie(db_session, document_id=document_a.id)
    await _creer_anomalie(db_session, document_id=document_b.id)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "GET",
        f"/api/anomalies?fournisseur_id={fournisseur_a.id}",
        cookie=cookie,
    )

    assert reponse.status_code == 200
    ids = {a["id"] for a in reponse.json()}
    assert ids == {str(anomalie_a.id)}


async def test_get_anomalies_filtre_periode(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Ruling R21 : `depuis`/`jusqu_a` sont des dates (`AAAA-MM-JJ`, valeur
    brute d'un `<input type="date">`), jamais des horodatages — c'est le
    serveur qui les convertit en bornes d'instants (début/fin de journée en
    Europe/Paris)."""
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies7@example.invalid", role="admin"
    )
    veille = await _creer_anomalie(
        db_session, created_at=datetime(2026, 8, 14, 12, 0, tzinfo=FUSEAU_PARIS)
    )
    du_jour = await _creer_anomalie(
        db_session, created_at=datetime(2026, 8, 15, 12, 0, tzinfo=FUSEAU_PARIS)
    )
    await _creer_anomalie(
        db_session, created_at=datetime(2026, 8, 16, 12, 0, tzinfo=FUSEAU_PARIS)
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "GET",
        "/api/anomalies?depuis=2026-08-15&jusqu_a=2026-08-15",
        cookie=cookie,
    )

    assert reponse.status_code == 200
    ids = {a["id"] for a in reponse.json()}
    ok = ids == {str(du_jour.id)} and str(veille.id) not in ids
    assert ok, "seule l'anomalie du jour demandé doit être renvoyée"


async def test_get_anomalies_filtre_periode_bornes_incluses(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Bornes incluses (`>=`/`<=`, jamais `>`/`<`) **et** verrou du fuseau
    (Ruling R21) : une anomalie créée juste après minuit à Paris appartient
    au jour parisien demandé, pas au précédent — alors qu'exprimé en UTC
    (session Postgres), cet instant tombe sur la veille (2026-08-15 est en
    heure d'été, Europe/Paris = UTC+2 : minuit Paris le 15 == 22h00 UTC le
    14). Une conversion naïve (bornes en UTC plutôt qu'en Europe/Paris)
    exclurait à tort `juste_apres_minuit` de cette période."""
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies7b@example.invalid", role="admin"
    )
    minuit_paris = datetime(2026, 8, 15, 0, 0, 0, tzinfo=FUSEAU_PARIS)
    fin_journee_paris = datetime(2026, 8, 15, 23, 59, 59, 999999, tzinfo=FUSEAU_PARIS)

    sur_borne_basse = await _creer_anomalie(db_session, created_at=minuit_paris)
    juste_apres_minuit = await _creer_anomalie(
        db_session, created_at=minuit_paris + timedelta(minutes=5)
    )
    sur_borne_haute = await _creer_anomalie(db_session, created_at=fin_journee_paris)
    juste_avant_minuit = await _creer_anomalie(
        db_session, created_at=minuit_paris - timedelta(minutes=5)
    )
    juste_apres_fin_journee = await _creer_anomalie(
        db_session, created_at=fin_journee_paris + timedelta(microseconds=1)
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "GET",
        "/api/anomalies?depuis=2026-08-15&jusqu_a=2026-08-15",
        cookie=cookie,
    )

    assert reponse.status_code == 200
    ids = {a["id"] for a in reponse.json()}
    assert ids == {
        str(sur_borne_basse.id),
        str(juste_apres_minuit.id),
        str(sur_borne_haute.id),
    }
    assert str(juste_avant_minuit.id) not in ids
    assert str(juste_apres_fin_journee.id) not in ids


async def test_get_anomalies_limite_bornee(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies8@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    trop_basse = await _requete(
        app_test, "GET", "/api/anomalies?limite=0", cookie=cookie
    )
    trop_haute = await _requete(
        app_test, "GET", "/api/anomalies?limite=501", cookie=cookie
    )

    assert trop_basse.status_code == 422
    assert trop_haute.status_code == 422


async def test_get_anomalies_forme_json(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.anomalies9@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(db_session, fournisseur=fournisseur, numero="F1")
    bloc = await _creer_bloc(db_session, facture=facture)
    anomalie = await _creer_anomalie(
        db_session,
        regle="R01",
        document_id=facture.id,
        bloc_id=bloc.id,
        detail={"numero_bl": "L0001", "montant_ht": "100.00"},
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/anomalies", cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()[0]
    assert corps["id"] == str(anomalie.id)
    assert corps["regle"] == "R01"
    assert corps["detail"] == {"numero_bl": "L0001", "montant_ht": "100.00"}
    assert corps["document_id"] == str(facture.id)
    assert corps["numero"] == "F1"
    assert corps["bloc_id"] == str(bloc.id)
    assert corps["fournisseur"] == fournisseur.nom
    assert corps["traitee_par"] is None
    assert corps["commentaire"] is None


# --------------------------------------------------------------------------
# POST /api/anomalies/{id}/traitement
# --------------------------------------------------------------------------


async def test_post_traitement_ok_traitee(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.traitement1@example.invalid", role="admin"
    )
    anomalie = await _creer_anomalie(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/anomalies/{anomalie.id}/traitement",
        cookie=cookie,
        json_body={"statut": "traitee", "commentaire": "Vérifié sur place."},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["statut"] == "traitee"
    assert corps["commentaire"] == "Vérifié sur place."
    assert corps["traitee_par"] is not None
    assert corps["traitee_le"] is not None


async def test_post_traitement_ok_ignoree(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.traitement2@example.invalid", role="admin"
    )
    anomalie = await _creer_anomalie(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/anomalies/{anomalie.id}/traitement",
        cookie=cookie,
        json_body={"statut": "ignoree", "commentaire": "Faux positif connu."},
    )

    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "ignoree"


async def test_post_traitement_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.traitement3@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/anomalies/{uuid.uuid4()}/traitement",
        cookie=cookie,
        json_body={"statut": "traitee", "commentaire": "Commentaire inventé."},
    )

    assert reponse.status_code == 404


async def test_post_traitement_transition_interdite_409(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.traitement4@example.invalid", role="admin"
    )
    anomalie = await _creer_anomalie(db_session, statut="traitee")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/anomalies/{anomalie.id}/traitement",
        cookie=cookie,
        json_body={"statut": "ignoree", "commentaire": "Trop tard."},
    )

    assert reponse.status_code == 409


async def test_post_traitement_commentaire_vide_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.traitement5@example.invalid", role="admin"
    )
    anomalie = await _creer_anomalie(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/anomalies/{anomalie.id}/traitement",
        cookie=cookie,
        json_body={"statut": "traitee", "commentaire": "   "},
    )

    assert reponse.status_code == 422


async def test_post_traitement_commentaire_trop_long_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """501 caractères : `Field(max_length=500)` doit refuser — écart de
    couverture signalé par la revue de la tâche (seul le commentaire vide
    était testé)."""
    admin = await _creer_utilisateur(
        db_session, email="admin.traitement5b@example.invalid", role="admin"
    )
    anomalie = await _creer_anomalie(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/anomalies/{anomalie.id}/traitement",
        cookie=cookie,
        json_body={"statut": "traitee", "commentaire": "a" * 501},
    )

    assert reponse.status_code == 422


async def test_post_traitement_statut_invalide_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.traitement6@example.invalid", role="admin"
    )
    anomalie = await _creer_anomalie(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/anomalies/{anomalie.id}/traitement",
        cookie=cookie,
        json_body={"statut": "ouverte", "commentaire": "Commentaire inventé."},
    )

    assert reponse.status_code == 422


# --------------------------------------------------------------------------
# GET /api/a-traiter — anomalies_hautes (L4-D18)
# --------------------------------------------------------------------------


async def test_a_traiter_expose_anomalies_hautes_ouvertes_les_plus_anciennes(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.atraiterhautes1@example.invalid", role="admin"
    )
    ancienne = await _creer_anomalie(
        db_session, gravite="haute", statut="ouverte", created_at=_instant(0)
    )
    recente = await _creer_anomalie(
        db_session, gravite="haute", statut="ouverte", created_at=_instant(10)
    )
    # Exclues : gravité non haute, ou statut non ouvert.
    await _creer_anomalie(db_session, gravite="basse", statut="ouverte")
    await _creer_anomalie(db_session, gravite="haute", statut="traitee")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/a-traiter", cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert "anomalies_hautes" in corps
    ids = [a["id"] for a in corps["anomalies_hautes"]]
    assert ids == [str(ancienne.id), str(recente.id)]


async def test_a_traiter_anomalies_hautes_limitees_a_vingt(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.atraiterhautes2@example.invalid", role="admin"
    )
    for indice in range(25):
        await _creer_anomalie(
            db_session,
            gravite="haute",
            statut="ouverte",
            created_at=_instant(indice),
            detail={"indice": str(indice)},
        )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(app_test, "GET", "/api/a-traiter", cookie=cookie)

    assert reponse.status_code == 200
    assert len(reponse.json()["anomalies_hautes"]) == 20


async def test_a_traiter_agent_renvoie_403_anomalies_hautes_incluses(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    # Non-régression : la route reste réservée à l'admin même après l'ajout
    # de la section `anomalies_hautes`.
    agent = await _creer_utilisateur(
        db_session, email="agent.atraiterhautes1@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(app_test, "GET", "/api/a-traiter", cookie=cookie)

    assert reponse.status_code == 403


# --------------------------------------------------------------------------
# Schémas OpenAPI
# --------------------------------------------------------------------------


async def test_schemas_openapi_presents(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    schema = app_test.openapi()

    ok = (
        "/api/anomalies" in schema["paths"]
        and "/api/anomalies/{anomalie_id}/traitement" in schema["paths"]
        and "AnomalieReponse" in schema["components"]["schemas"]
    )
    assert ok, "routes et schéma AnomalieReponse absents de l'OpenAPI"
