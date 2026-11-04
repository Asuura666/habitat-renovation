"""Table `prix_observe` : prix déjà vus chez un fournisseur, importés d'une
feuille d'historique d'un fichier de contrôle (lot 2 du 31/10/2026, B4).

Ces prix ne vont **jamais** dans la grille (`grille_prix`) : ils servent
seulement à afficher l'historique d'un produit. `cle_produit` suit la même
règle que la grille (`normalize.prix.cle_produit`).

Écrite à la main d'après la demande, puis relue.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-31 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prix_observe",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("fournisseur_id", sa.UUID(), nullable=False),
        sa.Column("cle_produit", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("designation", sa.Text(), nullable=False),
        sa.Column("unite_brut", sa.Text(), nullable=True),
        sa.Column("date_observation", sa.Date(), nullable=False),
        sa.Column("prix_ht", sa.Numeric(), nullable=False),
        sa.Column("quantite", sa.Numeric(), nullable=True),
        sa.Column("piece", sa.Text(), nullable=True),
        sa.Column("source_libelle", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("prix_ht > 0", name=op.f("ck_prix_observe_prix_ht_positif")),
        sa.ForeignKeyConstraint(
            ["fournisseur_id"],
            ["fournisseur.id"],
            name=op.f("fk_prix_observe_fournisseur_id_fournisseur"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prix_observe")),
    )
    op.create_index(
        "ix_prix_observe_fournisseur_produit_date",
        "prix_observe",
        ["fournisseur_id", "cle_produit", "date_observation"],
    )


def downgrade() -> None:
    op.drop_index("ix_prix_observe_fournisseur_produit_date", table_name="prix_observe")
    op.drop_table("prix_observe")
