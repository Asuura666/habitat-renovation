"""Client d'OpenCode (`ingest/opencode.py`, T3, phase 4 IA).

Seul module de tout le dépôt qui parle au moteur d'IA (décision D2 de
`docs/superpowers/specs/2026-09-27-phase-4-ia-design.md` : **OpenCode**
(`opencode serve`, conteneur interne) connecté à l'abonnement ChatGPT
Plus/Pro d'Ilane, choisi contre la recommandation de Claude — API Mistral en
direct, déjà dans la stack). Aucune classe « fournisseur » abstraite
(`CLAUDE.md` interdit les abstractions « pour plus tard ») : l'isolation
tient au fait que ce module est le seul point d'entrée réseau vers l'IA —
changer de fournisseur, c'est réécrire ce fichier, jamais un autre.

API utilisée (extrait réel de l'OpenAPI d'OpenCode 1.18.32,
`.superpowers/sdd/2026-09-27-phase-4-ia/opencode-api-extrait.json`) :
- `POST {url}/session` (`{"title": "habitat-<usage>"}`) -> `{"id": "ses..."}` ;
- `POST {url}/session/{id}/message` (`{"agent", "parts": [{"type": "text",
  "text": ...}], "format": {"type": "json_schema", "schema": ..., "retryCount":
  1}}`) -> `{"info": AssistantMessage, "parts": [Part, ...]}` — `info.error`
  (un des schémas `ProviderAuthError`/`APIError`/`UnknownError`/...) signale
  un échec fournisseur ; `info.structured` porte la sortie JSON demandée ;
- `DELETE {url}/session/{id}` -> tenté systématiquement, échec ignoré.

Authentification HTTP Basic, utilisateur `opencode`, mot de passe
`Settings.opencode_mot_de_passe` (§3.3/3.4 de la spec). Aucun message
d'erreur de ce module ne contient jamais ce mot de passe, le texte envoyé à
l'IA, ni sa réponse (même principe qu'`ErreurOCR`/`ErreurTelegram`) ; les
quelques `logger.warning` de ce module (fix round 1 : échec best-effort de
la suppression d'une session ou de la journalisation d'un appel) ne portent
jamais que l'`usage` et le nom de la classe d'une exception, jamais ce mot
de passe, le texte envoyé ni la réponse.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from datetime import time as heure
from typing import Any, Literal

import httpx
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings, get_settings
from app.core.fuseau import FUSEAU_PARIS
from app.modules.extract.reponses_ia import PageLue
from app.modules.ingest.models import AppelIA

logger = logging.getLogger(__name__)

_UTILISATEUR_BASIC = "opencode"
_DELAI_DEFAUT_S = 90.0
_OUTILS_PAGE = ("webfetch", "websearch")
# Codes journalisés dans `appel_ia.erreur` pour une exception qui n'est pas
# une `ErreurIA` (fix round 1) : `_creer_session`/`_envoyer_message` ne
# lèvent normalement que des `ErreurIA`, mais un bug imprévu ou une
# annulation de tâche (`asyncio.CancelledError`) doivent quand même être
# journalisés avant de rejaillir, jamais silencieusement perdus ni
# transformés en `UnboundLocalError` (voir `interroger`).
_CODE_ERREUR_INATTENDUE = "inattendue"
_CODE_ERREUR_INTERROMPU = "interrompu"


class ErreurIA(Exception):
    """Échec d'un appel à l'IA (réseau, délai, statut HTTP, erreur renvoyée
    par le fournisseur, réponse sans sortie structurée). `code` va dans
    `AppelIA.erreur` (ex. `"reseau"`, `"delai"`, `"http_401"`,
    `"ProviderAuthError"`, `"APIError_429"`, `"StructuredOutputError"`,
    `"sans_sortie"`) ; le message ne contient jamais le mot de passe, le
    texte envoyé, la réponse de l'IA, ni l'exception httpx brute (toujours
    levée `from None`)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IAIndisponible(Exception):
    """L'appel n'a **pas** été tenté (aucune requête, aucune ligne
    `appel_ia`) : `raison="eteinte"` (`IA_ACTIVE` faux) ou `raison="plafond"`
    (`IA_APPELS_MAX_JOUR` atteint pour la journée en cours, heure de
    Paris)."""

    def __init__(self, raison: Literal["eteinte", "plafond"]) -> None:
        super().__init__(raison)
        self.raison = raison


