"""Tests de `app/modules/ingest/opencode.py` (T3, phase 4 IA) : aucun appel
réseau réel (`httpx.MockTransport`, comme `test_mistral.py`), base de test
réelle (`bl_test`) pour la table `appel_ia`. Toutes les valeurs (URL, mot de
passe, textes envoyés/reçus, identifiants de session) sont inventées ; les
réponses d'erreur reprennent la *forme* de `exemple-reponse-erreur-
opencode.json` (même dossier de brief) avec un contenu entièrement remplacé,
jamais son contenu recopié tel quel.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.extract.reponses_ia import PageLue
from app.modules.ingest import opencode
from app.modules.ingest.models import AppelIA, Fournisseur
from app.modules.ingest.opencode import ErreurIA, IAIndisponible, interroger

pytestmark = [pytest.mark.anyio, pytest.mark.db]

URL_INVENTEE = "https://opencode.test"
MDP_INVENTE = "mdp-opencode-invente-pour-les-tests"
TEXTE_ENVOYE_INVENTE = "Texte envoyé à l'IA, entièrement inventé pour le test."
SCHEMA_INVENTE: dict[str, Any] = {
    "type": "object",
    "properties": {"resume": {"type": "string"}},
}
_AUTORISATION_ATTENDUE = (
    "Basic " + base64.b64encode(f"opencode:{MDP_INVENTE}".encode()).decode()
)


class _SettingsIAFake:
    """Substitut minimal de `Settings`, même principe que `_SettingsControlePrix`
    (`app/modules/ingest/tests/conftest.py`) : seuls les attributs lus par
    `opencode.py` sont portés."""

    def __init__(
        self,
        *,
        ia_active: bool = True,
        opencode_url: str | None = URL_INVENTEE,
        opencode_mot_de_passe: str | None = MDP_INVENTE,
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
    """IA allumée par défaut pour ce fichier (le défaut réel de l'application
    est éteinte) -- les tests dédiés à l'extinction/au plafond l'écrasent
    localement avec le même idiome (`get_settings` est `@cache`, on
    remplace donc la référence dans le module, jamais l'appel réel)."""
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())


