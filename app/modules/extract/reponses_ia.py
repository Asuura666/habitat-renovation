"""Lecture et gardes des réponses de l'IA (OpenCode), module PUR (T2, phase 4).

L'IA extrait et normalise, elle ne décide jamais (CLAUDE.md) : toute réponse
structurée renvoyée par OpenCode passe par une fonction `lire_...` de ce
module avant d'être enregistrée. Une réponse hors contrat (type inattendu,
champ manquant, texte vide ou trop long) est refusée via
`ReponseIAInvalide`, sauf pour le prix internet où une réponse douteuse
produit un résultat « non vérifiable » plutôt qu'une exception (§3.5, §6.2
de la spec) : l'IA y fait une recherche ouverte sur internet, un simple
doute sur la qualité de sa réponse n'est pas une erreur de contrat.

Aucune dépendance d'infrastructure (FastAPI, SQLAlchemy, httpx), aucun log,
aucun appel réseau : uniquement la bibliothèque standard.

Trois usages, chacun avec sa constante de schéma JSON (envoyée à l'IA en
sortie structurée par `ingest/opencode.py`, T3) et sa fonction de lecture :

- Synthèse hebdomadaire des commentaires (§4.3) : `SCHEMA_SYNTHESE`,
  `lire_synthese`. Une action n'est acceptée que si elle s'appuie sur au
  moins un commentaire réel (`references_valides`) : l'IA ne peut pas
  inventer une action sans preuve.
- Explication d'une alerte prix (§5.2) : `SCHEMA_EXPLICATION`,
  `lire_explication`. Garde des chiffres : chaque nombre écrit dans
  l'explication doit déjà exister dans le `detail` de l'anomalie -- l'IA ne
  peut ni inventer ni recalculer un montant, elle ne fait que le commenter
  (aucune exception, y compris pour les petits nombres : cf. brief T2).
- Prix trouvé sur internet (§6.2) : `SCHEMA_PRIX_INTERNET`,
  `lire_prix_internet`, quatre gardes en cascade (réponse complète, source
  réellement ouverte par l'IA dans cette session, prix relu dans le texte
  de cette page) : jamais de prix estimé.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

# --------------------------------------------------------------------------
# Erreur commune
# --------------------------------------------------------------------------


class ReponseIAInvalide(Exception):
    """Réponse de l'IA hors contrat (schéma, garde) : message court en
    français, jamais le texte de la réponse elle-même (pas de secret ni de
    contenu client dans un message d'erreur)."""


# --------------------------------------------------------------------------
# Page lue par l'orchestrateur (T3), consommée ici pour la garde 3 du prix
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PageLue:
    """Une partie `tool` terminée d'OpenCode. `webfetch` -> `adresse` est
    l'URL réellement lue ; `websearch` -> `adresse` est la requête (jamais
    une « page ouverte » au sens de la garde 3 du prix internet)."""

    outil: str
    adresse: str
    texte: str


# --------------------------------------------------------------------------
# Synthèse hebdomadaire des commentaires (§4.3)
# --------------------------------------------------------------------------

SCHEMA_SYNTHESE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["resume", "actions"],
    "properties": {
        "resume": {"type": "string"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["texte", "commentaires"],
                "properties": {
                    "texte": {"type": "string"},
                    "commentaires": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
}

_RESUME_MAX = 1200
_ACTION_TEXTE_MAX = 300
_ACTIONS_MAX = 10


@dataclass(frozen=True)
class ActionLue:
    texte: str
    references: tuple[str, ...]


@dataclass(frozen=True)
class SyntheseLue:
    resume: str
    actions: tuple[ActionLue, ...]


def _tronquer(texte: str, longueur_max: int) -> str:
    """Coupe `texte` à `longueur_max` caractères au plus (ellipse comprise),
    sans couper au milieu d'un mot quand un espace est disponible avant la
    limite (brief T2 : « pas d'exception », toujours tronquer, jamais
    refuser une réponse pour ce seul motif)."""
    if len(texte) <= longueur_max:
        return texte
    limite = longueur_max - 1
    coupe = texte[:limite]
    dernier_espace = coupe.rfind(" ")
    if dernier_espace > 0:
        coupe = coupe[:dernier_espace]
    return coupe.rstrip() + "…"


def lire_synthese(structure: Any, references_valides: Collection[str]) -> SyntheseLue:
    """Lit et garde une réponse `SCHEMA_SYNTHESE`. Une action est écartée
    silencieusement (jamais l'ensemble de la synthèse) si elle est mal
    formée, sans texte, ou si aucune de ses références ne figure parmi
    `references_valides` : toute action doit s'appuyer sur un commentaire
    réel, l'IA ne peut pas en inventer une. Seul un `resume` absent ou vide
    fait échouer toute la réponse."""
    if not isinstance(structure, dict):
        raise ReponseIAInvalide("réponse de l'IA invalide")

    resume_brut = structure.get("resume")
    actions_brutes = structure.get("actions")
    if not isinstance(resume_brut, str) or not isinstance(actions_brutes, list):
        raise ReponseIAInvalide("réponse de l'IA invalide")

    resume = resume_brut.strip()
    if not resume:
        raise ReponseIAInvalide("résumé vide")
    resume = _tronquer(resume, _RESUME_MAX)

    references_valides_figees = frozenset(references_valides)
    actions: list[ActionLue] = []
    for action_brute in actions_brutes[:_ACTIONS_MAX]:
        if not isinstance(action_brute, dict):
            continue
        texte_brut = action_brute.get("texte")
        commentaires_bruts = action_brute.get("commentaires")
        if not isinstance(texte_brut, str) or not isinstance(commentaires_bruts, list):
            continue
        texte = texte_brut.strip()
        if not texte:
            continue

        references: list[str] = []
        for reference in commentaires_bruts:
            if (
                isinstance(reference, str)
                and reference in references_valides_figees
                and reference not in references
            ):
                references.append(reference)
        if not references:
            continue

        actions.append(
            ActionLue(
                texte=_tronquer(texte, _ACTION_TEXTE_MAX),
                references=tuple(references),
            )
        )

    return SyntheseLue(resume=resume, actions=tuple(actions))


# --------------------------------------------------------------------------
# Explication d'une alerte prix (§5.2) -- garde des chiffres
# --------------------------------------------------------------------------

SCHEMA_EXPLICATION: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["explication"],
    "properties": {"explication": {"type": "string"}},
}

_EXPLICATION_MAX = 400

# Caractères construits via `chr()` (jamais recopiés tels quels dans le
# code) : signe moins Unicode U+2212 (parfois utilisé par le modèle au
# lieu du tiret ASCII), espace insécable U+00A0 et fine insécable U+202F --
# des caractères ambigus au regard d'un lecteur humain, que `ruff`
# (RUF001) signalerait à juste titre s'ils étaient écrits en clair dans
# une chaîne du code source.
_MOINS_UNICODE = chr(0x2212)
# Signe ignoré (brief T2) : tiret ASCII et moins Unicode ci-dessus.
_SIGNES = "-" + _MOINS_UNICODE
_ESPACE_INSECABLE = chr(0x00A0)
_ESPACE_FINE_INSECABLE = chr(0x202F)
# Séparateurs de milliers reconnus : espace normal, insécable, fine
# insécable -- jamais le point (réservé au séparateur décimal ici ; le
# point comme séparateur de milliers n'est admis que pour la lecture du
# prix dans une page web, cf. `_prix_dans_texte`, règle distincte du §6.2).
_SEPARATEURS_MILLIERS = " " + _ESPACE_INSECABLE + _ESPACE_FINE_INSECABLE

_NOMBRE_RE = re.compile(
    rf"[{_SIGNES}]?\d+(?:[{_SEPARATEURS_MILLIERS}]\d{{3}})*(?:[.,]\d+)?"
)


def nombres_du_texte(texte: str) -> frozenset[Decimal]:
    """Tous les nombres écrits dans `texte`, normalisés en `Decimal`
    (brief T2) : virgule ou point pour la partie décimale, espaces
    (normal/insécable/fine insécable) comme séparateurs de milliers retirés,
    signe ignoré. `Decimal("5,30")` et `Decimal("5.3")` comparent et
    hachent égal : aucune normalisation des zéros non significatifs n'est
    nécessaire. Une date `2026-09-01` produit trois nombres distincts
    (`-` n'est pas un séparateur de milliers reconnu), donc une date
    recopiée `01/09/2026` dans une explication est acceptée telle quelle."""
    nombres: set[Decimal] = set()
    for correspondance in _NOMBRE_RE.finditer(texte):
        brut = correspondance.group().lstrip(_SIGNES)
        sans_espaces = re.sub(f"[{_SEPARATEURS_MILLIERS}]", "", brut)
        nombres.add(Decimal(sans_espaces.replace(",", ".")))
    return frozenset(nombres)


def _nombres_de_valeur(valeur: Any) -> frozenset[Decimal]:
    """Nombres portés par une valeur du `detail` d'une anomalie : les
    dicts et listes sont parcourus récursivement, toute autre valeur est
    convertie en texte (`str`) avant extraction -- un montant `Decimal` ou
    `float` du détail redevient ainsi comparable à ce que l'IA a écrit."""
    if isinstance(valeur, Mapping):
        nombres: set[Decimal] = set()
        for sous_valeur in valeur.values():
            nombres |= _nombres_de_valeur(sous_valeur)
        return frozenset(nombres)
    if isinstance(valeur, (list, tuple)):
        nombres = set()
        for element in valeur:
            nombres |= _nombres_de_valeur(element)
        return frozenset(nombres)
    return nombres_du_texte(str(valeur))


def lire_explication(structure: Any, detail: Mapping[str, Any]) -> str:
    """Lit et garde une réponse `SCHEMA_EXPLICATION`. Garde des chiffres
    (brief T2, aucune exception) : chaque nombre écrit dans l'explication
    doit être égal à un nombre déjà présent dans `detail` -- l'IA commente
    un montant existant, elle n'en invente ni n'en recalcule aucun."""
    if not isinstance(structure, dict):
        raise ReponseIAInvalide("réponse de l'IA invalide")

    explication_brute = structure.get("explication")
    if not isinstance(explication_brute, str):
        raise ReponseIAInvalide("réponse de l'IA invalide")

    explication = explication_brute.strip()
    if not explication:
        raise ReponseIAInvalide("explication vide")
    if len(explication) > _EXPLICATION_MAX:
        raise ReponseIAInvalide("explication trop longue")

    if not nombres_du_texte(explication) <= _nombres_de_valeur(detail):
        raise ReponseIAInvalide("chiffre absent des données")

    return explication


# --------------------------------------------------------------------------
# Prix trouvé sur internet (§6.2) -- quatre gardes en cascade
# --------------------------------------------------------------------------

SCHEMA_PRIX_INTERNET: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "statut",
        "produit_trouve",
        "prix",
        "devise",
        "taxes",
        "unite",
        "conditionnement",
        "source_url",
        "confiance",
        "raison",
    ],
    "properties": {
        "statut": {"type": "string", "enum": ["trouve", "prix_non_verifiable"]},
        "produit_trouve": {"type": "string"},
        "prix": {"type": "number"},
        "devise": {"type": "string"},
        "taxes": {"type": "string", "enum": ["HT", "TTC", "inconnu"]},
        "unite": {"type": "string"},
        "conditionnement": {"type": "string"},
        "source_url": {"type": "string"},
        "confiance": {"type": "string", "enum": ["faible", "moyenne", "elevee"]},
        "raison": {"type": "string"},
    },
}

