"""Schémas Pydantic de réponse pour les routes JSON de lecture (L2-T5).

Décision du contrôleur : les routeurs (`factures.py`, `documents.py`) ne
construisent aucun de ces modèles à la main — ils appellent `model_validate`
sur les dataclasses renvoyées par `ingest/service.py` (`FactureResume`,
`FactureDetail`, `DocumentResume`, ...), grâce à `from_attributes=True`
(Pydantic v2 lit les attributs de n'importe quel objet, pas seulement les
lignes ORM). Aucune requête SQL ni règle métier ici : uniquement la forme de
la réponse JSON.

Montants en `Decimal`, sérialisés en chaîne décimale par Pydantic v2 (jamais
un `float`, comportement par défaut conservé). Dates et horodatages en ISO
8601 (comportement par défaut de Pydantic pour `date`/`datetime`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MotifReponse(BaseModel):
    """Un motif de mise « à vérifier » (L3-T7), tel que renvoyé par `GET
    /api/factures`/`GET /api/factures/{id}` (réutilisé par L3-T8a/L3-T8b) —
    mêmes champs qu'`ingest.lecture.MotifLu`."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    champ: str | None
    detail: dict[str, str]


class FactureResumeReponse(BaseModel):
    """Une ligne de `GET /api/factures` (statut/confiance/motifs, L3-T7)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero: str
    fournisseur: str
    date_doc: date | None
    total_ht: Decimal | None
    nb_blocs: int
    nb_blocs_recus: int
    cree_le: datetime
    statut: str
    confiance_reduite: bool
    confiance_min: Decimal | None
    motifs: list[MotifReponse]


class LigneFactureReponse(BaseModel):
    """Une ligne d'un bloc, dans `GET /api/factures/{id}`."""

    model_config = ConfigDict(from_attributes=True)

    ordre: int
    type_ligne: str
    code_brut: str | None
    article_brut: str | None
    qte_livree: Decimal | None
    qte_totale: Decimal | None
    pu_ht: Decimal | None
    pu_cdt: Decimal | None
    remise_pct: Decimal | None
    montant_ht: Decimal | None
    tva: Decimal | None


class BlocFactureReponse(BaseModel):
    """Un bloc « Concerne le B.L. », dans `GET /api/factures/{id}`
    (`chantier_id`, L3-T7)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero_bl: str | None
    date_bl: date | None
    numero_commande: str | None
    chantier_brut: str | None
    chantier_id: uuid.UUID | None
    commentaire: str | None
    montant_ht: Decimal
    bl_recu: bool
    bl_document_id: uuid.UUID | None
    lignes: list[LigneFactureReponse]


class FactureDetailReponse(BaseModel):
    """`GET /api/factures/{id}` : en-tête puis blocs (statut/confiance/
    motifs, L3-T7)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero: str
    fournisseur: str
    date_doc: date | None
    total_ht: Decimal | None
    cree_le: datetime
    deposant: str | None
    statut: str
    confiance_reduite: bool
    confiance_min: Decimal | None
    motifs: list[MotifReponse]
    blocs: list[BlocFactureReponse]


class DocumentReponse(BaseModel):
    """Une ligne de `GET /api/documents` (`confirmation` ajouté au Ruling
    L2-R8, correction de revue L2-T7 : le front ne doit plus dériver
    vérifié/écart à partir de `statut`, qui suit une tout autre logique —
    voir `ingest/service.py::lister_documents` ; `fournisseur`/
    `chantier_brut` ajoutés en L3-T8a pour un aperçu utile dans la liste)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero_interne: int
    type: str
    numero: str | None
    statut: str
    deposant: str | None
    cree_le: datetime
    confirme_le: datetime | None
    confirme_par: str | None
    photo_compressee: bool | None
    confirmation: Literal["verifiee", "ecart"] | None
    fournisseur: str | None
    chantier_brut: str | None


# --------------------------------------------------------------------------
# Détail, correction, validation, archivage et relance d'un BL (L3-T8a) :
# schémas consommés par `api/documents.py`, construits à partir des
# dataclasses d'`ingest/corrections.py` (`ChampLu`, `LigneLue`,
# `DocumentDetail`).
# --------------------------------------------------------------------------


class ChampReponse(BaseModel):
    """Un champ d'en-tête du détail d'un BL — mêmes attributs
    qu'`ingest.corrections.ChampLu`."""

    model_config = ConfigDict(from_attributes=True)

    valeur: str | None
    valeur_ocr: str | None
    confiance: Decimal | None
    corrige: bool
    corrige_par: str | None
    corrige_le: datetime | None


