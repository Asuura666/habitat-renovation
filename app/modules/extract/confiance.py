"""Confiance d'une valeur extraite, à partir des scores OCR Mistral par mot
(module PUR, L3-T1).

Contexte (constat 3, plan lot 3) : avec `confidence_scores_granularity:
"word"`, l'API Mistral OCR renvoie, par page, `confidence_scores` (texte de
`page["markdown"]`) et, pour chaque tableau détecté, ses propres
`word_confidence_scores` (texte de `table["content"]`). `document_annotation`
(lu par `extract/bl.py`, L3-T2) est produit par un modèle de langage : il
peut inventer ou reformuler une valeur. Ce module ne fait aucune hypothèse
sur la mise en page ; il détecte les valeurs inventées en vérifiant qu'elles
se retrouvent, telles quelles, dans le texte déjà OCRisé (L3-D2).

Algorithme (L3-D2) : on cherche la valeur brute dans chaque source de texte
indexée (page + tableaux), bornée par des caractères non alphanumériques,
insensible à la casse, espaces souples entre les jetons de la valeur ; pour
chaque occurrence, on prend le minimum des confiances des mots qui la
recouvrent (un mot ne comptant que s'il chevauche l'occurrence) ; le
résultat final est le maximum sur toutes les occurrences retenues. Une
valeur introuvable (aucune occurrence n'a de mot recouvrant) vaut confiance
**0** : l'annotation a inventé ou reformulé la valeur. Aucun score
disponible du tout (`IndexConfiance.disponible` faux) -> `None` : on ne peut
tout simplement pas juger.

Aucune dépendance d'infrastructure (`fastapi`, `sqlalchemy`, `httpx`),
aucun log, aucun appel réseau (R17) : ce module prend un `dict` JSON déjà
obtenu de l'API Mistral OCR.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# --------------------------------------------------------------------------
# Index des scores de confiance par mot
# --------------------------------------------------------------------------

_QUANTUM_CONFIANCE = Decimal("0.0001")


@dataclass(frozen=True)
class Mot:
    """Un mot indexé dans une source de texte, avec sa confiance OCR.

    `debut`/`fin` sont les index (le second exclusif) du mot dans le texte
    de la `Source` qui le contient — jamais un texte global reconstitué :
    chaque page et chaque tableau a ses propres index (constat 3).
    """

    debut: int
    fin: int
    confiance: Decimal


@dataclass(frozen=True)
class Source:
    """Un texte OCRisé (markdown de page ou contenu d'un tableau) et les
    mots dont la confiance est connue à l'intérieur de ce texte."""

    texte: str
    mots: tuple[Mot, ...]


@dataclass(frozen=True)
class IndexConfiance:
    """Toutes les sources de texte d'une réponse OCR, avec leurs mots."""

    sources: tuple[Source, ...]

    @property
    def disponible(self) -> bool:
        """Faux si aucune source n'a le moindre mot scoré (réponse sans
        `confidence_scores_granularity: "word"`, ou réponse fabriquée par un
        test synthétique qui n'en a pas besoin)."""
        return any(source.mots for source in self.sources)


def _decimal_confiance(valeur_brute: Any) -> Decimal | None:
    """Convertit une confiance brute (nombre JSON) en `Decimal` arrondi à 4
    décimales (`ROUND_HALF_UP`). `None` si le type est inattendu — un
    booléen est un `int` en Python, jamais une confiance valide — ou si le
    nombre n'est pas fini : `json.loads` accepte `NaN`/`Infinity`/
    `-Infinity` par défaut, et `Decimal("inf").quantize(...)` lève
    `InvalidOperation` (une réponse OCR corrompue doit être ignorée, jamais
    faire planter l'extraction)."""
    if isinstance(valeur_brute, bool) or not isinstance(valeur_brute, int | float):
        return None
    if not math.isfinite(valeur_brute):
        return None
    return Decimal(str(valeur_brute)).quantize(
        _QUANTUM_CONFIANCE, rounding=ROUND_HALF_UP
    )


def _mot_depuis_entree(entree: Any, texte: str) -> Mot | None:
    """Une entrée `word_confidence_scores` -> `Mot`, `None` si mal formée
    (type inattendu, index hors texte) — jamais d'exception levée."""
    if not isinstance(entree, dict):
        return None
    texte_mot = entree.get("text")
    debut = entree.get("start_index")
    confiance = _decimal_confiance(entree.get("confidence"))
    if not isinstance(texte_mot, str) or confiance is None:
        return None
    if isinstance(debut, bool) or not isinstance(debut, int):
        return None
    fin = debut + len(texte_mot)
    if debut < 0 or fin > len(texte):
        return None
    return Mot(debut=debut, fin=fin, confiance=confiance)


def _mots_depuis_scores(scores: Any, texte: str) -> tuple[Mot, ...]:
    if not isinstance(scores, list):
        return ()
    mots: list[Mot] = []
    for entree in scores:
        mot = _mot_depuis_entree(entree, texte)
        if mot is not None:
            mots.append(mot)
    return tuple(mots)


def indexer_confiance(reponse: dict[str, Any]) -> IndexConfiance:
    """Index des scores de confiance d'une réponse OCR Mistral (L3-D2).

    Une source par page (`page["markdown"]`, mots dans
    `page["confidence_scores"]["word_confidence_scores"]`), puis une source
    par tableau de la page (`table["content"]`, mots dans
    `table["word_confidence_scores"]`, directement — pas sous
    `confidence_scores`, contrairement à la page). Réponse sans `pages` ->
    index vide.
    """
    pages = reponse.get("pages")
    if not isinstance(pages, list):
        return IndexConfiance(sources=())

    sources: list[Source] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        texte_page = str(page.get("markdown") or "")
        scores_page = page.get("confidence_scores")
        mots_page = (
            _mots_depuis_scores(scores_page.get("word_confidence_scores"), texte_page)
            if isinstance(scores_page, dict)
            else ()
        )
        sources.append(Source(texte=texte_page, mots=mots_page))

        tables = page.get("tables")
        if isinstance(tables, list):
            for table in tables:
                if not isinstance(table, dict):
                    continue
                texte_table = str(table.get("content") or "")
                mots_table = _mots_depuis_scores(
                    table.get("word_confidence_scores"), texte_table
                )
                sources.append(Source(texte=texte_table, mots=mots_table))

    return IndexConfiance(sources=tuple(sources))


# --------------------------------------------------------------------------
# Recherche d'une valeur dans une source de texte
# --------------------------------------------------------------------------

# Une valeur qui ressemble à un nombre français ou anglais : chiffres et
# espaces (milliers), un seul séparateur décimal optionnel (« , » ou « . »).
_NOMBRE_RE = re.compile(r"^-?[\d\s]+(?:[.,]\d+)?$")


def _variantes(valeur: str) -> list[str]:
    """Variante de `valeur` avec l'autre séparateur décimal, si elle
    ressemble à un nombre (L3-D2) : l'annotation peut rendre un nombre avec
    un séparateur différent de celui imprimé sur le document (ex. « 126.00 »
    annoté pour « 126,00 » imprimé)."""
    if _NOMBRE_RE.match(valeur) is None:
        return [valeur]
    if "," in valeur:
        variante = valeur.replace(",", ".")
    elif "." in valeur:
        variante = valeur.replace(".", ",")
    else:
        return [valeur]
    return [valeur, variante]


def _motif_valeur(valeur: str) -> re.Pattern[str]:
    """Motif de recherche de `valeur` : jetons échappés joints par `\\s+`
    (espaces souples), bornés par des caractères non alphanumériques pour
    qu'un jeton isolé ne soit jamais confondu avec une partie d'un autre mot
    (ex. « 4 » ne doit matcher ni dans « 24,50 » ni dans « 4X5 »)."""
    jetons = valeur.split()
    corps = r"\s+".join(re.escape(jeton) for jeton in jetons)
    return re.compile(rf"(?<!\w){corps}(?!\w)", re.IGNORECASE)


def _confiance_dans_segment(
    mots: tuple[Mot, ...], decalage: int, segment: str, valeur: str
) -> Decimal | None:
    """Meilleure confiance de `valeur` dans `segment`, un texte situé à
    l'offset `decalage` dans le texte que `mots` indexe. `None` si aucune
    occurrence n'a de mot recouvrant (occurrence sans mot recouvrant
    ignorée, L3-D2)."""
    meilleure: Decimal | None = None
    for candidate in _variantes(valeur):
        for correspondance in _motif_valeur(candidate).finditer(segment):
            debut = decalage + correspondance.start()
            fin = decalage + correspondance.end()
            couvrants = [m.confiance for m in mots if m.debut < fin and m.fin > debut]
            if not couvrants:
                continue
            confiance = min(couvrants)
            if meilleure is None or confiance > meilleure:
                meilleure = confiance
    return meilleure


def confiance_valeur(index: IndexConfiance, valeur: str | None) -> Decimal | None:
    """Confiance d'une valeur isolée (en-tête d'un document) dans tout
    l'index (L3-D2). `None` si `valeur` est vide/`None` ou si l'index n'a
    aucun score ; `0` si la valeur est introuvable ; sinon le maximum sur
    toutes les occurrences trouvées dans toutes les sources."""
    if valeur is None or not valeur.strip():
        return None
    if not index.disponible:
        return None

    meilleure: Decimal | None = None
    for source in index.sources:
        confiance = _confiance_dans_segment(source.mots, 0, source.texte, valeur)
        if confiance is not None and (meilleure is None or confiance > meilleure):
            meilleure = confiance
    return meilleure if meilleure is not None else Decimal("0")


# --------------------------------------------------------------------------
# Confiance des valeurs d'une même ligne d'articles
# --------------------------------------------------------------------------


def _decouper_lignes(texte: str) -> list[tuple[int, str]]:
    """Lignes de `texte` (coupées sur `\\n`) avec leur offset d'origine."""
    lignes: list[tuple[int, str]] = []
    decalage = 0
    for segment in texte.split("\n"):
        lignes.append((decalage, segment))
        decalage += len(segment) + 1
    return lignes


@dataclass
class _CandidatLigne:
    nb_trouvees: int
    min_confiance: Decimal
    confiances: dict[int, Decimal]


def _evaluer_ligne(
    source: Source, decalage: int, segment: str, a_chercher: list[tuple[int, str]]
) -> _CandidatLigne:
    """Confiance de chaque valeur de `a_chercher` (index d'origine, valeur),
    cherchée uniquement dans `segment` (une ligne d'une source)."""
    confiances: dict[int, Decimal] = {}
    for i, valeur in a_chercher:
        confiance = _confiance_dans_segment(source.mots, decalage, segment, valeur)
        confiances[i] = confiance if confiance is not None else Decimal("0")
    trouvees = [c for c in confiances.values() if c > 0]
    return _CandidatLigne(
        nb_trouvees=len(trouvees),
        min_confiance=min(trouvees) if trouvees else Decimal("0"),
        confiances=confiances,
    )


def confiances_ligne(
    index: IndexConfiance, valeurs: Sequence[str | None]
) -> tuple[Decimal | None, ...]:
    """Confiance de chaque valeur d'une même ligne d'articles, cherchées
    ensemble dans **une seule** ligne source (L3-D2) : la ligne qui contient
    le plus de valeurs non nulles (à égalité : le meilleur minimum de
    confiance parmi les valeurs trouvées, puis la première rencontrée).
    Chaque valeur non nulle absente de la ligne retenue vaut `0` ; une
    valeur nulle vaut toujours `None`. Si aucune ligne ne contient aucune
    valeur, `0` pour chaque valeur non nulle. `None` partout si l'index n'a
    aucun score.
    """
    if not index.disponible:
        return tuple(None for _ in valeurs)

    a_chercher: list[tuple[int, str]] = [
        (i, v) for i, v in enumerate(valeurs) if v is not None and v.strip()
    ]
    if not a_chercher:
        return tuple(None for _ in valeurs)

    meilleure: _CandidatLigne | None = None
    for source in index.sources:
        for decalage, segment in _decouper_lignes(source.texte):
            candidat = _evaluer_ligne(source, decalage, segment, a_chercher)
            if candidat.nb_trouvees == 0:
                continue
            if meilleure is None or (candidat.nb_trouvees, candidat.min_confiance) > (
                meilleure.nb_trouvees,
                meilleure.min_confiance,
            ):
                meilleure = candidat

    resultats: list[Decimal | None] = []
    for i, v in enumerate(valeurs):
        if v is None or not v.strip():
            resultats.append(None)
        elif meilleure is None:
            resultats.append(Decimal("0"))
        else:
            resultats.append(meilleure.confiances.get(i, Decimal("0")))
    return tuple(resultats)


# --------------------------------------------------------------------------
# Confiance globale d'une page (facture, L3-D16)
# --------------------------------------------------------------------------


def confiance_min_pages(reponse: dict[str, Any]) -> Decimal | None:
    """Plus petit `minimum_page_confidence_score` des pages qui en ont un,
    `None` sinon (réponse sans `pages`, sans scores, ou types inattendus)."""
    pages = reponse.get("pages")
    if not isinstance(pages, list):
        return None

    minimums: list[Decimal] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        scores = page.get("confidence_scores")
        if not isinstance(scores, dict):
            continue
        minimum = _decimal_confiance(scores.get("minimum_page_confidence_score"))
        if minimum is not None:
            minimums.append(minimum)
    return min(minimums) if minimums else None
