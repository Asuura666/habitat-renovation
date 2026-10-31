"""Contrôle arithmétique d'une ligne de bon (module PUR, A6 du lot 2 du
31/10/2026) : quantité x prix unitaire = montant.

Le texte OCR d'un bon peut répartir les chiffres d'une ligne sur plusieurs
lignes de texte ; la position du texte ne prouve donc rien. Les chiffres, eux,
se vérifient : si le produit ne tombe pas sur le montant lu, la ligne est
incertaine quelle que soit la confiance de lecture.

Tolérance : un centime (arrondi du montant) plus la moitié de la dernière
décimale imprimée du prix, multipliée par la quantité -- les prix imprimés sont
arrondis (100 x 0,888 pour un vrai prix de 0,8875). Le schéma de lecture ne
porte pas de remise : une ligne remisée peut donc échouer ce contrôle (voir
`docs/dette.md`).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

_CENTIME = Decimal("0.01")
_NOMBRE_RE = re.compile(r"^-?[\d\s]+(?:[.,](\d+))?$")


def decimales_du_brut(brut: str | None) -> int | None:
    """Nombre de décimales d'un nombre tel qu'il est lu (« 0,888 » -> 3,
    « 14,80 » -> 2), `None` si le brut est absent ou n'est pas un nombre."""
    if brut is None:
        return None
    trouve = _NOMBRE_RE.match(brut.strip())
    if trouve is None:
        return None
    return len(trouve.group(1) or "")


def produit_attendu(quantite: Decimal, pu_ht: Decimal) -> Decimal:
    """Quantité x prix unitaire, arrondi commercial au centime."""
    return (quantite * pu_ht).quantize(_CENTIME, rounding=ROUND_HALF_UP)


def controle_arithmetique_ligne(
    quantite: Decimal | None,
    pu_ht: Decimal | None,
    montant_ht: Decimal | None,
    *,
    decimales_pu: int | None = None,
) -> bool | None:
    """`True` si le produit arrondi tombe sur le montant dans la tolérance
    (un centime + |quantité| x 0,5 x 10^-d, `d` = décimales du prix tel que lu ;
    à défaut de `decimales_pu`, celles de la valeur) ; `False` sinon ; `None` si
    le contrôle est impossible (une des trois valeurs absente, par exemple un
    bon sans prix)."""
    if quantite is None or pu_ht is None or montant_ht is None:
        return None
    if decimales_pu is None:
        decimales_pu = max(0, -int(pu_ht.as_tuple().exponent))
    tolerance = _CENTIME + abs(quantite) * Decimal("0.5") * Decimal(10) ** -decimales_pu
    montant = montant_ht.quantize(_CENTIME, rounding=ROUND_HALF_UP)
    return abs(produit_attendu(quantite, pu_ht) - montant) <= tolerance