@dataclass(frozen=True)
class ReponseIA:
    """Réponse d'un appel réussi à `interroger`. `structure` : le JSON
    demandé (`info.structured`), encore non gardé — chaque appelant le
    passe à la fonction `lire_...` de `extract.reponses_ia` qui va avec son
    usage. `pages` : les pages effectivement lues par l'IA (outils
    `webfetch`/`websearch` terminés). `modele` : `providerID/modelID`
    quand les deux sont présents, sinon `None`."""

    structure: Any
    pages: tuple[PageLue, ...]
    modele: str | None
    duree_ms: int


def ia_active() -> bool:
    """Seule lecture de `Settings.ia_active` de tout le code (même principe
    qu'`ingest.commun.controle_prix_actif` pour `CONTROLE_PRIX_ACTIF`)."""
    return get_settings().ia_active


def _debut_jour_paris() -> datetime:
    """Instant (tz-aware) du début (00:00:00) du jour civil parisien en
    cours -- même principe que `api.anomalies._debut_jour_paris`, dupliqué
    ici plutôt qu'importé : `ingest` ne peut pas importer `api` (frontière
    L2-D3, `tests/test_frontieres.py`), et cette fonction est trop petite
    pour justifier de la faire migrer vers `app.core`."""
    aujourd_hui = datetime.now(FUSEAU_PARIS).date()
    return datetime.combine(aujourd_hui, heure.min, tzinfo=FUSEAU_PARIS)


async def appels_du_jour(session: AsyncSession) -> int:
    """Nombre de lignes `appel_ia` dont `created_at` tombe dans la journée
    civile parisienne en cours (toutes valeurs de `usage`/`statut`
    confondues : le plafond compte aussi les échecs, brief T3 étape 7)."""
    resultat = await session.execute(
        select(func.count())
        .select_from(AppelIA)
        .where(AppelIA.created_at >= _debut_jour_paris())
    )
    return resultat.scalar_one()


def _url_opencode(settings: Settings) -> str:
    """`opencode_url` sans barre oblique finale (brief T3) : `Settings`
    garantit déjà sa présence quand `ia_active` est vrai (validateur
    croisé) -- le `RuntimeError` ci-dessous documente cet invariant, il ne
    signale jamais un échec d'appel (ce n'est pas une `ErreurIA`)."""
    if not settings.opencode_url:
        raise RuntimeError(
            "opencode_url manquant alors que l'IA est active "
            "(devrait être bloqué par Settings)"
        )
    return settings.opencode_url.rstrip("/")


def _authentification(settings: Settings) -> httpx.BasicAuth:
    """Authentification HTTP Basic (utilisateur `opencode`), même garde
    d'invariant que `_url_opencode`."""
    if settings.opencode_mot_de_passe is None:
        raise RuntimeError(
            "opencode_mot_de_passe manquant alors que l'IA est active "
            "(devrait être bloqué par Settings)"
        )
    return httpx.BasicAuth(
        _UTILISATEUR_BASIC, settings.opencode_mot_de_passe.get_secret_value()
    )


async def _requete_json(
    http: httpx.AsyncClient,
    url: str,
    corps: dict[str, Any],
    auth: httpx.BasicAuth,
    delai: float,
) -> dict[str, Any]:
    """`POST url` avec authentification Basic, traduit en `ErreurIA` selon
    le brief T3 : délai dépassé -> `"delai"` ; toute autre erreur httpx
    (connexion, DNS, ...) -> `"reseau"` ; statut >= 400 -> `"http_<statut>"` ;
    JSON illisible ou pas un objet -> `"reponse_illisible"`. Jamais
    l'exception httpx brute (elle embarque l'URL et, potentiellement, un
    fragment du corps envoyé)."""
    try:
        reponse = await http.post(url, json=corps, auth=auth, timeout=delai)
    except httpx.TimeoutException:
        raise ErreurIA("delai", "Délai dépassé lors de l'appel à OpenCode") from None
    except httpx.HTTPError:
        raise ErreurIA("reseau", "Échec réseau vers OpenCode") from None

    if reponse.status_code >= 400:
        raise ErreurIA(
            f"http_{reponse.status_code}",
            f"OpenCode a répondu {reponse.status_code}",
        )

    try:
        corps_reponse = reponse.json()
    except ValueError:
        raise ErreurIA(
            "reponse_illisible", "Réponse OpenCode illisible (JSON invalide)"
        ) from None
    if not isinstance(corps_reponse, dict):
        raise ErreurIA(
            "reponse_illisible", "Réponse OpenCode invalide (objet JSON attendu)"
        ) from None
    return corps_reponse


