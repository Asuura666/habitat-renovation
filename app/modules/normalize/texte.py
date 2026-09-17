"""Normalisation de libellés texte (module pur).

`normaliser_libelle` est le socle commun du paquet : clé d'alias chantier
(L3-D6), comparaison des mots d'un nom de fournisseur ou d'agence (L3-D8),
comparaison d'unité (`unites.py`). Elle ne devine rien : elle ne fait que
réduire une chaîne à une forme canonique comparable (accents, casse,
ponctuation), sans jamais interpréter son contenu.
"""

from __future__ import annotations

import unicodedata


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
