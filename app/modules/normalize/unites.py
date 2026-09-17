"""Normalisation des unités de mesure et de conditionnement (module pur).

Comparaison sur `normaliser_libelle` sans espaces (insensible aux accents,
à la casse et aux espaces internes) contre une table explicite de variantes
observées sur les BL/factures des deux fournisseurs (L3-T4). Une unité
absente de la table est jugée inconnue plutôt que devinée : aucune règle
métier ne doit s'appuyer sur une unité mal reconnue.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .texte import normaliser_libelle


class NatureUnite(StrEnum):
    MESURE = "mesure"
    CONDITIONNEMENT = "conditionnement"


@dataclass(frozen=True)
class Unite:
    code: str
    nature: NatureUnite


_MESURES: dict[str, tuple[str, ...]] = {
    "kg": ("KG", "KGS", "KILO", "KILOS", "KILOGRAMME", "KILOGRAMMES"),
    "g": ("G", "GR", "GRAMME", "GRAMMES"),
    "t": ("T", "TONNE", "TONNES"),
    "l": ("L", "LT", "LITRE", "LITRES"),
    "m": ("M", "ML", "METRE", "METRES", "MTR"),
    "m2": ("M2", "M²", "MQ", "METRECARRE"),
    "m3": ("M3", "M³"),
    "u": ("U", "UN", "UNITE", "UNITES", "PCE", "PC", "PIECE", "PIECES"),
}

_CONDITIONNEMENTS: dict[str, tuple[str, ...]] = {
    "seau": ("SEAU", "SEAUX", "SE"),
    "sac": ("SAC", "SACS", "BAG", "BAGS"),
    "rouleau": ("ROULEAU", "ROULEAUX", "RLX", "RL"),
    "bidon": ("BIDON", "BIDONS", "BID"),
    "pot": ("POT", "POTS"),
    "carton": ("CARTON", "CARTONS", "CTN"),
    "boite": ("BOITE", "BOITES", "BTE"),
    "palette": ("PALETTE", "PALETTES", "PAL"),
    "lot": ("LOT", "LOTS"),
    "paquet": ("PAQUET", "PAQUETS", "PAQ", "PQT"),
    "cartouche": ("CARTOUCHE", "CARTOUCHES", "CART"),
}


def _cle(variante: str) -> str:
    return normaliser_libelle(variante).replace(" ", "")


def _construire_index(
    table: dict[str, tuple[str, ...]], nature: NatureUnite
) -> dict[str, Unite]:
    index: dict[str, Unite] = {}
    for code, variantes in table.items():
        unite = Unite(code=code, nature=nature)
        for variante in variantes:
            index[_cle(variante)] = unite
    return index


_INDEX_UNITES: dict[str, Unite] = {
    **_construire_index(_MESURES, NatureUnite.MESURE),
    **_construire_index(_CONDITIONNEMENTS, NatureUnite.CONDITIONNEMENT),
}


def normaliser_unite(brut: str | None) -> Unite | None:
    if brut is None:
        return None
    return _INDEX_UNITES.get(_cle(brut))
