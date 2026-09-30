"""Essais de l'IA avant de s'y fier (« Laboratoire IA », tâche LABO, admin) :
lance un essai des trois usages de l'IA (prix internet, explication d'une
alerte prix, synthèse hebdomadaire) et garde, en mémoire du processus, une
trace complète de ce qui s'est passé -- texte envoyé, pages ouvertes, réponse
brute, contrôles anti-invention appliqués, résultat, erreur éventuelle -- pour
que l'admin voie exactement ce que fait l'IA avant de s'y fier (demande
d'Ilane, 28/09/2026).

Principes (non négociables, brief LABO) :

- **Un essai n'enregistre rien** : aucune `SyntheseCommentaires`,
  `SyntheseAction`, `ExplicationAlerte`, `PrixInternet`, aucune entrée de
  `journal`, aucune anomalie touchée. Seule la ligne `appel_ia` écrite par
  `ingest.opencode.interroger` existe (le plafond du jour compte aussi les
  essais).
- **Aucune duplication** des textes envoyés ni des gardes : ce module appelle
  les mêmes fonctions de construction de texte
  (`ia_prix._texte_prix`/`_texte_explication`,
  `ia_synthese._texte_synthese`/`_commentaires_de_la_semaine`) et de lecture
  (`extract.reponses_ia.lire_...`/`controles_...`) que la production -- jamais
  une seconde implémentation.
- Le serveur tourne en un seul processus uvicorn (`CMD` du `Dockerfile` :
  `uvicorn app.main:app ...` sans `--workers`) : un dictionnaire en mémoire du
  processus, borné aux 20 derniers essais, est donc un état cohérent pour
  toute requête -- perdu au redémarrage (l'écran le dit), acceptable pour un
  outil d'admin.
- Aucun secret ni texte envoyé/réponse de l'IA n'est journalisé par ce
  module -- seule `interroger` écrit une ligne `appel_ia` (usage/statut/durée/
  erreur, jamais le contenu).
- **Un essai se termine toujours** (fix round 1, revue LABO) : chaque
  `_executer_essai_...` porte un filet de sécurité (`except Exception`,
  jamais `except BaseException` -- une annulation continue de se propager)
  qui termine la trace en `erreur` (message générique, code = nom de la
  classe de l'exception seulement, jamais son message) au lieu de la laisser
  bloquée en `en_cours` pour toujours si un bug imprévu survient (dans
  `controles_...`, dans le calcul des appels restants, ...) -- l'écran
  interroge l'essai toutes les 2 s tant qu'il reste `en_cours`.

Chaque essai lance son travail en tâche de fond (`fastapi.BackgroundTasks`,
même mécanique que `ingest.router.webhook_telegram`) : la validation
(anomalie/semaine) et la construction du texte envoyé se font tout de suite
(pour que la trace `en_cours` affiche déjà « ① texte envoyé » sans attendre),
l'appel à l'IA et la suite (contrôles, lecture, résultat) se font ensuite,
dans une session et un client HTTP propres à l'application (jamais ceux de la
requête, fermés avant que la tâche de fond ne s'exécute)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx
from fastapi import BackgroundTasks
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.extract.reponses_ia import (
    SCHEMA_EXPLICATION,
    SCHEMA_PRIX_INTERNET,
    SCHEMA_SYNTHESE,
    Controle,
    PageLue,
    PrixInternetLu,
    ReponseIAInvalide,
    SyntheseLue,
    controles_explication,
    controles_prix_internet,
    controles_synthese,
    lire_explication,
    lire_prix_internet,
    lire_synthese,
)
from app.modules.ingest.anomalies import AnomalieIntrouvable, categorie_regle
from app.modules.ingest.ia_prix import (
    _TITRE_REPLI,
    TITRES_REGLES_PRIX,
    _texte_explication,
    _texte_prix,
)
from app.modules.ingest.ia_synthese import (
    _bornes_semaine_paris,
    _commentaires_de_la_semaine,
    _texte_synthese,
)
from app.modules.ingest.models import Anomalie, AppelIA, Document, Fournisseur
from app.modules.ingest.opencode import (
    ErreurIA,
    IAIndisponible,
    appels_du_jour,
    ia_appels_max_jour,
    interroger,
)

logger = logging.getLogger(__name__)

TypeEssai = Literal["prix", "explication", "synthese"]
StatutEssai = Literal["en_cours", "fini", "erreur"]

# Extrait des pages lues, tronqué (brief LABO) : une page web peut être très
# longue, jamais recopiée en entier dans une trace gardée en mémoire.
_EXTRAIT_MAX = 3000

# Essais gardés en mémoire du processus (brief LABO) : les plus anciens sont
# chassés au-delà de cette limite. Un dict Python garde l'ordre d'insertion
# (CPython >= 3.7, garanti par le langage) : le premier itéré est le plus
# ancien encore présent.
_ESSAIS_MAX = 20
_essais: dict[uuid.UUID, TraceEssai] = {}


@dataclass(frozen=True)
class OutilTrace:
    """Un outil utilisé par l'IA pendant l'essai (`websearch`/`webfetch`,
    brief LABO) : `adresse` est la requête pour une recherche, l'URL pour une
    page ouverte -- même convention que `extract.reponses_ia.PageLue`.
    `extrait` : le texte renvoyé par l'outil, tronqué à `_EXTRAIT_MAX`
    caractères."""

    outil: str
    adresse: str
    extrait: str


@dataclass
class TraceEssai:
    """Déroulé complet d'un essai (brief LABO) -- mutable : mise à jour en
    place par la tâche de fond au fil de son avancement (`statut`, `fin`,
    `duree_ms`, puis le reste), jamais reconstruite. `schema` : le schéma
    JSON envoyé à l'IA (`SCHEMA_...`, `extract.reponses_ia`). `resultat` : ce
    qui serait affiché à l'admin si l'essai était réel (prix trouvé ou non
    vérifiable et raison / texte de l'explication / résumé et actions
    gardées) -- `None` tant que l'essai est `en_cours` ou s'il a échoué.
    `erreur` : `{"code", "message_court", "brut"}` si l'essai a échoué,
    `None` sinon. `appels_restants` : plafond du jour moins les appels du
    jour, calculé juste après l'essai (compte l'essai lui-même)."""

    id: uuid.UUID
    type: TypeEssai
    statut: StatutEssai
    debut: datetime
    fin: datetime | None
    duree_ms: int | None
    agent: str
    texte_envoye: str
    schema: dict[str, Any]
    modele: str | None = None
    outils: tuple[OutilTrace, ...] = ()
    reponse_brute: Any = None
    controles: tuple[Controle, ...] = field(default_factory=tuple)
    resultat: dict[str, Any] | None = None
    erreur: dict[str, Any] | None = None
    appels_restants: int | None = None


def _enregistrer_trace(trace: TraceEssai) -> None:
    """Ajoute `trace` au registre en mémoire, en chassant les plus anciennes
    au-delà de `_ESSAIS_MAX` (brief LABO : « dictionnaire borné aux 20
    derniers essais, les plus anciens chassés »)."""
    _essais[trace.id] = trace
    while len(_essais) > _ESSAIS_MAX:
        plus_ancien_id = next(iter(_essais))
        del _essais[plus_ancien_id]


def lire_essai(essai_id: uuid.UUID) -> TraceEssai | None:
    """L'essai `essai_id`, ou `None` s'il est inconnu ou a été chassé (l'API
    traduit en 404)."""
    return _essais.get(essai_id)


def derniers_essais() -> tuple[TraceEssai, ...]:
    """Les essais encore en mémoire, les plus récents d'abord (brief LABO,
    « liste cliquable »)."""
    return tuple(reversed(_essais.values()))


@dataclass(frozen=True)
class LigneAppelIA:
    """Une ligne du journal des appels (brief LABO, `GET /api/ia/labo/appels`)
    -- mêmes colonnes qu'`AppelIA`, jamais le texte envoyé ni la réponse (que
    cette table ne porte de toute façon jamais, `ingest.opencode`)."""

    id: uuid.UUID
    usage: str
    statut: str
    erreur: str | None
    duree_ms: int
    created_at: datetime


async def journal_appels(
    session: AsyncSession, limite: int = 50
) -> tuple[LigneAppelIA, ...]:
    """Les `limite` dernières lignes `appel_ia`, les plus récentes d'abord
    (brief LABO)."""
    lignes = (
        await session.execute(
            select(AppelIA).order_by(desc(AppelIA.created_at)).limit(limite)
        )
    ).scalars()
    return tuple(
        LigneAppelIA(
            id=ligne.id,
            usage=ligne.usage,
            statut=ligne.statut,
            erreur=ligne.erreur,
            duree_ms=ligne.duree_ms,
            created_at=ligne.created_at,
        )
        for ligne in lignes
    )


# --------------------------------------------------------------------------
# Construction commune de la trace terminée (succès ou échec)
# --------------------------------------------------------------------------


def _outils_trace(pages: Sequence[PageLue]) -> tuple[OutilTrace, ...]:
    return tuple(
        OutilTrace(
            outil=page.outil, adresse=page.adresse, extrait=page.texte[:_EXTRAIT_MAX]
        )
        for page in pages
    )


_MESSAGES_IA_INDISPONIBLE: dict[str, str] = {
    "eteinte": "L'IA est éteinte sur cette instance.",
    "plafond": "Le plafond d'appels du jour est atteint.",
}


def _erreur_ia_indisponible(exc: IAIndisponible) -> dict[str, Any]:
    return {
        "code": exc.raison,
        "message_court": _MESSAGES_IA_INDISPONIBLE[exc.raison],
        "brut": None,
    }


def _erreur_erreur_ia(exc: ErreurIA) -> dict[str, Any]:
    return {"code": exc.code, "message_court": str(exc), "brut": exc.brut}


def _erreur_reponse_invalide(exc: ReponseIAInvalide) -> dict[str, Any]:
    return {"code": "reponse_invalide", "message_court": str(exc), "brut": None}


async def _appels_restants(session: AsyncSession) -> int:
    """Plafond du jour moins les appels du jour (brief LABO) -- calculé après
    l'essai, qui compte donc déjà dedans. `opencode.ia_appels_max_jour()`
    (jamais un import direct de `app.core.config.get_settings`, fix de
    revue) : seule référence que les tests substituent
    (`monkeypatch.setattr(opencode, "get_settings", ...)`, même mécanique
    qu'`ia_active`) -- un import direct aurait gardé la vraie fonction,
    jamais remplacée, et aurait donné un plafond incohérent avec celui
    réellement appliqué par `interroger` pour ce même essai."""
    return max(ia_appels_max_jour() - await appels_du_jour(session), 0)


async def _appels_restants_sans_echec(session: AsyncSession) -> int | None:
    """`_appels_restants`, best-effort (fix round 1, revue LABO) : une panne
    ici (ex. base indisponible juste après un essai autrement réussi) ne
    doit jamais empêcher l'essai de se terminer avec son résultat déjà
    calculé -- seul `appels_restants` reste alors `None`, jamais
    l'ensemble de la trace perdu au profit d'un état « erreur imprévue »
    générique. Journalisé (jamais le texte envoyé ni la réponse, qu'elle
    ne reçoit de toute façon pas)."""
    try:
        return await _appels_restants(session)
    except Exception:
        logger.exception(
            "échec du calcul des appels restants après un essai du Laboratoire IA"
        )
        return None


async def _terminer_en_echec_avant_appel(
    trace: TraceEssai, session: AsyncSession, erreur: dict[str, Any]
) -> None:
    """Termine `trace` sans qu'aucune requête n'ait été tentée (`IAIndisponible`,
    éteinte ou plafond) -- `appels_restants` reste malgré tout exact (aucun
    appel supplémentaire n'a été fait, mais le plafond peut déjà être
    atteint)."""
    fin = datetime.now(UTC)
    trace.statut = "erreur"
    trace.fin = fin
    trace.duree_ms = round((fin - trace.debut).total_seconds() * 1000)
    trace.erreur = erreur
    trace.appels_restants = await _appels_restants_sans_echec(session)


async def _terminer(
    trace: TraceEssai,
    session: AsyncSession,
    *,
    modele: str | None,
    outils: tuple[OutilTrace, ...],
    reponse_brute: Any,
    controles: tuple[Controle, ...],
    resultat: dict[str, Any] | None,
    erreur: dict[str, Any] | None,
) -> None:
    """Termine `trace` après une requête effectivement tentée à l'IA (succès
    ou échec de lecture de sa réponse) -- `statut="fini"` si `erreur` est
    `None`, `"erreur"` sinon."""
    fin = datetime.now(UTC)
    trace.statut = "erreur" if erreur is not None else "fini"
    trace.fin = fin
    trace.duree_ms = round((fin - trace.debut).total_seconds() * 1000)
    trace.modele = modele
    trace.outils = outils
    trace.reponse_brute = reponse_brute
    trace.controles = controles
    trace.resultat = resultat
    trace.erreur = erreur
    trace.appels_restants = await _appels_restants_sans_echec(session)


def _erreur_imprevue(exc: Exception) -> dict[str, Any]:
    """`code` : le nom de la classe de l'exception **seulement**, jamais
    `str(exc)` (pourrait porter une donnée -- brief fix round 1, même
    principe que les `logger.warning` d'`ingest.opencode`, qui ne portent
    eux non plus jamais que `type(exc).__name__`)."""
    return {
        "code": type(exc).__name__,
        "message_court": "Erreur imprévue pendant l'essai.",
        "brut": None,
    }


def _terminer_en_erreur_imprevue(trace: TraceEssai, exc: Exception) -> None:
    """Dernier filet (fix round 1, revue LABO) : une exception qu'aucun des
    `except` ciblés de `_executer_essai_...` ne prévoyait (bug dans
    `controles_...`/`_resultat_...`, panne à l'ouverture de la session, ...)
    ne doit **jamais** laisser une trace bloquée en `en_cours` pour toujours
    -- l'écran l'interroge toutes les 2 s tant qu'elle y reste. Ne recalcule
    pas `appels_restants` : le recalculer exigerait une nouvelle session,
    susceptible d'échouer pour la même raison que l'exception d'origine (une
    panne de base, par exemple) ; il reste à sa valeur précédente (`None` si
    l'essai n'avait encore rien terminé)."""
    fin = datetime.now(UTC)
    trace.statut = "erreur"
    trace.fin = fin
    trace.duree_ms = round((fin - trace.debut).total_seconds() * 1000)
    trace.erreur = _erreur_imprevue(exc)


def _resultat_prix(resultat: PrixInternetLu) -> dict[str, Any]:
    return {
        "statut": resultat.statut,
        "prix": str(resultat.prix) if resultat.prix is not None else None,
        "devise": resultat.devise,
        "taxes": resultat.taxes,
        "unite": resultat.unite,
        "conditionnement": resultat.conditionnement,
        "produit_trouve": resultat.produit_trouve,
        "source_url": resultat.source_url,
        "confiance": resultat.confiance,
        "raison": resultat.raison,
        "offres": [
            {
                "prix": str(o.prix),
                "taxes": o.taxes,
                "prix_ht": str(o.prix_ht) if o.prix_ht is not None else None,
                "unite": o.unite,
                "conditionnement": o.conditionnement,
                "produit_trouve": o.produit_trouve,
                "source_url": o.source_url,
                "confiance": o.confiance,
            }
            for o in resultat.offres
        ],
    }


def _resultat_synthese(synthese_lue: SyntheseLue) -> dict[str, Any]:
    return {
        "resume": synthese_lue.resume,
        "actions": [
            {"texte": action.texte, "commentaires": list(action.references)}
            for action in synthese_lue.actions
        ],
    }


# --------------------------------------------------------------------------
# Essai : prix trouvé sur internet
# --------------------------------------------------------------------------


async def _executer_essai_prix(
    trace: TraceEssai,
    sessions: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
) -> None:
    # Filet de sécurité (fix round 1, revue LABO) : `except Exception`, jamais
    # `except BaseException` -- une annulation (`asyncio.CancelledError`,
    # hérite de `BaseException` depuis Python 3.8) doit continuer à se
    # propager sans passer par ici. Tout le reste (bug dans `controles_...`,
    # panne à l'ouverture de la session, ...) termine la trace au lieu de la
    # laisser bloquée en `en_cours` pour toujours (l'écran l'interroge toutes
    # les 2 s tant qu'elle y reste).
    try:
        async with sessions() as session:
            try:
                reponse = await interroger(
                    session,
                    http,
                    usage="prix",
                    agent="habitat-prix",
                    texte=trace.texte_envoye,
                    schema=SCHEMA_PRIX_INTERNET,
                    delai=300,
                )
            except IAIndisponible as exc:
                await _terminer_en_echec_avant_appel(
                    trace, session, _erreur_ia_indisponible(exc)
                )
                return
            except ErreurIA as exc:
                await _terminer(
                    trace,
                    session,
                    modele=None,
                    outils=(),
                    reponse_brute=None,
                    controles=(),
                    resultat=None,
                    erreur=_erreur_erreur_ia(exc),
                )
                return

            controles = controles_prix_internet(reponse.structure, reponse.pages)
            outils = _outils_trace(reponse.pages)
            try:
                resultat = lire_prix_internet(reponse.structure, reponse.pages)
            except ReponseIAInvalide as exc:
                await _terminer(
                    trace,
                    session,
                    modele=reponse.modele,
                    outils=outils,
                    reponse_brute=reponse.brut,
                    controles=controles,
                    resultat=None,
                    erreur=_erreur_reponse_invalide(exc),
                )
                return

            await _terminer(
                trace,
                session,
                modele=reponse.modele,
                outils=outils,
                reponse_brute=reponse.brut,
                controles=controles,
                resultat=_resultat_prix(resultat),
                erreur=None,
            )
    except Exception as exc:
        logger.exception("erreur imprévue pendant un essai « prix » du Laboratoire IA")
        _terminer_en_erreur_imprevue(trace, exc)


async def lancer_essai_prix(
    sessions: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    background_tasks: BackgroundTasks,
    *,
    fournisseur: str | None,
    designation: str,
    code: str | None,
    unite: str | None,
) -> uuid.UUID:
    """Lance un essai de recherche de prix internet (brief LABO) : construit
    le texte exactement comme `ia_prix.rechercher_prix` (`_texte_prix`, même
    fonction, jamais dupliquée), crée la trace `en_cours` et exécute l'appel
    à l'IA en tâche de fond. Renvoie l'identifiant de l'essai."""
    texte = _texte_prix(
        fournisseur=fournisseur, designation=designation, code=code, unite=unite
    )
    trace = TraceEssai(
        id=uuid.uuid4(),
        type="prix",
        statut="en_cours",
        debut=datetime.now(UTC),
        fin=None,
        duree_ms=None,
        agent="habitat-prix",
        texte_envoye=texte,
        schema=dict(SCHEMA_PRIX_INTERNET),
    )
    _enregistrer_trace(trace)
    background_tasks.add_task(_executer_essai_prix, trace, sessions, http)
    return trace.id


