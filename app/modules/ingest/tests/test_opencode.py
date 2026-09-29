"""Tests de `app/modules/ingest/opencode.py` (T3, phase 4 IA) : aucun appel
réseau réel (`httpx.MockTransport`, comme `test_mistral.py`), base de test
réelle (`bl_test`) pour la table `appel_ia`. Toutes les valeurs (URL, mot de
passe, textes envoyés/reçus, identifiants de session) sont inventées ; les
réponses d'erreur reprennent la *forme* de `exemple-reponse-erreur-
opencode.json` (même dossier de brief) avec un contenu entièrement remplacé,
jamais son contenu recopié tel quel.
"""

from __future__ import annotations

import asyncio
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
from app.modules.ingest.opencode import (
    AGENTS_ATTENDUS,
    DiagnosticIA,
    ErreurIA,
    IAIndisponible,
    diagnostic_ia,
    interroger,
)

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


# --------------------------------------------------------------------------
# Fix round 1 : robustesse face à une exception inattendue / une annulation
# (`code_erreur` ne doit jamais rester non lié, la journalisation ne doit
# jamais remplacer l'exception d'origine).
# --------------------------------------------------------------------------


async def test_interroger_exception_inattendue_est_rejaillie_identique_et_journalisee(
    db_session: AsyncSession,
) -> None:
    """Un bug imprévu (ici une `RuntimeError` levée pendant l'appel réseau du
    message, jamais une `ErreurIA`) doit rejaillir tel quel -- ni avalé, ni
    remplacé par une `UnboundLocalError` de comptabilité interne -- tout en
    étant journalisé (`appel_ia`, code `"inattendue"`) et en tentant quand
    même la suppression de la session."""
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        if request.method == "POST" and request.url.path == "/session":
            return httpx.Response(200, json={"id": "ses_test_1"})
        if (
            request.method == "POST"
            and request.url.path == "/session/ses_test_1/message"
        ):
            raise RuntimeError("boum inventé, bug imprévu")
        if request.method == "DELETE" and request.url.path == "/session/ses_test_1":
            return httpx.Response(200, json=True)
        raise AssertionError(f"requête inattendue : {request.method} {request.url}")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeError, match="boum inventé, bug imprévu") as exc_info:
        await interroger(
            db_session,
            http,
            usage="synthese",
            agent="habitat-synthese",
            texte=TEXTE_ENVOYE_INVENTE,
            schema=SCHEMA_INVENTE,
        )

    # Le même objet exception, jamais enveloppé dans une `ErreurIA`.
    assert type(exc_info.value) is RuntimeError
    assert exc_info.value.__cause__ is None

    # La session est quand même supprimée (best-effort).
    assert [(r.method, r.url.path) for r in requetes] == [
        ("POST", "/session"),
        ("POST", "/session/ses_test_1/message"),
        ("DELETE", "/session/ses_test_1"),
    ]

    lignes = (await db_session.execute(select(AppelIA))).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].usage == "synthese"
    assert lignes[0].statut == "erreur"
    assert lignes[0].erreur == "inattendue"


