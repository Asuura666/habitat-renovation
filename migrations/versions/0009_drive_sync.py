"""Etat de synchronisation Google Drive des documents.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-19 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column("drive_sync_le", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document",
        sa.Column("drive_sync_echec_le", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document",
        sa.Column("drive_sync_tentative_le", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "document",
        sa.Column("drive_sync_erreur", sa.Text(), nullable=True),
    )
    # État nécessaire au signalement « au plus une fois » de L5-T11. Il est
    # persisté avant l'appel externe pour empêcher tout doublon en cas d'échec.
    op.add_column(
        "document",
        sa.Column("drive_sync_signale_le", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document", "drive_sync_signale_le")
    op.drop_column("document", "drive_sync_erreur")
    op.drop_column("document", "drive_sync_tentative_le")
    op.drop_column("document", "drive_sync_echec_le")
    op.drop_column("document", "drive_sync_le")
