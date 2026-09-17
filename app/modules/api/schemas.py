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

from pydantic import BaseModel, ConfigDict


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
    voir `ingest/service.py::lister_documents`)."""

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
