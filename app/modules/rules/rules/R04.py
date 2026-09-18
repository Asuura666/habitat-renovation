"""R04 — quantité facturée inférieure à la quantité BL (CDC §5, L4-T3).

Symétrique de `R03` (même garde, `ecart_qte_fact` réutilisé depuis là) : le
fournisseur a sous-facturé, ou la livraison est partielle. Gravité moyenne
(CDC §5), justification chiffrée identique à R03.

Ruling R16 (fix round 2 de L4-T7) : `ecart_qte_fact` (partagée avec R03) ne
compare deux quantités que si `LigneControlee.unite_implicite` porte la
même valeur des deux côtés -- une paire mixte (une seule ligne en unité
implicite) ne produit ni R03 ni R04."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from app.modules.rules.modeles import (
    Anomalie,
    ArticleControle,
    BlocControle,
    Gravite,
    LigneRapprochee,
)
from app.modules.rules.rules.R03 import detail_ecart_qte, ecart_qte_fact


def R04(
    bloc: BlocControle,
    rapprochee: LigneRapprochee,
    articles: Mapping[UUID, ArticleControle],
) -> Anomalie | None:
    """`None` si la ligne n'est pas appariée à une ligne de BL, ou si
    `ecart_qte_fact` ne renvoie pas un écart strictement négatif (égalité
    exacte -> ni R03 ni R04 ; écart positif -> matière de R03)."""
    if rapprochee.bl is None:
        return None
    facture, bl = rapprochee.facture, rapprochee.bl
    ecart = ecart_qte_fact(facture, bl)
    if ecart is None or ecart >= 0:
        return None

    return Anomalie(
        regle="R04",
        gravite=Gravite.MOYENNE,
        detail=detail_ecart_qte(facture, bl, articles, ecart),
        bloc_id=bloc.id,
        ligne_id=facture.id,
        article_id=facture.article_id,
    )