class ChampsDocumentReponse(BaseModel):
    """`DocumentDetail.champs` (`dict[str, ChampLu]`), à attributs nommés
    (une clé par champ correctible de l'en-tête, hors `type`/`fournisseur_id`
    — décision du contrôleur)."""

    model_config = ConfigDict(from_attributes=True)

    fournisseur: ChampReponse
    numero: ChampReponse
    date_doc: ChampReponse
    chantier_brut: ChampReponse
    numero_commande: ChampReponse
    enleve_par: ChampReponse
    total_ht: ChampReponse
    total_tva: ChampReponse
    total_ttc: ChampReponse


class LigneDocumentReponse(BaseModel):
    """Une ligne d'articles du détail d'un BL — mêmes attributs
    qu'`ingest.corrections.LigneLue`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ordre: int
    code_brut: str | None
    article_brut: str | None
    type_ligne: str
    qte_livree: Decimal | None
    qte_totale: Decimal | None
    unite_brut: str | None
    pu_ht: Decimal | None
    montant_ht: Decimal | None
    confiance: Decimal | None
    article_id: uuid.UUID | None


class DocumentDetailReponse(BaseModel):
    """`GET /api/documents/{id}` : détail complet d'un BL/enlèvement
    (L3-D19)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero_interne: int
    type: str
    statut: str
    deposant: str | None
    cree_le: datetime
    confirme_le: datetime | None
    confirme_par: str | None
    confirmation: Literal["verifiee", "ecart"] | None
    photo_compressee: bool | None
    fournisseur_id: uuid.UUID | None
    agence_fournisseur: str | None
    chantier_id: uuid.UUID | None
    chantier: str | None
    champs: ChampsDocumentReponse
    lignes: list[LigneDocumentReponse]
    motifs: list[MotifReponse]
    seuil_confiance: Decimal
    modifiable: bool


class CorrectionEnteteRequete(BaseModel):
    """`PATCH /api/documents/{id}` : tous les champs sont optionnels
    (`None` par défaut) — seuls ceux présents dans `model_fields_set` sont
    transmis au service (décision du contrôleur), pour distinguer « non
    envoyé » de « envoyé à `null` »."""

    type: Literal["bl", "enlevement"] | None = None
    fournisseur_id: uuid.UUID | None = None
    numero: str | None = None
    date_doc: date | None = None
    chantier_brut: str | None = None
    numero_commande: str | None = None
    enleve_par: str | None = None
    total_ht: Decimal | None = None
    total_tva: Decimal | None = None
    total_ttc: Decimal | None = None


class LigneSaisieRequete(BaseModel):
    """Une ligne de `PUT /api/documents/{id}/lignes` — `id` absent (`None`)
    -> insertion, sinon mise à jour de la ligne existante."""

    id: uuid.UUID | None = None
    code_brut: str | None = None
    article_brut: str | None = None
    qte_livree: Decimal | None = None
    qte_totale: Decimal | None = None
    unite_brut: str | None = None
    pu_ht: Decimal | None = None
    montant_ht: Decimal | None = None


class LignesRequete(BaseModel):
    """Corps de `PUT /api/documents/{id}/lignes` : liste complète des
    lignes du document après correction (mise à jour par `id`, ajout sans
    `id`, suppression des lignes absentes de la liste)."""

    lignes: list[LigneSaisieRequete]


