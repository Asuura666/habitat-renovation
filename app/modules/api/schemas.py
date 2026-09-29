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
    # Revue finale de la refonte du front (constat ECRAN-14) : déjà porté
    # par `ingest.lecture.BlocFactureLu`, exposé tel quel pour que la
    # facture distingue « jamais reçu » de « livré sans bon » (`None` tant
    # qu'aucun rapprochement n'a tourné).
    statut_rapprochement: str | None
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
    `chantier_brut` ajoutés en L3-T8a pour un aperçu utile dans la liste ;
    `chantier_id` ajouté au tour de correction 1 de Task 8 — le filtre
    `?chantier=` de la liste « Documents » ne peut comparer un identifiant
    de chantier connu (`?chantier=<id>`, résolu par `GET /api/chantiers`)
    qu'à un identifiant, jamais à un préfixe de texte brut non normalisé
    (`chantier_brut`) ; `date_doc` ajouté au tour de correction 2 — pour un
    BL/enlèvement, la date du bon telle qu'imprimée (sa date de livraison),
    pas sa date de dépôt (`cree_le`) : le filtre `?mois=` de la liste
    « Documents » comparait tout document sur `cree_le`, ce qui excluait un
    BL de son mois de livraison réel quand il est déposé un autre mois."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    numero_interne: int
    type: str
    numero: str | None
    statut: str
    deposant: str | None
    cree_le: datetime
    date_doc: date | None
    confirme_le: datetime | None
    confirme_par: str | None
    photo_compressee: bool | None
    confirmation: Literal["verifiee", "ecart"] | None
    fournisseur: str | None
    chantier_brut: str | None
    chantier_id: uuid.UUID | None


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
    legende: str | None
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


class ChoixChantierDocumentRequete(BaseModel):
    """Corps de `PUT /api/documents/{id}/chantier` (Task 6, avenant du
    27/09/2026, spec §2.4/§2.6) : le chantier choisi par un humain, pour
    régler une alerte « Chantier à confirmer » (R18) ou corriger le
    chantier d'un bon depuis sa fiche."""

    chantier_id: uuid.UUID


class ChoixChantierDocumentReponse(BaseModel):
    """Réponse de `PUT /api/documents/{id}/chantier` : le chantier
    réellement retenu (`ingest.rattachement_chantier.chantier_effectif` du
    chantier choisi, Task 7)."""

    chantier_id: uuid.UUID


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
    # Revue finale de la refonte du front (constat SERVEUR-3) : catégorie
    # calculée par `ingest.anomalies.categorie_regle` (table unique), lue
    # telle quelle par les filtres de l'écran « À régler ».
    categorie: Literal["bl", "prix", "quantites", "rattacher", "autre"]


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


