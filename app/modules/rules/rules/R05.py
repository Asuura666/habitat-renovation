"""R05 — ligne facturée absente du BL (CDC §5, L4-T3).

Une ligne de facture de type "article", non appariée à une ligne de BL
(`rapprochee.bl is None`, L4-D6), dans un bloc qui a bien un BL rapproché
(`bloc.bl is not None` — sinon c'est déjà R01/R02 qui signalent l'absence de
BL, pas R05) : gravité haute, justification chiffrée = article, quantité et
montant de la ligne facturée (CDC §5 : « Article, qté, montant »).

Ne dépend pas de `conversion_impossible` (L4-D7) : la ligne n'a de toute
façon pas de contrepartie BL à comparer, donc aucune conversion n'entre en
jeu — décision du contrôleur. Les lignes `eco`/`commentaire` ne produisent
jamais d'anomalie de ligne."""

from __future__ import annotations

from app.modules.rules.modeles import Anomalie, BlocControle, Gravite, LigneRapprochee

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)


def R05(bloc: BlocControle, rapprochee: LigneRapprochee) -> Anomalie | None:
    """`None` si la ligne est appariée, si elle n'est pas de type "article",
    ou si le bloc n'a pas de BL rapproché (matière de R01/R02, pas de R05)."""
    if rapprochee.bl is not None:
        return None
    if rapprochee.facture.type_ligne != "article":
        return None
    if bloc.bl is None:
        return None

    facture = rapprochee.facture
    qte = str(facture.qte_facturee) if facture.qte_facturee is not None else TIRET
    montant = str(facture.montant_ht) if facture.montant_ht is not None else TIRET
    return Anomalie(
        regle="R05",
        gravite=Gravite.HAUTE,
        detail={
            "article": facture.designation or TIRET,
            "code": facture.code or TIRET,
            "qte": qte,
            "montant": montant,
        },
        bloc_id=bloc.id,
        ligne_id=facture.id,
        article_id=facture.article_id,
    )
