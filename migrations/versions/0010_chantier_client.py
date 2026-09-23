"""Client final du chantier (ajout hors CDC demandé le 23/09/2026).

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-23 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chantier", sa.Column("client", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("chantier", "client")
