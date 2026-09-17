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
from typing import Literal

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
