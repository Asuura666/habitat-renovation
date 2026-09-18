"""Normalisation des unités de mesure et de conditionnement (module pur).

Comparaison sur `normaliser_libelle` sans espaces (insensible aux accents,
à la casse et aux espaces internes) contre une table explicite de variantes
observées sur les BL/factures des deux fournisseurs (L3-T4). Une unité
absente de la table est jugée inconnue plutôt que devinée : aucune règle
métier ne doit s'appuyer sur une unité mal reconnue.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
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


def convertir_en_unite_fact(
    qte: Decimal | None,
    unite_lue: str | None,
    unite_cdt: str | None,
    unite_fact: str | None,
    ratio: Decimal | None,
    ratio_valide: bool,
    *,
    unite_absente_acceptee: bool = False,
) -> Decimal | None:
    """Quantité facturée convertie dans l'unité de facturation de l'article
    (L4-D7, Ruling R6, R10, puis R14 -- fix round 1 de la tâche L4-T7). Les
    unités sont comparées après `normaliser_unite` (sur `Unite.code`, jamais
    sur les chaînes brutes) : cinq cas, dans cet ordre, sinon `None` -- une
    conversion incertaine n'est jamais devinée (CDC §10 : « 0 anomalie
    R03/R04 due à une unité »).

    1. `qte` absente -> `None`.
    2. `unite_lue` absente **et** `unite_fact` inconnue (absente ou non
       reconnue par `normaliser_unite`) -> `qte` inchangée, **quel que soit**
       `unite_absente_acceptee` (Ruling R14, constat réel sur la facture
       Unikalo d'août : aucune unité n'est jamais imprimée, ni sur la
       facture ni sur les BL, et l'article n'a donc pas d'`unite_fact`
       résolue) : deux documents du même fournisseur qui ne portent chacun
       aucune unité comptent implicitement dans la même unité (non
       identifiée, mais commune) -- ils restent comparables entre eux, une
       comparaison entre facture et BL ne doit donc pas être perdue faute
       d'unité connue nulle part.
    3. `unite_lue` absente, `unite_fact` connue (reconnue par
       `normaliser_unite`) : `unite_absente_acceptee` vrai -> `qte`
       inchangée ; faux -> `None`. `unite_absente_acceptee` ne garde son
       sens que pour ce cas précis -- « unité de facturation connue mais pas
       imprimée sur ce document » (Ruling R10, constat CDC §4.3) : une ligne
       de facture Unikalo n'imprime structurellement aucune unité (l'appelant
       passe `True`), alors qu'une ligne de BL photographié en imprime
       toujours une quand l'article est déjà résolu -- une unité absente y
       signale alors un échec d'OCR, pas l'absence de colonne, et ne doit
       jamais être acceptée telle quelle (l'appelant passe `False`, la
       valeur par défaut). `L4-T7` est responsable de choisir la valeur
       selon le type de document analysé.
    4. `unite_lue` normalisée == `unite_fact` normalisée -> `qte` inchangée.
    5. `unite_lue` normalisée == `unite_cdt` normalisée, avec un `ratio`
       strictement positif et validé (`ratio_valide`) -> `qte * ratio`.

    Tout le reste (`unite_lue` connue -- présente et reconnue -- mais qui ne
    correspond ni à `unite_fact` ni à `unite_cdt`, `unite_lue` présente mais
    non reconnue par `normaliser_unite`, ratio absent, nul, négatif ou non
    validé) -> `None` : un cas 2 ne s'applique jamais quand une unité a
    effectivement été lue, même si elle est illisible -- seule l'absence
    structurelle des deux côtés déclenche la comparaison implicite.
    """
    if qte is None:
        return None

    unite_fact_normalisee = normaliser_unite(unite_fact)

    if unite_lue is None:
        if unite_fact_normalisee is None:
            return qte
        if unite_absente_acceptee:
            return qte
        return None

    unite_lue_normalisee = normaliser_unite(unite_lue)
    if unite_lue_normalisee is None:
        return None

    if (
        unite_fact_normalisee is not None
        and unite_lue_normalisee.code == unite_fact_normalisee.code
    ):
        return qte

    unite_cdt_normalisee = normaliser_unite(unite_cdt)
    if (
        unite_cdt_normalisee is not None
        and unite_lue_normalisee.code == unite_cdt_normalisee.code
        and ratio is not None
        and ratio > 0
        and ratio_valide
    ):
        return qte * ratio

    return None