async def _creer_session(
    http: httpx.AsyncClient,
    url: str,
    auth: httpx.BasicAuth,
    usage: str,
    delai: float,
) -> str:
    """`POST {url}/session` -> identifiant de la session créée."""
    corps = await _requete_json(
        http, f"{url}/session", {"title": f"habitat-{usage}"}, auth, delai
    )
    identifiant = corps.get("id")
    if not isinstance(identifiant, str):
        raise ErreurIA(
            "reponse_illisible",
            "Réponse OpenCode illisible (session sans identifiant)",
        )
    return identifiant


def _code_erreur_info(erreur_info: Any) -> str:
    """`code` d'`ErreurIA` à partir d'`info.error` : le nom de l'erreur
    (`ProviderAuthError`, `StructuredOutputError`, `UnknownError`, ...),
    suffixé du statut HTTP pour `APIError` quand `data.statusCode` est
    présent (`"APIError_429"`, brief T3 étape 5)."""
    if not isinstance(erreur_info, dict):
        return "erreur_ia_inconnue"
    nom = erreur_info.get("name")
    if not isinstance(nom, str) or not nom:
        return "erreur_ia_inconnue"
    if nom == "APIError":
        data = erreur_info.get("data")
        if isinstance(data, dict):
            statut = data.get("statusCode")
            if isinstance(statut, int):
                return f"APIError_{statut}"
    return nom


def _modele_info(info: Mapping[str, Any]) -> str | None:
    """`providerID/modelID` quand les deux sont présents et non vides,
    sinon `None` (brief T3)."""
    provider = info.get("providerID")
    modele_id = info.get("modelID")
    if (
        isinstance(provider, str)
        and provider
        and isinstance(modele_id, str)
        and modele_id
    ):
        return f"{provider}/{modele_id}"
    return None


def _page_lue(part: Any) -> PageLue | None:
    """Une partie `tool` d'OpenCode -> `PageLue`, ou `None` si elle ne
    correspond pas à une page lue (pas un outil `webfetch`/`websearch`, pas
    encore terminée, ou mal formée -- brief T3 : « ignorer silencieusement
    un élément mal formé »)."""
    if not isinstance(part, dict) or part.get("type") != "tool":
        return None
    outil = part.get("tool")
    if outil not in _OUTILS_PAGE:
        return None
    etat = part.get("state")
    if not isinstance(etat, dict) or etat.get("status") != "completed":
        return None
    entree = etat.get("input")
    sortie = etat.get("output")
    if not isinstance(entree, dict) or not isinstance(sortie, str):
        return None
    cle_adresse = "url" if outil == "webfetch" else "query"
    adresse = entree.get(cle_adresse)
    if not isinstance(adresse, str):
        return None
    return PageLue(outil=outil, adresse=adresse, texte=sortie)


def _pages_lues(parts: Any) -> tuple[PageLue, ...]:
    if not isinstance(parts, list):
        return ()
    pages = (_page_lue(part) for part in parts)
    return tuple(page for page in pages if page is not None)


async def _envoyer_message(
    http: httpx.AsyncClient,
    url: str,
    auth: httpx.BasicAuth,
    session_id: str,
    *,
    agent: str,
    texte: str,
    schema: Mapping[str, Any],
    delai: float,
) -> tuple[Any, tuple[PageLue, ...], str | None]:
    """`POST {url}/session/{id}/message` en sortie structurée -> `(structure,
    pages, modele)`. Lève `ErreurIA` sur `info.error` ou `info.structured`
    absent/`None` (brief T3 étape 5)."""
    corps_requete = {
        "agent": agent,
        "parts": [{"type": "text", "text": texte}],
        "format": {"type": "json_schema", "schema": dict(schema), "retryCount": 1},
    }
    corps = await _requete_json(
        http, f"{url}/session/{session_id}/message", corps_requete, auth, delai
    )

    info = corps.get("info")
    if not isinstance(info, dict):
        raise ErreurIA(
            "reponse_illisible", "Réponse OpenCode illisible (message sans info)"
        )

    erreur_info = info.get("error")
    if erreur_info is not None:
        raise ErreurIA(_code_erreur_info(erreur_info), "OpenCode a renvoyé une erreur")

    structure = info.get("structured")
    if structure is None:
        raise ErreurIA("sans_sortie", "Réponse d'OpenCode sans sortie structurée")

    return structure, _pages_lues(corps.get("parts")), _modele_info(info)


