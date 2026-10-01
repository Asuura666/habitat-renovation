"""Colonne `synthese_commentaires.nb_contestations` (tâche 4 de la conception
`docs/superpowers/specs/2026-10-01-prix-recherche-et-contestations-design.md`,
§5) : nombre de prix contestés pris en compte par la synthèse de la semaine.
Les synthèses déjà écrites reçoivent 0.

Écrite à la main d'après la conception (spec §5), puis relue.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-01 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "synthese_commentaires",
        sa.Column("nb_contestations", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("synthese_commentaires", "nb_contestations")
