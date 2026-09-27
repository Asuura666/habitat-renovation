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
- Aucun `ondelete` en cascade : aucune suppression physique de document --
  sauf `commentaire` (migration 0012, §3 de la conception des commentaires
  du 27/09/2026) : `document_id` en `ON DELETE CASCADE` et `ligne_id` en
  `ON DELETE SET NULL`, pour qu'un commentaire ne disparaisse jamais avec sa
  ligne (recréée à chaque lecture ou relance de la lecture) et reste
  rattaché au bon tant que celui-ci existe.
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
    Identity,
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
    """Comptes applicatifs (admin / agent).

    Mapping fastapi-users (L2-D1, `app/core/auth.py`) : les colonnes gardent
    le nom du CDC (`mdp_hash`, `actif`), mais deux attributs Python portent
    le nom que la bibliothèque attend en accès direct (`SQLAlchemyUserDatabase`,
    `BaseUserManager.authenticate`, `Authenticator._authenticate`) — obtenu en
    passant le nom de colonne en premier argument positionnel de
    `mapped_column`, distinct du nom d'attribut. `is_verified` et
    `is_superuser` sont dérivés (jamais stockés) : toujours vérifié ; superuser
    ⇔ `role == 'admin'`.
    """

    __tablename__ = "utilisateur"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'agent')", name="role_valide"),
    )

    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nom: Mapped[str | None] = mapped_column(Text, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column("mdp_hash", Text, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    agence: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        "actif", Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
    updated_by: Mapped[uuid.UUID | None] = _updated_by()

    @property
    def is_verified(self) -> bool:
        """Toujours vrai : le CDC ne prévoit pas de vérification d'e-mail
        (L2-D1) — attribut dérivé, jamais une colonne."""
        return True

    @property
    def is_superuser(self) -> bool:
        """Dérivé du rôle, jamais stocké (L2-D1) : seule `role` fait foi."""
        return self.role == "admin"


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
    client: Mapped[str | None] = mapped_column(Text, nullable=True)
    actif: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Migration 0011 (avenant du 27/09/2026, rattachement automatique des
    # chantiers) : chantier créé automatiquement (aucune agence ni client
    # renseignés) quand un nom lu ou une légende Telegram ne ressemble à
    # aucun chantier connu -- signalé dans « À régler » (section « Nouveaux
    # chantiers à compléter ») tant qu'un humain n'a pas complété sa fiche
    # (`PUT /api/chantiers/{id}`) ou ne l'a pas fusionné avec un doublon.
    a_completer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Chantier fusionné dans un autre (bouton « Fusionner avec… ») : jamais
    # supprimé physiquement -- `actif` et `a_completer` passés à faux, ses
    # bons, blocs, alias et anomalies déplacés vers la cible. `NULL` tant
    # que ce chantier n'a pas été fusionné.
    fusionne_dans_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chantier.id"), nullable=True
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
    # Numéro interne lisible (L2-D5/L2-R4, lot 2) : affiché à l'agent
    # (`Reçu — document n° <numero_interne>`) et dans les lignes de
    # supervision (L2-D8) — l'`id` UUID n'est jamais montré à un humain.
    # `Identity()` (BY DEFAULT) plutôt qu'une séquence manuelle : généré
    # côté base à l'insertion, récupéré par SQLAlchemy au `flush()` (même
    # mécanisme que `id`, qui utilise déjà `gen_random_uuid()` côté base).
    numero_interne: Mapped[int] = mapped_column(
        BigInteger, Identity(), nullable=False, unique=True
    )
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
    drive_sync_le: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    drive_sync_echec_le: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    drive_sync_tentative_le: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    drive_sync_erreur: Mapped[str | None] = mapped_column(Text, nullable=True)
    drive_sync_signale_le: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    deposant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateur.id"), nullable=True
    )
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Photo Telegram compressée (`photo[]`) plutôt qu'envoyée « en fichier »
    # (L2-D5/constat 4, lot 2) : renseignée depuis `FichierEntrant.compresse`
    # par `ingest/service.py::traiter_fichier`. `NULL` pour un document non
    # issu de Telegram (ex. une facture uploadée, L2-T4).
    photo_compressee: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confirme_le: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirme_par: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateur.id"), nullable=True
    )
    statut: Mapped[str] = mapped_column(Text, nullable=False)
    confiance_min: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    # Total HT lu sur la facture (L2-D5/constat 3, lot 2) : lecture directe
    # pour `GET /api/factures` (L2-T5) et R10 (lot 4), sans recalculer la
    # somme des lignes à chaque affichage. `NULL` pour un BL/enlèvement.
    total_ht: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    ocr_brut: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Migration 0005 (L3-D5, constat 5 du lot 3 : le modèle n'avait pas de
    # chantier sur `document`, seulement sur `bloc_facture`) :
    # - `chantier_brut`/`chantier_id` : chantier lu sur un BL/enlèvement,
    #   résolu comme pour `BlocFacture.chantier_brut`/`chantier_id`
    #   ci-dessus (même clé d'alias, L3-D6) ;
    # - `numero_commande`/`enleve_par` : champs propres à un bon
    #   d'enlèvement Point.P (CDC §4.4) ;
    # - `total_tva`/`total_ttc` : totaux lus sur une facture, en plus de
    #   `total_ht` (dette L2-R5) ;
    # - `extraction` : instantané immuable de l'extraction OCR (valeurs
    #   brutes, valeurs converties, confiances, motifs d'origine) — « valeur
    #   OCR d'origine conservée » (CDC §4.3), y compris après une correction
    #   (L3-D13) ou une nouvelle extraction (L3-D15) ;
    #   `motifs` : motifs de mise « à vérifier » courants (L3-D3), recalculés
    #   à chaque correction ou validation.
    chantier_brut: Mapped[str | None] = mapped_column(Text, nullable=True)
    chantier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chantier.id"), nullable=True
    )
    # Légende Telegram tapée par l'employé au moment d'envoyer la photo
    # (`message.caption`, migration 0011, avenant du 27/09/2026) : seconde
    # source du nom de chantier, à côté du nom lu sur le bon (`chantier_
    # brut`), pour le rattachement automatique (`normalize.chantier`).
    # Affichée sur la page du bon (« Chantier indiqué par l'employé »).
    # `NULL` si la photo n'a pas de légende ou si le document ne vient pas
    # de Telegram.
    legende: Mapped[str | None] = mapped_column(Text, nullable=True)
    numero_commande: Mapped[str | None] = mapped_column(Text, nullable=True)
    enleve_par: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_tva: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    total_ttc: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    motifs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
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
    # Position du bloc dans la facture (L2-D5bis, constat de la tâche T5) :
    # `deposer_facture` insère tous les blocs d'une même facture dans une
    # seule transaction, où `created_at` (`func.now()`) vaut le même
    # horodatage de début de transaction pour toutes les lignes insérées —
    # il ne peut donc pas servir à reconstituer l'ordre d'apparition des
    # blocs sur la facture (contrairement à `Ligne.ordre`, qui, lui, se
    # limite à l'ordre des lignes *à l'intérieur* d'un même bloc). Renseigné
    # par `deposer_facture` (`enumerate(facture.blocs)`), lu par
    # `ingest/service.py::facture_detail` (L2-T5, `GET /api/factures/{id}`)
    # pour renvoyer les blocs « dans l'ordre ».
    ordre: Mapped[int] = mapped_column(Integer, nullable=False)
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
    # Migration 0005 (L3-D5) : confiance OCR de la ligne (minimum des
    # confiances de ses valeurs, L3-D2) ; `NULL` pour une ligne de facture
    # (scores au niveau page seulement, L3-D16) ou une ligne corrigée/ajoutée
    # par l'admin (L3-D13, « une ligne modifiée ou ajoutée a confiance =
    # NULL »).
    confiance: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
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
    """Sortie des règles de contrôle.

    Migration 0006 (L4-D11/L4-D13, ruling R1 de la tâche L4-T8) :
    - `article_id` : porté par une anomalie de niveau ligne/article (R03-R09,
      R13, R17), sert à la règle des 90 jours (`ingest.anomalies
      .synchroniser_anomalies`, L4-D13) — une anomalie sans article (niveau
      bloc ou document, ex. R01/R02/R10-R12) n'est jamais bloquée par cette
      règle.

    Migration 0007 (Ruling R13 de la tâche L4-T11, `ingest/suivi.py` :
    premier code à persister des anomalies de suivi R06/R14/R15/R16) :
    - `chantier_id` (FK `chantier.id`) : porte la portée d'une anomalie R16
      (chantier silencieux), qui n'est rattachée ni à un document, ni à un
      bloc, ni à une ligne — sans lui, deux chantiers silencieux distincts
      partageraient l'identité `(regle="R16", document_id=None, bloc_id=None,
      ligne_id=None)` et se confondraient en une seule anomalie.
    - `alias_id` (FK `chantier_alias.id`) : même besoin pour R14 (chantier
      non résolu) — signalé par le docstring de `rules/rules/R14.py` (« sans
      lui, deux alias en attente distincts partageraient la même identité »)
      et son test `test_R14_deux_alias_distincts_portent_des_alias_id
      _distincts`, alors que la fiche de cette tâche ne demandait
      explicitement que `chantier_id` (écart signalé au contrôleur) : sans
      `alias_id` ici aussi, deux alias en attente distincts se confondraient
      de la même façon que deux chantiers silencieux.
    - Index unique remplacé par `(regle, document_id, bloc_id, ligne_id,
      chantier_id, alias_id)`, toujours `NULLS NOT DISTINCT`.

    Index unique `NULLS NOT DISTINCT` (comme `chantier_alias`) : identité
    d'une anomalie (L4-D11). Garantit qu'aucune ligne dupliquée ne peut
    jamais exister en base pour la même clé, quel que soit le chemin
    applicatif ; l'upsert (`ingest.anomalies.synchroniser_anomalies`)
    s'appuie dessus pour sa recherche par clé, mais ne fait pas d'`ON
    CONFLICT` — deux rapprochements strictement concurrents sur la même
    facture (cas non prévu par l'orchestration actuelle, toujours
    séquentielle) feraient échouer le second avec une violation de
    contrainte plutôt que d'être absorbés silencieusement.
    """

    __tablename__ = "anomalie"
    __table_args__ = (
        CheckConstraint(
            "gravite IN ('haute', 'moyenne', 'basse')", name="gravite_valide"
        ),
        CheckConstraint(
            "statut IN ('ouverte', 'traitee', 'ignoree')", name="statut_valide"
        ),
        CheckConstraint("detail <> '{}'::jsonb", name="detail_non_vide"),
        UniqueConstraint(
            "regle",
            "document_id",
            "bloc_id",
            "ligne_id",
            "chantier_id",
            "alias_id",
            postgresql_nulls_not_distinct=True,
        ),
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
    article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("article.id"), nullable=True
    )
    chantier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chantier.id"), nullable=True
    )
    alias_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chantier_alias.id"), nullable=True
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