class ArchivageRequete(BaseModel):
    """Corps de `POST /api/documents/{id}/archivage` : commentaire
    obligatoire (1 à 500 caractères, blanc refusé)."""

    commentaire: str = Field(min_length=1, max_length=500)

    @field_validator("commentaire")
    @classmethod
    def _commentaire_non_blanc(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("commentaire requis")
        return valeur


# --------------------------------------------------------------------------
# Écran « À traiter » et référentiels admin (L3-T8b) : schémas construits à
# partir des dataclasses d'`ingest/a_traiter.py` (`DocumentATraiter`,
# `AliasEnAttente`, `ArticleAValider`, `ATraiter`) et d'`ingest/
# referentiels.py` (`ChantierResume`, `FournisseurResume`).
# --------------------------------------------------------------------------


class DocumentATraiterReponse(BaseModel):
    """Une ligne « document à vérifier » de `GET /api/a-traiter` — mêmes
    attributs qu'`ingest.a_traiter.DocumentATraiter`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero_interne: int
    type: str
    numero: str | None
    fournisseur: str | None
    chantier_brut: str | None
    deposant: str | None
    cree_le: datetime
    confirmation: Literal["verifiee", "ecart"] | None
    motifs: list[MotifReponse]


class AliasEnAttenteReponse(BaseModel):
    """Un alias chantier en attente de validation, dans `GET /api/a-traiter`
    — mêmes attributs qu'`ingest.a_traiter.AliasEnAttente`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fournisseur: str
    libelle: str
    exemple_brut: str | None
    nb_documents: int
    cree_le: datetime


class ArticleAValiderReponse(BaseModel):
    """Un article à valider, dans `GET /api/a-traiter` — mêmes attributs
    qu'`ingest.a_traiter.ArticleAValider`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fournisseur: str
    code: str
    libelle: str | None
    unite_cdt: str | None
    unite_fact: str | None
    ratio: Decimal | None
    cree_le: datetime


# --------------------------------------------------------------------------
# Anomalies (L4-T9) : schéma construit à partir d'`ingest.anomalies
# .AnomalieLue` (`GET /api/anomalies`, section `anomalies_hautes` de `GET
# /api/a-traiter`) et corps de `POST /api/anomalies/{id}/traitement`.
# --------------------------------------------------------------------------


class AnomalieReponse(BaseModel):
    """Une anomalie, telle qu'exposée par `GET /api/anomalies` et par
    `POST /api/anomalies/{id}/traitement` — mêmes attributs qu'`ingest
    .anomalies.AnomalieLue`. `detail` est exposé tel quel (`dict[str,
    str]`, décision du contrôleur) : la phrase de justification est
    construite côté front à partir de ce champ (L4-D17), jamais ici."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    regle: str
    gravite: str
    statut: str
    detail: dict[str, str]
    cree_le: datetime
    traitee_le: datetime | None
    traitee_par: str | None
    commentaire: str | None
    document_id: uuid.UUID | None
    numero_interne: int | None
    type: str | None
    numero: str | None
    bloc_id: uuid.UUID | None
    numero_bl: str | None
    chantier_id: uuid.UUID | None
    chantier: str | None
    fournisseur_id: uuid.UUID | None
    fournisseur: str | None
    bl_document_id: uuid.UUID | None


class TraitementAnomalieRequete(BaseModel):
    """Corps de `POST /api/anomalies/{id}/traitement` (L4-D15) : `statut`
    restreint aux deux transitions autorisées (`Literal`, un `statut` hors
    de cet ensemble est un 422, jamais transmis au service), commentaire
    obligatoire (1 à 500 caractères, blanc refusé — même convention que
    `ArchivageRequete` ci-dessus)."""

    statut: Literal["traitee", "ignoree"]
    commentaire: str = Field(min_length=1, max_length=500)

    @field_validator("commentaire")
    @classmethod
    def _commentaire_non_blanc(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("commentaire requis")
        return valeur


class ATraiterReponse(BaseModel):
    """`GET /api/a-traiter` : contenu complet de l'écran admin (L3-D18),
    complété par `anomalies_hautes` (anomalies ouvertes de gravité haute,
    L4-D18)."""

    model_config = ConfigDict(from_attributes=True)

    documents: list[DocumentATraiterReponse]
    alias: list[AliasEnAttenteReponse]
    articles: list[ArticleAValiderReponse]
    anomalies_hautes: list[AnomalieReponse]


class ChantierReponse(BaseModel):
    """Une ligne de `GET /api/chantiers` — mêmes attributs qu'`ingest
    .referentiels.ChantierResume`. `client` : ajout hors CDC demandé le
    23/09/2026 (`docs/dette.md`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom_canonique: str
    agence: str | None
    client: str | None
    actif: bool


class ChantierCreationRequete(BaseModel):
    """Corps de `POST /api/chantiers` : nom obligatoire (1 à 200 caractères,
    blanc refusé), agence et client optionnels."""

    nom_canonique: str = Field(min_length=1, max_length=200)
    agence: str | None = None
    client: str | None = Field(default=None, max_length=200)

    @field_validator("nom_canonique")
    @classmethod
    def _nom_non_blanc(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("nom requis")
        return valeur


class ChantierModificationRequete(BaseModel):
    """Corps de `PUT /api/chantiers/{id}` : remplace nom, agence, client et
    état actif."""

    nom_canonique: str = Field(min_length=1, max_length=200)
    agence: str | None = Field(default=None, max_length=200)
    client: str | None = Field(default=None, max_length=200)
    actif: bool

    @field_validator("nom_canonique")
    @classmethod
    def _nom_non_blanc(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("nom vide")
        return valeur


class AgenceFournisseurReponse(BaseModel):
    """Une agence (point de vente) d'un fournisseur, dans `GET /api
    /fournisseurs` (Ruling L5-R9, tour de correction 1 de L5-T8) — mêmes
    attributs qu'`ingest.referentiels.AgenceResume`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str
    adresse: str | None


class FournisseurReponse(BaseModel):
    """Une ligne de `GET /api/fournisseurs` — mêmes attributs qu'`ingest
    .referentiels.FournisseurResume`. `agences` : liste vide si le
    fournisseur n'en a aucune, jamais `null` (Ruling L5-R9)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str
    agences: list[AgenceFournisseurReponse]


class ValidationAliasRequete(BaseModel):
    """Corps de `POST /api/alias-chantier/{id}/validation`."""

    chantier_id: uuid.UUID


class ValidationAliasReponse(BaseModel):
    """Réponse de `POST /api/alias-chantier/{id}/validation`."""

    nb_mis_a_jour: int


class ValidationArticleRequete(BaseModel):
    """Corps de `POST /api/articles/{id}/validation` : `ratio` strictement
    positif s'il est fourni (`gt=0`, revérifié aussi côté service en défense
    en profondeur)."""

    unite_cdt: str | None = None
    unite_fact: str | None = None
    ratio: Decimal | None = Field(default=None, gt=0)


# --------------------------------------------------------------------------
# Bilan (L5-T3) : schémas construits à partir des dataclasses
# d'`ingest.bilan` (`MontantsBilan`, `LigneBilanChantier`,
# `LigneBilanFournisseur`, `LigneBilanBl`), consommés par `api/bilan.py`.
# Comme pour les sections précédentes, aucun de ces modèles n'importe
# `ingest` : ils sont peuplés par attribut (`from_attributes=True`) sur les
# dataclasses renvoyées par le service, jamais construits à la main.
# --------------------------------------------------------------------------


class MontantsBilanReponse(BaseModel):
    """Les quatre montants d'un périmètre de bilan (L5-D3) plus le nombre
    d'anomalies ouvertes qui s'y rattachent — mêmes attributs
    qu'`ingest.bilan.MontantsBilan`. Les quatre montants ne forment pas une
    partition (L5-D3) : c'est au front de le dire en toutes lettres, jamais
    calculé ni recalculé ici."""

    model_config = ConfigDict(from_attributes=True)

    facture_ht: Decimal
    rapproche: Decimal
    en_ecart: Decimal
    non_justifie: Decimal
    nb_anomalies_ouvertes: int


class LigneBilanChantierReponse(BaseModel):
    """Une ligne de `GET /api/bilan/chantiers` — mêmes attributs
    qu'`ingest.bilan.LigneBilanChantier`. `chantier_id` (et `nom_canonique`/
    `agence`) valent `None` pour les blocs dont le chantier n'a pas pu être
    résolu (décision du contrôleur, L5-T1) : cette ligne n'est pas une
    erreur, elle doit être sérialisée comme les autres."""

    model_config = ConfigDict(from_attributes=True)

    chantier_id: uuid.UUID | None
    nom_canonique: str | None
    agence: str | None
    client: str | None
    montants: MontantsBilanReponse


class LigneBilanFournisseurReponse(BaseModel):
    """Une ligne de `GET /api/bilan/chantiers/{id}/fournisseurs` et de sa
    vue inverse `GET /api/bilan/fournisseurs` — mêmes attributs
    qu'`ingest.bilan.LigneBilanFournisseur`. `fournisseur_id`/`nom` valent
    `None` pour les blocs dont le fournisseur n'a pas pu être résolu, même
    principe que `LigneBilanChantierReponse.chantier_id`."""

    model_config = ConfigDict(from_attributes=True)

    fournisseur_id: uuid.UUID | None
    nom: str | None
    montants: MontantsBilanReponse


class LigneBilanBlReponse(BaseModel):
    """Une ligne de `GET /api/bilan/chantiers/{id}/fournisseurs/{id}/bl` —
    mêmes attributs qu'`ingest.bilan.LigneBilanBl`. `bl_document_id` est
    `None` tant que la photo du BL n'a pas été retrouvée par le
    rapprochement (L4-D4) : c'est ce qui permet au front de proposer, ou
    non, l'ouverture du document source."""

    model_config = ConfigDict(from_attributes=True)

    bloc_id: uuid.UUID
    numero_bl: str | None
    date_bl: date | None
    statut_rapprochement: str | None
    bl_document_id: uuid.UUID | None
    facture_id: uuid.UUID
    montants: MontantsBilanReponse


# --------------------------------------------------------------------------
# Tableau de bord du mois (refonte front T2) : schémas construits à partir
# des dataclasses d'`ingest.tableau_de_bord` (`TotauxMois`,
# `ChantierTableau`, `ProblemePrioritaire`, `TableauDeBord`), consommés par
# `api/tableau_de_bord.py`. Même principe que les sections précédentes :
# aucun de ces modèles n'importe `ingest`, ils sont peuplés par attribut
# (`from_attributes=True`) sur les dataclasses renvoyées par le service.
# --------------------------------------------------------------------------


class TotauxMoisReponse(BaseModel):
    """Les quatre montants du bilan du mois plus `conforme` — mêmes
    attributs qu'`ingest.tableau_de_bord.TotauxMois`."""

    model_config = ConfigDict(from_attributes=True)

    facture_ht: Decimal
    rapproche: Decimal
    en_ecart: Decimal
    non_justifie: Decimal
    conforme: Decimal


class ChantierTableauReponse(BaseModel):
    """Une ligne de `chantiers` dans `GET /api/tableau-de-bord` — mêmes
    attributs qu'`ingest.tableau_de_bord.ChantierTableau`. `chantier_id`
    (et `nom_canonique`/`client`/`agence`) valent `None` pour les blocs
    dont le chantier n'a pas pu être résolu (`etat="a_rattacher"` dans ce
    cas), même principe que `LigneBilanChantierReponse.chantier_id`."""

    model_config = ConfigDict(from_attributes=True)

    chantier_id: uuid.UUID | None
    nom_canonique: str | None
    client: str | None
    agence: str | None
    etat: str
    montants: MontantsBilanReponse
    a_verifier: Decimal


class ProblemePrioritaireReponse(BaseModel):
    """Une ligne de `priorites` dans `GET /api/tableau-de-bord` — mêmes
    attributs qu'`ingest.tableau_de_bord.ProblemePrioritaire`.
    `montant_en_jeu` vaut `None` quand la règle de l'anomalie n'en porte
    pas ou que la valeur lue sur `detail` n'est pas convertible."""

    model_config = ConfigDict(from_attributes=True)

    anomalie: AnomalieReponse
    montant_en_jeu: Decimal | None


class TableauDeBordReponse(BaseModel):
    """`GET /api/tableau-de-bord` — mêmes attributs
    qu'`ingest.tableau_de_bord.TableauDeBord`."""

    model_config = ConfigDict(from_attributes=True)

    mois: date
    totaux: TotauxMoisReponse
    nb_problemes_ouverts: int
    nb_problemes_urgents: int
    nb_bl_factures: int
    nb_bl_recus: int
    chantiers: list[ChantierTableauReponse]
    priorites: list[ProblemePrioritaireReponse]


class DepotAgentReponse(BaseModel):
    """Une ligne de `GET /api/referentiels/depots-par-agent` (L5-T7) —
    mêmes attributs qu'`ingest.referentiels_vue.DepotAgent`. `role`
    (tour de correction 1 bis) : la valeur brute de `Utilisateur.role`,
    pour distinguer un administrateur d'un agent depuis que la liste peut
    contenir les deux (Ruling L5-R7)."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: uuid.UUID
    nom: str | None
    email: str
    role: str
    nombre_depots: int


class ChantierSilencieuxReponse(BaseModel):
    """Une ligne de `GET /api/referentiels/chantiers-silencieux` (L5-T7) —
    mêmes attributs qu'`ingest.referentiels_vue.ChantierSilencieux`."""

    model_config = ConfigDict(from_attributes=True)

    chantier_id: uuid.UUID
    nom_canonique: str
    agence: str | None
    dernier_depot_le: datetime | None


class ParametreReponse(BaseModel):
    """Un seuil administrable avec ses métadonnées de présentation."""

    model_config = ConfigDict(from_attributes=True)

    cle: str
    valeur: str
    libelle: str
    unite: str
    minimum: str
    maximum: str
    entier: bool


class ModificationParametreRequete(BaseModel):
    """Nouvelle valeur textuelle, validée dans le service métier."""

    valeur: str = Field(min_length=1, max_length=50)


class LigneCompareeReponse(BaseModel):
    """Une ligne de `GET /api/documents/{id}/comparaison` — mêmes attributs
    qu'`ingest.comparaison_bl.LigneComparee`. `qte_facturee`/`pu_facture`
    valent `None` si la ligne n'a jamais été appariée à une ligne de facture
    (`rapprochement_ligne`)."""

    model_config = ConfigDict(from_attributes=True)

    ordre: int
    code: str | None
    article: str | None
    qte_livree: Decimal | None
    qte_facturee: Decimal | None
    pu_facture: Decimal | None
    regles_ouvertes: list[str]


class ComparaisonBlReponse(BaseModel):
    """`GET /api/documents/{id}/comparaison` (Task 3, refonte front) —
    mêmes attributs qu'`ingest.comparaison_bl.ComparaisonBl`.
    `facture_id`/`numero_facture`/`montant_facture_ht` valent `None` quand
    aucun bloc de facture ne cite ce BL (`bloc_facture.bl_document_id`,
    même principe que `LigneBilanBlReponse.bl_document_id`)."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    facture_id: uuid.UUID | None
    numero_facture: str | None
    montant_facture_ht: Decimal | None
    lignes: list[LigneCompareeReponse]


class JournalReponse(BaseModel):
    """Une entrée de journal, telle qu'exposée par `GET /api/journal`
    (L5-T9) — mêmes attributs qu'`ingest.journal.JournalLue`. `avant`/
    `apres` sont exposés tels quels (JSON brut : `dict[str, Any] | None`,
    décision du contrôleur) — aucune interprétation métier ici, la mise en
    forme lisible revient au front (`Journal.tsx`), même principe que
    `detail` sur `AnomalieReponse`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    utilisateur_id: uuid.UUID | None
    auteur: str | None
    action: str
    cible_table: str | None
    cible_id: str | None
    avant: dict[str, Any] | None
    apres: dict[str, Any] | None
    horodatage: datetime
