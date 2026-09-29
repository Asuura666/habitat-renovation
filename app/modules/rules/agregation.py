"""Agrégation des lignes de même code d'un bloc (B-06, module pur).

Quand un même code article apparaît sur plusieurs lignes de la facture ou
du BL d'un bloc, R03/R04/R05 comparent les quantités *totales* (déjà
converties en unité de facturation) plutôt qu'une ligne contre une autre
choisie arbitrairement. Prudence : on n'agrège que des lignes "article"
dont la conversion est possible et dont les quantités sont comparables
entre elles (même `unite_implicite`) ; sinon `agreger_lignes` renvoie
`None` et l'appelant garde la comparaison ligne à ligne."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from app.modules.rules.modeles import LigneControlee, LigneRapprochee


def _somme(valeurs: Sequence[Decimal | None]) -> Decimal | None:
    if any(valeur is None for valeur in valeurs):
        return None
    return sum((v for v in valeurs if v is not None), Decimal("0"))


def agreger_lignes(lignes: Sequence[LigneControlee]) -> LigneControlee | None:
    """Ligne unique portant les quantités sommées (identité de la première).
    `None` si la liste est vide ou si l'agrégation ne serait pas fiable."""
    if not lignes:
        return None
    if any(ligne.type_ligne != "article" for ligne in lignes):
        return None
    if any(ligne.conversion_impossible or ligne.qte_fact is None for ligne in lignes):
        return None
    if len({ligne.unite_implicite for ligne in lignes}) != 1:
        return None
    # Même code mais articles différents : chaque quantité est convertie
    # dans l'unité de facturation de son article, deux unités possibles.
    if len({ligne.article_id for ligne in lignes}) != 1:
        return None
    if len(lignes) == 1:
        return lignes[0]
    return replace(
        lignes[0],
        qte_fact=_somme([ligne.qte_fact for ligne in lignes]),
        qte_facturee=_somme([ligne.qte_facturee for ligne in lignes]),
        qte_conditionnements=_somme([ligne.qte_conditionnements for ligne in lignes]),
        montant_ht=_somme([ligne.montant_ht for ligne in lignes]),
    )


def lignes_a_comparer(
    rapprochee: LigneRapprochee,
) -> tuple[LigneControlee, LigneControlee] | None:
    """Couple (facture, BL) que R03/R04 comparent : les lignes agrégées du
    groupe pour la tête d'un groupe, la paire appariée sinon. `None` si la
    ligne n'a pas de BL apparié, ou si c'est une ligne secondaire d'un
    groupe (déjà comparée via sa tête)."""
    if rapprochee.secondaire or rapprochee.bl is None:
        return None
    if rapprochee.groupe_facture and rapprochee.groupe_bl:
        facture = agreger_lignes(rapprochee.groupe_facture)
        bl = agreger_lignes(rapprochee.groupe_bl)
        if facture is not None and bl is not None:
            return facture, bl
    return rapprochee.facture, rapprochee.bl


def detail_groupe(rapprochee: LigneRapprochee) -> dict[str, str]:
    """Clés de `detail` ajoutées quand la comparaison porte sur un groupe :
    quantités de chaque ligne réunie, côté facture et côté BL. Vide hors
    groupe (le `detail` des anomalies isolées reste inchangé)."""
    if not (rapprochee.groupe_facture and rapprochee.groupe_bl):
        return {}
    return {
        "lignes_facture": " + ".join(
            str(g.qte_fact) for g in rapprochee.groupe_facture
        ),
        "lignes_bl": " + ".join(str(g.qte_fact) for g in rapprochee.groupe_bl),
    }