class Commentaire(Base):
    """Commentaire libre sur une ligne d'un bon (append-only, comme
    `journal`) : migration 0012, §3 de
    `docs/superpowers/specs/2026-09-27-commentaires-lignes-design.md`.
    Décisions d'Ilane du 27/09/2026 : tout compte connecté qui voit la page
    du bon peut commenter ; un commentaire n'est ni modifiable ni
    supprimable (pour se corriger, on en ajoute un autre) ; chaque ajout est
    journalisé (`commentaire_ajoute`).

    - `document_id` (`ON DELETE CASCADE`) : garde le commentaire rattaché au
      bon même si sa ligne disparaît -- les lignes d'un bon sont supprimées
      puis recréées à chaque lecture ou relance de la lecture
      (`extraction_bl.enregistrer_extraction_bl`), et une correction
      manuelle peut en supprimer (`corrections.corriger_lignes`).
    - `ligne_id` (`ON DELETE SET NULL`) : ligne commentée ; devient vide si
      la ligne est supprimée. Le commentaire reste alors affichable grâce à
      `ligne_libelle`, figé au moment de l'ajout (« code — désignation », ou
      la partie présente seule, ou « Ligne <n> » si les deux manquent).
    - Pas de colonne `updated_*` : aucune modification n'est prévue, et
      aucune route ne modifie ni ne supprime un commentaire.
    """

    __tablename__ = "commentaire"
    __table_args__ = (
        CheckConstraint("char_length(texte) BETWEEN 1 AND 1000", name="texte_longueur"),
    )

    id: Mapped[uuid.UUID] = _id()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ligne_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ligne.id", ondelete="SET NULL"),
        nullable=True,
    )
    ligne_libelle: Mapped[str] = mapped_column(Text, nullable=False)
    auteur_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateur.id"), nullable=True
    )
    texte: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class TelegramUpdate(Base):
    """Dédoublonnage des webhooks Telegram (append-only)."""

    __tablename__ = "telegram_update"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    recu_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = _created_at()


class JetonSession(Base):
    """Jeton de session (`app/core/auth.py`, `DatabaseStrategy` de
    fastapi-users, L2-D2) : une ligne par connexion active, supprimée à la
    déconnexion.

    `created_at` sert de double rôle : horodatage de création **et** de
    dernière activité (expiration glissante). `utilisateur_courant` le
    rafraîchit au plus toutes les 5 minutes ; `DatabaseStrategy.read_token`
    traite tout jeton dont `created_at` a plus de 12 h comme expiré (filtre
    SQL sur `created_at >= now() - 12h`, jamais chargé en Python).
    L'attribut Python est `user_id` (nom attendu par
    `SQLAlchemyAccessTokenDatabase`/`AccessTokenProtocol`), porté par la
    colonne `utilisateur_id` (convention du CDC, comme les autres clés
    étrangères vers `utilisateur`).

    Table hors des 14 du CDC (ajout d'infrastructure auth) : pas
    d'`updated_at`/`updated_by` (append/delete-only, comme `telegram_update`).
    """

    __tablename__ = "jeton_session"

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        "utilisateur_id",
        UUID(as_uuid=True),
        ForeignKey("utilisateur.id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = _created_at()