def _info_minimal(**overrides: Any) -> dict[str, Any]:
    """`AssistantMessage` minimal valide (tous les champs requis du schéma
    OpenCode), personnalisable par `overrides` (`structured`, `error`, ...)."""
    info: dict[str, Any] = {
        "id": "msg_test_1",
        "sessionID": "ses_test_1",
        "role": "assistant",
        "time": {"created": 1, "completed": 2},
        "parentID": "msg_test_0",
        "modelID": "modele-invente",
        "providerID": "fournisseur-invente",
        "mode": "habitat-synthese",
        "agent": "habitat-synthese",
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


def _partie_outil(
    *,
    id_partie: str,
    outil: str,
    statut: str,
    entree: dict[str, Any],
    **etat_extra: Any,
) -> dict[str, Any]:
    etat: dict[str, Any] = {"status": statut, "input": entree, **etat_extra}
    return {
        "id": id_partie,
        "sessionID": "ses_test_1",
        "messageID": "msg_test_1",
        "type": "tool",
        "callID": f"call_{id_partie}",
        "tool": outil,
        "state": etat,
    }


def _handler_json(
    reponses: dict[tuple[str, str], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    """Handler `MockTransport` qui répond selon `(méthode, chemin)`, et fait
    échouer le test sur toute requête non prévue (jamais un 404 silencieux)."""

    def handler(request: httpx.Request) -> httpx.Response:
        cle = (request.method, request.url.path)
        if cle not in reponses:
            raise AssertionError(f"requête inattendue : {request.method} {request.url}")
        return reponses[cle]

    return handler


def _reponse_nominale() -> dict[tuple[str, str], httpx.Response]:
    info = _info_minimal(structured={"resume": "résumé inventé", "actions": []})
    parts = [
        _partie_outil(
            id_partie="prt_1",
            outil="webfetch",
            statut="completed",
            entree={"url": "https://exemple.invalid/page-lue"},
            output="texte de la page inventé",
            title="titre inventé",
            metadata={},
            time={"start": 1, "end": 2},
        ),
        _partie_outil(
            id_partie="prt_2",
            outil="websearch",
            statut="completed",
            entree={"query": "requête inventée"},
            output="résultats de recherche inventés",
            title="titre inventé",
            metadata={},
            time={"start": 1, "end": 2},
        ),
        # Outil pas encore terminé -- doit être ignoré (brief T3 étape 5).
        _partie_outil(
            id_partie="prt_3",
            outil="webfetch",
            statut="running",
            entree={"url": "https://exemple.invalid/en-cours"},
        ),
        # Partie texte -- jamais confondue avec une page lue.
        {
            "id": "prt_4",
            "sessionID": "ses_test_1",
            "messageID": "msg_test_1",
            "type": "text",
            "text": "réponse textuelle inventée",
        },
    ]
    return {
        ("POST", "/session"): httpx.Response(200, json={"id": "ses_test_1"}),
        ("POST", "/session/ses_test_1/message"): httpx.Response(
            200, json={"info": info, "parts": parts}
        ),
        ("DELETE", "/session/ses_test_1"): httpx.Response(200, json=True),
    }


async def test_interroger_nominal_trois_requetes_et_reponse_complete(
    db_session: AsyncSession,
) -> None:
    requetes: list[httpx.Request] = []
    reponses = _reponse_nominale()

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return _handler_json(reponses)(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    resultat = await interroger(
        db_session,
        http,
        usage="synthese",
        agent="habitat-synthese",
        texte=TEXTE_ENVOYE_INVENTE,
        schema=SCHEMA_INVENTE,
    )

    assert [(r.method, r.url.path) for r in requetes] == [
        ("POST", "/session"),
        ("POST", "/session/ses_test_1/message"),
        ("DELETE", "/session/ses_test_1"),
    ]
    for requete in requetes:
        assert requete.headers["authorization"] == _AUTORISATION_ATTENDUE

    corps_session = json.loads(requetes[0].content)
    assert corps_session == {"title": "habitat-synthese"}

    corps_message = json.loads(requetes[1].content)
    assert corps_message == {
        "agent": "habitat-synthese",
        "parts": [{"type": "text", "text": TEXTE_ENVOYE_INVENTE}],
        "format": {"type": "json_schema", "schema": SCHEMA_INVENTE, "retryCount": 1},
    }

    assert resultat.structure == {"resume": "résumé inventé", "actions": []}
    assert resultat.modele == "fournisseur-invente/modele-invente"
    assert resultat.pages == (
        PageLue(
            outil="webfetch",
            adresse="https://exemple.invalid/page-lue",
            texte="texte de la page inventé",
        ),
        PageLue(
            outil="websearch",
            adresse="requête inventée",
            texte="résultats de recherche inventés",
        ),
    )
    assert resultat.duree_ms >= 0

    lignes = (await db_session.execute(select(AppelIA))).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].usage == "synthese"
    assert lignes[0].statut == "ok"
    assert lignes[0].erreur is None
    assert lignes[0].duree_ms == resultat.duree_ms


@pytest.mark.parametrize(
    ("erreur_info", "code_attendu"),
    [
        pytest.param(
            {
                "name": "ProviderAuthError",
                "data": {
                    "providerID": "fournisseur-invente",
                    "message": "message d'erreur inventé",
                },
            },
            "ProviderAuthError",
            id="provider-auth-error",
        ),
        pytest.param(
            {
                "name": "APIError",
                "data": {
                    "message": "message inventé",
                    "statusCode": 429,
                    "isRetryable": True,
                },
            },
            "APIError_429",
            id="api-error-429",
        ),
    ],
)
async def test_interroger_info_error_leve_erreur_ia_et_supprime_la_session(
    db_session: AsyncSession, erreur_info: dict[str, Any], code_attendu: str
) -> None:
    info = _info_minimal(error=erreur_info)
    reponses = {
        ("POST", "/session"): httpx.Response(200, json={"id": "ses_test_1"}),
        ("POST", "/session/ses_test_1/message"): httpx.Response(
            200, json={"info": info, "parts": []}
        ),
        ("DELETE", "/session/ses_test_1"): httpx.Response(200, json=True),
    }
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return _handler_json(reponses)(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ErreurIA) as exc_info:
        await interroger(
            db_session,
            http,
            usage="explication",
            agent="habitat-explication",
            texte=TEXTE_ENVOYE_INVENTE,
            schema=SCHEMA_INVENTE,
        )

    assert exc_info.value.code == code_attendu
    assert MDP_INVENTE not in str(exc_info.value)
    assert TEXTE_ENVOYE_INVENTE not in str(exc_info.value)
    # La session est supprimée même en cas d'erreur du fournisseur.
    assert [(r.method, r.url.path) for r in requetes] == [
        ("POST", "/session"),
        ("POST", "/session/ses_test_1/message"),
        ("DELETE", "/session/ses_test_1"),
    ]

    lignes = (await db_session.execute(select(AppelIA))).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].usage == "explication"
    assert lignes[0].statut == "erreur"
    assert lignes[0].erreur == code_attendu


async def test_interroger_reprend_la_forme_de_lexemple_derreur_opencode(
    db_session: AsyncSession,
) -> None:
    """Même forme qu'`exemple-reponse-erreur-opencode.json` (APIError,
    `data.statusCode` 403) -- tout le contenu (identifiants, messages,
    en-têtes, corps de réponse fournisseur) est ici entièrement inventé,
    rien n'est recopié du fichier réel."""
    info = _info_minimal(
        error={
            "name": "APIError",
            "data": {
                "message": "Erreur inventée du fournisseur",
                "statusCode": 403,
                "isRetryable": False,
                "responseHeaders": {"content-type": "application/json"},
                "responseBody": '{"type":"error","error":{"type":"ErreurInventee"}}',
                "metadata": {"url": "https://fournisseur-invente.test/v1/chat"},
            },
        }
    )
    reponses = {
        ("POST", "/session"): httpx.Response(200, json={"id": "ses_test_1"}),
        ("POST", "/session/ses_test_1/message"): httpx.Response(
            200, json={"info": info, "parts": []}
        ),
        ("DELETE", "/session/ses_test_1"): httpx.Response(200, json=True),
    }
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    with pytest.raises(ErreurIA) as exc_info:
        await interroger(
            db_session,
            http,
            usage="prix",
            agent="habitat-prix",
            texte=TEXTE_ENVOYE_INVENTE,
            schema=SCHEMA_INVENTE,
        )

    assert exc_info.value.code == "APIError_403"


async def test_interroger_sans_sortie_structuree(db_session: AsyncSession) -> None:
    info = _info_minimal()  # pas de clé "structured"
    reponses = {
        ("POST", "/session"): httpx.Response(200, json={"id": "ses_test_1"}),
        ("POST", "/session/ses_test_1/message"): httpx.Response(
            200, json={"info": info, "parts": []}
        ),
        ("DELETE", "/session/ses_test_1"): httpx.Response(200, json=True),
    }
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    with pytest.raises(ErreurIA) as exc_info:
        await interroger(
            db_session,
            http,
            usage="synthese",
            agent="habitat-synthese",
            texte=TEXTE_ENVOYE_INVENTE,
            schema=SCHEMA_INVENTE,
        )

    assert exc_info.value.code == "sans_sortie"

    lignes = (await db_session.execute(select(AppelIA))).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].erreur == "sans_sortie"


async def test_interroger_401_sur_session_pas_de_delete_mais_ligne_appel_ia(
    db_session: AsyncSession,
) -> None:
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return httpx.Response(401, json={"message": "non autorisé"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ErreurIA) as exc_info:
        await interroger(
            db_session,
            http,
            usage="prix",
            agent="habitat-prix",
            texte=TEXTE_ENVOYE_INVENTE,
            schema=SCHEMA_INVENTE,
        )

    assert exc_info.value.code == "http_401"
    assert MDP_INVENTE not in str(exc_info.value)
    # Une seule requête (POST /session) : sans identifiant de session, aucun
    # DELETE ne peut être tenté.
    assert len(requetes) == 1

    lignes = (await db_session.execute(select(AppelIA))).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].usage == "prix"
    assert lignes[0].statut == "erreur"
    assert lignes[0].erreur == "http_401"


async def test_interroger_delai_depasse(db_session: AsyncSession) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("délai inventé dépassé", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ErreurIA) as exc_info:
        await interroger(
            db_session,
            http,
            usage="synthese",
            agent="habitat-synthese",
            texte=TEXTE_ENVOYE_INVENTE,
            schema=SCHEMA_INVENTE,
            delai=0.01,
        )

    assert exc_info.value.code == "delai"
    assert MDP_INVENTE not in str(exc_info.value)

    lignes = (await db_session.execute(select(AppelIA))).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].erreur == "delai"