# --------------------------------------------------------------------------
# Essai : explication d'une alerte prix
# --------------------------------------------------------------------------


async def _nom_fournisseur_anomalie(
    session: AsyncSession, anomalie: Anomalie
) -> str | None:
    """Nom du fournisseur du document de `anomalie`, ou `None` s'il n'en a
    pas -- même donnée que `ia_prix.expliquer_alertes` (jointe en lot pour la
    tâche planifiée, ici pour une seule anomalie)."""
    if anomalie.document_id is None:
        return None
    ligne = await session.execute(
        select(Fournisseur.nom)
        .join(Document, Document.fournisseur_id == Fournisseur.id)
        .where(Document.id == anomalie.document_id)
    )
    return ligne.scalar_one_or_none()


async def _executer_essai_explication(
    trace: TraceEssai,
    sessions: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    detail: dict[str, Any],
) -> None:
    # Filet de sécurité (fix round 1, revue LABO) -- voir le commentaire
    # d'`_executer_essai_prix` (même principe, `except Exception` seulement).
    try:
        async with sessions() as session:
            try:
                reponse = await interroger(
                    session,
                    http,
                    usage="explication",
                    agent="habitat-explication",
                    texte=trace.texte_envoye,
                    schema=SCHEMA_EXPLICATION,
                )
            except IAIndisponible as exc:
                await _terminer_en_echec_avant_appel(
                    trace, session, _erreur_ia_indisponible(exc)
                )
                return
            except ErreurIA as exc:
                await _terminer(
                    trace,
                    session,
                    modele=None,
                    outils=(),
                    reponse_brute=None,
                    controles=(),
                    resultat=None,
                    erreur=_erreur_erreur_ia(exc),
                )
                return

            controles = controles_explication(reponse.structure, detail)
            outils = _outils_trace(reponse.pages)
            try:
                texte_explication = lire_explication(reponse.structure, detail)
            except ReponseIAInvalide as exc:
                await _terminer(
                    trace,
                    session,
                    modele=reponse.modele,
                    outils=outils,
                    reponse_brute=reponse.brut,
                    controles=controles,
                    resultat=None,
                    erreur=_erreur_reponse_invalide(exc),
                )
                return

            await _terminer(
                trace,
                session,
                modele=reponse.modele,
                outils=outils,
                reponse_brute=reponse.brut,
                controles=controles,
                resultat={"texte": texte_explication},
                erreur=None,
            )
    except Exception as exc:
        logger.exception(
            "erreur imprévue pendant un essai « explication » du Laboratoire IA"
        )
        _terminer_en_erreur_imprevue(trace, exc)


