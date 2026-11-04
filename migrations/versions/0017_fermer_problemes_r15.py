"""Fermeture des problèmes R15 encore ouverts (« Quantités non confirmées par
l'équipe »), décision d'Ilane du 31/10/2026 : la confirmation des quantités
par l'équipe est retirée, la règle R15 n'est plus produite.

Chaque anomalie `regle = 'R15'` et `statut = 'ouverte'` passe à `traitee`
avec le commentaire « Confirmation des quantités retirée (31/10/2026) »,
`traitee_le = now()` et `traitee_par` vide ; une ligne de journal
`anomalie_traitee` (auteur vide, `avant`/`apres` comme les fermetures
existantes) est écrite pour chacune. Les anomalies R15 déjà traitées ou
ignorées ne sont pas touchées.

Écrite à la main, puis relue.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-31 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMENTAIRE = "Confirmation des quantités retirée (31/10/2026)"


def upgrade() -> None:
    # Une seule instruction : la fermeture et le journal partent des mêmes
    # lignes, sans second balayage ni état intermédiaire. `cibles` garde le
    # commentaire d'avant (le champ `avant` du journal), `fermees` ne
    # renvoie que les lignes réellement modifiées.
    op.get_bind().execute(
        sa.text(
            """
        WITH cibles AS (
            SELECT id, commentaire
              FROM anomalie
             WHERE regle = 'R15' AND statut = 'ouverte'
               FOR UPDATE
        ),
        fermees AS (
            UPDATE anomalie
               SET statut = 'traitee',
                   commentaire = :commentaire,
                   traitee_le = now(),
                   traitee_par = NULL
             WHERE id IN (SELECT id FROM cibles)
         RETURNING id
        )
        INSERT INTO journal
               (utilisateur_id, action, cible_table, cible_id, avant, apres)
        SELECT NULL,
               'anomalie_traitee',
               'anomalie',
               cibles.id::text,
               jsonb_build_object(
                   'statut', 'ouverte', 'commentaire', cibles.commentaire
               ),
               jsonb_build_object('statut', 'traitee', 'commentaire', :commentaire)
          FROM cibles
          JOIN fermees ON fermees.id = cibles.id
            """
        ),
        {"commentaire": _COMMENTAIRE},
    )


def downgrade() -> None:
    # Sans effet sur les données : les problèmes fermés ne sont pas rouverts
    # (la règle R15 est retirée) et les lignes de journal restent (journal
    # en ajout seul).
    pass
