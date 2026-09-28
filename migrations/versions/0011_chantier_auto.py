"""Rattachement automatique des chantiers (avenant du 27/09/2026) : légende
Telegram, chantier créé « à compléter », fusion de chantiers doublons (§6
de docs/superpowers/specs/2026-09-27-mise-en-production-1er-octobre-design.md).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-27 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document", sa.Column("legende", sa.Text(), nullable=True))
    op.add_column(
        "chantier",
        sa.Column(
            "a_completer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("chantier", sa.Column("fusionne_dans_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_chantier_fusionne_dans_id_chantier"),
        "chantier",
        "chantier",
        ["fusionne_dans_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_chantier_fusionne_dans_id_chantier"), "chantier", type_="foreignkey"
    )
    op.drop_column("chantier", "fusionne_dans_id")
    op.drop_column("chantier", "a_completer")
    op.drop_column("document", "legende")
