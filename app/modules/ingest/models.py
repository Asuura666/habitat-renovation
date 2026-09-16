"""Modèles ORM des 14 tables de la section 6 du cahier des charges.

Source de vérité unique du schéma (décision D8 du brief T3) : la migration
`migrations/versions/0001_schema_initial.py` est autogénérée à partir de ces
modèles, puis relue à la main. `alembic check` (voir
`app/core/tests/test_migrations.py`) garantit qu'aucune dérive ne s'installe
entre ce fichier et la base.

Conventions appliquées partout (décisions D2 à D7, D9, et décisions du
contrôleur pour T3) :
- `id` en UUID, généré côté base (`gen_random_uuid()`), sauf `parametre`
  (clé `cle`) et `telegram_update` (clé `update_id`, propre à Telegram).
- `created_at` sur les 14 tables, y compris `journal` et `telegram_update`
  (décision D5, « `created_at` partout ») : ces deux tables portent en plus
  leur propre horodatage métier (`horodatage`, `recu_le`), qui n'a pas le
  même sens (heure de l'action / de la réception, potentiellement distincte
  de l'insertion en base) et n'est donc pas redondant.
- `updated_at` + `updated_by` sur toutes les tables modifiables, sauf
  `journal` et `telegram_update` (append-only) et `parametre` (qui garde
  ses colonnes natives du CDC `modifie_par` / `modifie_le`).
- Listes fermées du CDC en `text` + `CHECK` nommé, jamais d'`ENUM` Postgres
  (décision D4) : plus simple à faire évoluer par migration.
- Montants et quantités en `numeric` sans précision imposée (décision D3),
  mappés en `Decimal` côté Python.
- Aucun `ondelete` en cascade : aucune suppression physique de document.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _id() -> Mapped[uuid.UUID]:
    """Clé primaire UUID générée côté base."""
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def _updated_by() -> Mapped[uuid.UUID | None]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateur.id"), nullable=True
    )


class Utilisateur(Base):
    """Comptes applicatifs (admin / agent)."""

    __tablename__ = "utilisateur"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'agent')", name="role_valide"),
    )

    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nom: Mapped[str | None] = mapped_column(Text, nullable=True)
    mdp_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    agence: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()


class Fournisseur(Base):
    """Référentiel fournisseurs."""

    __tablename__ = "fournisseur"

    id: Mapped[uuid.UUID] = _id()
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    siret: Mapped[str | None] = mapped_column(Text, nullable=True)
    tva: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()


class AgenceFournisseur(Base):
    """Point de vente d'un fournisseur (ex. Unikalo Nord, St Orens)."""

    __tablename__ = "agence_fournisseur"

    id: Mapped[uuid.UUID] = _id()
    fournisseur_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fournisseur.id"), nullable=False
    )
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()


class Chantier(Base):
    """Référentiel des chantiers du client."""

    __tablename__ = "chantier"

    id: Mapped[uuid.UUID] = _id()
    nom_canonique: Mapped[str] = mapped_column(Text, nullable=False)
    agence: Mapped[str | None] = mapped_column(Text, nullable=True)
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    ouvert_le: Mapped[date | None] = mapped_column(Date, nullable=True)
    ferme_le: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()


class ChantierAlias(Base):
    """Résolution des libellés chantier bruts des fournisseurs."""

    __tablename__ = "chantier_alias"
    __table_args__ = (
        UniqueConstraint(
            "fournisseur_id",
            "libelle_brut",
            "code_brut",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    fournisseur_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fournisseur.id"), nullable=False
    )
    libelle_brut: Mapped[str] = mapped_column(Text, nullable=False)
    code_brut: Mapped[str | None] = mapped_column(Text, nullable=True)
    chantier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chantier.id"), nullable=True
    )
    valide_par: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateur.id"), nullable=True
    )
    valide_le: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()


class Article(Base):
    """Catalogue article par fournisseur, avec conversion d'unité."""

    __tablename__ = "article"
    __table_args__ = (UniqueConstraint("fournisseur_id", "code"),)

    id: Mapped[uuid.UUID] = _id()
    fournisseur_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fournisseur.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    libelle: Mapped[str | None] = mapped_column(Text, nullable=True)
    unite_cdt: Mapped[str | None] = mapped_column(Text, nullable=True)
    unite_fact: Mapped[str | None] = mapped_column(Text, nullable=True)
    ratio: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    valide: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()


