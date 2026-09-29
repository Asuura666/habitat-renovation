"""Tests des routes `/api/ia/labo/...` (tâche LABO, Laboratoire IA) :
autorisation, codes HTTP, forme JSON -- voir `app/modules/ingest/tests
/test_ia_labo.py` pour les scénarios métier détaillés (trace complète,
contrôles, rien enregistré hors `appel_ia`, IA éteinte, plafond, erreur du
fournisseur, borne des 20 essais).

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3). Même schéma que
`test_ia.py`/`test_comptes.py` : `FastAPI` isolé, `app.state.sessions`
branché sur `bl_test`, `app.state.http` sur un `httpx.MockTransport` (aucun
appel réseau réel), IP dédiées pour ne jamais partager le quota `slowapi` du
login avec un autre fichier de test.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.config import get_settings
from app.modules.api import router as api_router
from app.modules.ingest import ia_labo, opencode
from app.modules.ingest.models import Anomalie, Document, Fournisseur, Utilisateur

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_URL_OPENCODE_INVENTEE = "https://opencode-api-labo.test"
_MDP_OPENCODE_INVENTE = "mdp-opencode-invente-api-labo"


class _SettingsIAFake:
    """Substitut minimal de `Settings` (même idiome que `test_opencode.py`) :
    seuls les attributs lus par `opencode.py` sont portés. IA allumée par
    défaut dans ce fichier (le défaut réel de l'application est éteinte) --
    `test_get_etat_labo_admin_200_ia_eteinte` l'écrase localement pour tester
    ce cas précis."""

    def __init__(
        self,
        *,
        ia_active: bool = True,
        opencode_url: str | None = _URL_OPENCODE_INVENTEE,
        opencode_mot_de_passe: str | None = _MDP_OPENCODE_INVENTE,
        ia_appels_max_jour: int = 40,
    ) -> None:
        self.ia_active = ia_active
        self.opencode_url = opencode_url
        self.opencode_mot_de_passe = (
            SecretStr(opencode_mot_de_passe)
            if opencode_mot_de_passe is not None
            else None
        )
        self.ia_appels_max_jour = ia_appels_max_jour


@pytest.fixture(autouse=True)
def _ia_active_par_defaut(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())


@pytest.fixture(autouse=True)
def _vider_essais() -> None:
    """`ingest.ia_labo._essais` est un registre en mémoire du processus,
    partagé par toute la suite de tests (voulu en production, un seul
    processus uvicorn) -- vidé avant chaque test pour ne jamais dépendre de
    l'ordre d'exécution des fichiers de tests."""
    ia_labo._essais.clear()


_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-labo-1234"

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.89.0.{next(_IPS)}"


def _handler_json(
    reponses: dict[tuple[str, str], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        cle = (request.method, request.url.path)
        if cle not in reponses:
            raise AssertionError(f"requête inattendue : {request.method} {request.url}")
        return reponses[cle]

    return handler


def _info_minimal(**overrides: Any) -> dict[str, Any]:
    info: dict[str, Any] = {
        "id": "msg_api_labo_1",
        "sessionID": "ses_api_labo_1",
        "role": "assistant",
        "time": {"created": 1, "completed": 2},
        "parentID": "msg_api_labo_0",
        "modelID": "modele-invente",
        "providerID": "fournisseur-invente",
        "mode": "habitat-prix",
        "agent": "habitat-prix",
        "path": {"cwd": "/", "root": "/"},
        "cost": 0,
        "tokens": {
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "cache": {"read": 0, "write": 0},
        },
    }
    info.update(overrides)
    return info


def _reponses_session(structured: Any) -> dict[tuple[str, str], httpx.Response]:
    info = _info_minimal(structured=structured)
    return {
        ("POST", "/session"): httpx.Response(200, json={"id": "ses_api_labo_1"}),
        ("POST", "/session/ses_api_labo_1/message"): httpx.Response(
            200, json={"info": info, "parts": []}
        ),
        ("DELETE", "/session/ses_api_labo_1"): httpx.Response(200, json=True),
    }


def _app_test(
    sessions: async_sessionmaker[AsyncSession],
    docs_dir: Path,
    http: httpx.AsyncClient,
) -> FastAPI:
    app_test = FastAPI()
    app_test.state.sessions = sessions
    app_test.state.http = http
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


async def _creer_anomalie_prix(db_session: AsyncSession) -> Anomalie:
    fournisseur = Fournisseur(nom="Fournisseur API Labo Invente")
    db_session.add(fournisseur)
    await db_session.flush()
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"facture-api-labo-invente-{uuid.uuid4()}.pdf",
        fournisseur_id=fournisseur.id,
        numero=f"FA-API-LABO-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(document)
    await db_session.flush()
    anomalie = Anomalie(
        regle="R07",
        gravite="moyenne",
        detail={
            "article": "Sable 0/4",
            "code": "SAB04",
            "pu_facture": "12.50",
            "mediane": "10.00",
            "occurrences": "6",
            "ecart_pct": "25.00",
        },
        statut="ouverte",
        document_id=document.id,
    )
    db_session.add(anomalie)
    await db_session.commit()
    return anomalie


# --------------------------------------------------------------------------
# Autorisation
# --------------------------------------------------------------------------


async def test_routes_labo_anonyme_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    app_test = _app_test(sessions_test, tmp_path, http)
    transport = ASGITransport(app=app_test, client=(_ip_isolee(), 12345))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        etat = await client.get("/api/ia/labo/etat")
        essais = await client.get("/api/ia/labo/essais")
        appels = await client.get("/api/ia/labo/appels")
        lance = await client.post(
            "/api/ia/labo/essais/prix", json={"designation": "Produit"}
        )

    assert [reponse.status_code for reponse in [etat, essais, appels, lance]] == [
        401
    ] * 4


async def test_routes_labo_agent_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.labo@example.invalid", role="agent"
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    app_test = _app_test(sessions_test, tmp_path, http)
    cookie = await _login(app_test, email=agent.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        etat = await client.get("/api/ia/labo/etat")
        lance = await client.post(
            "/api/ia/labo/essais/prix", json={"designation": "Produit"}
        )

    assert etat.status_code == 403
    assert lance.status_code == 403


# --------------------------------------------------------------------------
# GET /api/ia/labo/etat
# --------------------------------------------------------------------------


async def test_get_etat_labo_admin_200_ia_eteinte(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_active=False)
    )
    admin = await _creer_utilisateur(
        db_session, email="admin.labo.etat@example.invalid", role="admin"
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    app_test = _app_test(sessions_test, tmp_path, http)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get("/api/ia/labo/etat")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["ia_active"] is False
    assert corps["url_configuree"] is True
    assert corps["joignable"] is False
    assert corps["agents"] == []
    assert corps["abonnement_connecte"] is False
    assert corps["recherche_web"] is False
    assert corps["appels_aujourdhui"] == 0
    assert isinstance(corps["appels_max_jour"], int)


# --------------------------------------------------------------------------
# POST /api/ia/labo/essais/prix, GET /api/ia/labo/essais/{id}
# --------------------------------------------------------------------------


async def test_lancer_et_lire_essai_prix_202_puis_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.labo.prix@example.invalid", role="admin"
    )
    reponses = _reponses_session(
        {"statut": "prix_non_verifiable", "raison": "essai API"}
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    app_test = _app_test(sessions_test, tmp_path, http)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        lance = await client.post(
            "/api/ia/labo/essais/prix",
            json={
                "fournisseur": "Point P",
                "designation": "Ciment 25kg",
                "code": "CIM25",
                "unite": "sac",
            },
        )
        assert lance.status_code == 202
        essai_id = lance.json()["id"]

        # Sous ASGITransport, la tâche de fond s'exécute avant que la
        # réponse ne soit rendue (Starlette l'attend dans le même appel) :
        # l'essai est donc déjà `fini` à ce stade, sans polling.
        lu = await client.get(f"/api/ia/labo/essais/{essai_id}")

    assert lu.status_code == 200
    corps = lu.json()
    assert corps["type"] == "prix"
    assert corps["statut"] == "fini"
    assert corps["resultat"]["statut"] == "non_verifiable"
    assert corps["schema"]["type"] == "object"  # alias `schema` bien restitué
    assert corps["erreur"] is None


async def test_lancer_essai_prix_designation_vide_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.labo.prix.422@example.invalid", role="admin"
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    app_test = _app_test(sessions_test, tmp_path, http)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.post(
            "/api/ia/labo/essais/prix", json={"designation": ""}
        )

    assert reponse.status_code == 422


async def test_lire_essai_inconnu_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.labo.404@example.invalid", role="admin"
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    app_test = _app_test(sessions_test, tmp_path, http)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.get(f"/api/ia/labo/essais/{uuid.uuid4()}")

    assert reponse.status_code == 404


# --------------------------------------------------------------------------
# POST /api/ia/labo/essais/explication
# --------------------------------------------------------------------------


async def test_lancer_essai_explication_anomalie_introuvable_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.labo.explication.404@example.invalid", role="admin"
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    app_test = _app_test(sessions_test, tmp_path, http)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.post(
            "/api/ia/labo/essais/explication", json={"anomalie_id": str(uuid.uuid4())}
        )

    assert reponse.status_code == 404


async def test_lancer_essai_explication_202_puis_fini(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.labo.explication@example.invalid", role="admin"
    )
    anomalie = await _creer_anomalie_prix(db_session)
    reponses = _reponses_session(
        {"explication": "Prix 12.50, médiane 10.00, écart 25.00 %."}
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    app_test = _app_test(sessions_test, tmp_path, http)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        lance = await client.post(
            "/api/ia/labo/essais/explication", json={"anomalie_id": str(anomalie.id)}
        )
        assert lance.status_code == 202
        lu = await client.get(f"/api/ia/labo/essais/{lance.json()['id']}")

    assert lu.status_code == 200
    corps = lu.json()
    assert corps["type"] == "explication"
    assert corps["statut"] == "fini"
    assert corps["resultat"]["texte"] == "Prix 12.50, médiane 10.00, écart 25.00 %."


# --------------------------------------------------------------------------
# POST /api/ia/labo/essais/synthese
# --------------------------------------------------------------------------


async def test_lancer_essai_synthese_pas_lundi_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.labo.synthese.422@example.invalid", role="admin"
    )
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    app_test = _app_test(sessions_test, tmp_path, http)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse = await client.post(
            "/api/ia/labo/essais/synthese", json={"semaine_debut": "2026-09-22"}
        )

    assert reponse.status_code == 422


async def test_lancer_essai_synthese_202_puis_fini(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.labo.synthese@example.invalid", role="admin"
    )
    reponses = _reponses_session({"resume": "Rien à signaler.", "actions": []})
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    app_test = _app_test(sessions_test, tmp_path, http)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        lance = await client.post(
            "/api/ia/labo/essais/synthese", json={"semaine_debut": "2026-09-21"}
        )
        assert lance.status_code == 202
        lu = await client.get(f"/api/ia/labo/essais/{lance.json()['id']}")

    assert lu.status_code == 200
    corps = lu.json()
    assert corps["type"] == "synthese"
    assert corps["statut"] == "fini"
    assert corps["resultat"] == {"resume": "Rien à signaler.", "actions": []}


# --------------------------------------------------------------------------
# GET /api/ia/labo/essais, GET /api/ia/labo/appels
# --------------------------------------------------------------------------


async def test_derniers_essais_et_journal_appels_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.labo.liste@example.invalid", role="admin"
    )
    reponses = _reponses_session({"statut": "prix_non_verifiable", "raison": "essai"})
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))
    app_test = _app_test(sessions_test, tmp_path, http)
    cookie = await _login(app_test, email=admin.email)

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        await client.post("/api/ia/labo/essais/prix", json={"designation": "Produit"})
        essais = await client.get("/api/ia/labo/essais")
        appels = await client.get("/api/ia/labo/appels")

    assert essais.status_code == 200
    assert len(essais.json()) == 1
    assert essais.json()[0]["type"] == "prix"

    assert appels.status_code == 200
    assert len(appels.json()) == 1
    assert appels.json()[0]["usage"] == "prix"
    assert appels.json()[0]["statut"] == "ok"