async def test_interroger_annulation_pendant_le_message_est_rejaillie_et_journalisee(
    db_session: AsyncSession,
) -> None:
    """`asyncio.CancelledError` (hérite de `BaseException`, pas d'`Exception`
    depuis Python 3.8) ne doit jamais être avalée : elle est journalisée
    (code `"interrompu"`) puis rejaillit sans changer de type."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/session":
            return httpx.Response(200, json={"id": "ses_test_1"})
        if (
            request.method == "POST"
            and request.url.path == "/session/ses_test_1/message"
        ):
            raise asyncio.CancelledError()
        if request.method == "DELETE" and request.url.path == "/session/ses_test_1":
            return httpx.Response(200, json=True)
        raise AssertionError(f"requête inattendue : {request.method} {request.url}")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(asyncio.CancelledError):
        await interroger(
            db_session,
            http,
            usage="synthese",
            agent="habitat-synthese",
            texte=TEXTE_ENVOYE_INVENTE,
            schema=SCHEMA_INVENTE,
        )

    lignes = (await db_session.execute(select(AppelIA))).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].statut == "erreur"
    assert lignes[0].erreur == "interrompu"


async def test_interroger_exception_inattendue_pendant_la_suppression_napres_succes(
    db_session: AsyncSession,
) -> None:
    """Une exception qui n'est pas `httpx.HTTPError` pendant la suppression
    (best-effort, ici une `RuntimeError`) après un message réussi ne doit
    jamais empêcher le résultat d'être renvoyé, ni transformer la ligne
    `appel_ia` en échec."""
    reponses_base = _reponse_nominale()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            raise RuntimeError("boum inventé pendant la suppression")
        return _handler_json(reponses_base)(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    resultat = await interroger(
        db_session,
        http,
        usage="synthese",
        agent="habitat-synthese",
        texte=TEXTE_ENVOYE_INVENTE,
        schema=SCHEMA_INVENTE,
    )

    assert resultat.structure == {"resume": "résumé inventé", "actions": []}

    lignes = (await db_session.execute(select(AppelIA))).scalars().all()
    assert len(lignes) == 1
    assert lignes[0].statut == "ok"
    assert lignes[0].erreur is None


async def test_interroger_journal_defaillant_sur_echec_ne_masque_pas_lorigine(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si la journalisation elle-même échoue sur un chemin d'échec,
    l'exception d'origine (ici une `ErreurIA` `http_401`) doit continuer à
    remonter -- jamais remplacée par l'échec de comptabilité interne."""

    async def _journal_qui_echoue(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("panne de la base inventée pour le test")

    monkeypatch.setattr(opencode, "_journaliser_appel", _journal_qui_echoue)

    def handler(request: httpx.Request) -> httpx.Response:
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


# --------------------------------------------------------------------------
# `ReponseIA.brut` / `ErreurIA.brut` (Laboratoire IA, tâche LABO)
# --------------------------------------------------------------------------


async def test_interroger_reponse_brut_porte_info_et_parts(
    db_session: AsyncSession,
) -> None:
    reponses = _reponse_nominale()
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    resultat = await interroger(
        db_session,
        http,
        usage="synthese",
        agent="habitat-synthese",
        texte=TEXTE_ENVOYE_INVENTE,
        schema=SCHEMA_INVENTE,
    )

    assert isinstance(resultat.brut, dict)
    assert resultat.brut["info"]["structured"] == {
        "resume": "résumé inventé",
        "actions": [],
    }
    assert len(resultat.brut["parts"]) == 4


async def test_interroger_erreur_ia_porte_info_error_brut(
    db_session: AsyncSession,
) -> None:
    erreur_info = {
        "name": "ProviderAuthError",
        "data": {
            "providerID": "fournisseur-invente",
            "message": "message d'erreur inventé",
        },
    }
    info = _info_minimal(error=erreur_info)
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
            usage="explication",
            agent="habitat-explication",
            texte=TEXTE_ENVOYE_INVENTE,
            schema=SCHEMA_INVENTE,
        )

    assert exc_info.value.brut == erreur_info
    # Jamais dans le message (même principe que le mot de passe/le texte
    # envoyé, brief T-LABO).
    assert "message d'erreur inventé" not in str(exc_info.value)


async def test_interroger_erreur_sans_info_error_brut_none(
    db_session: AsyncSession,
) -> None:
    """`ErreurIA.brut` reste `None` quand l'échec ne vient pas d'`info.error`
    (ex. un statut HTTP 401 avant même d'atteindre `info`)."""
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, json={"message": "non autorisé"})
        )
    )

    with pytest.raises(ErreurIA) as exc_info:
        await interroger(
            db_session,
            http,
            usage="prix",
            agent="habitat-prix",
            texte=TEXTE_ENVOYE_INVENTE,
            schema=SCHEMA_INVENTE,
        )

    assert exc_info.value.brut is None


# --------------------------------------------------------------------------
# diagnostic_ia (Laboratoire IA, tâche LABO)
# --------------------------------------------------------------------------


