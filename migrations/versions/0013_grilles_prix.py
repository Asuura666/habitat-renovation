"""Grilles de prix fournisseur : historique inaltérable, contrôle des prix
des bons (phase 3, §3 de
docs/superpowers/specs/2026-09-27-prix-design.md, session B).

- `grille_import` : une ligne par import confirmé d'un fichier Excel de
  grille (jamais pour un aperçu).
- `grille_prix` : historique des prix d'un produit d'un fournisseur --
  chaque changement **ajoute** une ligne, rien n'est jamais modifié ni
  supprimé. Deux déclencheurs (`grille_prix_inalterable` sur `UPDATE` et
  `DELETE`, `grille_prix_sans_truncate` sur `TRUNCATE`) appellent la même
  fonction `grille_prix_refuser_modification()`, qui lève toujours
  `RAISE EXCEPTION 'historique des prix inaltérable'` : le seul chemin de
  suppression est une migration descendante (celle-ci), jamais le code
  applicatif.
- `anomalie.ligne_id` (§3.3) : la contrainte de clé étrangère est recréée en
  `ON DELETE CASCADE` (elle n'avait aucun `ondelete` depuis la migration
  0006) -- les lignes d'un bon sont supprimées puis recréées à chaque
  relance de la lecture, et une correction peut en retirer ; une alerte de
  prix posée sur une ligne bloquerait sinon cette suppression. `SET NULL`
  est écarté : deux anomalies de la même règle sur le même bon
  deviendraient identiques pour l'index unique `NULLS NOT DISTINCT` et la
  suppression échouerait.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-27 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "grille_import",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("fournisseur_id", sa.UUID(), nullable=False),
        sa.Column("nom_fichier", sa.Text(), nullable=False),
        sa.Column("empreinte", sa.Text(), nullable=False),
        sa.Column("chemin", sa.Text(), nullable=False),
        sa.Column("date_effet", sa.Date(), nullable=False),
        sa.Column("nb_nouveaux", sa.Integer(), nullable=False),
        sa.Column("nb_modifies", sa.Integer(), nullable=False),
        sa.Column("nb_inchanges", sa.Integer(), nullable=False),
        sa.Column("nb_erreurs", sa.Integer(), nullable=False),
        sa.Column("auteur_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["auteur_id"],
            ["utilisateur.id"],
            name=op.f("fk_grille_import_auteur_id_utilisateur"),
        ),
        sa.ForeignKeyConstraint(
            ["fournisseur_id"],
            ["fournisseur.id"],
            name=op.f("fk_grille_import_fournisseur_id_fournisseur"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grille_import")),
    )

    op.create_table(
        "grille_prix",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("fournisseur_id", sa.UUID(), nullable=False),
        sa.Column("cle_produit", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("designation", sa.Text(), nullable=False),
        sa.Column("unite_brut", sa.Text(), nullable=True),
        sa.Column("unite", sa.Text(), nullable=True),
        sa.Column("prix_ht", sa.Numeric(), nullable=False),
        sa.Column("remise_pct", sa.Numeric(), nullable=True),
        sa.Column("prix_net", sa.Numeric(), nullable=False),
        sa.Column("marque", sa.Text(), nullable=True),
        sa.Column("famille", sa.Text(), nullable=True),
        sa.Column("date_effet", sa.Date(), nullable=False),
        sa.Column(
            "retire", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("import_id", sa.UUID(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("ligne_libelle", sa.Text(), nullable=True),
        sa.Column("auteur_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("prix_ht > 0", name=op.f("ck_grille_prix_prix_ht_positif")),
        sa.CheckConstraint(
            "remise_pct IS NULL OR (remise_pct >= 0 AND remise_pct < 100)",
            name=op.f("ck_grille_prix_remise_pct_bornee"),
        ),
        sa.CheckConstraint(
            "prix_net > 0", name=op.f("ck_grille_prix_prix_net_positif")
        ),
        sa.CheckConstraint(
            "source IN ('import', 'saisie', 'validation')",
            name=op.f("ck_grille_prix_source_valide"),
        ),
        sa.CheckConstraint(
            "source <> 'import' OR import_id IS NOT NULL",
            name=op.f("ck_grille_prix_import_id_requis_si_import"),
        ),
        sa.CheckConstraint(
            "source <> 'validation' OR document_id IS NOT NULL",
            name=op.f("ck_grille_prix_document_id_requis_si_validation"),
        ),
        sa.ForeignKeyConstraint(
            ["auteur_id"],
            ["utilisateur.id"],
            name=op.f("fk_grille_prix_auteur_id_utilisateur"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name=op.f("fk_grille_prix_document_id_document"),
        ),
        sa.ForeignKeyConstraint(
            ["fournisseur_id"],
            ["fournisseur.id"],
            name=op.f("fk_grille_prix_fournisseur_id_fournisseur"),
        ),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["grille_import.id"],
            name=op.f("fk_grille_prix_import_id_grille_import"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grille_prix")),
    )
    op.create_index(
        "ix_grille_prix_prix_en_vigueur",
        "grille_prix",
        ["fournisseur_id", "cle_produit", "date_effet", "created_at"],
    )

    # Historique inaltérable : aucun UPDATE, DELETE ni TRUNCATE, quel que
    # soit le chemin applicatif -- seule une migration descendante peut
    # supprimer des lignes de `grille_prix` (downgrade() ci-dessous).
    op.execute(
        """
        CREATE FUNCTION grille_prix_refuser_modification()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'historique des prix inaltérable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER grille_prix_inalterable
        BEFORE UPDATE OR DELETE ON grille_prix
        FOR EACH ROW
        EXECUTE FUNCTION grille_prix_refuser_modification()
        """
    )
    op.execute(
        """
        CREATE TRIGGER grille_prix_sans_truncate
        BEFORE TRUNCATE ON grille_prix
        FOR EACH STATEMENT
        EXECUTE FUNCTION grille_prix_refuser_modification()
        """
    )

    # `anomalie.ligne_id` : FK sans `ondelete` depuis la migration 0006,
    # recréée en `ON DELETE CASCADE` (§3.3 de la conception).
    op.drop_constraint(
        op.f("fk_anomalie_ligne_id_ligne"), "anomalie", type_="foreignkey"
    )
    op.create_foreign_key(
        op.f("fk_anomalie_ligne_id_ligne"),
        "anomalie",
        "ligne",
        ["ligne_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_anomalie_ligne_id_ligne"), "anomalie", type_="foreignkey"
    )
    op.create_foreign_key(
        op.f("fk_anomalie_ligne_id_ligne"),
        "anomalie",
        "ligne",
        ["ligne_id"],
        ["id"],
    )

    op.execute("DROP TRIGGER grille_prix_sans_truncate ON grille_prix")
    op.execute("DROP TRIGGER grille_prix_inalterable ON grille_prix")
    op.execute("DROP FUNCTION grille_prix_refuser_modification()")

    op.drop_index("ix_grille_prix_prix_en_vigueur", table_name="grille_prix")
    op.drop_table("grille_prix")
    op.drop_table("grille_import")
