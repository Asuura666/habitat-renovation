"""Utilitaires génériques de lecture d'une réponse OCR Mistral (module PUR).

Ce fichier ne connaît **aucun** fournisseur en particulier (CDC §13 : un
parseur par fournisseur) : il ne fait que restituer le texte d'une réponse
OCR et fournir des briques réutilisables de lecture de tableau markdown et
de nombres français. Le parseur Unikalo (`unikalo.py`) s'appuie dessus.

Aucune dépendance d'infrastructure (`fastapi`, `sqlalchemy`, `httpx`),
aucun log : ce module prend un `dict` JSON déjà obtenu de l'API Mistral OCR
et ne fait lui-même aucun appel réseau (R17).

Forme observée de la réponse (`table_format: "markdown"`) :
- `reponse["pages"]` : une entrée par page, avec un champ `markdown` (texte
  hors tableaux), un champ `tables` (liste de `{"format": "markdown",
  "content": "..."}`) et, quand l'OCR l'a détecté, un champ `blocks` (liste
  ordonnée de blocs `{"type": ..., "content": ...}` couvrant toute la page,
  tableaux compris).
- Point important : `page["markdown"]` ne contient PAS le texte des
  tableaux, seulement un lien (`[Tableau](tbl-0.md)`) vers eux. Reconstruire
  le texte complet d'une page exige donc `page["blocks"]` — `texte_ocr`
  s'appuie dessus quand il est présent et non vide, et se rabat sur
  `markdown` sinon (cas des réponses fabriquées par les tests synthétiques,
  qui n'ont pas besoin de ce niveau de détail).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

# Un nombre français avec espaces de milliers (espace normal, insécable ou
# fine insécable) et virgule décimale : « 12 345,67 », « 1,234 », « -5,00 ».
_NOMBRE_DECIMAL_RE = re.compile(r"-?\d{1,3}(?:[\s\u202f\xa0]\d{3})*,\d+")


def decimal_fr(texte: str) -> Decimal | None:
    """Convertit un nombre français (espaces de milliers, virgule) en `Decimal`.

    `None` si la cellule est vide ou n'est pas un nombre reconnaissable
    (jamais de `float` intermédiaire).
    """
    brut = texte.strip()
    if not brut:
        return None
    for espace in ("\u202f", "\xa0", " "):
        brut = brut.replace(espace, "")
    brut = brut.replace(",", ".")
    try:
        return Decimal(brut)
    except InvalidOperation:
        return None


def pourcentage_fr(texte: str) -> Decimal | None:
    """Extrait un pourcentage français (ex. « (20%) », « 100% ») en `Decimal`."""
    correspondance = re.search(r"(-?\d[\d.,]*)\s*%", texte)
    if correspondance is None:
        return None
    return decimal_fr(correspondance.group(1))


def date_fr(texte: str) -> date | None:
    """Convertit une date `JJ/MM/AAAA` en `date`, `None` si mal formée."""
    morceaux = texte.strip().split("/")
    if len(morceaux) != 3:
        return None
    jour_s, mois_s, annee_s = morceaux
    try:
        return date(int(annee_s), int(mois_s), int(jour_s))
    except ValueError:
        return None


def _texte_page(page: dict[str, Any]) -> str:
    """Texte complet d'une page : blocs OCR concaténés dans l'ordre de lecture.

    `page["blocks"]` couvre toute la page (en-têtes, titres, texte, tableaux)
    et restitue donc le texte des tableaux, contrairement à `page["markdown"]`
    qui ne fait que les référencer par un lien. On se rabat sur `markdown`
    seulement quand `blocks` est absent ou vide (réponses synthétiques des
    tests, qui n'ont pas besoin de ce niveau de détail).
    """
    blocs = page.get("blocks")
    if isinstance(blocs, list) and blocs:
        segments = [
            str(bloc.get("content") or "") for bloc in blocs if isinstance(bloc, dict)
        ]
        if any(segment.strip() for segment in segments):
            return "\n".join(segments)
    return str(page.get("markdown") or "")


def texte_ocr(reponse: dict[str, Any]) -> str:
    """Texte complet de la réponse OCR, une page après l'autre, séparées par « \\n »."""
    pages = reponse.get("pages")
    if not isinstance(pages, list):
        return ""
    return "\n".join(_texte_page(page) for page in pages if isinstance(page, dict))


# --------------------------------------------------------------------------
# Détection du numéro de BL sur une photo (T6b, OCR Mistral minimal)
#
# Contrairement à une facture (couche texte structurée en tableaux),
# une photo de BL n'a que du texte libre : `detecter_numero_bl` prend le
# texte déjà obtenu via `texte_ocr` (jamais la réponse OCR brute) et cherche
# le motif « <mot-clé> N° <numéro> » écrit en haut du document (Q5 du brief,
# option a). Aucun appel réseau, aucun log ici (module PUR, R17).
#
# Formats réels observés (valeurs à NE PAS recopier, décision du contrôleur
# T6b) : Unikalo imprime « LIVRAISON N°L » suivi de 12 chiffres (le préfixe
# « L » fait partie du numéro) ; Point.P imprime « Bon d'enlèvement N° »
# suivi de 10 chiffres, sans préfixe. Les tests n'utilisent que des numéros
# inventés de même forme (ex. « L209900000123 », « 9900001234 »).
#
# Tolérance OCR : « N° » est régulièrement mal lu (« N °», « No », « N0 »),
# avec ou sans espace avant le numéro ; la casse et l'accent d'« enlèvement »
# (rendu parfois « enlevement ») sont ignorés. Deux numéros distincts trouvés
# dans le texte -> ambigu, jamais deviné : `None` (le document part en
# `a_verifier`, décision du contrôleur T6b sur `traiter_fichier`).
# --------------------------------------------------------------------------


class TypeBL(StrEnum):
    """Nature du bon détecté sur la photo."""

    LIVRAISON = "bl"
    ENLEVEMENT = "enlevement"


@dataclass(frozen=True)
class NumeroBL:
    """Numéro de BL détecté, normalisé (sans espace, préfixe `L` en
    majuscule pour Unikalo)."""

    numero: str
    type_bl: TypeBL


# "N°" mal lu : "N°", "N °", "No", "N0", avec espaces tolérés de part et
# d'autre du symbole (mais le symbole lui-même — un de ces quatre — reste
# obligatoire, pour ne pas confondre un "N" isolé ailleurs dans le texte
# avec ce motif).
_N_DEGRE_RE = r"N\s*(?:°|[oO]|0)\s*"

_MOTIF_LIVRAISON_RE = re.compile(
    rf"LIVRAISON\s+{_N_DEGRE_RE}(?P<numero>L\d+)", re.IGNORECASE
)
_MOTIF_ENLEVEMENT_RE = re.compile(
    rf"ENL[EÈÉ]VEMENT\s+{_N_DEGRE_RE}(?P<numero>\d+)", re.IGNORECASE
)


def detecter_numero_bl(texte_ocr: str) -> NumeroBL | None:
    """Détecte le numéro de BL dans le texte OCR d'une photo.

    `None` si aucun motif reconnu, ou si plusieurs numéros distincts sont
    trouvés (ambigu : ne jamais deviner lequel est le bon). Le même numéro
    répété plusieurs fois n'est pas ambigu.
    """
    candidats: dict[str, TypeBL] = {}
    for correspondance in _MOTIF_LIVRAISON_RE.finditer(texte_ocr):
        numero = correspondance.group("numero").upper()
        candidats.setdefault(numero, TypeBL.LIVRAISON)
    for correspondance in _MOTIF_ENLEVEMENT_RE.finditer(texte_ocr):
        numero = correspondance.group("numero")
        candidats.setdefault(numero, TypeBL.ENLEVEMENT)

    if len(candidats) != 1:
        return None
    numero, type_bl = next(iter(candidats.items()))
    return NumeroBL(numero=numero, type_bl=type_bl)


def decouper_ligne_tableau(ligne: str) -> list[str] | None:
    """Cellules d'une ligne de tableau markdown (`| a | b |` -> `["a", "b"]`).

    `None` si la ligne ne ressemble pas à une ligne de tableau.
    """
    brut = ligne.strip()
    if not brut.startswith("|"):
        return None
    brut = brut.strip("|")
    return [cellule.strip() for cellule in brut.split("|")]


def est_separateur(cellules: list[str]) -> bool:
    """Ligne `| --- | --- |` (séparateur d'en-tête markdown)."""
    non_vides = [c for c in cellules if c]
    return bool(non_vides) and all(set(c) <= {"-"} for c in non_vides)


def tables_de_page(page: dict[str, Any]) -> list[str]:
    """Contenu markdown de chaque tableau détecté sur une page."""
    tables = page.get("tables")
    if not isinstance(tables, list):
        return []
    return [
        str(table.get("content") or "") for table in tables if isinstance(table, dict)
    ]


def est_ligne_empilee(valeurs: list[str]) -> bool:
    """Au moins une valeur porte deux nombres décimaux à virgule distincts.

    Signal d'une fusion OCR de deux lignes source dans une même ligne de
    tableau. Signal volontairement strict : un simple découpage sur
    l'espace confondrait un séparateur de milliers français
    (« 12 345,67 », un seul nombre) avec deux valeurs empilées.
    """
    return any(len(_NOMBRE_DECIMAL_RE.findall(v)) >= 2 for v in valeurs)


def diviser_valeurs_empilees(valeurs: list[str]) -> list[list[str]]:
    """Sépare les valeurs empilées d'une ligne fusionnée par l'OCR.

    Chaque valeur est découpée sur les espaces. Quand une valeur n'a pas
    autant de jetons que les autres, son unique jeton (ou une valeur vide,
    si elle n'en a aucun) est **dupliqué à l'identique** sur toutes les
    lignes issues de la division, faute de pouvoir le répartir entre elles
    (voir `docs/dette.md`, l'attribution par ligne n'est alors pas exacte).
    """
    decoupees = [v.split() for v in valeurs]
    largeur = max((len(d) for d in decoupees), default=1) or 1
    return [
        [
            decoupee[i] if i < len(decoupee) else (decoupee[-1] if decoupee else "")
            for decoupee in decoupees
        ]
        for i in range(largeur)
    ]
