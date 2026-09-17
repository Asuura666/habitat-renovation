"""Appariement des lignes d'un bloc facture/BL (module pur, L4-D6, L4-T6).

Deux passes, dans l'ordre du CDC §4.5 : d'abord par code article normalisé,
puis, pour les lignes de facture restantes, par désignation normalisée.
Chaque ligne de BL n'est consommée qu'une seule fois et l'appariement ne
franchit jamais la frontière d'un bloc -- c'est l'appelant (`ingest`,
L4-T7) qui ne fournit que les lignes d'un même bloc de part et d'autre.
Une ligne de facture sans correspondance produit `cle_bl=None,
methode=None` plutôt que d'être devinée.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from .texte import normaliser_libelle


@dataclass(frozen=True)
class LigneAApparier:
    cle: uuid.UUID
    code: str | None
    designation: str | None


@dataclass(frozen=True)
class Appariement:
    cle_facture: uuid.UUID
    cle_bl: uuid.UUID | None
    methode: str | None  # "code" | "libelle" | None


def _cle_comparaison(valeur: str | None) -> str:
    """`normaliser_libelle` puis suppression des espaces (Ruling R6) : une
    clé vide (ex. code réduit à de la ponctuation) ne peut apparier
    personne, elle est donc rejetée par les deux passes."""
    return normaliser_libelle(valeur).replace(" ", "")


def apparier_lignes(
    lignes_facture: Sequence[LigneAApparier],
    lignes_bl: Sequence[LigneAApparier],
) -> tuple[Appariement, ...]:
    """Une entrée par ligne de facture, dans l'ordre reçu. Passe 1 : code
    normalisé. Passe 2 (lignes de facture encore sans correspondance) :
    désignation normalisée. Dans chaque passe, une ligne de facture prend la
    première ligne de BL disponible (ordre stable) dont la clé correspond,
    puis la retire des lignes disponibles pour la suite."""
    bl_disponibles: list[LigneAApparier | None] = list(lignes_bl)
    resultats: dict[uuid.UUID, Appariement] = {}

    for ligne_facture in lignes_facture:
        cle_code = _cle_comparaison(ligne_facture.code)
        if not cle_code:
            continue
        for indice, ligne_bl in enumerate(bl_disponibles):
            if ligne_bl is not None and _cle_comparaison(ligne_bl.code) == cle_code:
                resultats[ligne_facture.cle] = Appariement(
                    cle_facture=ligne_facture.cle, cle_bl=ligne_bl.cle, methode="code"
                )
                bl_disponibles[indice] = None
                break

    for ligne_facture in lignes_facture:
        if ligne_facture.cle in resultats:
            continue
        cle_designation = _cle_comparaison(ligne_facture.designation)
        if not cle_designation:
            continue
        for indice, ligne_bl in enumerate(bl_disponibles):
            if (
                ligne_bl is not None
                and _cle_comparaison(ligne_bl.designation) == cle_designation
            ):
                resultats[ligne_facture.cle] = Appariement(
                    cle_facture=ligne_facture.cle,
                    cle_bl=ligne_bl.cle,
                    methode="libelle",
                )
                bl_disponibles[indice] = None
                break

    return tuple(
        resultats.get(
            ligne_facture.cle,
            Appariement(cle_facture=ligne_facture.cle, cle_bl=None, methode=None),
        )
        for ligne_facture in lignes_facture
    )
