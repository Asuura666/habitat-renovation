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
  `lire_prix_internet`, une liste de 1 à 5 offres (depuis le 29/09/2026) ;
  chaque offre passe trois gardes (réponse complète, source réellement
  ouverte par l'IA dans cette session, prix relu dans le texte de cette
  page) et est ramenée en HT (`prix_ht`) : jamais de prix estimé.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
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
# Détail d'un contrôle anti-invention (Laboratoire IA, tâche LABO) : chaque
# fonction `controles_...` ci-dessous détaille, contrôle par contrôle, ce que
# sa fonction `lire_...` correspondante vérifie déjà -- jamais une seconde
# implémentation des gardes (les deux s'appuient sur les mêmes fonctions
# privées), seulement une vue plus détaillée pour l'écran d'essai admin.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Controle:
    """Un contrôle anti-invention appliqué à une réponse de l'IA, tel
    qu'affiché à l'admin sur le Laboratoire IA. `nom` : ce qui est vérifié,
    en français courant (ex. « La page source a vraiment été ouverte »).
    `detail` : le verdict précis pour cette réponse (ex. « page https://…
    lue » / « aucune page ouverte à cette adresse »). Un contrôle qui n'a pas
    pu être évalué parce qu'un contrôle précédent a déjà échoué porte
    `ok=False` et `detail="non vérifié (contrôle précédent en échec)"`."""

    nom: str
    ok: bool
    detail: str


_CONTROLE_NON_EVALUE = "non vérifié (contrôle précédent en échec)"


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