async def test_interroger_ia_eteinte_aucune_requete_aucune_ligne(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_active=False)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucune requête ne doit être faite, IA éteinte")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(IAIndisponible) as exc_info:
        await interroger(
            db_session,
            http,
            usage="synthese",
            agent="habitat-synthese",
            texte=TEXTE_ENVOYE_INVENTE,
            schema=SCHEMA_INVENTE,
        )

    assert exc_info.value.raison == "eteinte"
    lignes = (await db_session.execute(select(AppelIA))).scalars().all()
    assert lignes == []


async def test_interroger_plafond_atteint_aucune_requete_aucune_ligne_supplementaire(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_appels_max_jour=2)
    )

    aujourdhui_paris = datetime.now(FUSEAU_PARIS).date()
    hier_23h_paris = datetime.combine(
        aujourdhui_paris - timedelta(days=1), time(23, 0), tzinfo=FUSEAU_PARIS
    )
    aujourdhui_00h30_paris = datetime.combine(
        aujourdhui_paris, time(0, 30), tzinfo=FUSEAU_PARIS
    )

    # Une ligne d'hier (heure de Paris) : ne doit jamais compter dans le
    # plafond du jour, même si elle tombe le même jour civil en UTC ou pas.
    db_session.add(
        AppelIA(usage="synthese", statut="ok", duree_ms=1, created_at=hier_23h_paris)
    )
    # Deux lignes d'aujourd'hui : atteignent déjà le plafond (2).
    db_session.add(
        AppelIA(
            usage="synthese",
            statut="ok",
            duree_ms=1,
            created_at=aujourdhui_00h30_paris,
        )
    )
    db_session.add(
        AppelIA(
            usage="prix",
            statut="erreur",
            erreur="reseau",
            duree_ms=1,
            created_at=aujourdhui_00h30_paris,
        )
    )
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucune requête ne doit être faite, plafond atteint")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(IAIndisponible) as exc_info:
        await interroger(
            db_session,
            http,
            usage="synthese",
            agent="habitat-synthese",
            texte=TEXTE_ENVOYE_INVENTE,
            schema=SCHEMA_INVENTE,
        )

    assert exc_info.value.raison == "plafond"
    lignes = (await db_session.execute(select(AppelIA))).scalars().all()
    assert len(lignes) == 3  # aucune ligne supplémentaire insérée


async def test_ligne_appel_ia_commitee_malgre_rollback_de_lappelant(
    db_session: AsyncSession,
) -> None:
    """Étape 7 du brief : la ligne `appel_ia` est commitée dans sa propre
    session, indépendamment de la transaction de l'appelant -- ici
    matérialisé par un `Fournisseur` ajouté par l'appelant puis annulé."""
    db_session.add(Fournisseur(nom="Fournisseur inventé, annulé ensuite"))

    reponses = _reponse_nominale()
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    await interroger(
        db_session,
        http,
        usage="synthese",
        agent="habitat-synthese",
        texte=TEXTE_ENVOYE_INVENTE,
        schema=SCHEMA_INVENTE,
    )

    await db_session.rollback()

    lignes = (await db_session.execute(select(AppelIA))).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].statut == "ok"

    fournisseurs = (await db_session.execute(select(Fournisseur))).scalars().all()
    assert fournisseurs == []