async def lancer_essai_explication(
    sessions: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    background_tasks: BackgroundTasks,
    anomalie_id: uuid.UUID,
) -> uuid.UUID:
    """Lance un essai d'explication d'une alerte prix (brief LABO) :
    `AnomalieIntrouvable` si l'anomalie est inconnue ou n'est pas de
    catégorie « prix » (`ingest.anomalies.categorie_regle`) -- l'API traduit
    en 404. Construit le texte exactement comme `ia_prix.expliquer_alertes`
    (`_texte_explication`, même fonction), crée la trace `en_cours` et
    exécute l'appel à l'IA en tâche de fond. Renvoie l'identifiant de
    l'essai."""
    async with sessions() as session:
        anomalie = await session.get(Anomalie, anomalie_id)
        if anomalie is None or categorie_regle(anomalie.regle) != "prix":
            raise AnomalieIntrouvable(str(anomalie_id))
        nom_fournisseur = await _nom_fournisseur_anomalie(session, anomalie)
        detail = dict(anomalie.detail)
        titre = TITRES_REGLES_PRIX.get(anomalie.regle, _TITRE_REPLI)
        texte = _texte_explication(titre, nom_fournisseur, detail)

    trace = TraceEssai(
        id=uuid.uuid4(),
        type="explication",
        statut="en_cours",
        debut=datetime.now(UTC),
        fin=None,
        duree_ms=None,
        agent="habitat-explication",
        texte_envoye=texte,
        schema=dict(SCHEMA_EXPLICATION),
    )
    _enregistrer_trace(trace)
    background_tasks.add_task(
        _executer_essai_explication, trace, sessions, http, detail
    )
    return trace.id