def _reference_normalisee(reference: Any) -> str | None:
    """Référence de commentaire citée par l'IA, ramenée à la forme `cN` :
    espaces et crochets autour retirés, minuscules -- `None` si ce n'est pas
    un texte. 29/09/2026, essai réel : la consigne envoyée demandait « les
    références [cN] » (avec crochets), celle de l'agent « c1, c2 » ; une
    réponse citant « [c1] » voyait toutes ses actions écartées. La référence
    normalisée reste vérifiée contre les références réellement envoyées."""
    if not isinstance(reference, str):
        return None
    return reference.strip().strip("[]").strip().lower()


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
        for reference_citee in commentaires_bruts:
            reference = _reference_normalisee(reference_citee)
            if (
                reference is not None
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


_NOM_FORME_SYNTHESE = "La réponse a la forme attendue (résumé et actions)"
_NOM_RESUME_SYNTHESE = "Le résumé n'est pas vide"


def controles_synthese(
    structure: Any, references_valides: Collection[str]
) -> tuple[Controle, ...]:
    """Détail, contrôle par contrôle, de ce que vérifie `lire_synthese` sur
    la même entrée (Laboratoire IA) : forme de la réponse, résumé non vide,
    puis une ligne par action brute -- gardée (toutes ses références valides,
    ou certaines retirées) ou écartée (sans texte, aucune référence valide,
    au-delà des `_ACTIONS_MAX` premières). Jamais de seconde implémentation
    des gardes : mêmes conditions que `lire_synthese`, lues sur la même
    entrée."""
    if not isinstance(structure, dict):
        return (Controle(_NOM_FORME_SYNTHESE, False, "réponse de l'IA invalide"),)

    resume_brut = structure.get("resume")
    actions_brutes = structure.get("actions")
    if not isinstance(resume_brut, str) or not isinstance(actions_brutes, list):
        return (
            Controle(
                _NOM_FORME_SYNTHESE,
                False,
                "champ « resume » ou « actions » manquant ou invalide",
            ),
        )
    controles: list[Controle] = [
        Controle(_NOM_FORME_SYNTHESE, True, "réponse bien formée")
    ]

    resume = resume_brut.strip()
    if not resume:
        controles.append(Controle(_NOM_RESUME_SYNTHESE, False, "résumé vide"))
        return tuple(controles)
    controles.append(
        Controle(_NOM_RESUME_SYNTHESE, True, f"{len(resume)} caractère(s)")
    )

    references_valides_figees = frozenset(references_valides)
    for indice, action_brute in enumerate(actions_brutes, start=1):
        nom = f"Action {indice} de la réponse"
        if indice > _ACTIONS_MAX:
            controles.append(
                Controle(nom, False, f"au-delà des {_ACTIONS_MAX} premières, écartée")
            )
            continue
        if not isinstance(action_brute, dict):
            controles.append(Controle(nom, False, "action mal formée, écartée"))
            continue
        texte_brut = action_brute.get("texte")
        commentaires_bruts = action_brute.get("commentaires")
        if not isinstance(texte_brut, str) or not isinstance(commentaires_bruts, list):
            controles.append(Controle(nom, False, "action mal formée, écartée"))
            continue
        if not texte_brut.strip():
            controles.append(Controle(nom, False, "sans texte, écartée"))
            continue

        references_valides_de_laction = [
            reference
            for reference in commentaires_bruts
            if _reference_normalisee(reference) in references_valides_figees
        ]
        references_inconnues = [
            reference
            for reference in commentaires_bruts
            if _reference_normalisee(reference) not in references_valides_figees
        ]
        if not references_valides_de_laction:
            citees = (
                "citées : "
                + ", ".join(str(reference) for reference in commentaires_bruts)
                if commentaires_bruts
                else "aucune citée"
            )
            controles.append(
                Controle(nom, False, f"aucune référence valide ({citees}), écartée")
            )
            continue

        if references_inconnues:
            detail = "gardée, références inconnues retirées : " + ", ".join(
                str(reference) for reference in references_inconnues
            )
        else:
            detail = "gardée, toutes les références citées sont valides"
        controles.append(Controle(nom, True, detail))

    return tuple(controles)


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


def _normaliser_nombre(brut: str) -> Decimal:
    """Normalise une correspondance de `_NOMBRE_RE` (signe éventuel,
    séparateurs de milliers, virgule ou point décimal) en `Decimal`."""
    sans_signe = brut.lstrip(_SIGNES)
    sans_espaces = re.sub(f"[{_SEPARATEURS_MILLIERS}]", "", sans_signe)
    return Decimal(sans_espaces.replace(",", "."))


def nombres_du_texte(texte: str) -> frozenset[Decimal]:
    """Tous les nombres écrits dans `texte`, normalisés en `Decimal`
    (brief T2) : virgule ou point pour la partie décimale, espaces
    (normal/insécable/fine insécable) comme séparateurs de milliers retirés,
    signe ignoré. `Decimal("5,30")` et `Decimal("5.3")` comparent et
    hachent égal : aucune normalisation des zéros non significatifs n'est
    nécessaire. Une date `2026-09-01` produit trois nombres distincts
    (`-` n'est pas un séparateur de milliers reconnu), donc une date
    recopiée `01/09/2026` dans une explication est acceptée telle quelle.

    Attention (fix round 1, revue T2) : cette lecture fusionne deux nombres
    réellement distincts séparés par un simple espace quand le second fait
    exactement 3 chiffres (« 5 300 bons » -> `{5300}`, pas `{5, 300}`), au
    même titre qu'un vrai « 5 300 » milliers. `lire_explication` compense
    ce cas via `_nombre_valide_dans_detail` (lecture fusionnée OU chaque
    partie individuellement) ; cette fonction reste telle que spécifiée
    (signature et comportement publics, testés en propre)."""
    return frozenset(
        _normaliser_nombre(correspondance.group())
        for correspondance in _NOMBRE_RE.finditer(texte)
    )


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


def _nombre_valide_dans_detail(brut: str, nombres_detail: frozenset[Decimal]) -> bool:
    """Un nombre écrit dans l'explication (correspondance brute de
    `_NOMBRE_RE`) est accepté si sa lecture fusionnée normale figure dans
    le détail, OU si chacune de ses parties séparées par un espace de
    milliers y figure individuellement (fix round 1, revue T2) : corrige
    le cas où deux valeurs réellement distinctes se retrouvent accolées
    par hasard dans le texte (« 5 300 bons » = « 5 » puis « 300 », pas
    nécessairement 5300) sans jamais relâcher la garde pour un nombre
    absent des deux lectures -- un nombre sans espace qui échoue au test
    fusionné n'a pas de seconde lecture possible et reste refusé."""
    if _normaliser_nombre(brut) in nombres_detail:
        return True
    parties = re.split(f"[{_SEPARATEURS_MILLIERS}]", brut)
    return len(parties) > 1 and all(
        _normaliser_nombre(partie) in nombres_detail for partie in parties
    )


def lire_explication(structure: Any, detail: Mapping[str, Any]) -> str:
    """Lit et garde une réponse `SCHEMA_EXPLICATION`. Garde des chiffres
    (brief T2, aucune exception) : chaque nombre écrit dans l'explication
    doit être égal à un nombre déjà présent dans `detail` (ou s'y retrouver
    partie par partie, cf. `_nombre_valide_dans_detail`) -- l'IA commente un
    montant existant, elle n'en invente ni n'en recalcule aucun."""
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

    nombres_detail = _nombres_de_valeur(detail)
    for correspondance in _NOMBRE_RE.finditer(explication):
        if not _nombre_valide_dans_detail(correspondance.group(), nombres_detail):
            raise ReponseIAInvalide("chiffre absent des données")

    return explication


_NOM_FORME_EXPLICATION = "La réponse a la forme attendue (texte)"
_NOM_LONGUEUR_EXPLICATION = (
    f"Le texte n'est ni vide ni trop long ({_EXPLICATION_MAX} caractères au plus)"
)


def controles_explication(
    structure: Any, detail: Mapping[str, Any]
) -> tuple[Controle, ...]:
    """Détail, contrôle par contrôle, de ce que vérifie `lire_explication`
    sur la même entrée (Laboratoire IA) : forme de la réponse, longueur, puis
    un contrôle par nombre écrit dans l'explication -- même garde que
    `lire_explication` (`_nombre_valide_dans_detail`, lecture fusionnée ou
    par parties), jamais une seconde implémentation."""
    if not isinstance(structure, dict):
        return (Controle(_NOM_FORME_EXPLICATION, False, "réponse de l'IA invalide"),)

    explication_brute = structure.get("explication")
    if not isinstance(explication_brute, str):
        return (
            Controle(
                _NOM_FORME_EXPLICATION,
                False,
                "champ « explication » manquant ou invalide",
            ),
        )
    controles: list[Controle] = [
        Controle(_NOM_FORME_EXPLICATION, True, "réponse bien formée")
    ]

    explication = explication_brute.strip()
    if not explication:
        controles.append(Controle(_NOM_LONGUEUR_EXPLICATION, False, "texte vide"))
        return tuple(controles)
    if len(explication) > _EXPLICATION_MAX:
        controles.append(
            Controle(
                _NOM_LONGUEUR_EXPLICATION,
                False,
                f"{len(explication)} caractères, plus de {_EXPLICATION_MAX}",
            )
        )
        return tuple(controles)
    controles.append(
        Controle(_NOM_LONGUEUR_EXPLICATION, True, f"{len(explication)} caractère(s)")
    )

    nombres_detail = _nombres_de_valeur(detail)
    for correspondance in _NOMBRE_RE.finditer(explication):
        brut = correspondance.group()
        valide = _nombre_valide_dans_detail(brut, nombres_detail)
        controles.append(
            Controle(
                nom=f"Le nombre « {brut} » écrit par l'IA",
                ok=valide,
                detail=(
                    f"{brut} figure dans les données"
                    if valide
                    else f"{brut} absent des données"
                ),
            )
        )

    return tuple(controles)


# --------------------------------------------------------------------------
# Prix trouvé sur internet (§6.2) -- quatre gardes en cascade
# --------------------------------------------------------------------------

SCHEMA_PRIX_INTERNET: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["statut", "raison", "offres"],
    "properties": {
        "statut": {"type": "string", "enum": ["trouve", "prix_non_verifiable"]},
        "raison": {"type": "string"},
        "offres": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "produit_trouve",
                    "prix",
                    "devise",
                    "taxes",
                    "unite",
                    "conditionnement",
                    "source_url",
                    "confiance",
                ],
                "properties": {
                    "produit_trouve": {"type": "string"},
                    "prix": {"type": "number"},
                    "devise": {"type": "string"},
                    "taxes": {"type": "string", "enum": ["HT", "TTC", "inconnu"]},
                    "unite": {"type": "string"},
                    "conditionnement": {"type": "string"},
                    "source_url": {"type": "string"},
                    "confiance": {
                        "type": "string",
                        "enum": ["faible", "moyenne", "elevee"],
                    },
                },
            },
        },
    },
}

