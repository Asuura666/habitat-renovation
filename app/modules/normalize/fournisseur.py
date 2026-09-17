"""Résolution fournisseur et agence (module pur, L3-D8).

Un fournisseur est résolu par SIREN (9 premiers chiffres du SIRET lu), puis
par numéro de TVA, puis par nom : la première étape qui désigne un
**résultat unique** conclut, une étape ambiguë passe à la suivante. « Résultat
unique » se lit sur le fournisseur (`FournisseurRef.id`), pas sur le nombre
de références qui correspondent : un même fournisseur peut apparaître sous
plusieurs `FournisseurRef` (une par agence ayant son propre SIRET) sans que
cela rende l'étape SIRET ambiguë (cf. tests). Aucun fournisseur n'est jamais
créé automatiquement (Q7, L3-D8) : le référentiel est alimenté par la CLI
`fournisseur-definir`, ce module ne fait que le consulter.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .texte import normaliser_libelle

_TVA_RE = re.compile(r"^[A-Z]{2}[0-9A-Z]{2,13}$")


def normaliser_siret(brut: str | None) -> str | None:
    """Chiffres seuls ; 14 (SIRET) ou 9 (SIREN) chiffres, sinon `None`."""
    if brut is None:
        return None
    chiffres = "".join(c for c in brut if c.isdigit())
    return chiffres if len(chiffres) in (9, 14) else None


def normaliser_tva(brut: str | None) -> str | None:
    """Majuscules sans espaces ni points ; `^[A-Z]{2}[0-9A-Z]{2,13}$` sinon
    `None`."""
    if brut is None:
        return None
    nettoye = brut.upper().replace(" ", "").replace(".", "")
    return nettoye if _TVA_RE.match(nettoye) else None


class MethodeFournisseur(StrEnum):
    SIRET = "siret"
    TVA = "tva"
    NOM = "nom"


@dataclass(frozen=True)
class FournisseurRef:
    id: uuid.UUID
    nom: str
    siret: str | None
    tva: str | None
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class ResolutionFournisseur:
    fournisseur_id: uuid.UUID | None
    methode: MethodeFournisseur | None


@dataclass(frozen=True)
class AgenceRef:
    id: uuid.UUID
    nom: str


def _correspond_par_nom(ref: FournisseurRef, mots_lus: set[str]) -> bool:
    """Le nom ou l'un des alias de `ref` a un ensemble non vide de mots
    normalisés entièrement inclus dans `mots_lus`."""
    for candidat in (ref.nom, *ref.aliases):
        mots_candidat = set(normaliser_libelle(candidat).split())
        if mots_candidat and mots_candidat.issubset(mots_lus):
            return True
    return False


def resoudre_fournisseur(
    *,
    siret: str | None,
    tva: str | None,
    nom: str | None,
    referentiel: Sequence[FournisseurRef],
) -> ResolutionFournisseur:
    siret_normalise = normaliser_siret(siret)
    if siret_normalise is not None:
        siren = siret_normalise[:9]
        ids_siret = {
            ref.id
            for ref in referentiel
            if (siret_ref := normaliser_siret(ref.siret)) is not None
            and siret_ref.startswith(siren)
        }
        if len(ids_siret) == 1:
            return ResolutionFournisseur(
                next(iter(ids_siret)), MethodeFournisseur.SIRET
            )

    tva_normalisee = normaliser_tva(tva)
    if tva_normalisee is not None:
        ids_tva = {
            ref.id for ref in referentiel if normaliser_tva(ref.tva) == tva_normalisee
        }
        if len(ids_tva) == 1:
            return ResolutionFournisseur(next(iter(ids_tva)), MethodeFournisseur.TVA)

    mots_lus = set(normaliser_libelle(nom).split())
    if mots_lus:
        ids_nom = {ref.id for ref in referentiel if _correspond_par_nom(ref, mots_lus)}
        if len(ids_nom) == 1:
            return ResolutionFournisseur(next(iter(ids_nom)), MethodeFournisseur.NOM)

    return ResolutionFournisseur(None, None)


def resoudre_agence(brut: str | None, agences: Sequence[AgenceRef]) -> uuid.UUID | None:
    """Agence dont les mots normalisés (non vides) sont tous inclus dans les
    mots du brut lu ; résolution exigée unique, jamais créée (L3-D8)."""
    mots_bruts = set(normaliser_libelle(brut).split())
    correspondances = [
        agence.id
        for agence in agences
        if (mots_agence := set(normaliser_libelle(agence.nom).split()))
        and mots_agence.issubset(mots_bruts)
    ]
    return correspondances[0] if len(correspondances) == 1 else None