async def _journaliser_appel(
    session: AsyncSession,
    *,
    usage: Literal["synthese", "explication", "prix"],
    statut: Literal["ok", "erreur"],
    erreur: str | None,
    duree_ms: int,
) -> None:
    """Insère la ligne `appel_ia` et la **commite dans sa propre session**,
    jamais dans `session` (celle de l'appelant, brief T3 étape 7) : le
    plafond quotidien (`appels_du_jour`) doit compter une requête tentée
    même si l'appelant annule ensuite (`rollback`) le reste de sa propre
    transaction.

    `interroger` ne reçoit qu'une `AsyncSession` (jamais l'`AsyncEngine` ni
    la fabrique de sessions qui l'a créée -- voir la dépendance FastAPI
    `app.core.db.get_session`), donc la façon la plus simple d'obtenir « le
    même moteur » pour une session indépendante est de le retrouver depuis
    `session` elle-même : `AsyncSession.get_bind()` renvoie l'`Engine`
    synchrone sous-jacent (celui que `AsyncEngine.sync_engine` expose déjà,
    documenté par SQLAlchemy comme le bind du `Session` proxifié), et
    `AsyncEngine(engine_sync)` en reconstruit un wrapper asyncio -- même
    moteur, même pool de connexions, sans ouvrir de pool ni de connexion
    supplémentaire. Toutes les sessions de ce dépôt sont créées via
    `app.core.db.creer_sessionmaker(engine)` (jamais liées à une
    `Connection` isolée), donc `get_bind()` y renvoie toujours un `Engine`
    -- le `RuntimeError` ci-dessous documente cet invariant plutôt que de le
    supposer silencieusement."""
    bind = session.get_bind()
    if not isinstance(bind, Engine):
        raise RuntimeError(
            "session sans Engine (get_bind() a renvoyé autre chose) -- ne "
            "devrait jamais arriver dans ce dépôt"
        )
    async with AsyncSession(AsyncEngine(bind)) as session_isolee:
        session_isolee.add(
            AppelIA(usage=usage, statut=statut, erreur=erreur, duree_ms=duree_ms)
        )
        await session_isolee.commit()