OFFRES_MAX = 5
TVA_PRIX_INTERNET = Decimal("1.20")
_CENTIME = Decimal("0.01")

_RAISON_MAX = 300
_CONFIANCES_VALIDES = frozenset({"faible", "moyenne", "elevee"})
_TAXES_VALIDES = frozenset({"HT", "TTC"})

# Garde 4 (lecture du prix dans le texte d'une page) : le point y est
# admis comme séparateur de milliers en plus des espaces (`1.234,56`), à
# la différence de `nombres_du_texte` -- une page web écrit ses prix dans
# des formats variés que l'on ne fait ici que rechercher, jamais
# interpréter comme un nombre autonome.
_SEPARATEURS_PRIX = _SEPARATEURS_MILLIERS + "."


def prix_ht(prix: Decimal, taxes: str | None) -> Decimal | None:
    """Prix ramené en HT pour comparer des offres entre elles et au prix
    facturé (HT) : `HT` tel quel, `TTC` ÷ 1,20 (TVA 20 %), au centime ;
    `None` quand le site ne dit ni HT ni TTC (décision d'Ilane du
    29/09/2026 : une telle offre reste listée mais ne compte ni dans le plus
    bas ni dans l'écart)."""
    if taxes == "HT":
        return prix.quantize(_CENTIME, rounding=ROUND_HALF_UP)
    if taxes == "TTC":
        return (prix / TVA_PRIX_INTERNET).quantize(_CENTIME, rounding=ROUND_HALF_UP)
    return None


