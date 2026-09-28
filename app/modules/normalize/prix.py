"""Calculs purs du contrôle des prix (module pur, phase 3, spec
`docs/superpowers/specs/2026-09-27-prix-design.md` §4).

Trois briques, indépendantes de toute base ou requête réseau :

- la **clé produit** d'une grille (`cle_produit`) et le prix net d'une ligne
  de grille (`prix_net`) ;
- la **correspondance** d'un nom de produit lu sur un bon avec les produits
  d'une grille (`ressemblance_produit`, `trouver_produit`) : la fonction
  `ressemblance` de `texte.py` compare un nom entier à un autre et ne
  distingue pas un nom de grille court (« Cloison 48 ») de ses voisins face
  au nom long imprimé sur le bon (« CLOISON STD KX 48 NF 3M ») -- mesure
  faite sur les vraies paires Point.P (spec §4.3). `ressemblance_produit`
  mesure plutôt la **couverture** des mots du nom le plus court par ceux de
  l'autre ;
- la **comparabilité des unités** de deux prix (`unites_comparables`), qui
  ramène le prix de référence à l'unité du bon quand l'une est le
  conditionnement de l'article et l'autre sa facturation.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .texte import normaliser_libelle, ressemblance
from .unites import normaliser_unite

_QUANTUM_PRIX = Decimal("0.0001")

# Sépare une lettre suivie d'un chiffre ou l'inverse (« 70mm » -> « 70 mm »,
# « d14mm » -> « d 14 mm ») : `normaliser_libelle` a déjà réduit la casse et
# les accents, il ne reste qu'à isoler ces deux types de caractères pour
# comparer des « mots » homogènes (spec §4.3).
_LETTRE_CHIFFRE_RE = re.compile(r"(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])")


def normaliser_reference(reference: str | None) -> str:
    """`normaliser_libelle` puis suppression des espaces : deux références
    écrites différemment (espaces, casse, tirets) mais identiques une fois
    réduites sont le même produit. La conversion d'une référence lue comme
    nombre par Excel (`4000493.0` -> `"4000493"`) est faite en amont, dans
    `extract` (spec §4.1) : ce module ne reçoit que des chaînes."""
    return normaliser_libelle(reference).replace(" ", "")


def cle_produit(reference: str | None, designation: str | None) -> str:
    """Identité d'un produit dans une grille (spec §4.1) : par référence
    normalisée si elle est non vide, sinon par désignation normalisée. Deux
    lignes d'une même grille de même clé sont le même produit."""
    ref_normalisee = normaliser_reference(reference)
    if ref_normalisee:
        return f"ref:{ref_normalisee}"
    return f"nom:{normaliser_libelle(designation)}"


def prix_net(prix_ht: Decimal, remise_pct: Decimal | None) -> Decimal:
    """`prix_ht` si `remise_pct` est absent, sinon `prix_ht * (100 -
    remise_pct) / 100`, arrondi à 4 décimales (`ROUND_HALF_UP`, spec §4.2).
    Refuse (`ValueError`) un `prix_ht` non strictement positif ou une remise
    hors `[0, 100[`."""
    if prix_ht <= 0:
        raise ValueError("le prix doit être supérieur à 0")
    if remise_pct is None:
        net = prix_ht
    else:
        if remise_pct < 0 or remise_pct >= 100:
            raise ValueError("la remise doit être comprise entre 0 et 100 (exclu)")
        net = prix_ht * (Decimal(100) - remise_pct) / Decimal(100)
    return net.quantize(_QUANTUM_PRIX, rounding=ROUND_HALF_UP)


def mots_produit(nom: str | None) -> frozenset[str]:
    """Ensemble des mots d'un nom de produit : `normaliser_libelle`, puis
    séparation des lettres et des chiffres accolés (spec §4.3, point 1)."""
    normalise = normaliser_libelle(nom)
    separe = _LETTRE_CHIFFRE_RE.sub(" ", normalise)
    return frozenset(separe.split())


def _couverture(mots_a: frozenset[str], mots_b: frozenset[str]) -> int:
    """Proportion des mots de `mots_a` présents dans `mots_b`, en entier
    (`⌊100 * |a ∩ b| / |a|⌋`) ; 0 si `mots_a` est vide (spec §4.3, point 2)."""
    if not mots_a:
        return 0
    return (100 * len(mots_a & mots_b)) // len(mots_a)


def ressemblance_produit(a: str | None, b: str | None) -> int:
    """Ressemblance entière 0-100 entre deux noms de produit : le plus grand
    des deux taux de couverture, dans un sens puis dans l'autre (spec §4.3,
    point 3). Pensée pour comparer un nom de grille court à un nom long
    imprimé sur un bon, contrairement à `ressemblance` (`texte.py`, pensée
    pour les chantiers, nom entier contre nom entier)."""
    mots_a, mots_b = mots_produit(a), mots_produit(b)
    return max(_couverture(mots_a, mots_b), _couverture(mots_b, mots_a))


