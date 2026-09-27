"""Tables de l'IA (tâche T1 de la conception
`docs/superpowers/specs/2026-09-27-phase-4-ia-design.md`, §8) : cinq tables
au service de la synthèse hebdomadaire des commentaires (§4.4), de
l'explication des alertes prix (§5.3) et du prix trouvé sur internet (§6.3).
`appel_ia` est le journal technique commun aux trois usages (jamais le texte
envoyé ni la réponse, sert au plafond quotidien).

`down_revision = "0012"` : le lot Prix (session B, branche
`feature/phase-3-prix`) ajoute en parallèle une migration `0013`. Cette
branche (`feature/phase-4-ia`) ne la voit pas encore ; la chaîne
`0012 -> 0013 -> 0014` sera remise en ligne par la branche qui fusionne dans
`dev` en second (roadmap §2.4, vérifié par `tests/test_migrations.py`).

Autogénérée depuis `app/modules/ingest/models.py` puis relue.

Revision ID: 0014
Revises: 0012
Create Date: 2026-09-27 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "appel_ia",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("usage", sa.Text(), nullable=False),
        sa.Column("statut", sa.Text(), nullable=False),
        sa.Column("erreur", sa.Text(), nullable=True),
        sa.Column("duree_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "usage IN ('synthese', 'explication', 'prix')",
            name=op.f("ck_appel_ia_usage_valide"),
        ),
        sa.CheckConstraint(
            "statut IN ('ok', 'erreur')", name=op.f("ck_appel_ia_statut_valide")
        ),
        sa.CheckConstraint("duree_ms >= 0", name=op.f("ck_appel_ia_duree_ms_positif")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appel_ia")),
    )
    op.create_index(op.f("ix_appel_ia_created_at"), "appel_ia", ["created_at"])

    op.create_table(
        "synthese_commentaires",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("semaine_debut", sa.Date(), nullable=False),
        sa.Column("semaine_fin", sa.Date(), nullable=False),
        sa.Column("statut", sa.Text(), nullable=False),
        sa.Column("resume", sa.Text(), nullable=False),
        sa.Column("nb_commentaires", sa.Integer(), nullable=False),
        sa.Column("modele", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "statut IN ('ok', 'vide')",
            name=op.f("ck_synthese_commentaires_statut_valide"),
        ),
        sa.CheckConstraint(
            "nb_commentaires >= 0",
            name=op.f("ck_synthese_commentaires_nb_commentaires_positif"),
        ),
        sa.CheckConstraint(
            "semaine_fin >= semaine_debut",
            name=op.f("ck_synthese_commentaires_periode_valide"),
        ),
        sa.UniqueConstraint(
            "semaine_debut", name=op.f("uq_synthese_commentaires_semaine_debut")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_synthese_commentaires")),
    )

    op.create_table(
        "synthese_action",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("synthese_id", sa.UUID(), nullable=False),
        sa.Column("ordre", sa.Integer(), nullable=False),
        sa.Column("texte", sa.Text(), nullable=False),
        sa.Column(
            "commentaire_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "document_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("faite_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("faite_par", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(texte) BETWEEN 1 AND 300",
            name=op.f("ck_synthese_action_texte_longueur"),
        ),
        sa.ForeignKeyConstraint(
            ["synthese_id"],
            ["synthese_commentaires.id"],
            name=op.f("fk_synthese_action_synthese_id_synthese_commentaires"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["faite_par"],
            ["utilisateur.id"],
            name=op.f("fk_synthese_action_faite_par_utilisateur"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_synthese_action")),
    )
    op.create_index(
        op.f("ix_synthese_action_synthese_id"), "synthese_action", ["synthese_id"]
    )

    op.create_table(
        "explication_alerte",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("anomalie_id", sa.UUID(), nullable=False),
        sa.Column("empreinte_detail", sa.Text(), nullable=False),
        sa.Column("statut", sa.Text(), nullable=False),
        sa.Column("texte", sa.Text(), nullable=True),
        sa.Column("echecs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("modele", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "statut IN ('ok', 'echec')",
            name=op.f("ck_explication_alerte_statut_valide"),
        ),
        sa.CheckConstraint(
            "echecs >= 0", name=op.f("ck_explication_alerte_echecs_positif")
        ),
        sa.CheckConstraint(
            "statut <> 'ok' OR texte IS NOT NULL",
            name=op.f("ck_explication_alerte_ok_avec_texte"),
        ),
        sa.ForeignKeyConstraint(
            ["anomalie_id"],
            ["anomalie.id"],
            name=op.f("fk_explication_alerte_anomalie_id_anomalie"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_explication_alerte")),
        sa.UniqueConstraint(
            "anomalie_id", name=op.f("uq_explication_alerte_anomalie_id")
        ),
    )

    op.create_table(
        "prix_internet",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("fournisseur_id", sa.UUID(), nullable=True),
        sa.Column("cle", sa.Text(), nullable=False),
        sa.Column("designation", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("statut", sa.Text(), nullable=False),
        sa.Column("prix", sa.Numeric(12, 4), nullable=True),
        sa.Column("devise", sa.Text(), nullable=True),
        # Amendement du contrôleur (27/09/2026) : un prix public trouvé sur
        # internet est le plus souvent TTC, alors que les prix de grille et
        # des bons sont HT (CDC) -- l'écran doit pouvoir dire lequel.
        sa.Column("taxes", sa.Text(), nullable=True),
        sa.Column("unite", sa.Text(), nullable=True),
        sa.Column("conditionnement", sa.Text(), nullable=True),
        sa.Column("produit_trouve", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("confiance", sa.Text(), nullable=True),
        sa.Column("raison", sa.Text(), nullable=True),
        sa.Column("modele", sa.Text(), nullable=True),
        sa.Column("consulte_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "statut IN ('trouve', 'non_verifiable', 'echec')",
            name=op.f("ck_prix_internet_statut_valide"),
        ),
        sa.CheckConstraint(
            "prix IS NULL OR prix > 0", name=op.f("ck_prix_internet_prix_positif")
        ),
        sa.CheckConstraint(
            "taxes IS NULL OR taxes IN ('HT', 'TTC')",
            name=op.f("ck_prix_internet_taxes_valide"),
        ),
        sa.CheckConstraint(
            "confiance IS NULL OR confiance IN ('faible', 'moyenne', 'elevee')",
            name=op.f("ck_prix_internet_confiance_valide"),
        ),
        sa.CheckConstraint(
            "statut <> 'trouve' OR (prix IS NOT NULL AND source_url IS NOT NULL)",
            name=op.f("ck_prix_internet_trouve_avec_prix_et_source"),
        ),
        sa.ForeignKeyConstraint(
            ["fournisseur_id"],
            ["fournisseur.id"],
            name=op.f("fk_prix_internet_fournisseur_id_fournisseur"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prix_internet")),
    )
    op.create_index(
        op.f("ix_prix_internet_fournisseur_id_cle_consulte_le"),
        "prix_internet",
        ["fournisseur_id", "cle", sa.text("consulte_le DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_prix_internet_fournisseur_id_cle_consulte_le"),
        table_name="prix_internet",
    )
    op.drop_table("prix_internet")
    op.drop_table("explication_alerte")
    op.drop_index(op.f("ix_synthese_action_synthese_id"), table_name="synthese_action")
    op.drop_table("synthese_action")
    op.drop_table("synthese_commentaires")
    op.drop_index(op.f("ix_appel_ia_created_at"), table_name="appel_ia")
    op.drop_table("appel_ia")