@dataclass(frozen=True)
class OffreLue:
    """Une offre gardée (§6.2) : page ouverte, prix relu dans son texte."""

    prix: Decimal
    devise: str
    taxes: Literal["HT", "TTC"] | None
    prix_ht: Decimal | None
    unite: str | None
    conditionnement: str | None
    produit_trouve: str
    source_url: str
    confiance: str


@dataclass(frozen=True)
class PrixInternetLu:
    """Résultat de la lecture. Les champs à plat reprennent l'offre la moins
    chère en HT (à défaut la première gardée) ; `offres` liste les offres
    gardées, triées par `prix_ht` croissant (`None` à la fin, ordre de l'IA
    à égalité)."""

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
    offres: tuple[OffreLue, ...] = ()


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


def _est_prix_valide(valeur: Any) -> bool:
    """`_est_nombre` et strictement positif. Isolé dans une fonction dont
    le paramètre est un `Any` simple (fix round 1, revue T2) : `dict.get`
    sans valeur par défaut type son retour `Any | None`, et mypy refuse
    alors `valeur > 0` (opérande `None` de l'union) même si `valeur` est en
    réalité toujours un nombre à ce stade -- un paramètre `Any` nommé,
    plutôt qu'un `and prix_brut is not None` redondant avec `_est_nombre`
    dans l'appelant, tranche le problème sans changer le comportement."""
    return _est_nombre(valeur) and valeur > 0