_RAISON_MAX = 300
_CONFIANCES_VALIDES = frozenset({"faible", "moyenne", "elevee"})
_TAXES_VALIDES = frozenset({"HT", "TTC"})

# Garde 4 (lecture du prix dans le texte d'une page) : le point y est
# admis comme séparateur de milliers en plus des espaces (`1.234,56`), à
# la différence de `nombres_du_texte` -- une page web écrit ses prix dans
# des formats variés que l'on ne fait ici que rechercher, jamais
# interpréter comme un nombre autonome.
_SEPARATEURS_PRIX = _SEPARATEURS_MILLIERS + "."


@dataclass(frozen=True)
class PrixInternetLu:
    statut: Literal["trouve", "non_verifiable"]
    prix: Decimal | None
    devise: str | None
    taxes: Literal["HT", "TTC"] | None
    unite: str | None
    conditionnement: str | None
    produit_trouve: str | None
    source_url: str | None
    confiance: str | None
    raison: str | None


def _texte_ou_none(valeur: Any) -> str | None:
    """Chaîne non vide (`strip()`), sinon `None` -- « chaîne vide -> None »
    du §6.2, appliqué uniformément à tous les champs texte optionnels."""
    if not isinstance(valeur, str):
        return None
    nettoyee = valeur.strip()
    return nettoyee or None