@dataclass(frozen=True)
class ProduitGrille:
    """Un produit tel qu'il figure dans une grille, au prix en vigueur
    considéré (l'appelant -- `ingest/grilles.py` -- choisit la date)."""

    cle: str
    reference: str | None
    designation: str
    unite: str | None
    prix_net: Decimal
    date_effet: date


@dataclass(frozen=True)
class Correspondance:
    """Résultat de `trouver_produit` : `produit` est `None` quand aucun
    produit ne se distingue (égalité non départagée) -- `candidats` porte
    alors les désignations à égalité (3 au plus, spec §4.3)."""

    produit: ProduitGrille | None
    methode: str  # "reference" ou "nom"
    ressemblance: int
    candidats: tuple[str, ...] = field(default_factory=tuple)


def trouver_produit(
    code: str | None,
    designation: str | None,
    produits: Sequence[ProduitGrille],
    seuil: int,
) -> Correspondance | None:
    """Cherche le produit d'une grille correspondant à une ligne de bon
    (spec §4.3) :

    1. si `code` est fourni et qu'un produit de `produits` a la même
       référence normalisée -> correspondance par référence, ressemblance
       100 ;
    2. sinon, score de `ressemblance_produit` de chaque produit sur sa
       désignation ; le meilleur est retenu s'il atteint `seuil` et qu'il
       est seul à ce score -- à égalité, départage par `ressemblance`
       (`texte.py`) ; si l'égalité persiste, aucune correspondance mais les
       désignations à égalité sont rendues (`candidats`, 3 au plus) ;
    3. sous le seuil, ou sans aucun produit -> `None` (aucune information à
       transmettre, contrairement au cas d'égalité).
    """
    ref_normalisee = normaliser_reference(code)
    if ref_normalisee:
        for produit in produits:
            if normaliser_reference(produit.reference) == ref_normalisee:
                return Correspondance(
                    produit=produit, methode="reference", ressemblance=100
                )

    if not produits:
        return None

    scores = [
        (produit, ressemblance_produit(designation, produit.designation))
        for produit in produits
    ]
    meilleur = max(score for _, score in scores)
    if meilleur < seuil:
        return None

    gagnants = [produit for produit, score in scores if score == meilleur]
    if len(gagnants) > 1:
        scores_anciens = [
            (produit, ressemblance(designation, produit.designation))
            for produit in gagnants
        ]
        meilleur_ancien = max(score for _, score in scores_anciens)
        departages = [
            produit for produit, score in scores_anciens if score == meilleur_ancien
        ]
        if len(departages) == 1:
            gagnants = departages
        else:
            candidats = tuple(produit.designation for produit in departages[:3])
            return Correspondance(
                produit=None,
                methode="nom",
                ressemblance=meilleur,
                candidats=candidats,
            )

    return Correspondance(produit=gagnants[0], methode="nom", ressemblance=meilleur)


@dataclass(frozen=True)
class Conversion:
    """Résultat de `unites_comparables` : `facteur` multiplie le prix de
    référence pour le ramener à l'unité du bon (`None` si `possible` est
    faux)."""

    possible: bool
    facteur: Decimal | None = None


_UN = Decimal(1)


def unites_comparables(
    unite_bon: str | None,
    unite_ref: str | None,
    unite_cdt: str | None,
    unite_fact: str | None,
    ratio: Decimal | None,
    ratio_valide: bool,
) -> Conversion:
    """Deux prix (bon, référence) sont-ils comparables, et avec quel
    facteur sur le prix de référence (spec §4.4) ?

    - une unité inconnue ou absente d'un côté (ou des deux) -> comparables,
      facteur 1 : c'est le cas de toute la grille Cedeo, sans unité --
      l'humain juge sur le détail affiché ;
    - mêmes codes normalisés -> comparables, facteur 1 ;
    - l'une est le conditionnement de l'article (`unite_cdt`) et l'autre sa
      facturation (`unite_fact`), avec un ratio strictement positif et
      validé -> facteur `ratio` ou `1 / ratio` selon le sens ;
    - sinon -> non comparables."""
    unite_bon_n = normaliser_unite(unite_bon)
    unite_ref_n = normaliser_unite(unite_ref)

    if unite_bon_n is None or unite_ref_n is None:
        return Conversion(possible=True, facteur=Decimal("1"))

    if unite_bon_n.code == unite_ref_n.code:
        return Conversion(possible=True, facteur=Decimal("1"))

    if ratio is not None and ratio > 0 and ratio_valide:
        unite_cdt_n = normaliser_unite(unite_cdt)
        unite_fact_n = normaliser_unite(unite_fact)
        if unite_cdt_n is not None and unite_fact_n is not None:
            bon_est_cdt = unite_bon_n.code == unite_cdt_n.code
            ref_est_fact = unite_ref_n.code == unite_fact_n.code
            bon_est_fact = unite_bon_n.code == unite_fact_n.code
            ref_est_cdt = unite_ref_n.code == unite_cdt_n.code
            if bon_est_cdt and ref_est_fact:
                return Conversion(possible=True, facteur=ratio)
            if bon_est_fact and ref_est_cdt:
                return Conversion(possible=True, facteur=_UN / ratio)

    return Conversion(possible=False)