def _non_verifiable(structure: dict[Any, Any], raison: str) -> PrixInternetLu:
    """Résultat `non_verifiable` : `produit_trouve`/`source_url` de la
    première offre gardés quand présents (utiles à l'humain même sans prix
    fiable), `prix` et le reste toujours `None` (§6.2, dernier paragraphe)."""
    offres = structure.get("offres")
    premiere = offres[0] if isinstance(offres, list) and offres else None
    if not isinstance(premiere, dict):
        premiere = {}
    return PrixInternetLu(
        statut="non_verifiable",
        prix=None,
        devise=None,
        taxes=None,
        unite=None,
        conditionnement=None,
        produit_trouve=_texte_ou_none(premiere.get("produit_trouve")),
        source_url=_texte_ou_none(premiere.get("source_url")),
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


# Garde 4, bornes du nombre recherché (fix round 1, revue T2) :
# - avant : ni collé à un chiffre ou une lettre (`[^\W_]` = alphanumérique
#   unicode, donc « AB12,34 » ne valide pas 12,34), ni précédé d'un
#   « chiffre + séparateur de milliers » qui le rattacherait en réalité à
#   un nombre plus grand (`1 212,34` ne doit valider que 1212,34, jamais
#   212,34 -- la garde ci-dessous inspecte les 2 caractères qui précèdent).
_PAS_PRECEDE_DUN_CHIFFRE_OU_DUNE_LETTRE = r"(?<![^\W_])"
_PAS_PRECEDE_DUN_MILLIER = rf"(?<!\d[{_SEPARATEURS_PRIX}])"
_AVANT_PRIX = _PAS_PRECEDE_DUN_CHIFFRE_OU_DUNE_LETTRE + _PAS_PRECEDE_DUN_MILLIER
# - après : ni chiffre ni lettre (`12,34eme` ne valide pas 12,34 ; un « € »
#   ou une fin de texte/phrase après un espace restent acceptés puisque
#   l'espace lui-même n'est ni l'un ni l'autre -- `12,34 €TTC` est donc
#   accepté, la garde ne regarde que le caractère immédiatement collé).
_APRES_PRIX = r"(?!\d)(?![^\W\d_])"


def _prix_dans_texte(prix: Decimal, texte: str) -> bool:
    """Garde 4 : le prix (arrondi à 2 décimales pour la recherche, comme
    un prix imprimé) doit apparaître dans `texte`, jamais collé à d'autres
    chiffres ni à des lettres (`_AVANT_PRIX`/`_APRES_PRIX`) : ni
    `112,34` pour 12,34, ni `AB12,34`, ni `12,34eme`, ni `1 212,34` pour
    212,34 (seul 1212,34 y est valide). Un prix entier est aussi cherché
    sous la forme « nombre suivi de €/EUR » en plus de son écriture à deux
    décimales (`45,00`/`45.00`, déjà couverte par le premier motif) : le
    « € » est accepté collé ou après un simple espace, « EUR » doit être un
    mot entier (`EUR\\b`) pour ne pas matcher un mot qui commence pareil
    (« 45 Euromaster »). Le « € » est aussi reconnu entre les euros et les
    centimes (« 7€47 », « 2 €49 »), écriture courante chez les enseignes
    (29/09/2026, page Brico Dépôt : prix rejeté alors qu'il figurait sur la
    page) -- espace admis avant le « € », jamais après, mêmes bornes que
    l'écriture « 7,47 »."""
    prix_2dec = prix.quantize(Decimal("0.01"))
    entier_str, decimales_str = f"{prix_2dec:.2f}".split(".")
    motif_entier = _motif_entier(entier_str)

    motifs = [
        rf"{_AVANT_PRIX}{motif_entier}[.,]{decimales_str}{_APRES_PRIX}",
        rf"{_AVANT_PRIX}{motif_entier}[{_SEPARATEURS_MILLIERS}]?€{decimales_str}"
        rf"{_APRES_PRIX}",
    ]
    if decimales_str == "00":
        separateur_devise = f"[{_SEPARATEURS_MILLIERS}]?"
        motifs.append(rf"{_AVANT_PRIX}{motif_entier}{separateur_devise}€")
        motifs.append(
            rf"{_AVANT_PRIX}{motif_entier}{separateur_devise}EUR\b{_APRES_PRIX}"
        )

    return any(re.search(motif, texte, re.IGNORECASE) for motif in motifs)


_NOM_GARDE_STATUT = "L'IA annonce un prix, pas « non vérifiable »"
_NOM_AUCUNE_OFFRE = "Au moins une offre"
_DETAIL_INCOMPLETE = (
    "écartée : champ manquant ou invalide (prix, devise, source ou confiance)"
)


def _domaine(adresse: Any) -> str | None:
    if not isinstance(adresse, str):
        return None
    hote = urlsplit(adresse).netloc.lower()
    return hote.removeprefix("www.") or None


def _nom_offre(indice: int, offre_brute: Any) -> str:
    domaine = (
        _domaine(offre_brute.get("source_url"))
        if isinstance(offre_brute, dict)
        else None
    )
    return f"Offre {indice} — {domaine}" if domaine else f"Offre {indice}"


def _evaluer_offre(
    offre_brute: Any, pages: Sequence[PageLue]
) -> tuple[OffreLue | None, str, str]:
    """Gardes 2 à 4 du §6.2 sur une offre -> `(offre gardée ou None,
    raison courte, détail pour le Laboratoire)`."""
    if not isinstance(offre_brute, dict):
        return None, "réponse incomplète", _DETAIL_INCOMPLETE
    prix_brut = offre_brute.get("prix")
    devise_brute = offre_brute.get("devise")
    source_url = _texte_ou_none(offre_brute.get("source_url"))
    produit_trouve = _texte_ou_none(offre_brute.get("produit_trouve"))
    confiance = offre_brute.get("confiance")
    if (
        not _est_prix_valide(prix_brut)
        or not isinstance(devise_brute, str)
        or devise_brute.strip().upper() != "EUR"
        or source_url is None
        or not source_url.startswith("https://")
        or produit_trouve is None
        or confiance not in _CONFIANCES_VALIDES
    ):
        return None, "réponse incomplète", _DETAIL_INCOMPLETE
    page = _page_ouverte(source_url, pages)
    if page is None:
        return (
            None,
            "source non ouverte",
            f"écartée : aucune page ouverte à l'adresse {source_url}",
        )
    prix = Decimal(str(prix_brut)).quantize(Decimal("0.0001"))
    if not _prix_dans_texte(prix, page.texte):
        return (
            None,
            "prix absent de la page",
            "écartée : prix absent du texte de la page lue",
        )
    taxes_brut = offre_brute.get("taxes")
    taxes: Literal["HT", "TTC"] | None = (
        taxes_brut if taxes_brut in _TAXES_VALIDES else None
    )
    offre = OffreLue(
        prix=prix,
        devise="EUR",
        taxes=taxes,
        prix_ht=prix_ht(prix, taxes),
        unite=_texte_ou_none(offre_brute.get("unite")),
        conditionnement=_texte_ou_none(offre_brute.get("conditionnement")),
        produit_trouve=produit_trouve,
        source_url=source_url,
        confiance=str(confiance),
    )
    return offre, "", f"gardée : page {source_url} lue, prix retrouvé"


def _gardes_prix_internet(
    structure: dict[Any, Any], pages: Sequence[PageLue]
) -> tuple[PrixInternetLu, tuple[Controle, ...]]:
    """Évalue les gardes du §6.2 une seule fois -- `lire_prix_internet`
    (résultat) et `controles_prix_internet` (détail affiché à l'admin,
    Laboratoire IA) s'appuient toutes les deux sur cette fonction, jamais sur
    deux implémentations distinctes des gardes. Le statut est contrôlé une
    fois, puis chaque offre (5 au plus, de pages différentes) passe les
    gardes 2 à 4 : une offre en échec est écartée, les autres restent."""
    statut_brut = structure.get("statut")

    # `raison` est coupée brutalement à `_RAISON_MAX` caractères (jamais
    # `_tronquer` : pas de règle « … sans couper un mot » pour ce champ).
    if statut_brut == "prix_non_verifiable":
        raison_brute = _texte_ou_none(structure.get("raison"))
        raison = (
            raison_brute[:_RAISON_MAX] if raison_brute is not None else "non vérifiable"
        )
        return _non_verifiable(structure, raison), (
            Controle(_NOM_GARDE_STATUT, False, "l'IA répond « prix non vérifiable »"),
        )

    if statut_brut != "trouve":
        return _non_verifiable(structure, "réponse incomplète"), (
            Controle(
                _NOM_GARDE_STATUT, False, "réponse de l'IA sans statut exploitable"
            ),
        )

    controles: list[Controle] = [
        Controle(_NOM_GARDE_STATUT, True, "l'IA répond « trouvé »")
    ]
    offres_brutes = structure.get("offres")
    if not isinstance(offres_brutes, list):
        offres_brutes = []

    gardees: list[OffreLue] = []
    adresses_gardees: set[str] = set()
    premiere_raison: str | None = None
    for indice, offre_brute in enumerate(offres_brutes, start=1):
        nom = _nom_offre(indice, offre_brute)
        if len(gardees) >= OFFRES_MAX:
            controles.append(
                Controle(
                    nom, False, f"écartée : au-delà des {OFFRES_MAX} offres gardées"
                )
            )
            continue
        offre, raison_courte, detail = _evaluer_offre(offre_brute, pages)
        if offre is None:
            if premiere_raison is None:
                premiere_raison = raison_courte
            controles.append(Controle(nom, False, detail))
            continue
        adresse = _normaliser_adresse(offre.source_url)
        if adresse in adresses_gardees:
            controles.append(
                Controle(nom, False, "écartée : même page qu'une offre déjà gardée")
            )
            continue
        adresses_gardees.add(adresse)
        gardees.append(offre)
        controles.append(Controle(nom, True, detail))

    if not offres_brutes:
        controles.append(
            Controle(_NOM_AUCUNE_OFFRE, False, "aucune offre dans la réponse")
        )

    if not gardees:
        return _non_verifiable(structure, premiere_raison or "aucune offre"), tuple(
            controles
        )

    triees = sorted(gardees, key=lambda o: (o.prix_ht is None, o.prix_ht or Decimal(0)))
    m = triees[0]
    resultat = PrixInternetLu(
        statut="trouve",
        prix=m.prix,
        devise="EUR",
        taxes=m.taxes,
        unite=m.unite,
        conditionnement=m.conditionnement,
        produit_trouve=m.produit_trouve,
        source_url=m.source_url,
        confiance=m.confiance,
        raison=None,
        offres=tuple(triees),
    )
    return resultat, tuple(controles)


def lire_prix_internet(structure: Any, pages: Sequence[PageLue]) -> PrixInternetLu:
    """Lit et garde une réponse `SCHEMA_PRIX_INTERNET`. Seule une
    `structure` qui n'est pas un dict est un échec de contrat (exception) :
    toute autre réponse douteuse (statut inconnu, ancien format sans
    `offres`, source non ouverte par l'IA, prix introuvable dans la page)
    donne un résultat `non_verifiable` ou écarte l'offre concernée, jamais
    une exception -- la recherche sur internet est par nature incertaine
    (§6.2)."""
    if not isinstance(structure, dict):
        raise ReponseIAInvalide("réponse de l'IA invalide")
    resultat, _controles = _gardes_prix_internet(structure, pages)
    return resultat


def controles_prix_internet(
    structure: Any, pages: Sequence[PageLue]
) -> tuple[Controle, ...]:
    """Détail des gardes de `lire_prix_internet` (statut, puis une ligne par
    offre) sur la même entrée (Laboratoire IA) -- s'appuie sur
    `_gardes_prix_internet`, jamais sur une seconde implémentation."""
    if not isinstance(structure, dict):
        return (Controle(_NOM_GARDE_STATUT, False, "réponse de l'IA invalide"),)
    _resultat, controles = _gardes_prix_internet(structure, pages)
    return controles
