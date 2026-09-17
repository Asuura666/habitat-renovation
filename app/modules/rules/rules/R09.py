"""R09 — remise absente (CDC §5, L4-T4).

Un article habituellement remisé chez ce fournisseur (`remise_habituelle`
non nulle et `occurrences_remise >= occurrences_prix_min`,
`HistoriqueArticle`, L4-D9) mais facturé sans remise sur cette ligne
(`remise_pct` absente **ou** égale à zéro — décision du contrôleur : une
remise plus faible que l'habituelle n'est **pas** R09, le CDC ne parle que
de l'absence) : gravité moyenne, justification chiffrée = article, remise
habituelle, remise appliquée et nombre d'occurrences (CDC §5).

Indépendante de `mediane_pu`/`occurrences` (matière de R07/R08) : sa garde
d'historique porte sur `occurrences_remise` et `remise_habituelle`, pas sur
les prix (décisions du contrôleur). Ne dépend ni du BL rapproché ni de
`conversion_impossible` (Ruling R7)."""

from __future__ import annotations

from app.modules.rules.modeles import (
    Anomalie,
    ArticleControle,
    Gravite,
    HistoriqueArticle,
    LigneControlee,
    Parametres,
)

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)


def R09(
    ligne: LigneControlee,
    article: ArticleControle,
    historique: HistoriqueArticle,
    parametres: Parametres,
) -> Anomalie | None:
    """`None` si la ligne n'est pas de type "article", si l'article n'a pas
    de remise habituelle connue, si l'historique de remise est trop pauvre
    (`occurrences_remise < occurrences_prix_min`), ou si la ligne porte
    elle-même une remise non nulle (même plus faible que l'habituelle :
    seule l'absence totale déclenche R09, décision du contrôleur)."""
    if ligne.type_ligne != "article":
        return None
    if historique.remise_habituelle is None:
        return None
    if historique.occurrences_remise < parametres.occurrences_prix_min:
        return None
    if ligne.remise_pct is not None and ligne.remise_pct != 0:
        return None

    remise_appliquee = str(ligne.remise_pct) if ligne.remise_pct is not None else TIRET
    return Anomalie(
        regle="R09",
        gravite=Gravite.MOYENNE,
        detail={
            "article": article.libelle or ligne.designation or TIRET,
            "code": ligne.code or TIRET,
            "remise_habituelle": str(historique.remise_habituelle),
            "remise_appliquee": remise_appliquee,
            "occurrences": str(historique.occurrences_remise),
        },
        ligne_id=ligne.id,
        article_id=article.id,
    )
