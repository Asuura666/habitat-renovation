"""Aides communes aux règles de prix des bons (R19 à R25, phase 3, spec
`docs/superpowers/specs/2026-09-27-prix-design.md` §5.2) : module pur,
préfixé `_` (comme `_evaluer_prix` dans `engine.py`) pour marquer qu'il
n'est pas un point d'entrée du moteur, seulement partagé entre R19, R20,
R21 et R25."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

TIRET = "—"  # tiret cadratin — valeur manquante dans un detail (décision du contrôleur)

# Arrondi de l'écart de prix (spec §5.2 : « arrondi à 0,1 »), contrairement
# à R07/R08 (`ecart_prix_pct`, arrondi à 0,01 et toujours positif) : ici
# l'écart est **signé** -- positif pour une hausse (R19/R20), négatif pour
# une baisse (R21) -- jamais une valeur absolue.
_QUANTUM_ECART_PRIX_BL = Decimal("0.1")


def ecart_pct(prix_bon: Decimal, reference: Decimal) -> Decimal:
    """Écart signé entre `prix_bon` et `reference`, en pourcentage, arrondi
    à 0,1 (`ROUND_HALF_UP`, spec §5.2) : `(prix_bon - reference) /
    reference * 100`. Positif si le bon est plus cher, négatif s'il est
    moins cher -- le signe distingue une hausse (R19/R20) d'une baisse
    (R21), à l'inverse de `rules.rules.R07.ecart_prix_pct` (toujours en
    valeur absolue)."""
    ecart = (prix_bon - reference) / reference * 100
    return ecart.quantize(_QUANTUM_ECART_PRIX_BL, rounding=ROUND_HALF_UP)


def candidats_ou_tiret(candidats: tuple[str, ...]) -> str:
    """`candidats` joints par « / » (même forme que R18), ou le tiret
    cadratin si aucun (spec §5.2, R22 : « — » si aucun)."""
    return " / ".join(candidats) if candidats else TIRET


def mois_ecoules(depuis: date, jusqu_a: date) -> int:
    """Nombre de mois pleins écoulés entre deux dates (matière de R25, spec
    §5.2 : « calcul des mois exact, fin de mois »). Différence naïve en
    mois de calendrier, corrigée d'un mois quand `jusqu_a` tombe un jour du
    mois strictement antérieur à celui de `depuis` (ex. grille du 31/01,
    aujourd'hui le 28/02 : le mois n'est pas encore plein, contrairement à
    un simple compte de mois calendaires) -- même idiome que les
    bibliothèques usuelles de différence de dates en mois, réimplémenté ici
    pour ne pas ajouter de dépendance à un module pur."""
    mois = (jusqu_a.year - depuis.year) * 12 + (jusqu_a.month - depuis.month)
    if jusqu_a.day < depuis.day:
        mois -= 1
    return mois