def _est_nombre(valeur: Any) -> bool:
    """`int`/`float` au sens JSON, jamais un booléen (`bool` est une
    sous-classe d'`int` en Python -- brief T2 : « bool refusé »)."""
    return isinstance(valeur, (int, float)) and not isinstance(valeur, bool)


def _non_verifiable(structure: dict[Any, Any], raison: str) -> PrixInternetLu:
    """Résultat `non_verifiable` : `produit_trouve`/`source_url` gardés
    quand présents (utiles à l'humain même sans prix fiable), `prix` et le
    reste toujours `None` (§6.2, dernier paragraphe)."""
    return PrixInternetLu(
        statut="non_verifiable",
        prix=None,
        devise=None,
        taxes=None,
        unite=None,
        conditionnement=None,
        produit_trouve=_texte_ou_none(structure.get("produit_trouve")),
        source_url=_texte_ou_none(structure.get("source_url")),
        confiance=None,
        raison=raison,
    )


def _normaliser_adresse(adresse: str) -> str:
    """Adresse comparable pour la garde 3 : schéma et hôte en minuscules,
    barre oblique finale du chemin et fragment ignorés (§6.2 : « à la barre
    oblique finale près »)."""
    sans_fragment, _, _ = adresse.partition("#")
    decoupee = urlsplit(sans_fragment)
    chemin = decoupee.path.rstrip("/")
    return urlunsplit(
        (decoupee.scheme.lower(), decoupee.netloc.lower(), chemin, decoupee.query, "")
    )