# --------------------------------------------------------------------------
# Essai : synthèse hebdomadaire des commentaires
# --------------------------------------------------------------------------


async def _executer_essai_synthese(
    trace: TraceEssai,
    sessions: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    references_valides: frozenset[str],
) -> None:
    # Filet de sécurité (fix round 1, revue LABO) -- voir le commentaire
    # d'`_executer_essai_prix` (même principe, `except Exception` seulement).
    try:
        async with sessions() as session:
            try:
                reponse = await interroger(
                    session,
                    http,
                    usage="synthese",
                    agent="habitat-synthese",
                    texte=trace.texte_envoye,
                    schema=SCHEMA_SYNTHESE,
                )
            except IAIndisponible as exc:
                await _terminer_en_echec_avant_appel(
                    trace, session, _erreur_ia_indisponible(exc)
                )
                return
            except ErreurIA as exc:
                await _terminer(
                    trace,
                    session,
                    modele=None,
                    outils=(),
                    reponse_brute=None,
                    controles=(),
                    resultat=None,
                    erreur=_erreur_erreur_ia(exc),
                )
                return

            controles = controles_synthese(reponse.structure, references_valides)
            outils = _outils_trace(reponse.pages)
            try:
                synthese_lue = lire_synthese(reponse.structure, references_valides)
            except ReponseIAInvalide as exc:
                await _terminer(
                    trace,
                    session,
                    modele=reponse.modele,
                    outils=outils,
                    reponse_brute=reponse.brut,
                    controles=controles,
                    resultat=None,
                    erreur=_erreur_reponse_invalide(exc),
                )
                return

            await _terminer(
                trace,
                session,
                modele=reponse.modele,
                outils=outils,
                reponse_brute=reponse.brut,
                controles=controles,
                resultat=_resultat_synthese(synthese_lue),
                erreur=None,
            )
    except Exception as exc:
        logger.exception(
            "erreur imprévue pendant un essai « synthèse » du Laboratoire IA"
        )
        _terminer_en_erreur_imprevue(trace, exc)


