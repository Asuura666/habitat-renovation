"""Normalisation de libellés texte (module pur).

`normaliser_libelle` est le socle commun du paquet : clé d'alias chantier
(L3-D6), comparaison des mots d'un nom de fournisseur ou d'agence (L3-D8),
comparaison d'unité (`unites.py`). Elle ne devine rien : elle ne fait que
réduire une chaîne à une forme canonique comparable (accents, casse,
ponctuation), sans jamais interpréter son contenu.

`ressemblance` (décision d'Ilane du 27/09/2026, spec §2.2) mesure à quel
point deux libellés se ressemblent, 0 à 100, insensible à la casse, aux
accents, à la ponctuation et à l'ordre des mots. Générique : le socle commun
l'utilise pour rapprocher un nom de chantier lu d'un chantier existant
(`normalize/chantier.py`) et la phase 3 la réutilisera telle quelle pour la
ressemblance des désignations de produits (page Prix).
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


def normaliser_libelle(texte: str | None) -> str:
    """NFKD sans diacritiques, casefold, tout non-alphanumérique -> espace,
    espaces réduits, strip. `None` -> chaîne vide.

    Le retrait des diacritiques passe par une décomposition canonique de
    compatibilité (NFKD) suivie du retrait des caractères combinants : elle
    gère à la fois les accents (« é » -> « e ») et les caractères de
    compatibilité comme les chiffres en exposant (« m² » -> « m2 »).
    """
    if texte is None:
        return ""
    decompose = unicodedata.normalize("NFKD", texte)
    sans_diacritiques = "".join(c for c in decompose if not unicodedata.combining(c))
    minuscules = sans_diacritiques.casefold()
    caracteres = (c if c.isalnum() else " " for c in minuscules)
    return " ".join("".join(caracteres).split())


def _forme_triee(texte: str | None) -> str:
    """Forme normalisée dont les mots sont triés : rend la comparaison
    insensible à l'ordre des mots (« Tilleuls résidence » ~ « Résidence
    Tilleuls »)."""
    return " ".join(sorted(normaliser_libelle(texte).split()))


def ressemblance(a: str | None, b: str | None) -> int:
    """Ressemblance entière 0-100 entre deux noms, insensible à la casse, aux
    accents, à la ponctuation et à l'ordre des mots (mots triés puis
    `SequenceMatcher`). Calcul exact en entiers (200 * M // T) : jamais un
    arrondi flottant qui ferait basculer un score pile au seuil."""
    fa, fb = _forme_triee(a), _forme_triee(b)
    if not fa or not fb:
        return 0
    appariement = SequenceMatcher(None, fa, fb, autojunk=False)
    communs = sum(bloc.size for bloc in appariement.get_matching_blocks())
    return (200 * communs) // (len(fa) + len(fb))


_NOMBRE_RE = re.compile(r"\d+")


def _nombres(texte: str | None) -> list[str]:
    """Nombres du libellé normalisé (suites de chiffres, zéros de tête
    ignorés : « 03 » = « 3 »), triés : l'ordre ne compte pas."""
    return sorted(
        (m.lstrip("0") or "0") for m in _NOMBRE_RE.findall(normaliser_libelle(texte))
    )


def nombres_differents(a: str | None, b: str | None) -> bool:
    """Vrai si les deux libellés ne portent pas les mêmes nombres (« Lot 12 »
    / « Lot 13 », « Les Pins » / « Les Pins 2 »). Une ressemblance élevée ne
    prouve pas qu'il s'agit du même chantier quand seul un numéro change
    (B-05, décision d'Ilane du 29/09/2026) : le rattachement automatique
    s'en sert pour refuser de rattacher d'office."""
    return _nombres(a) != _nombres(b)
