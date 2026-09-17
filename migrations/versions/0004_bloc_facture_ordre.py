"""bloc_facture_ordre

Migration 0004 (constat de la tâche L2-T5) : une colonne `ordre` sur
`bloc_facture`, nécessaire pour renvoyer les blocs d'une facture « dans
l'ordre » (`GET /api/factures/{id}`, décision du contrôleur L2-T5).

`created_at` ne convient pas : `deposer_facture` insère tous les blocs d'une
même facture dans une seule transaction, où `created_at` (`func.now()`) vaut
le même horodatage de début de transaction pour toutes les lignes insérées.

`server_default='0'` posé puis retiré dans la même migration : rend la
colonne satisfiable pour d'éventuelles lignes déjà présentes (aucune en
pratique, ce lot n'a pas encore de donnée de production), sans laisser de
valeur par défaut côté base ensuite — le modèle (`app/modules/ingest/models.py
::BlocFacture.ordre`) n'en déclare aucune, `deposer_facture` la renseigne
toujours explicitement (`enumerate(facture.blocs)`).

Autogénérée depuis `app/modules/ingest/models.py::BlocFacture` puis relue.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-17 03:10:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bloc_facture",
        sa.Column("ordre", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("bloc_facture", "ordre", server_default=None)


def downgrade() -> None:
    op.drop_column("bloc_facture", "ordre")
