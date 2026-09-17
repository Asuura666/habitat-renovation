"""R06 — ligne BL non facturée (CDC §5, L4-T5).

Une ligne de type "article" présente sur le BL d'un bloc mais sans ligne
correspondante côté facture (`bloc.lignes_bl_non_facturees`, L4-D6), dont la
date du BL (`bloc.date_bl`) remonte à plus de
`delai_ligne_bl_non_facturee_j` jours (défaut 45, L4-D10) : gravité basse,
justification chiffrée = article, quantité, date du BL et nombre de jours
écoulés (CDC §5 : « Article, qté, date BL »).

Règle de suivi (L4-D14) : bien que de niveau ligne dans le catalogue du CDC
§5, elle est évaluée par `evaluer_suivi`, pas par `evaluer_facture` — elle
dépend du temps écoulé depuis le BL, pas d'un document nouvellement déposé
(décision du contrôleur, regroupée avec R14-R16). Comparaison strictement
supérieure au délai, en jours entiers : exactement au délai -> rien
(décision du contrôleur)."""

from __future__ import annotations

from datetime import datetime

from app.modules.rules.modeles import (
    Anomalie,
    BlocControle,
    Gravite,
    LigneControlee,
    Parametres,
)

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)


def R06(
    bloc: BlocControle,
    ligne_bl: LigneControlee,
    aujourdhui: datetime,
    parametres: Parametres,
) -> Anomalie | None:
    """`None` si la ligne n'est pas de type "article", si le bloc n'a pas de
    date de BL, ou si `delai_ligne_bl_non_facturee_j` jours au plus se sont
    écoulés depuis cette date."""
    if ligne_bl.type_ligne != "article":
        return None
    if bloc.date_bl is None:
        return None

    jours = (aujourdhui.date() - bloc.date_bl).days
    if jours <= parametres.delai_ligne_bl_non_facturee_j:
        return None

    qte = str(ligne_bl.qte_facturee) if ligne_bl.qte_facturee is not None else TIRET
    return Anomalie(
        regle="R06",
        gravite=Gravite.BASSE,
        detail={
            "article": ligne_bl.designation or TIRET,
            "code": ligne_bl.code or TIRET,
            "qte": qte,
            "date_bl": bloc.date_bl.isoformat(),
            "jours": str(jours),
        },
        bloc_id=bloc.id,
        ligne_id=ligne_bl.id,
        article_id=ligne_bl.article_id,
    )