class Document(Base):
    """Un document par fichier reçu (BL, enlèvement, facture, avoir)."""

    __tablename__ = "document"
    __table_args__ = (
        UniqueConstraint("fournisseur_id", "numero"),
        CheckConstraint(
            "type IN ('bl', 'enlevement', 'facture', 'avoir')", name="type_valide"
        ),
        CheckConstraint("source IN ('telegram', 'upload')", name="source_valide"),
        CheckConstraint(
            "statut IN ('recu', 'a_verifier', 'archive')", name="statut_valide"
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    type: Mapped[str] = mapped_column(Text, nullable=False)
    fournisseur_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fournisseur.id"), nullable=True
    )
    agence_fournisseur_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agence_fournisseur.id"), nullable=True
    )
    numero: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_doc: Mapped[date | None] = mapped_column(Date, nullable=True)
    fichier_path: Mapped[str] = mapped_column(Text, nullable=False)
    drive_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    deposant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateur.id"), nullable=True
    )
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirme_le: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirme_par: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateur.id"), nullable=True
    )
    statut: Mapped[str] = mapped_column(Text, nullable=False)
    confiance_min: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    ocr_brut: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()


class BlocFacture(Base):
    """Un bloc « Concerne le B.L. n°… » d'une facture."""

    __tablename__ = "bloc_facture"
    __table_args__ = (
        CheckConstraint(
            "statut_rapprochement IN ('recu', 'non_recu', 'pas_de_bon')",
            name="statut_rapprochement_valide",
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    facture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id"), nullable=False
    )
    numero_bl: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_bl: Mapped[date | None] = mapped_column(Date, nullable=True)
    numero_commande: Mapped[str | None] = mapped_column(Text, nullable=True)
    chantier_brut: Mapped[str | None] = mapped_column(Text, nullable=True)
    chantier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chantier.id"), nullable=True
    )
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    bl_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id"), nullable=True
    )
    statut_rapprochement: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()


class Ligne(Base):
    """Ligne de tout document (facture, bloc, BL)."""

    __tablename__ = "ligne"
    __table_args__ = (
        CheckConstraint(
            "type_ligne IN ('article', 'eco', 'commentaire')", name="type_ligne_valide"
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id"), nullable=False
    )
    bloc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bloc_facture.id"), nullable=True
    )
    article_brut: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_brut: Mapped[str | None] = mapped_column(Text, nullable=True)
    article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("article.id"), nullable=True
    )
    qte_livree: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    qte_totale: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    unite_brut: Mapped[str | None] = mapped_column(Text, nullable=True)
    qte_fact: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    pu_ht: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    pu_cdt: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    remise_pct: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    montant_ht: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    tva: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    type_ligne: Mapped[str] = mapped_column(Text, nullable=False)
    ordre: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()


class RapprochementLigne(Base):
    """Correspondance entre une ligne de facture et une ligne de BL."""

    __tablename__ = "rapprochement_ligne"
    __table_args__ = (
        CheckConstraint(
            "methode IN ('code', 'libelle', 'manuel')", name="methode_valide"
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    ligne_facture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ligne.id"), nullable=False
    )
    ligne_bl_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ligne.id"), nullable=False
    )
    methode: Mapped[str] = mapped_column(Text, nullable=False)
    ecart_qte: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()


class Anomalie(Base):
    """Sortie des règles de contrôle."""

    __tablename__ = "anomalie"
    __table_args__ = (
        CheckConstraint(
            "gravite IN ('haute', 'moyenne', 'basse')", name="gravite_valide"
        ),
        CheckConstraint(
            "statut IN ('ouverte', 'traitee', 'ignoree')", name="statut_valide"
        ),
        CheckConstraint("detail <> '{}'::jsonb", name="detail_non_vide"),
    )

    id: Mapped[uuid.UUID] = _id()
    regle: Mapped[str] = mapped_column(Text, nullable=False)
    gravite: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document.id"), nullable=True
    )
    bloc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bloc_facture.id"), nullable=True
    )
    ligne_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ligne.id"), nullable=True
    )
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    statut: Mapped[str] = mapped_column(Text, nullable=False)
    traitee_par: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateur.id"), nullable=True
    )
    traitee_le: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()


class Parametre(Base):
    """Seuils des règles, modifiables par l'admin."""

    __tablename__ = "parametre"

    cle: Mapped[str] = mapped_column(Text, primary_key=True)
    valeur: Mapped[str] = mapped_column(Text, nullable=False)
    modifie_par: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateur.id"), nullable=True
    )
    modifie_le: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = _created_at()


class Journal(Base):
    """Traçabilité de toute modification (append-only)."""

    __tablename__ = "journal"

    id: Mapped[uuid.UUID] = _id()
    utilisateur_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateur.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    cible_table: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Texte et non UUID : la cible peut être `parametre` (clé texte) ou
    # `telegram_update` (clé bigint) autant qu'une table à clé UUID.
    cible_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    avant: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    apres: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    horodatage: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = _created_at()


class TelegramUpdate(Base):
    """Dédoublonnage des webhooks Telegram (append-only)."""

    __tablename__ = "telegram_update"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    recu_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = _created_at()
