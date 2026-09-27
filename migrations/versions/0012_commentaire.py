"""Commentaires sur les lignes d'un bon (§3 de
docs/superpowers/specs/2026-09-27-commentaires-lignes-design.md, décisions
d'Ilane du 27/09/2026, question §6.3-8) : table `commentaire`, append-only
comme `journal`.

`document_id` en `ON DELETE CASCADE` (garde le commentaire rattaché au bon
même si sa ligne disparaît) et `ligne_id` en `ON DELETE SET NULL` (la ligne
commentée peut être supprimée puis recréée à chaque relance de la lecture,
`extraction_bl.enregistrer_extraction_bl`, ou par une correction manuelle,
`corrections.corriger_lignes`) : les deux seules exceptions à la convention
« aucun ondelete en cascade » du module (`app/modules/ingest/models.py`).

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-27 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commentaire",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("ligne_id", sa.UUID(), nullable=True),
        sa.Column("ligne_libelle", sa.Text(), nullable=False),
        sa.Column("auteur_id", sa.UUID(), nullable=True),
        sa.Column("texte", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(texte) BETWEEN 1 AND 1000",
            name=op.f("ck_commentaire_texte_longueur"),
        ),
        sa.ForeignKeyConstraint(
            ["auteur_id"],
            ["utilisateur.id"],
            name=op.f("fk_commentaire_auteur_id_utilisateur"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name=op.f("fk_commentaire_document_id_document"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ligne_id"],
            ["ligne.id"],
            name=op.f("fk_commentaire_ligne_id_ligne"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commentaire")),
    )
    op.create_index(op.f("ix_commentaire_document_id"), "commentaire", ["document_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_commentaire_document_id"), table_name="commentaire")
    op.drop_table("commentaire")