async def interroger(
    session: AsyncSession,
    http: httpx.AsyncClient,
    *,
    usage: Literal["synthese", "explication", "prix"],
    agent: str,
    texte: str,
    schema: Mapping[str, Any],
    delai: float | None = None,
) -> ReponseIA:
    """Envoie `texte` à l'agent OpenCode `agent`, en demandant une sortie
    structurée conforme à `schema` (`extract.reponses_ia.SCHEMA_...`).

    1. `ia_active()` faux -> `IAIndisponible("eteinte")`, aucune requête ;
    2. plafond quotidien atteint (`appels_du_jour`) -> `IAIndisponible
       ("plafond")`, aucune requête ;
    3-4. création de la session OpenCode puis envoi du message (§module) ;
    5. lecture de la réponse (`_envoyer_message`) ;
    6. suppression de la session OpenCode **toujours** tentée dès qu'elle a
       été créée (succès ou échec) -- un échec de cette suppression est
       ignoré (best-effort) et ne masque jamais l'erreur d'origine ;
    7. une ligne `appel_ia` est **toujours** insérée et commitée (dans une
       session à part, voir `_journaliser_appel`) dès qu'une requête a été
       tentée (donc jamais pour `IAIndisponible`, toujours pour toute autre
       exception ou tout succès).

    Délai par défaut 90 s (`delai=None`) ; `prix` passe `delai=240` (recherche
    internet, plus longue). `ErreurIA`/`IAIndisponible` ne contiennent jamais
    le mot de passe, le texte envoyé, ni la réponse ; les `logger.warning` de
    ce module (fix round 1, voir plus bas) non plus, ils ne portent jamais que
    l'`usage` et le nom de la classe d'une exception.

    Robustesse (fix round 1, revue de la tâche T3) : l'écriture de la ligne
    `appel_ia` (étape 7) ne doit **jamais** remplacer l'exception d'origine
    par une exception de comptabilité interne, y compris quand
    `_creer_session`/`_envoyer_message` lève autre chose qu'une `ErreurIA`
    (bug imprévu -- code `"inattendue"`) ou une `asyncio.CancelledError`
    (annulation de la tâche -- code `"interrompu"`, jamais avalée : elle est
    quand même journalisée avant de rejaillir, mais aucun `except Exception`
    de cette fonction ne la capture jamais, puisqu'elle hérite de
    `BaseException` depuis Python 3.8). Si la suppression de la session
    (étape 6) est elle-même annulée, l'annulation prend le pas sur toute
    erreur déjà en cours (elle sera rejaillie après la journalisation). Si la
    journalisation elle-même échoue : sur un chemin d'échec, l'exception
    d'origine est rejaillie **inchangée** (le même objet, jamais enveloppé) et
    l'échec de la journalisation n'est que journalisé (`logger.warning`, sans
    aucun contenu) ; sur le chemin de succès, un échec de la journalisation
    remonte tel quel (rien à préserver derrière)."""
    if not ia_active():
        raise IAIndisponible("eteinte")

    settings = get_settings()
    if await appels_du_jour(session) >= settings.ia_appels_max_jour:
        raise IAIndisponible("plafond")

    url = _url_opencode(settings)
    auth = _authentification(settings)
    delai_effectif = delai if delai is not None else _DELAI_DEFAUT_S

    debut = time.monotonic()
    session_id: str | None = None
    resultat: tuple[Any, tuple[PageLue, ...], str | None] | None = None
    # Toujours bindés avant le `try` (fix round 1) : aucune exception, connue
    # ou non, ne peut jamais laisser ces deux variables non définies au
    # moment de la journalisation ci-dessous.
    exception_survenue: BaseException | None = None
    code_erreur: str | None = None

    try:
        session_id = await _creer_session(http, url, auth, usage, delai_effectif)
        resultat = await _envoyer_message(
            http,
            url,
            auth,
            session_id,
            agent=agent,
            texte=texte,
            schema=schema,
            delai=delai_effectif,
        )
    except ErreurIA as erreur:
        code_erreur = erreur.code
        exception_survenue = erreur
    except asyncio.CancelledError as erreur:
        code_erreur = _CODE_ERREUR_INTERROMPU
        exception_survenue = erreur
    except Exception as erreur:
        code_erreur = _CODE_ERREUR_INATTENDUE
        exception_survenue = erreur

    if session_id is not None:
        try:
            reponse_suppression = await http.delete(
                f"{url}/session/{session_id}", auth=auth, timeout=delai_effectif
            )
            reponse_suppression.raise_for_status()
        except asyncio.CancelledError as erreur:
            # Une annulation pendant la suppression prime sur toute erreur
            # déjà en cours (jamais avalée) : elle remplace `exception_
            # survenue`, rejaillie après la journalisation ci-dessous.
            code_erreur = _CODE_ERREUR_INTERROMPU
            exception_survenue = erreur
        except Exception as erreur_suppression:
            # Best-effort (§module) : jamais l'erreur d'origine (si déjà
            # connue) n'est remplacée par un échec de suppression. Seul le
            # nom de la classe est journalisé, jamais un message qui
            # pourrait embarquer une URL ou un fragment de réponse.
            logger.warning(
                "échec de la suppression d'une session OpenCode : %s",
                type(erreur_suppression).__name__,
            )

    duree_ms = round((time.monotonic() - debut) * 1000)

    try:
        await _journaliser_appel(
            session,
            usage=usage,
            statut="erreur" if exception_survenue is not None else "ok",
            erreur=code_erreur,
            duree_ms=duree_ms,
        )
    except Exception as erreur_journal:
        if exception_survenue is not None:
            logger.warning(
                "échec de la journalisation d'un appel IA en échec (usage=%s) : %s",
                usage,
                type(erreur_journal).__name__,
            )
            raise exception_survenue from None
        raise

    if exception_survenue is not None:
        raise exception_survenue

    if resultat is None:
        raise RuntimeError(
            "état interne incohérent (ni exception ni résultat) -- ne "
            "devrait jamais arriver"
        )
    structure, pages, modele = resultat
    return ReponseIA(structure=structure, pages=pages, modele=modele, duree_ms=duree_ms)
