"""Vue des référentiels (`ingest/referentiels_vue.py`, L5-T7) : qui a
déposé quoi ces N derniers jours (`depots_par_agent`), quels chantiers n'ont
plus rien envoyé depuis trop longtemps (`chantiers_sans_depot`), et les
agences déjà renseignées sur un chantier (`agences_connues`) — trois
lectures pures (aucune écriture) consommées par les routes admin ajoutées à
`api/referentiels.py`.

Décisions du contrôleur (L5-T7) :
- Un agent sans aucun dépôt apparaît quand même, avec `nombre_depots=0`
  (`depots_par_agent`) : un `LEFT JOIN` sur les documents déposés, jamais un
  filtre qui ne garderait que les agents ayant déjà déposé — ce serait
  cacher précisément ceux qu'on veut voir. Aucun filtre non plus sur
  `Utilisateur.is_active` : un agent désactivé qui a cessé de déposer est
  justement ce que ce tableau doit pouvoir montrer.
- Ruling L5-R7 (tour de correction 1) : le rôle sert à composer la **liste
  de référence** de `depots_par_agent` (tout compte `role == 'agent'`, pour
  que les agents à zéro apparaissent), jamais à **filtrer les dépôts**
  eux-mêmes. Le rattachement Telegram d'un dépôt ne regarde pas le rôle du
  compte : un bon de livraison déposé par un administrateur est possible,
  et ce projet refuse les disparitions silencieuses (une valeur illisible
  produit un motif nommé, un bloc sans chantier reste visible sous une
  ligne « non résolu » — un dépôt invisible serait du même ordre). La liste
  finale est donc l'union de tous les agents et de tout compte ayant
  effectivement déposé sur la fenêtre, quel que soit son rôle ; un
  administrateur qui n'a rien déposé n'y figure pas pour autant.
- Le décompte de `depots_par_agent` porte sur tous les documents déposés
  par l'agent, quel que soit leur statut (y compris `archive`) : c'est une
  mesure d'activité de l'agent, pas de la qualité de ce qu'il a déposé.
- La fenêtre de `depots_par_agent` (30 jours par défaut) se compte en jours
  calendaires **Europe/Paris**, jamais en multiples de 24 h UTC : un
  changement d'heure d'été/hiver traversant la fenêtre décalerait sinon le
  jour civil retenu comme borne. `_debut_periode_paris` construit un instant
  tz-aware à partir d'une date civile parisienne (même principe que
  `api.anomalies._debut_jour_paris`/`_fin_jour_paris`, généralisé à une
  fenêtre de N jours plutôt qu'à un seul), jamais par soustraction d'un
  `timedelta` sur un `datetime.now(UTC)`.
- `chantiers_sans_depot` lit elle-même le seuil de silence
  (`delai_chantier_silencieux_j`, table `parametre`, 7 jours de repli) via
  `referentiels.lire_parametre_decimal` : le seuil n'est **jamais** reçu en
  argument, pour rester visible et modifiable depuis l'écran de réglages
  d'une autre tâche (L5-D9) sans changer la signature de cette fonction.
  Écart signalé par rapport à la fiche (qui documentait la signature
  `chantiers_sans_depot(session, *, jours)`) : la décision du contrôleur
  pour cette tâche tranche explicitement en faveur d'une lecture interne du
  paramètre, jamais reçue de l'appelant (le routeur n'a donc aucun
  paramètre de requête `jours` sur cette route).
- Un chantier fermé (`ferme_le` renseigné et déjà passé ou aujourd'hui, ou
  `actif` faux) n'est jamais « silencieux » : on ne signale pas un chantier
  qu'on a soi-même arrêté.
- Le dernier dépôt d'un chantier se lit sur `document.chantier_id`
  (BL/enlèvements, constat 2 du plan) — jamais `bloc_facture.chantier_id`,
  qui n'est jamais alimenté par un dépôt du chantier lui-même (une facture
  vient du fournisseur, pas du terrain). Un chantier sans aucun document
  déposé (`dernier_depot_le=None`) est inclus : l'absence totale de dépôt
  est, a fortiori, un silence.
- `agences_connues` renvoie les valeurs distinctes non nulles et non vides
  de `chantier.agence`, triées (L5-D6) : aucune table d'agences, la liste
  peut être vide (cas normal, pas une erreur).
- Tour de correction 1, point 2 : `chantiers_sans_depot` trie par
  `chantier_id` en dernière clé (`Chantier.nom_canonique` n'est pas
  garanti unique en base) — même correctif, pour la même raison, que
  `ingest.bilan.bilan_par_chantier` (tour de correction 1).
- Tour de correction 1 bis : `DepotAgent.role` (valeur brute de
  `Utilisateur.role`) expose désormais le rôle réel de chaque ligne. Depuis
  le Ruling L5-R7, la liste peut contenir un administrateur ; sans ce
  champ, rien ne le distinguerait d'un agent de terrain dans un écran qui
  affiche cette vue — la confusion serait celle-là même que le Ruling
  L5-R7 cherchait à éviter, déplacée du calcul vers l'affichage.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.models import Chantier, Document, Utilisateur
from app.modules.ingest.referentiels import lire_parametre_decimal

DEPOTS_PAR_AGENT_JOURS_DEFAUT = 30

CLE_DELAI_CHANTIER_SILENCIEUX_J = "delai_chantier_silencieux_j"
DELAI_CHANTIER_SILENCIEUX_DEFAUT = Decimal("7")


def _debut_periode_paris(jours: int) -> datetime:
    """Instant (tz-aware, Europe/Paris) marquant le début du jour civil
    parisien situé `jours` jours calendaires avant aujourd'hui (voir
    docstring de module : jamais une soustraction de `timedelta` sur un
    instant, qui décalerait la borne d'une heure si la fenêtre traverse un
    changement d'heure d'été/hiver)."""
    aujourd_hui = datetime.now(FUSEAU_PARIS).date()
    jour_debut = aujourd_hui - timedelta(days=jours)
    return datetime.combine(jour_debut, time.min, tzinfo=FUSEAU_PARIS)


@dataclass(frozen=True)
class DepotAgent:
    """Une ligne de `GET /api/referentiels/depots-par-agent` : un compte de
    la liste de référence — tout agent (`Utilisateur.role == 'agent'`),
    actif ou non, plus tout compte ayant effectivement déposé sur la
    fenêtre quel que soit son rôle (Ruling L5-R7) — et son nombre de dépôts
    (`0` pour un agent qui n'a rien déposé).

    `role` (valeur brute de `Utilisateur.role`, tour de correction 1 bis) :
    depuis que la liste peut contenir un administrateur, `agent_id` seul ne
    suffit plus à distinguer un agent de terrain d'un administrateur ayant
    déposé — un écran qui l'ignorerait ferait croire à un agent de plus.
    `agent_id` garde son nom d'origine (pas de renommage : une cascade sans
    bénéfice, `role` lève l'ambiguïté à lui seul)."""

    agent_id: uuid.UUID
    nom: str | None
    email: str
    role: str
    nombre_depots: int


async def depots_par_agent(
    session: AsyncSession, *, jours: int = DEPOTS_PAR_AGENT_JOURS_DEFAUT
) -> list[DepotAgent]:
    """Nombre de documents déposés sur les `jours` derniers jours
    calendaires (Europe/Paris), pour tout agent (y compris à `0`) et tout
    compte ayant effectivement déposé sur la fenêtre quel que soit son
    rôle (Ruling L5-R7 : le rôle compose la liste de référence, il ne
    filtre jamais les dépôts). Le compte porte sur tous les documents
    déposés, quel que soit leur statut (voir docstring de module)."""
    borne = _debut_periode_paris(jours)

    depots = (
        select(
            Document.deposant_id.label("deposant_id"),
            func.count().label("nombre_depots"),
        )
        .where(
            Document.deposant_id.is_not(None),
            Document.created_at >= borne,
        )
        .group_by(Document.deposant_id)
        .subquery()
    )

    resultat = await session.execute(
        select(
            Utilisateur.id,
            Utilisateur.nom,
            Utilisateur.email,
            Utilisateur.role,
            func.coalesce(depots.c.nombre_depots, 0),
        )
        .select_from(Utilisateur)
        .outerjoin(depots, depots.c.deposant_id == Utilisateur.id)
        .where(
            or_(
                Utilisateur.role == "agent",
                depots.c.deposant_id.is_not(None),
            )
        )
        .order_by(Utilisateur.nom.asc().nulls_last(), Utilisateur.email.asc())
    )
    return [
        DepotAgent(
            agent_id=agent_id, nom=nom, email=email, role=role, nombre_depots=nombre
        )
        for agent_id, nom, email, role, nombre in resultat.all()
    ]


@dataclass(frozen=True)
class ChantierSilencieux:
    """Une ligne de `GET /api/referentiels/chantiers-silencieux` :
    `dernier_depot_le=None` si le chantier n'a jamais reçu le moindre
    document."""

    chantier_id: uuid.UUID
    nom_canonique: str
    agence: str | None
    dernier_depot_le: datetime | None


async def chantiers_sans_depot(session: AsyncSession) -> list[ChantierSilencieux]:
    """Chantiers actifs et non fermés dont le dernier document déposé
    (`document.chantier_id`, tous statuts confondus) date de plus de
    `delai_chantier_silencieux_j` jours (table `parametre`, 7 jours de repli
    si absente ou non convertible — `referentiels.lire_parametre_decimal`).

    Le seuil est lu ici, jamais reçu en argument (voir docstring de
    module) : c'est cette fonction, pas le routeur, qui sait comment
    déterminer le silence d'un chantier."""
    seuil_jours = await lire_parametre_decimal(
        session,
        CLE_DELAI_CHANTIER_SILENCIEUX_J,
        DELAI_CHANTIER_SILENCIEUX_DEFAUT,
    )
    borne = _debut_periode_paris(int(seuil_jours))
    aujourd_hui = datetime.now(FUSEAU_PARIS).date()

    derniers_depots = (
        select(
            Document.chantier_id.label("chantier_id"),
            func.max(Document.created_at).label("dernier_depot_le"),
        )
        .where(Document.chantier_id.is_not(None))
        .group_by(Document.chantier_id)
        .subquery()
    )

    resultat = await session.execute(
        select(
            Chantier.id,
            Chantier.nom_canonique,
            Chantier.agence,
            derniers_depots.c.dernier_depot_le,
        )
        .select_from(Chantier)
        .outerjoin(derniers_depots, derniers_depots.c.chantier_id == Chantier.id)
        .where(
            Chantier.actif.is_(True),
            or_(Chantier.ferme_le.is_(None), Chantier.ferme_le > aujourd_hui),
            or_(
                derniers_depots.c.dernier_depot_le.is_(None),
                derniers_depots.c.dernier_depot_le < borne,
            ),
        )
        .order_by(Chantier.nom_canonique.asc(), Chantier.id.asc())
    )
    return [
        ChantierSilencieux(
            chantier_id=chantier_id,
            nom_canonique=nom_canonique,
            agence=agence,
            dernier_depot_le=dernier_depot_le,
        )
        for chantier_id, nom_canonique, agence, dernier_depot_le in resultat.all()
    ]


async def agences_connues(session: AsyncSession) -> list[str]:
    """Valeurs distinctes non nulles et non vides de `chantier.agence`,
    triées (L5-D6) : aucune table d'agences, la liste peut être vide."""
    resultat = await session.execute(
        select(Chantier.agence)
        .where(Chantier.agence.is_not(None), Chantier.agence != "")
        .distinct()
        .order_by(Chantier.agence.asc())
    )
    return [agence for (agence,) in resultat.all()]
