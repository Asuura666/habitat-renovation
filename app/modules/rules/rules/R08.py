"""R08 — prix hors historique fort (CDC §5, L4-T4).

Même calcul que R07 (écart relatif à la médiane des 6 derniers mois,
`ecart_prix_pct`/`mediane_utilisable`, réutilisées depuis R07 plutôt que
dupliquées, à l'image de `mention_pas_de_bon` partagée entre R01 et R02),
mais gravité haute quand l'écart dépasse strictement `seuil_prix_fort_pct`
(15 % par défaut). R07 s'arrête à cette borne incluse (`<=`), R08 prend le
relais strictement au-dessus (`>`) : les deux comparaisons complémentaires
garantissent l'exclusivité (CDC §5 : « R07 et R08 s'excluent »)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.modules.rules.modeles import (
    Anomalie,
    ArticleControle,
    Gravite,
    HistoriqueArticle,
    LigneControlee,
    Parametres,
)
from app.modules.rules.rules.R07 import ecart_prix_pct, mediane_utilisable

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)
_QUANTUM_ECART = Decimal("0.01")


def R08(
    ligne: LigneControlee,
    article: ArticleControle,
    historique: HistoriqueArticle,
    parametres: Parametres,
) -> Anomalie | None:
    """`None` si la ligne n'est pas de type "article", si son `pu_ht` est
    absent, si l'historique est trop pauvre, ou si l'écart ne dépasse pas
    strictement `seuil_prix_fort_pct` (matière de R07 sinon)."""
    if ligne.type_ligne != "article":
        return None
    if ligne.pu_ht is None:
        return None
    mediane = mediane_utilisable(historique, parametres)
    if mediane is None:
        return None

    ecart = ecart_prix_pct(ligne.pu_ht, mediane)
    if ecart <= parametres.seuil_prix_fort_pct:
        return None

    return Anomalie(
        regle="R08",
        gravite=Gravite.HAUTE,
        detail={
            "article": article.libelle or ligne.designation or TIRET,
            "code": ligne.code or TIRET,
            "pu_facture": str(ligne.pu_ht),
            "mediane": str(mediane),
            "occurrences": str(historique.occurrences),
            "ecart_pct": str(ecart.quantize(_QUANTUM_ECART, rounding=ROUND_HALF_UP)),
        },
        ligne_id=ligne.id,
        article_id=article.id,
    )
