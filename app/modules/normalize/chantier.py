"""Décomposition du libellé chantier fournisseur (module pur, L3-D6).

La clé d'alias chantier est `(fournisseur_id, libellé normalisé)` : le code
chantier fournisseur ne peut pas être une clé, il change d'une commande à
l'autre (constat 6, CDC §4.4). `decomposer_chantier` isole ce code s'il
existe (un groupe final entre parenthèses) sans qu'il participe à la clé, et
normalise le reste via `normaliser_libelle`. Le libellé brut complet, lui,
reste stocké tel quel par l'appelant (`document.chantier_brut`).

Exemple public du CDC (§4.4, donnée publique, jamais une donnée client) :
« ORMEAUX (9944126862) » -> `LibelleChantier(libelle="ormeaux",
code="9944126862")`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .texte import normaliser_libelle

_PREFIXE_CHANTIER_RE = re.compile(r"^\s*chantier\s*:?\s*", re.IGNORECASE)
_CODE_FINAL_RE = re.compile(r"\(\s*([A-Za-z0-9-]+)\s*\)\s*$")


@dataclass(frozen=True)
class LibelleChantier:
    libelle: str
    code: str | None


def decomposer_chantier(brut: str | None) -> LibelleChantier | None:
    if brut is None:
        return None
    sans_prefixe = _PREFIXE_CHANTIER_RE.sub("", brut)

    code: str | None = None
    reste = sans_prefixe
    correspondance_code = _CODE_FINAL_RE.search(sans_prefixe)
    if correspondance_code is not None:
        code = correspondance_code.group(1)
        reste = sans_prefixe[: correspondance_code.start()]

    libelle = normaliser_libelle(reste)
    if not libelle:
        return None
    return LibelleChantier(libelle=libelle, code=code)