def _page_ouverte(adresse: str, pages: Sequence[PageLue]) -> PageLue | None:
    """La page `webfetch` (jamais `websearch`) dont l'adresse normalisée
    correspond à `adresse`, ou `None` si aucune (garde 3)."""
    cible = _normaliser_adresse(adresse)
    for page in pages:
        if page.outil == "webfetch" and _normaliser_adresse(page.adresse) == cible:
            return page
    return None


def _motif_entier(entier: str) -> str:
    """Motif de la partie entière d'un prix recherché dans le texte d'une
    page : un séparateur de milliers (§6.2 : espace, insécable, point) peut
    apparaître, de façon optionnelle, entre deux chiffres quelconques --
    couvre aussi bien un regroupement par trois (`1 234`, `1.234`) qu'une
    écriture sans regroupement (`1234`), sans avoir à connaître la
    convention de regroupement de la page lue."""
    premier, reste = entier[0], entier[1:]
    optionnel = f"[{_SEPARATEURS_PRIX}]?"
    return premier + "".join(f"{optionnel}{chiffre}" for chiffre in reste)


def _prix_dans_texte(prix: Decimal, texte: str) -> bool:
    """Garde 4 : le prix (arrondi à 2 décimales pour la recherche, comme
    un prix imprimé) doit apparaître dans `texte`, jamais collé à d'autres
    chiffres (`(?<!\\d)`/`(?!\\d)` : `112,34` ne valide pas `12,34`). Un
    prix entier est aussi cherché sous la forme « nombre suivi de €/EUR »
    en plus de son écriture à deux décimales (`45,00`/`45.00`, déjà
    couverte par le premier motif)."""
    prix_2dec = prix.quantize(Decimal("0.01"))
    entier_str, decimales_str = f"{prix_2dec:.2f}".split(".")
    motif_entier = _motif_entier(entier_str)

    motifs = [rf"(?<!\d){motif_entier}[.,]{decimales_str}(?!\d)"]
    if decimales_str == "00":
        motifs.append(rf"(?<!\d){motif_entier}[{_SEPARATEURS_PRIX}]?(?:€|EUR)")

    return any(re.search(motif, texte, re.IGNORECASE) for motif in motifs)