def _reponses_diagnostic(
    *,
    agents: dict[str, Any] | None = None,
    connected: list[str] | None = None,
    outils: list[str] | None = None,
) -> dict[tuple[str, str], httpx.Response]:
    agents_effectifs = (
        agents
        if agents is not None
        else {
            "habitat-synthese": {},
            "habitat-explication": {},
            "habitat-prix": {},
            "un-autre-agent": {},
        }
    )
    connected_effectifs = connected if connected is not None else ["opencode", "openai"]
    outils_effectifs = (
        outils if outils is not None else ["bash", "websearch", "webfetch"]
    )
    return {
        ("GET", "/agent"): httpx.Response(200, json=agents_effectifs),
        ("GET", "/provider"): httpx.Response(
            200,
            json={"all": [], "connected": connected_effectifs, "default": "openai"},
        ),
        ("GET", "/experimental/tool/ids"): httpx.Response(200, json=outils_effectifs),
    }


async def test_diagnostic_ia_eteinte_aucune_requete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucune requête ne doit être faite, IA éteinte")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_active=False)
    )

    resultat = await diagnostic_ia(http)

    assert resultat == DiagnosticIA(
        ia_active=False,
        url_configuree=True,
        joignable=False,
        joignable_detail=None,
        agents=frozenset(),
        abonnement_connecte=False,
        recherche_web=False,
    )


async def test_diagnostic_ia_eteinte_sans_url_configuree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opencode,
        "get_settings",
        lambda: _SettingsIAFake(ia_active=False, opencode_url=None),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucune requête, IA éteinte")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    resultat = await diagnostic_ia(http)

    assert resultat.url_configuree is False


async def test_diagnostic_ia_active_nominal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())
    reponses = _reponses_diagnostic()
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    resultat = await diagnostic_ia(http)

    assert resultat.ia_active is True
    assert resultat.url_configuree is True
    assert resultat.joignable is True
    assert resultat.joignable_detail == "200"
    assert resultat.agents == AGENTS_ATTENDUS
    assert resultat.abonnement_connecte is True
    assert resultat.recherche_web is True


async def test_diagnostic_ia_abonnement_non_connecte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())
    reponses = _reponses_diagnostic(connected=["opencode"])
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    resultat = await diagnostic_ia(http)

    assert resultat.abonnement_connecte is False


async def test_diagnostic_ia_recherche_web_absente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())
    reponses = _reponses_diagnostic(outils=["bash", "webfetch"])
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    resultat = await diagnostic_ia(http)

    assert resultat.recherche_web is False


async def test_diagnostic_ia_agents_partiels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())
    reponses = _reponses_diagnostic(agents={"habitat-synthese": {}})
    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler_json(reponses)))

    resultat = await diagnostic_ia(http)

    assert resultat.agents == {"habitat-synthese"}


async def test_diagnostic_ia_injoignable_ne_leve_pas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brief LABO : « aucune exception ne remonte » -- une panne réseau se
    traduit en `joignable=False` avec le nom de l'exception, jamais une
    exception qui remonte à l'appelant."""
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("panne réseau inventée", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    resultat = await diagnostic_ia(http)

    assert resultat.joignable is False
    assert resultat.joignable_detail == "ConnectError"
    assert resultat.agents == frozenset()
    assert resultat.abonnement_connecte is False
    assert resultat.recherche_web is False


async def test_diagnostic_ia_statut_http_erreur(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    )

    resultat = await diagnostic_ia(http)

    assert resultat.joignable is False
    assert resultat.joignable_detail == "500"


# --------------------------------------------------------------------------
# ia_appels_max_jour (Laboratoire IA, tâche LABO) -- même principe qu'ia_active
# --------------------------------------------------------------------------


def test_ia_appels_max_jour_lit_les_reglages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        opencode, "get_settings", lambda: _SettingsIAFake(ia_appels_max_jour=17)
    )

    assert opencode.ia_appels_max_jour() == 17