class ChantierACompleterReponse(BaseModel):
    """Un chantier créé automatiquement encore à compléter, dans `GET /api
    /a-traiter` — mêmes attributs qu'`ingest.a_traiter.ChantierACompleter`
    (Task 6, avenant du 27/09/2026, spec §2.6)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str
    nb_bons: int
    cree_le: datetime


class ATraiterReponse(BaseModel):
    """`GET /api/a-traiter` : contenu complet de l'écran admin (L3-D18),
    complété par `anomalies_hautes` (anomalies ouvertes de gravité haute,
    L4-D18) et `chantiers_a_completer` (Task 6, avenant du 27/09/2026)."""

    model_config = ConfigDict(from_attributes=True)

    documents: list[DocumentATraiterReponse]
    alias: list[AliasEnAttenteReponse]
    articles: list[ArticleAValiderReponse]
    anomalies_hautes: list[AnomalieReponse]
    chantiers_a_completer: list[ChantierACompleterReponse]


class CompteProblemesReponse(BaseModel):
    """`GET /api/a-regler/compte` : nombre de problèmes « à régler », tous
    mois confondus -- mêmes attributs qu'`ingest.a_traiter.CompteProblemes`
    (revue finale de la refonte du front : un seul compte pour la pastille
    de navigation, la vue d'ensemble et l'écran « À régler »).

    `controle_prix_actif` (décision d'Ilane du 24/09/2026, `docs/dette.md`) :
    le front adapte ses libellés (« Écart prix ou quantité » -> « Écart de
    quantité ») et masque le filtre « Prix » de l'écran « À régler » quand
    ce drapeau est faux -- voir `ingest.a_traiter.CompteProblemes`.

    `controle_livre_non_facture_actif` n'est plus un attribut de cette
    réponse : depuis que `ingest.parametres._cle_masquee` masque
    `delai_ligne_bl_non_facturee_j` côté serveur, plus aucun écran ne lit
    ce second drapeau -- voir `ingest.a_traiter.CompteProblemes`."""

    model_config = ConfigDict(from_attributes=True)

    nb_problemes: int
    nb_urgents: int
    controle_prix_actif: bool


class ChantierReponse(BaseModel):
    """Une ligne de `GET /api/chantiers`, et la fiche `GET /api
    /chantiers/{id}` (Task 7) — mêmes attributs qu'`ingest.referentiels
    .ChantierResume`. `client` : ajout hors CDC demandé le 23/09/2026
    (`docs/dette.md`). `a_completer` (Task 6, avenant du 27/09/2026) :
    chantier créé automatiquement, pas encore complété.

    `fusionne_dans_id`/`fusionne_dans_nom` (Task 7, avenant du 27/09/2026,
    spec §2.7) : chantier absorbé par un autre (« Fusionner avec… ») --
    toujours `None` sur `GET /api/chantiers` (qui exclut déjà les chantiers
    fusionnés, Task 6) ; non `None` seulement quand `GET /api/chantiers
    /{id}` renvoie un chantier fusionné, pour son bandeau « Ce chantier a
    été fusionné dans <cible> »."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom_canonique: str
    agence: str | None
    client: str | None
    actif: bool
    a_completer: bool
    fusionne_dans_id: uuid.UUID | None
    fusionne_dans_nom: str | None


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


class FusionChantierRequete(BaseModel):
    """Corps de `POST /api/chantiers/{id}/fusionner` (Task 7, avenant du
    27/09/2026, spec §2.7) : `{id}` (source) est fusionné dans `cible_id`."""

    cible_id: uuid.UUID


class ResultatFusionReponse(BaseModel):
    """Réponse de `POST /api/chantiers/{id}/fusionner` — mêmes attributs
    qu'`ingest.fusion_chantier.ResultatFusion`."""

    model_config = ConfigDict(from_attributes=True)

    cible_id: uuid.UUID
    nb_documents: int
    nb_blocs: int
    nb_alias: int
    nb_anomalies: int


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
    conforme: Decimal
    a_verifier: Decimal


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


class LigneLivraisonReponse(BaseModel):
    """Une ligne de `GET /api/bilan/livraisons` (Task 13, mise en production
    du 1er octobre) -- mêmes attributs qu'`ingest.bilan.LigneLivraison` :
    ceux de `LigneBilanBlReponse`, plus le chantier et le fournisseur de
    chaque ligne (cette liste n'est jamais imbriquée sous un chantier et un
    fournisseur déjà fixés par l'URL, contrairement à `LigneBilanBlReponse`)."""

    model_config = ConfigDict(from_attributes=True)

    bloc_id: uuid.UUID
    numero_bl: str | None
    date_bl: date | None
    statut_rapprochement: str | None
    bl_document_id: uuid.UUID | None
    facture_id: uuid.UUID
    chantier_id: uuid.UUID | None
    chantier: str | None
    fournisseur_id: uuid.UUID | None
    fournisseur: str | None
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
    # Revue finale (constat SERVEUR-7) : les six valeurs exactes
    # d'`ingest.tableau_de_bord.ETATS`, plus jamais une chaîne libre -- le type
    # généré côté front est donc exact, sans conversion forcée.
    etat: Literal[
        "a_rattacher", "bl_manquant", "prix", "quantites", "a_voir", "conforme"
    ]
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
    nb_bl_manquants: int
    chantiers: list[ChantierTableauReponse]
    priorites: list[ProblemePrioritaireReponse]
    dernier_mois_facture: date | None
    nb_bons_recus: int
    montant_bons_recus: Decimal
    nb_bons_sans_montant: int


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
    """Un seuil administrable avec ses métadonnées de présentation.

    `interrupteur` et `groupe` (phase 3, §3.4 de la conception des prix) :
    ajoutés à la fin, présents pour tous les réglages (défauts `False`/``""``
    pour ceux d'avant cette phase)."""

    model_config = ConfigDict(from_attributes=True)

    cle: str
    valeur: str
    libelle: str
    unite: str
    minimum: str
    maximum: str
    entier: bool
    interrupteur: bool = False
    groupe: str = ""


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
    montant_facture: Decimal | None
    regles_ouvertes: list[str]
    # Revue finale (constats SERVEUR-6/ECRAN-3) : verdict de la ligne,
    # calculé par `ingest.comparaison_bl`, affiché tel quel par la page BL.
    controle: Literal[
        "conforme", "ecart", "non_facture", "non_controle", "pas_encore_facture"
    ]


class ComparaisonBlReponse(BaseModel):
    """`GET /api/documents/{id}/comparaison` (Task 3, refonte front) —
    mêmes attributs qu'`ingest.comparaison_bl.ComparaisonBl`.
    `facture_id`/`numero_facture`/`montant_facture_ht` valent `None` quand
    aucun bloc de facture ne cite ce BL (`bloc_facture.bl_document_id`,
    même principe que `LigneBilanBlReponse.bl_document_id`).

    `nb_problemes` (tour de correction 1, Task 8) : nombre d'anomalies
    ouvertes concernant ce BL, au sens large — pas seulement la somme des
    `regles_ouvertes` des `lignes` (voir le docstring de
    `ingest.comparaison_bl.ComparaisonBl`). C'est ce champ, jamais un calcul
    front, qui doit fonder le nombre de problèmes affiché et déterminer si
    le BL peut être présenté comme « Conforme »."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    facture_id: uuid.UUID | None
    bloc_id: uuid.UUID | None
    numero_facture: str | None
    montant_facture_ht: Decimal | None
    lignes: list[LigneCompareeReponse]
    nb_problemes: int


class JournalReponse(BaseModel):
    """Une entrée de journal, telle qu'exposée par `GET /api/journal`
    (L5-T9) — mêmes attributs qu'`ingest.journal.JournalLue`. `avant`/
    `apres` sont exposés tels quels (JSON brut : `dict[str, Any] | None`,
    décision du contrôleur) — aucune interprétation métier ici, la mise en
    forme lisible revient au front (`Journal.tsx`), même principe que
    `detail` sur `AnomalieReponse`.

    `noms` (Task 12, spec §4.1) : identifiant (texte) -> nom, pour toute
    valeur d'`avant`/`apres` que le serveur a su résoudre (compte, chantier,
    fournisseur — voir `ingest.journal.JournalLue`) ; jamais l'UUID brut
    côté client, ni un calcul côté front, qui n'a pas accès aux
    référentiels."""

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
    noms: dict[str, str]


# --------------------------------------------------------------------------
# Comptes (Task 10, spec §3) : schémas construits à partir d'`app.core.auth
# .CompteLu`, consommés par `api/comptes.py`. `CompteReponse` n'expose jamais
# `hashed_password`/`mdp_hash` -- `CompteLu` ne les porte même pas (défense
# en profondeur, décision du contrôleur).
# --------------------------------------------------------------------------


class CompteReponse(BaseModel):
    """Une ligne de `GET /api/comptes`, et la réponse de chaque route
    d'écriture de l'écran « Comptes » -- mêmes attributs qu'`app.core.auth
    .CompteLu`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str | None
    email: str
    role: str
    agence: str | None
    telegram_user_id: int | None
    actif: bool
    cree_le: datetime


class CompteCreationRequete(BaseModel):
    """Corps de `POST /api/comptes` (spec §3 : « Créer ») : e-mail et nom
    obligatoires (blanc refusé, même convention que `ChantierCreationRequete`
    ci-dessus), rôle restreint aux deux valeurs valides (`Literal`, un rôle
    hors de cet ensemble est un 422 avant même d'atteindre le service),
    agence et identifiant Telegram facultatifs, mot de passe provisoire
    (longueur revérifiée par `app.core.auth._mot_de_passe_valide`, jamais
    ici : une seule source de vérité pour ce seuil)."""

    email: str = Field(min_length=1, max_length=320)
    nom: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "agent"]
    agence: str | None = Field(default=None, max_length=200)
    telegram_user_id: int | None = None
    mot_de_passe: str = Field(min_length=1)

    @field_validator("email", "nom")
    @classmethod
    def _non_blanc(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("champ requis")
        return valeur


class CompteModificationRequete(BaseModel):
    """Corps de `PUT /api/comptes/{id}` (spec §3 : « Modifier ») -- jamais le
    mot de passe (`ChangementMotDePasseRequete` ci-dessous), mêmes règles que
    `CompteCreationRequete`."""

    email: str = Field(min_length=1, max_length=320)
    nom: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "agent"]
    agence: str | None = Field(default=None, max_length=200)
    telegram_user_id: int | None = None

    @field_validator("email", "nom")
    @classmethod
    def _non_blanc(cls, valeur: str) -> str:
        if not valeur.strip():
            raise ValueError("champ requis")
        return valeur


class ChangementMotDePasseRequete(BaseModel):
    """Corps de `PUT /api/comptes/{id}/mot-de-passe` (spec §3 : « Changer le
    mot de passe ») : l'admin saisit lui-même le nouveau mot de passe, jamais
    d'envoi d'e-mail -- longueur revérifiée par `app.core.auth
    ._mot_de_passe_valide`, jamais ici (même raison que `mot_de_passe`
    ci-dessus)."""

    mot_de_passe: str = Field(min_length=1)


# --------------------------------------------------------------------------
# Commentaires sur les lignes d'un bon (tâche C2, phase 3) : schémas
# construits à partir des dataclasses d'`ingest.commentaires`
# (`CommentaireLu`, `LigneCommentee`, `CommentairesBon`).
# --------------------------------------------------------------------------


class CommentaireReponse(BaseModel):
    """Un commentaire, sous sa ligne, dans `sans_ligne`, ou seul (retour de
    `POST /api/commentaires/lignes/{id}`) — mêmes attributs
    qu'`ingest.commentaires.CommentaireLu`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ligne_libelle: str
    auteur: str | None
    texte: str
    cree_le: datetime


class LigneCommenteeReponse(BaseModel):
    """Une ligne du bon avec ses commentaires, dans `GET
    /api/commentaires/documents/{id}` — mêmes attributs
    qu'`ingest.commentaires.LigneCommentee`."""

    model_config = ConfigDict(from_attributes=True)

    ligne_id: uuid.UUID
    code: str | None
    article: str | None
    quantite: Decimal | None
    unite: str | None
    commentaires: list[CommentaireReponse]


class CommentairesBonReponse(BaseModel):
    """Réponse de `GET /api/commentaires/documents/{id}` — mêmes attributs
    qu'`ingest.commentaires.CommentairesBon`."""

    model_config = ConfigDict(from_attributes=True)

    nb_commentaires: int
    lignes: list[LigneCommenteeReponse]
    sans_ligne: list[CommentaireReponse]


class CommentaireRequete(BaseModel):
    """Corps de `POST /api/commentaires/lignes/{id}` : borne de taille dès
    la validation Pydantic (comme `ArchivageRequete`), pour rejeter un corps
    trop volumineux avant même de le charger entièrement en mémoire. Un
    texte blanc une fois nettoyé (espaces seuls) passe encore cette borne
    (`min_length` compte les espaces) : il reste refusé par le service
    (`ingest.commentaires.ajouter_commentaire`, `str.strip()`,
    `CommentaireInvalide`, 422)."""

    texte: str = Field(min_length=1, max_length=1000)


# --------------------------------------------------------------------------
# Synthèse hebdomadaire des commentaires (T4, phase 4 IA) : schémas
# construits à partir des dataclasses d'`ingest.ia_synthese` (`BonLie`,
# `ActionVue`, `SyntheseVue`, `SyntheseAccueil`), consommés par `api/ia.py`.
# --------------------------------------------------------------------------


class BonLieReponse(BaseModel):
    """Un bon cité par une action de synthèse — mêmes attributs
    qu'`ingest.ia_synthese.BonLie`."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    numero: str | None


class ActionSyntheseReponse(BaseModel):
    """Une action de synthèse, dans `SyntheseReponse.actions` ou
    `SyntheseAccueilReponse.encore_a_faire` — mêmes attributs
    qu'`ingest.ia_synthese.ActionVue` ; réponse aussi de `POST /api/ia
    /synthese/actions/{id}/faite` et `.../a-faire`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    texte: str
    semaine_debut: date
    faite_le: datetime | None
    faite_par: str | None
    bons: list[BonLieReponse]


class SyntheseReponse(BaseModel):
    """La dernière synthèse (`SyntheseAccueilReponse.derniere`) — mêmes
    attributs qu'`ingest.ia_synthese.SyntheseVue`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    semaine_debut: date
    semaine_fin: date
    statut: str
    resume: str
    nb_commentaires: int
    actions: list[ActionSyntheseReponse]


class SyntheseAccueilReponse(BaseModel):
    """Réponse de `GET /api/ia/synthese` — mêmes attributs
    qu'`ingest.ia_synthese.SyntheseAccueil`."""

    model_config = ConfigDict(from_attributes=True)

    ia_active: bool
    derniere: SyntheseReponse | None
    encore_a_faire: list[ActionSyntheseReponse]


# --------------------------------------------------------------------------
# Avis de l'IA sur une anomalie de prix (T6, phase 4 IA) : schémas construits
# à partir des dataclasses d'`ingest.ia_prix` (`ExplicationVue`,
# `PrixInternetVue`, `AvisIA`), consommés par `GET /api/ia/anomalies/{id}`
# (`api/ia.py`).
# --------------------------------------------------------------------------


class ExplicationAlerteReponse(BaseModel):
    """Explication d'une alerte prix — mêmes attributs
    qu'`ingest.ia_prix.ExplicationVue`."""

    model_config = ConfigDict(from_attributes=True)

    texte: str
    cree_le: datetime


class PrixInternetReponse(BaseModel):
    """Dernier prix trouvé sur internet pour le produit d'une anomalie —
    mêmes attributs qu'`ingest.ia_prix.PrixInternetVue`."""

    model_config = ConfigDict(from_attributes=True)

    statut: str
    prix: Decimal | None
    devise: str | None
    taxes: str | None
    unite: str | None
    conditionnement: str | None
    produit_trouve: str | None
    source_url: str | None
    confiance: str | None
    raison: str | None
    consulte_le: datetime


class AvisIAReponse(BaseModel):
    """Réponse de `GET /api/ia/anomalies/{id}` — mêmes attributs
    qu'`ingest.ia_prix.AvisIA`."""

    model_config = ConfigDict(from_attributes=True)

    ia_active: bool
    explication: ExplicationAlerteReponse | None
    prix_internet: PrixInternetReponse | None


class PrixInternetLotReponse(BaseModel):
    """Réponse de `GET /api/ia/prix-internet` (T10a) — mêmes attributs
    qu'`ingest.ia_prix.PrixInternetLot`, à ceci près que les identifiants
    d'anomalie sont des clés texte (JSON n'admet pas l'UUID comme clé
    d'objet) : réutilise `PrixInternetReponse`, déjà exposé par `GET
    /api/ia/anomalies/{id}`. Construite à la main par le routeur (jamais
    `model_validate` : la conversion UUID -> texte des clés n'est pas un
    changement de forme que `from_attributes` sait faire)."""

    ia_active: bool
    prix: dict[str, PrixInternetReponse | None]


# --------------------------------------------------------------------------
# Laboratoire IA (tâche LABO) : schémas construits à partir des dataclasses
# d'`ingest.ia_labo` (`TraceEssai`, `OutilTrace`, `LigneAppelIA`) et
# `ingest.opencode` (`DiagnosticIA`), consommés par `api/ia.py`.
# --------------------------------------------------------------------------


class ControleReponse(BaseModel):
    """Un contrôle anti-invention -- mêmes attributs
    qu'`extract.reponses_ia.Controle`."""

    model_config = ConfigDict(from_attributes=True)

    nom: str
    ok: bool
    detail: str


class OutilTraceReponse(BaseModel):
    """Une recherche ou une page ouverte par l'IA pendant un essai -- mêmes
    attributs qu'`ingest.ia_labo.OutilTrace`."""

    model_config = ConfigDict(from_attributes=True)

    outil: str
    adresse: str
    extrait: str


class TraceEssaiReponse(BaseModel):
    """Réponse de `GET /api/ia/labo/essais/{id}` -- mêmes attributs
    qu'`ingest.ia_labo.TraceEssai`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: Literal["prix", "explication", "synthese"]
    statut: Literal["en_cours", "fini", "erreur"]
    debut: datetime
    fin: datetime | None
    duree_ms: int | None
    agent: str
    texte_envoye: str
    # `schema_` (jamais `schema`) : `BaseModel.schema()` est une méthode
    # historique de Pydantic (dépréciée en v2, encore présente) -- un champ
    # nommé `schema` écraserait son type et ferait échouer mypy strict.
    # `alias="schema"` restitue le nom attendu côté JSON (`model_validate`
    # lit `TraceEssai.schema` malgré l'alias, `from_attributes=True`), sans
    # toucher au nom de l'attribut Python de la dataclass source.
    schema_: dict[str, Any] = Field(alias="schema")
    modele: str | None
    outils: list[OutilTraceReponse]
    reponse_brute: Any
    controles: list[ControleReponse]
    resultat: dict[str, Any] | None
    erreur: dict[str, Any] | None
    appels_restants: int | None


class TraceEssaiResumeReponse(BaseModel):
    """Une ligne de `GET /api/ia/labo/essais` (résumé, sans le texte envoyé
    ni la réponse brute -- trop volumineux pour une liste)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: Literal["prix", "explication", "synthese"]
    statut: Literal["en_cours", "fini", "erreur"]
    debut: datetime
    fin: datetime | None
    duree_ms: int | None
    erreur: dict[str, Any] | None


class EtatLaboReponse(BaseModel):
    """Réponse de `GET /api/ia/labo/etat` -- diagnostic (`ingest.opencode
    .DiagnosticIA`) et appels du jour/plafond, construite à la main par le
    routeur (deux sources combinées, jamais une seule dataclass)."""

    ia_active: bool
    url_configuree: bool
    joignable: bool
    joignable_detail: str | None
    agents: list[str]
    abonnement_connecte: bool
    recherche_web: bool
    appels_aujourdhui: int
    appels_max_jour: int


class AppelIALigneReponse(BaseModel):
    """Une ligne de `GET /api/ia/labo/appels` -- mêmes attributs
    qu'`ingest.ia_labo.LigneAppelIA`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    usage: str
    statut: str
    erreur: str | None
    duree_ms: int
    created_at: datetime


class EssaiPrixRequete(BaseModel):
    """Corps de `POST /api/ia/labo/essais/prix`. `designation` nettoyée des
    espaces de tête/fin (fix round 1, revue LABO) : `min_length=1` seul
    laissait passer une chaîne blanche (« un espace » a une longueur de 1),
    envoyée telle quelle à l'IA -- même principe que `ChantierCreationRequete
    ._nom_non_blanc`."""

    fournisseur: str | None = None
    designation: str = Field(min_length=1, max_length=300)
    code: str | None = None
    unite: str | None = None

    @field_validator("designation")
    @classmethod
    def _designation_non_blanche(cls, valeur: str) -> str:
        nettoyee = valeur.strip()
        if not nettoyee:
            raise ValueError("désignation requise")
        return nettoyee


class EssaiExplicationRequete(BaseModel):
    """Corps de `POST /api/ia/labo/essais/explication`."""

    anomalie_id: uuid.UUID


class EssaiSyntheseRequete(BaseModel):
    """Corps de `POST /api/ia/labo/essais/synthese`."""

    semaine_debut: date


class EssaiLanceReponse(BaseModel):
    """Réponse `202` des trois routes `POST /api/ia/labo/essais/...`."""

    id: uuid.UUID


# --------------------------------------------------------------------------
# Grilles de prix fournisseur (phase 3, tâche P4) : schémas construits à
# partir des dataclasses d'`ingest.grilles` (`ProduitGrilleAffiche`,
# `GrilleFournisseur`, `LigneHistorique`, `ApercuImport`, `ImportEffectue`).
# --------------------------------------------------------------------------


class ProduitGrilleReponse(BaseModel):
    """Un produit de la grille -- mêmes attributs qu'`ingest.grilles
    .ProduitGrilleAffiche`. Réponse de `GET /api/grilles/fournisseurs/{id}`
    (dans `GrilleFournisseurReponse.produits`) et de `POST /api/grilles
    /fournisseurs/{id}/prix` (la ligne enregistrée)."""

    model_config = ConfigDict(from_attributes=True)

    cle_produit: str
    reference: str | None
    designation: str
    unite_brut: str | None
    prix_ht: Decimal
    remise_pct: Decimal | None
    prix_net: Decimal
    marque: str | None
    famille: str | None
    date_effet: date


class GrilleFournisseurReponse(BaseModel):
    """`GET /api/grilles/fournisseurs/{id}` -- mêmes attributs
    qu'`ingest.grilles.GrilleFournisseur`."""

    model_config = ConfigDict(from_attributes=True)

    fournisseur_id: uuid.UUID
    nom_fournisseur: str
    nb_produits: int
    dernier_import_le: datetime | None
    page: int
    pages: int
    produits: list[ProduitGrilleReponse]


class LigneHistoriqueReponse(BaseModel):
    """`GET /api/grilles/fournisseurs/{id}/produits/{cle}/historique` --
    mêmes attributs qu'`ingest.grilles.LigneHistorique`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str | None
    designation: str
    unite_brut: str | None
    unite: str | None
    prix_ht: Decimal
    remise_pct: Decimal | None
    prix_net: Decimal
    marque: str | None
    famille: str | None
    date_effet: date
    retire: bool
    source: str
    document_id: uuid.UUID | None
    ligne_libelle: str | None
    auteur: str | None
    created_at: datetime


class SaisiePrixRequete(BaseModel):
    """Corps de `POST /api/grilles/fournisseurs/{id}/prix` (spec §7.4) :
    `date_effet` absente -> aujourd'hui, résolu par le routeur (le service
    ne connaît que des dates déjà choisies, comme `ingest.grilles.SaisiePrix`
    l'exige)."""

    reference: str | None = Field(default=None, max_length=200)
    designation: str = Field(min_length=1, max_length=500)
    unite: str | None = Field(default=None, max_length=50)
    prix_ht: Decimal
    remise_pct: Decimal | None = None
    date_effet: date | None = None
    marque: str | None = Field(default=None, max_length=200)
    famille: str | None = Field(default=None, max_length=200)


class RetraitProduitRequete(BaseModel):
    """Corps de `POST /api/grilles/fournisseurs/{id}/retrait`."""

    # 4 (préfixe "ref:" ou "nom:") + 500 (désignation maximale, cf.
    # `SaisiePrixRequete.designation`) : `cle_produit` peut produire jusqu'à
    # 504 caractères, la colonne `grille_prix.cle_produit` étant un `Text`
    # non borné (constat relecture qualité, tour 3).
    cle_produit: str = Field(min_length=1, max_length=504)
    date_effet: date


class LigneCompareeGrilleReponse(BaseModel):
    """Une ligne « nouveau » ou « modifié » d'un aperçu d'import de grille --
    mêmes attributs qu'`ingest.grilles.LigneComparee`. Nommée distinctement
    de `LigneCompareeReponse` (comparaison BL/facture, ci-dessus) : même
    mot, deux objets métier sans rapport."""

    model_config = ConfigDict(from_attributes=True)

    reference: str | None
    designation: str
    nouveau_prix_net: Decimal
    ancien_prix_net: Decimal | None
    nouvelle_unite: str | None
    ancienne_unite: str | None


class ProduitAbsentReponse(BaseModel):
    """Un produit en vigueur absent du fichier importé -- mêmes attributs
    qu'`ingest.grilles.ProduitAbsent`."""

    model_config = ConfigDict(from_attributes=True)

    reference: str | None
    designation: str
    prix_net: Decimal


class ErreurImportReponse(BaseModel):
    """Une ligne du fichier non retenue -- mêmes attributs
    qu'`ingest.grilles.ErreurImport`."""

    model_config = ConfigDict(from_attributes=True)

    feuille: str
    numero_ligne: int
    message: str


class ApercuImportReponse(BaseModel):
    """`POST /api/grilles/fournisseurs/{id}/import/apercu` -- mêmes
    attributs qu'`ingest.grilles.ApercuImport`."""

    model_config = ConfigDict(from_attributes=True)

    nb_nouveaux: int
    nb_modifies: int
    nb_inchanges: int
    nb_erreurs: int
    nouveaux: list[LigneCompareeGrilleReponse]
    modifies: list[LigneCompareeGrilleReponse]
    absents_du_fichier: list[ProduitAbsentReponse]
    erreurs: list[ErreurImportReponse]
    feuilles_ignorees: list[str]


class ImportEffectueReponse(BaseModel):
    """`POST /api/grilles/fournisseurs/{id}/import` -- mêmes attributs
    qu'`ingest.grilles.ImportEffectue`."""

    model_config = ConfigDict(from_attributes=True)

    import_id: uuid.UUID
    nb_nouveaux: int
    nb_modifies: int
    nb_inchanges: int
    nb_erreurs: int


# --------------------------------------------------------------------------
# Page « Prix à vérifier » (phase 3, tâche P8) : schémas construits à partir
# des dataclasses d'`ingest.prix_bl` (`AlerteProduit`, `ValidationPrixEffectuee`,
# `ResultatRecontrolePrix`).
# --------------------------------------------------------------------------


class AlerteProduitReponse(BaseModel):
    """Une rangée de `GET /api/prix/alertes` -- mêmes attributs
    qu'`ingest.prix_bl.AlerteProduit`."""

    model_config = ConfigDict(from_attributes=True)

    fournisseur_id: uuid.UUID
    fournisseur: str
    produit: str
    code: str | None
    prix_bon: Decimal
    unite_bon: str | None
    date_bon: date
    nb_bons: int
    nb_prix_differents: int
    prix_grille: Decimal | None
    unite_grille: str | None
    date_grille: date | None
    grille_posterieure_au_bon: bool
    dernier_prix: Decimal | None
    unite_dernier_prix: str | None
    date_dernier_prix: date | None
    numero_facture: str | None
    ecart_pct: Decimal | None
    methode: str | None
    ressemblance: int | None
    unite_grille_non_comparable: str | None
    regles: list[str]
    anomalie_ids: list[uuid.UUID]
    document_id: uuid.UUID
    ligne_id: uuid.UUID
    numero_interne: int | None


class ValiderPrixRequete(BaseModel):
    """Corps de `POST /api/prix/valider` (spec §8.2)."""

    anomalie_ids: list[uuid.UUID] = Field(min_length=1)
    ligne_id: uuid.UUID


class ContesterPrixRequete(BaseModel):
    """Corps de `POST /api/prix/contester` (spec §8.2) : commentaire
    obligatoire (validé de nouveau par `ingest.prix_bl.contester_prix`, même
    principe que `TraitementAnomalieRequete`)."""

    anomalie_ids: list[uuid.UUID] = Field(min_length=1)
    commentaire: str = Field(min_length=1, max_length=500)


class IgnorerPrixRequete(BaseModel):
    """Corps de `POST /api/prix/ignorer` (spec §8.2) : commentaire
    facultatif."""

    anomalie_ids: list[uuid.UUID] = Field(min_length=1)
    commentaire: str | None = Field(default=None, max_length=500)


class ValidationPrixReponse(BaseModel):
    """`POST /api/prix/valider` -- mêmes attributs
    qu'`ingest.prix_bl.ValidationPrixEffectuee`."""

    model_config = ConfigDict(from_attributes=True)

    prix_net: Decimal
    date_effet: date
    nb_alertes_reglees: int


class FermetureAlertesReponse(BaseModel):
    """`POST /api/prix/contester` et `/ignorer` -- nombre d'alertes
    fermées."""

    nb_alertes_reglees: int


class RecontrolePrixReponse(BaseModel):
    """`POST /api/prix/recontrole` -- mêmes attributs
    qu'`ingest.prix_bl.ResultatRecontrolePrix`."""

    model_config = ConfigDict(from_attributes=True)

    nb_bons: int
    nb_echecs: int
    nb_alertes_ouvertes: int