def lire_prix_internet(structure: Any, pages: Sequence[PageLue]) -> PrixInternetLu:
    """Lit et garde une réponse `SCHEMA_PRIX_INTERNET`. Seule une
    `structure` qui n'est pas un dict est un échec de contrat (exception) :
    toute autre réponse douteuse (statut inconnu, champ manquant, source
    non ouverte par l'IA, prix introuvable dans la page) donne un résultat
    `non_verifiable`, jamais une exception -- la recherche sur internet est
    par nature incertaine (§6.2)."""
    if not isinstance(structure, dict):
        raise ReponseIAInvalide("réponse de l'IA invalide")

    statut_brut = structure.get("statut")

    # Garde 1.
    if statut_brut == "prix_non_verifiable":
        raison_brute = _texte_ou_none(structure.get("raison"))
        raison = (
            raison_brute[:_RAISON_MAX] if raison_brute is not None else "non vérifiable"
        )
        return _non_verifiable(structure, raison)

    if statut_brut != "trouve":
        return _non_verifiable(structure, "réponse incomplète")

    # Garde 2.
    prix_brut = structure.get("prix")
    devise_brute = structure.get("devise")
    source_url = _texte_ou_none(structure.get("source_url"))
    produit_trouve = _texte_ou_none(structure.get("produit_trouve"))
    confiance = structure.get("confiance")

    reponse_complete = (
        _est_nombre(prix_brut)
        and prix_brut is not None
        and prix_brut > 0
        and isinstance(devise_brute, str)
        and devise_brute.strip().upper() == "EUR"
        and source_url is not None
        and source_url.startswith("https://")
        and produit_trouve is not None
        and confiance in _CONFIANCES_VALIDES
    )
    if not reponse_complete or source_url is None:
        return _non_verifiable(structure, "réponse incomplète")

    # Garde 3.
    page = _page_ouverte(source_url, pages)
    if page is None:
        return _non_verifiable(structure, "source non ouverte")

    # Garde 4.
    prix_decimal = Decimal(str(prix_brut)).quantize(Decimal("0.0001"))
    if not _prix_dans_texte(prix_decimal, page.texte):
        return _non_verifiable(structure, "prix absent de la page")

    taxes_brut = structure.get("taxes")
    taxes: Literal["HT", "TTC"] | None = (
        taxes_brut if taxes_brut in _TAXES_VALIDES else None
    )

    return PrixInternetLu(
        statut="trouve",
        prix=prix_decimal,
        devise="EUR",
        taxes=taxes,
        unite=_texte_ou_none(structure.get("unite")),
        conditionnement=_texte_ou_none(structure.get("conditionnement")),
        produit_trouve=produit_trouve,
        source_url=source_url,
        confiance=confiance,
        raison=None,
    )
