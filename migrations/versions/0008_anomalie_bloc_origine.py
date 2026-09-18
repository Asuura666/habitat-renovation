"""anomalie_bloc_origine

Migration de données pure (Ruling L5-R6, tour de correction 2 de L5-T1) —
aucune modification de schéma.

Le Ruling L5-R3 (tour de correction 1) a changé `ingest.rapprochement
.rapprocher_facture` pour qu'il complète `bloc_id` sur toute anomalie qui
porte un `ligne_id` mais pas de `bloc_id` nativement (R07, R08, R09, R13,
R17 — la règle pure ne reçoit que la ligne, jamais le bloc). Ce complément
ne modifie pas seulement une information affichée : `bloc_id` fait partie
de la clé d'identité d'une anomalie (`(regle, document_id, bloc_id,
ligne_id, chantier_id, alias_id)`, L4-D11). Une anomalie de l'une de ces
cinq règles, enregistrée **avant** ce correctif, porte donc `bloc_id
IS NULL` en base.

Si un humain a **traité** ou **ignoré** cette anomalie, puis que le
rapprochement de sa facture est rejoué après déploiement du correctif (ce
qui arrive tout seul dès qu'un BL correspondant est validé) : la nouvelle
anomalie recalculée porte désormais un `bloc_id` renseigné, la recherche par
clé (`ingest.anomalies._trouver_par_cle`) ne retrouve donc plus l'ancienne
ligne (`bloc_id` différent), et une **seconde** anomalie, `ouverte`, est
insérée pour la même cause — la décision de l'humain est contournée en
silence, ce que L4-D12 interdit explicitement (« une anomalie traitée ou
ignorée n'est jamais touchée »). `ingest.anomalies._bloquee_par_ignorance`
ne protège que le statut `ignoree`, et seulement pendant `duree_ignorance_j`
(90 jours par défaut) : elle ne rattrape pas ce cas, et jamais le statut
`traitee`.

`upgrade()` répare donc les lignes déjà en base, **quel que soit leur
statut** (`ouverte`, `traitee` ou `ignoree`) : c'est justement les lignes
`traitee`/`ignoree` qu'il faut sauver, une anomalie déjà `ouverte` n'ayant de
toute façon rien à perdre à voir son `bloc_id` complété. Un seul `UPDATE`
ensembliste (pas de boucle Python ligne à ligne, volume potentiellement non
trivial) : `bloc_id` pris sur la ligne visée par `ligne_id`, seulement quand
`anomalie.bloc_id` est vide et que la ligne porte elle-même un bloc.

`downgrade()` remet `bloc_id` à `NULL` pour les anomalies des règles qui ne
le posaient pas nativement avant le Ruling L5-R3 (R07, R08, R09, R13, R17 —
seules celles listées explicitement ici, pas R01/R02/R03/R04/R05/R06/R12 qui
posent déjà `bloc_id` eux-mêmes) et qui portent un `ligne_id` : symétrique
de `upgrade()`, sans condition sur le statut pour la même raison.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-18 06:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import bindparam, text

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Règles qui ne posent jamais `bloc_id` nativement sur l'anomalie qu'elles
# produisent (seulement `ligne_id`/`article_id`, la règle pure ne reçoit que
# la ligne) — voir le docstring de module et celui de
# `app.modules.ingest.rapprochement` (Ruling L5-R3). Toutes les autres
# règles de facture (R01, R02, R03, R04, R05, R06, R12) posent `bloc_id`
# elles-mêmes et ne sont jamais concernées par cette migration.
_REGLES_SANS_BLOC_ID_NATIF: tuple[str, ...] = ("R07", "R08", "R09", "R13", "R17")


def upgrade() -> None:
    op.execute(
        "UPDATE anomalie "
        "SET bloc_id = ligne.bloc_id "
        "FROM ligne "
        "WHERE anomalie.ligne_id = ligne.id "
        "AND anomalie.bloc_id IS NULL "
        "AND ligne.bloc_id IS NOT NULL"
    )


def downgrade() -> None:
    requete = text(
        "UPDATE anomalie "
        "SET bloc_id = NULL "
        "WHERE regle IN :regles "
        "AND ligne_id IS NOT NULL"
    ).bindparams(bindparam("regles", expanding=True))
    op.get_bind().execute(requete, {"regles": list(_REGLES_SANS_BLOC_ID_NATIF)})
