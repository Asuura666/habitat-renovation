"""Colonne `prix_internet.offres` (tâche 2 de la conception
`docs/superpowers/specs/2026-09-29-prix-internet-plusieurs-sources-design.md`,
§5) : jusqu'à cinq offres vérifiées de sites différents, stockées en JSONB
(prix en texte décimal). Les colonnes existantes décrivent la moins chère en
HT. Les lignes `trouve` déjà présentes sont reprises comme une offre unique ;
les autres reçoivent une liste vide.

Autogénérée depuis `app/modules/ingest/models.py` puis relue.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-29 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prix_internet",
        sa.Column(
            "offres",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE prix_internet
        SET offres = jsonb_build_array(jsonb_build_object(
            'prix', prix::text,
            'devise', devise,
            'taxes', taxes,
            'unite', unite,
            'conditionnement', conditionnement,
            'produit_trouve', produit_trouve,
            'source_url', source_url,
            'confiance', confiance
        ))
        WHERE statut = 'trouve'
        """
    )


def downgrade() -> None:
    op.drop_column("prix_internet", "offres")