_RESUME_SEMAINE_VIDE = (
    "Aucun commentaire cette semaine : pas de synthèse, l'IA n'est pas appelée "
    "(comme en production)."
)


async def _essai_synthese_semaine_vide(
    sessions: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """Essai terminé sur-le-champ pour une semaine sans commentaire, sans
    aucune requête à l'IA (voir `lancer_essai_synthese`)."""
    maintenant = datetime.now(UTC)
    trace = TraceEssai(
        id=uuid.uuid4(),
        type="synthese",
        statut="fini",
        debut=maintenant,
        fin=maintenant,
        duree_ms=0,
        agent="habitat-synthese",
        texte_envoye="",
        schema=dict(SCHEMA_SYNTHESE),
        resultat={"resume": _RESUME_SEMAINE_VIDE, "actions": []},
    )
    async with sessions() as session:
        trace.appels_restants = await _appels_restants_sans_echec(session)
    _enregistrer_trace(trace)
    return trace.id


async def lancer_essai_synthese(
    sessions: async_sessionmaker[AsyncSession],
    http: httpx.AsyncClient,
    background_tasks: BackgroundTasks,
    semaine_debut: date,
) -> uuid.UUID:
    """Lance un essai de synthèse hebdomadaire des commentaires (brief LABO) :
    `semaine_debut` doit être un lundi (`ValueError` sinon, l'API traduit en
    422). Charge les commentaires de la semaine et construit le texte
    exactement comme `ia_synthese.generer_synthese`
    (`_commentaires_de_la_semaine`/`_texte_synthese`, mêmes fonctions,
    jamais dupliquées). Crée la trace `en_cours` et exécute l'appel à l'IA
    en tâche de fond. Renvoie l'identifiant de l'essai.

    Semaine sans commentaire : comme en production (`generer_synthese`,
    synthèse « vide »), l'IA n'est pas appelée -- l'essai se termine tout de
    suite, sans texte envoyé, avec un résumé qui le dit (29/09/2026 : un
    essai sur une semaine vide avait été pris pour une synthèse ratée)."""
    if semaine_debut.weekday() != 0:
        raise ValueError(
            f"semaine_debut doit être un lundi (reçu {semaine_debut.isoformat()})"
        )

    debut_dt, fin_dt = _bornes_semaine_paris(semaine_debut)
    async with sessions() as session:
        (
            commentaires_envoyes,
            commentaire_par_reference,
            nb_total,
        ) = await _commentaires_de_la_semaine(session, debut_dt, fin_dt)
    if nb_total == 0:
        return await _essai_synthese_semaine_vide(sessions)

    texte = _texte_synthese(commentaires_envoyes, nb_total)
    references_valides = frozenset(commentaire_par_reference.keys())

    trace = TraceEssai(
        id=uuid.uuid4(),
        type="synthese",
        statut="en_cours",
        debut=datetime.now(UTC),
        fin=None,
        duree_ms=None,
        agent="habitat-synthese",
        texte_envoye=texte,
        schema=dict(SCHEMA_SYNTHESE),
    )
    _enregistrer_trace(trace)
    background_tasks.add_task(
        _executer_essai_synthese, trace, sessions, http, references_valides
    )
    return trace.id
