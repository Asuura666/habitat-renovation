"""Dataclasses d'entrée/sortie du moteur de règles (module PUR, L4-D1).

Ce module ne réutilise ni `extract.verification.Motif`, ni les dataclasses
de `extract.bl`/`extract.facture` : `rules` n'importe aucun autre module de
`app.modules` (frontière vérifiée par `tests/test_frontieres.py`), il
redéfinit donc ses propres vues, construites par `ingest` (L4-T7/T8) à
partir de la base. Seuls `uuid`, `decimal`, `datetime`, `enum` et
`dataclasses`/`collections.abc` sont utilisés — décision du contrôleur.

Toutes les dataclasses sont gelées (`frozen=True`) : une règle ne modifie
jamais ses entrées, elle ne fait que lire et produire des `Anomalie`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class Gravite(StrEnum):
    """Gravité d'une anomalie (CDC §5, colonne `anomalie.gravite`)."""

    HAUTE = "haute"
    MOYENNE = "moyenne"
    BASSE = "basse"


@dataclass(frozen=True)
class Anomalie:
    """Sortie d'une règle `Rxx` (L4-D2). `detail` porte toutes les valeurs
    ayant déclenché la règle, en chaînes (montants/quantités : `str
    (Decimal)`, jamais de formatage français ; dates : ISO — décision du
    contrôleur) et n'est **jamais vide** : une anomalie sans justification
    chiffrée ne doit jamais exister."""

    regle: str  # "R01" … "R17"
    gravite: Gravite
    detail: dict[str, str]
    document_id: uuid.UUID | None = None
    bloc_id: uuid.UUID | None = None
    ligne_id: uuid.UUID | None = None
    article_id: uuid.UUID | None = None


@dataclass(frozen=True)
class LigneControlee:
    """Une ligne de BL ou de facture, vue du moteur de règles. `qte_fact`
    est la quantité convertie en unité de facturation par `ingest`
    (`normalize.unites.convertir_en_unite_fact`, L4-D7) ; `None` si la
    conversion est impossible, auquel cas `conversion_impossible` vaut
    `True` et aucune règle de quantité (R03/R04) ne doit se déclencher
    dessus (L4-D7 : « 0 anomalie R03/R04 due à une unité »)."""

    id: uuid.UUID
    ordre: int
    code: str | None  # code article normalisé, None si absent
    designation: str | None
    article_id: uuid.UUID | None
    qte_conditionnements: Decimal | None  # ligne.qte_livree
    qte_facturee: Decimal | None  # ligne.qte_totale
    qte_fact: Decimal | None  # convertie en unité de facturation, None si impossible
    unite: str | None
    pu_ht: Decimal | None
    remise_pct: Decimal | None
    montant_ht: Decimal | None
    type_ligne: str  # "article" | "eco" | "commentaire"
    conversion_impossible: bool


@dataclass(frozen=True)
class ArticleControle:
    """Référentiel article (`article`), vue du moteur de règles."""

    id: uuid.UUID
    code: str
    libelle: str | None
    unite_cdt: str | None
    unite_fact: str | None
    ratio: Decimal | None
    valide: bool


@dataclass(frozen=True)
class LigneRapprochee:
    """Une ligne de facture appariée (ou non) à une ligne de BL (L4-D6).
    `bl` est `None` quand la ligne facturée n'a pas de correspondance sur
    le BL (matière de R05) ; `methode` est `None` dans ce cas."""

    facture: LigneControlee
    bl: LigneControlee | None
    methode: str | None  # "code" | "libelle" | None


@dataclass(frozen=True)
class DocumentControle:
    """Un document (facture ou BL), vue du moteur de règles pour R10/R11.
    `ecart_somme` reprend le motif `somme_incoherente` déjà produit par
    l'extraction (lot 3), sans que `rules` ne recalcule la somme (L4-D8) :
    `None` si la somme est cohérente ou non calculable."""

    id: uuid.UUID
    numero_interne: int
    numero: str | None
    date_doc: date | None
    statut: str
    somme_lignes: Decimal | None
    total_ht: Decimal | None
    ecart_somme: Decimal | None  # None si la somme est cohérente ou non calculable
    depose_le: datetime | None
    deposant: str | None
    confirme_le: datetime | None


