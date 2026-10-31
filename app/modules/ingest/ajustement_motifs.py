"""Ajustement des motifs « à vérifier » d'un bon une fois ses référentiels
résolus (lot 2 du 31/10/2026, décisions d'Ilane).

`verifier_bl` (module pur) ne connaît que la lecture : un nom mal lu par
l'OCR donne un motif « lecture incertaine ». Mais quand le référentiel
confirme la lecture, ce motif ne sert plus à rien et encombre « À régler » :

- fournisseur reconnu par son SIREN ou sa TVA (pas par son nom) : le motif de
  confiance du champ `fournisseur` est retiré ;
- (A3) chantier reconnu dans le référentiel ;
- (A4) chantier vide retrouvé par la référence de commande.

Une seule fonction, `ajuster_motifs`, appelée par l'extraction d'un bon
(`extraction_bl`) ; la relance d'extraction et la commande de recalcul passent
par ce même chemin. Chaque motif levé est rendu avec sa raison, pour le
journal et l'historique du bon à l'écran.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.extract.verification import Motif, retirer_motifs_confirmes
from app.modules.normalize.fournisseur import MethodeFournisseur

_RAISON_FOURNISSEUR = {
    MethodeFournisseur.SIRET: "Fournisseur confirmé par son SIREN",
    MethodeFournisseur.TVA: "Fournisseur confirmé par son numéro de TVA",
}


@dataclass(frozen=True)
class MotifsAjustes:
    motifs: tuple[Motif, ...]
    # Une entrée par champ dont un motif a été levé : `{"champ", "raison"}`
    # (la raison est la phrase affichée telle quelle dans le journal).
    leves: tuple[dict[str, str], ...]


def ajuster_motifs(
    motifs: Sequence[Motif], *, methode_fournisseur: MethodeFournisseur | None
) -> MotifsAjustes:
    """Motifs restants après confirmation de la lecture par les référentiels,
    et les motifs levés avec leur raison (jamais d'entrée si rien n'a été
    retiré)."""
    restants = tuple(motifs)
    leves: list[dict[str, str]] = []

    raison = (
        _RAISON_FOURNISSEUR.get(methode_fournisseur)
        if methode_fournisseur is not None
        else None
    )
    if raison is not None:
        apres = retirer_motifs_confirmes(restants, frozenset({"fournisseur"}))
        if len(apres) != len(restants):
            leves.append({"champ": "fournisseur", "raison": raison})
        restants = apres

    return MotifsAjustes(motifs=restants, leves=tuple(leves))
