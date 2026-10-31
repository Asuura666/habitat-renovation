"""Contrôle arithmétique d'une ligne de bon (module PUR, A6 du lot 2 du
31/10/2026) : quantité x prix unitaire = montant, au centime près.

Le texte OCR d'un bon peut répartir les chiffres d'une ligne sur plusieurs
lignes de texte ; la position du texte ne prouve donc rien. Les chiffres, eux,
se vérifient : si le produit ne tombe pas sur le montant lu, la ligne est
incertaine quelle que soit la confiance de lecture. Le schéma de lecture ne
porte pas de remise : une ligne remisée peut donc échouer ce contrôle (voir
`docs/dette.md`).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_CENTIME = Decimal("0.01")


def controle_arithmetique_ligne(
    quantite: Decimal | None, pu_ht: Decimal | None, montant_ht: Decimal | None
) -> bool | None:
    """`True` si quantité x prix unitaire, arrondi commercial au centime,
    tombe à un centime près sur le montant ; `False` sinon ; `None` si le
    contrôle est impossible (une des trois valeurs absente, par exemple un
    bon sans prix)."""
    if quantite is None or pu_ht is None or montant_ht is None:
        return None
    produit = (quantite * pu_ht).quantize(_CENTIME, rounding=ROUND_HALF_UP)
    montant = montant_ht.quantize(_CENTIME, rounding=ROUND_HALF_UP)
    return abs(produit - montant) <= _CENTIME