@dataclass(frozen=True)
class BlocControle:
    """Un bloc BL d'une facture, avec son éventuel BL rapproché (L4-D4,
    L4-D5) et ses lignes appariées (L4-D6)."""

    id: uuid.UUID
    numero_bl: str | None
    date_bl: date | None
    chantier_brut: str | None
    chantier: str | None  # nom canonique si résolu
    commentaire: str | None
    montant_ht: Decimal
    bl: DocumentControle | None
    lignes: tuple[LigneRapprochee, ...]
    lignes_bl_non_facturees: tuple[LigneControlee, ...]
    autre_facture_numero: str | None  # R12 : même n° de BL dans une autre facture
    autre_facture_id: uuid.UUID | None


@dataclass(frozen=True)
class HistoriqueArticle:
    """Historique des prix/remises d'un article chez le fournisseur de la
    facture contrôlée, sur les 6 mois précédents (L4-D9)."""

    article_id: uuid.UUID
    mediane_pu: Decimal | None
    occurrences: int
    remise_habituelle: Decimal | None
    occurrences_remise: int


@dataclass(frozen=True)
class FactureControlee:
    """Vue complète d'une facture soumise à `evaluer_facture`."""

    document: DocumentControle
    fournisseur: str
    blocs: tuple[BlocControle, ...]
    articles: Mapping[uuid.UUID, ArticleControle]
    historiques: Mapping[uuid.UUID, HistoriqueArticle]
    lignes_negatives_sans_origine: tuple[tuple[LigneControlee, str | None], ...]


@dataclass(frozen=True)
class AliasEnAttenteControle:
    """Alias de chantier chez un fournisseur, créé lors d'une extraction et
    toujours pas validé par l'admin (matière de R14, L4-T5)."""

    id: uuid.UUID
    libelle: str
    fournisseur: str
    cree_le: datetime


@dataclass(frozen=True)
class ChantierSuiviControle:
    """Vue d'un chantier pour le suivi temporel (R16, L4-T5). `dernier_depot`
    est `None` si aucun BL n'a jamais été déposé pour ce chantier — R16 ne
    peut alors rien comparer et ne se déclenche jamais."""

    id: uuid.UUID
    nom: str
    dernier_depot: datetime | None
    nb_bl_factures_depuis: int


@dataclass(frozen=True)
class ContexteSuivi:
    """Entrée de `evaluer_suivi` (R06, R14, R15, R16 — contrôles différés au
    temps écoulé, déclenchés par la commande `controles-differes`, L4-D14),
    séparée de `FactureControlee` : ces règles ne portent pas sur une
    facture en cours de contrôle mais sur le temps écoulé depuis un dépôt,
    une création d'alias ou un dernier dépôt de chantier — décision du
    contrôleur, `ContexteSuivi` reste utilisable sans aucune facture."""

    aujourdhui: datetime
    lignes_bl_non_facturees: tuple[tuple[BlocControle, LigneControlee], ...]
    alias_en_attente: tuple[AliasEnAttenteControle, ...]
    bl_sans_confirmation: tuple[DocumentControle, ...]
    chantiers: tuple[ChantierSuiviControle, ...]


@dataclass(frozen=True)
class Parametres:
    """Seuils modifiables par l'admin (CDC §5, L4-D10), avec leur valeur
    par défaut : `ingest` les lit depuis la table `parametre` et construit
    cette dataclasse, le moteur ne connaît jamais la base."""

    tolerance_total_ht: Decimal = Decimal("0.05")
    seuil_prix_pct: Decimal = Decimal("5")
    seuil_prix_fort_pct: Decimal = Decimal("15")
    occurrences_prix_min: int = 3
    delai_ligne_bl_non_facturee_j: int = 45
    delai_alias_non_resolu_h: int = 48
    delai_confirmation_bl_h: int = 24
    delai_chantier_silencieux_j: int = 7
    duree_ignorance_j: int = 90
