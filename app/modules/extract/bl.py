"""Lecture d'un bon de livraison depuis l'annotation Mistral (module PUR, L3-T2).

Contexte (constat 1, décision L3-D1) : aucune photo de BL n'est disponible
pour écrire un parseur par fournisseur à l'aveugle (contrairement à
`unikalo.py`, écrit sur une facture réelle). La lecture d'une photo de BL
repose donc entièrement sur l'annotation structurée de l'API Mistral OCR
(`document_annotation`, un même schéma JSON pour Unikalo et Point.P) :
`SCHEMA_ANNOTATION_BL` demande au modèle de recopier chaque valeur telle
qu'imprimée (ou `null`), jamais de la calculer ou de la corriger ; ce module
lit cette annotation et convertit chaque valeur de façon déterministe
(`nombre_bl`, `date_bl`) — l'IA extrait, elle ne décide jamais (CLAUDE.md).

Chaque valeur brute est en outre confrontée au texte déjà OCRisé via
`confiance.py` (L3-T1, L3-D2) : une valeur que l'annotation a inventée ou
reformulée n'aura aucune occurrence dans le texte et vaudra confiance 0.
`verification.py` (L3-T3) décidera, à partir de `BLExtrait`, si le document
part « à vérifier ».

Ajustements L3-T6b (constat 11, premier essai réel, L3-D24 à L3-D26) : le
premier lot de photos réelles a montré des formes que le schéma initial ne
couvrait pas — une date parfois imprimée en toutes lettres (`date_bl`), deux
quantités par ligne d'article chez un fournisseur (conditionnements vs
quantité facturée, `quantite_conditionnements`), des lignes d'éco-
participation à isoler (`est_ligne_eco`), et des consignes de schéma trop
ambiguës sur qui est l'émetteur du document et ce qui constitue le
« chantier » (`_DESCRIPTIONS_ENTETE`/`_DESCRIPTIONS_LIGNE` réécrites). Aucune
valeur réelle n'est reproduite ici : seules les formes observées (constat 11
du plan) guident ces ajustements.

Aucune dépendance d'infrastructure (`fastapi`, `sqlalchemy`, `httpx`), aucun
log, aucun appel réseau (R17) : ce module prend un `dict` JSON déjà obtenu
de l'API Mistral OCR (`OPTIONS_OCR_BL` documente seulement les options à
fusionner dans la requête, envoyée par `ingest/mistral.py`, L3-T6).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from .confiance import (
    IndexConfiance,
    confiance_valeur,
    confiances_ligne,
    indexer_confiance,
)
from .ocr import NumeroBL, detecter_numero_bl, texte_ocr

# --------------------------------------------------------------------------
# Schéma d'annotation Mistral OCR (L3-D1)
# --------------------------------------------------------------------------

CHAMPS_ENTETE_BL: tuple[str, ...] = (
    "type_bon",
    "fournisseur",
    "agence_fournisseur",
    "siret",
    "tva_intracommunautaire",
    "numero",
    "date_doc",
    "chantier_brut",
    "numero_commande",
    "enleve_par",
    "total_ht",
    "total_tva",
    "total_ttc",
)

CHAMPS_LIGNE_BL: tuple[str, ...] = (
    "code",
    "designation",
    "quantite_conditionnements",
    "quantite",
    "unite",
    "pu_ht",
    "montant_ht",
)


def _propriete(description: str) -> dict[str, Any]:
    """Propriété du schéma d'annotation : chaîne telle qu'imprimée ou
    `null`, jamais un autre type (le modèle recopie, il n'invente ni ne
    calcule — `CONSIGNE_ANNOTATION_BL`)."""
    return {"type": ["string", "null"], "description": description}


_DESCRIPTIONS_ENTETE: dict[str, str] = {
    "type_bon": (
        '"livraison" pour un bon de livraison, "enlevement" pour un bon '
        "d'enlèvement, null si indéterminé"
    ),
    # Descriptions réécrites L3-D26 (constat 11) : l'annotation confondait
    # émetteur/client (adresse de livraison prise pour le chantier, SIRET/TVA
    # du client pris pour ceux du fournisseur) sur une des quatre photos.
    "fournisseur": (
        "Raison sociale de l'entreprise qui émet le document (en-tête ou "
        "pied de page), jamais le client destinataire ni l'adresse de "
        "livraison"
    ),
    "agence_fournisseur": (
        "Agence ou point de vente de l'émetteur tel qu'imprimé (ex. le nom "
        "d'agence à côté de la raison sociale), null si absent"
    ),
    "siret": "SIRET de l'émetteur tel qu'imprimé, jamais celui du client",
    "tva_intracommunautaire": (
        "Numéro de TVA intracommunautaire de l'émetteur tel qu'imprimé "
        "(parfois libellé id.cee), jamais celui du client"
    ),
    "numero": 'numéro du bon tel qu\'imprimé, sans le libellé "N°"',
    "date_doc": "date du bon telle qu'imprimée",
    "chantier_brut": (
        'Texte imprimé après "CHANTIER :" ou "Votre chantier :", code entre '
        "parenthèses compris ; null s'il n'y a pas de telle mention (jamais "
        "l'adresse de livraison ni le nom du client)"
    ),
    "numero_commande": "référence de commande telle qu'imprimée",
    "enleve_par": "nom de la personne ayant enlevé la marchandise tel qu'imprimé",
    "total_ht": (
        "Total hors taxes du document qui inclut les éco-contributions "
        '(ex. "Total HT" ou "H.T. €"), jamais un total "hors éco-contribution"'
    ),
    "total_tva": "montant total de TVA tel qu'imprimé",
    "total_ttc": "total toutes taxes comprises tel qu'imprimé",
}

_DESCRIPTION_LIGNES: str = (
    "Une entrée par article ou par ligne d'éco-participation portant son "
    "propre montant dans la colonne des montants ; ne crée pas d'entrée "
    'pour une mention "Dont éco-contribution" incluse dans le montant '
    "d'une autre ligne, ni pour un commentaire ou une suite de désignation "
    "(à rattacher à la désignation de la ligne précédente)"
)

_DESCRIPTIONS_LIGNE: dict[str, str] = {
    "code": "code ou référence article tel qu'imprimé",
    "designation": "désignation de l'article telle qu'imprimée",
    # Descriptions réécrites L3-D26 (constat 11) : deux quantités distinctes
    # chez un fournisseur (conditionnements vs quantité facturée).
    "quantite_conditionnements": (
        "Nombre de conditionnements quand le document l'imprime dans une "
        "colonne distincte de la quantité facturée (ex. colonne UNITE qui "
        "contient un nombre), sinon null"
    ),
    "quantite": (
        "Quantité facturée de la ligne (celle qui multiplie le prix "
        "unitaire), nombre seul sans unité"
    ),
    "unite": (
        "Unité imprimée à côté ou en face de la quantité facturée "
        "(ex. BAG, RL, PAQ, KG), null si aucune"
    ),
    "pu_ht": "prix unitaire hors taxes tel qu'imprimé",
    "montant_ht": "montant hors taxes de la ligne tel qu'imprimé",
}

SCHEMA_ANNOTATION_BL: dict[str, Any] = {
    "type": "object",
    "properties": {
        **{
            champ: _propriete(_DESCRIPTIONS_ENTETE[champ]) for champ in CHAMPS_ENTETE_BL
        },
        "lignes": {
            "type": "array",
            "description": _DESCRIPTION_LIGNES,
            "items": {
                "type": "object",
                "properties": {
                    champ: _propriete(_DESCRIPTIONS_LIGNE[champ])
                    for champ in CHAMPS_LIGNE_BL
                },
                "required": list(CHAMPS_LIGNE_BL),
                "additionalProperties": False,
            },
        },
    },
    "required": [*CHAMPS_ENTETE_BL, "lignes"],
    "additionalProperties": False,
}

CONSIGNE_ANNOTATION_BL: str = (
    "Recopie chaque valeur exactement telle qu'elle est imprimée sur le "
    "document (mêmes caractères, virgule décimale conservée). Mets null "
    "si la valeur est absente ou illisible. N'invente, ne calcule et ne "
    "corrige aucune valeur. Ignore les mentions manuscrites."
)

OPTIONS_OCR_BL: dict[str, Any] = {
    "confidence_scores_granularity": "word",
    "document_annotation_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "bon_de_livraison",
            "schema": SCHEMA_ANNOTATION_BL,
            "strict": True,
        },
    },
    "document_annotation_prompt": CONSIGNE_ANNOTATION_BL,
}


# --------------------------------------------------------------------------
# Types lus (valeur brute, valeur convertie, confiance)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TexteLu:
    """Un champ texte de l'annotation : valeur telle qu'imprimée (`brut`,
    non convertie) et sa confiance OCR (L3-D2)."""

    brut: str | None
    confiance: Decimal | None


@dataclass(frozen=True)
class NombreLu:
    """Un champ numérique : `valeur` est `None` si `brut` est `None` ou non
    convertible par `nombre_bl` (jamais deviné)."""

    brut: str | None
    valeur: Decimal | None
    confiance: Decimal | None


@dataclass(frozen=True)
class DateLue:
    """Un champ date : `valeur` est `None` si `brut` est `None` ou non
    convertible par `date_bl`."""

    brut: str | None
    valeur: date | None
    confiance: Decimal | None


@dataclass(frozen=True)
class LigneBL:
    """Une ligne d'articles du BL, dans l'ordre des lignes gardées de
    l'annotation (`ordre`, une ligne entièrement nulle est ignorée).

    `quantite_conditionnements` (L3-D24, constat 11) : nombre de
    conditionnements (ex. 4 seaux) quand le document l'imprime dans une
    colonne distincte de `quantite`, la quantité facturée (ex. 100 kg) —
    même sens que les colonnes QTÉ LIVRÉE / QTÉ TOTALE de la facture
    Unikalo. `None` quand le document n'imprime qu'une seule quantité."""

    ordre: int
    code: TexteLu
    designation: TexteLu
    quantite_conditionnements: NombreLu
    quantite: NombreLu
    unite: TexteLu
    pu_ht: NombreLu
    montant_ht: NombreLu


@dataclass(frozen=True)
class BLExtrait:
    """Un bon de livraison entièrement lu depuis l'annotation Mistral et
    confronté au texte OCR : en-tête, lignes, et numéro détecté par le
    motif déterministe existant (`ocr.detecter_numero_bl`, indépendant de
    l'annotation — recoupement fait par `verification.py`, L3-T3)."""

    type_bon: TexteLu
    fournisseur: TexteLu
    agence_fournisseur: TexteLu
    siret: TexteLu
    tva_intracommunautaire: TexteLu
    numero: TexteLu
    date_doc: DateLue
    chantier_brut: TexteLu
    numero_commande: TexteLu
    enleve_par: TexteLu
    total_ht: NombreLu
    total_tva: NombreLu
    total_ttc: NombreLu
    lignes: tuple[LigneBL, ...]
    numero_detecte: NumeroBL | None


class AnnotationIllisible(Exception):
    """`document_annotation` inexploitable : absente, `null`, JSON invalide
    ou JSON qui n'est pas un objet. Message toujours fixe, jamais le
    contenu de l'annotation (donnée potentiellement client, CLAUDE.md)."""


# --------------------------------------------------------------------------
# Conversions déterministes (L3-D1)
# --------------------------------------------------------------------------

_ESPACES_MILLIERS = (" ", "\u202f", "\xa0")
_NOMBRE_BL_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")

# L3-T6b, fix round 1 (constat 11, gap confirmé par le contrôleur) : un bon
# d'enlèvement réel a renvoyé `total_ht` sous la forme « <nombre> € » --
# `nombre_bl` refusait ce texte, ce qui mettait un document par ailleurs bien
# lu « à vérifier » (`VALEUR_ILLISIBLE`). Un seul marqueur, en tête ou en
# queue du nombre (jamais les deux) : `€` ou `EUR`, insensible à la casse.
_MARQUEURS_DEVISE = ("EUR", "€")


def _sans_marqueur_devise(texte: str) -> str | None:
    """Retire un marqueur de devise optionnel unique, en tête ou en queue
    (jamais les deux), de `texte` (déjà débarrassé de ses espaces par
    `nombre_bl` : « 45,70 € » et « 45,70€ » sont donc indiscernables ici).

    `None` si `texte` est le marqueur seul (aucun nombre à convertir).
    Si un marqueur apparaît des deux côtés (ex. « 45,70€€ », « €45,70€ »),
    un seul est retiré ; le `€`/`EUR` résiduel fait ensuite échouer
    `_NOMBRE_BL_RE` normalement, sans logique dédiée ici. Aucun marqueur
    reconnu -> `texte` inchangé (ex. « 45,70$ », refusé plus loin)."""
    majuscule = texte.upper()
    for marqueur in _MARQUEURS_DEVISE:
        taille = len(marqueur)
        commence = majuscule.startswith(marqueur)
        finit = majuscule.endswith(marqueur)
        if commence and finit and len(texte) == taille:
            return None
        if commence:
            return texte[taille:]
        if finit:
            return texte[: len(texte) - taille]
    return texte


def nombre_bl(brut: str | None) -> Decimal | None:
    """Convertit un nombre annoté (« 1 234,56 », « 31.50 », « 4 », « -2,5 »,
    « 45,70 € », « 45,70€ », « € 45,70 », « 45,70 EUR ») en `Decimal`.
    Accepte les espaces de milliers (normale, insécable, fine insécable), un
    seul séparateur décimal (`,` ou `.`) et un marqueur de devise optionnel
    unique (`€`/`EUR`, L3-T6b fix round 1). Tout autre texte (deux
    séparateurs, lettres, devise étrangère, deux marqueurs, etc.) -> `None`,
    jamais de `float` intermédiaire, jamais deviné.
    """
    if brut is None:
        return None
    texte = brut.strip()
    if not texte:
        return None
    for espace in _ESPACES_MILLIERS:
        texte = texte.replace(espace, "")
    sans_devise = _sans_marqueur_devise(texte)
    if sans_devise is None:
        return None
    texte = sans_devise
    if _NOMBRE_BL_RE.match(texte) is None:
        return None
    return Decimal(texte.replace(",", "."))


_DATE_BL_RE = re.compile(r"^(\d{2})[./-](\d{2})[./-](\d{2}|\d{4})$")


def _sans_accents_minuscule(texte: str) -> str:
    """`texte` sans diacritiques et en minuscules (NFKD + retrait des
    caractères combinants) — module PUR : pas d'import de `normalize.texte
    .normaliser_libelle` (frontière L2-D3/L3), une copie minimale suffit
    ici (on ne réduit pas la ponctuation, seulement la casse et l'accent)."""
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c)).lower()


# Mois français en toutes lettres ou abrégés (L3-D26, constat 11 : une date
# imprimée « 27 <mois> 2026 »), sans diacritique ni casse (comparés après
# `_sans_accents_minuscule`).
_MOIS_FR: dict[str, int] = {
    "janvier": 1,
    "janv": 1,
    "fevrier": 2,
    "fevr": 2,
    "mars": 3,
    "avril": 4,
    "avr": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "juil": 7,
    "aout": 8,
    "septembre": 9,
    "sept": 9,
    "octobre": 10,
    "oct": 10,
    "novembre": 11,
    "nov": 11,
    "decembre": 12,
    "dec": 12,
}

# Jour (1 ou 2 chiffres, « 1er » accepté), mois en toutes lettres ou abrégé
# (point final toléré, consommé hors du groupe capturé), année sur 4
# chiffres, préfixe « Du » ou « le » toléré — comparaison faite sur le texte
# déjà passé par `_sans_accents_minuscule`.
_DATE_MOTS_RE = re.compile(
    r"^(?:(?:du|le)\s+)?(\d{1,2})(?:er)?\s+([a-z]+)\.?\s+(\d{4})$"
)


def _date_bl_mots(texte: str) -> date | None:
    """Date en toutes lettres (« 27 septembre 2026 », « Du 1er janv. 2026 »)
    -> `date`, `None` si le motif ne correspond pas, si le mois est inconnu,
    ou si la date est impossible (ex. « 31 février 2026 »)."""
    correspondance = _DATE_MOTS_RE.match(_sans_accents_minuscule(texte))
    if correspondance is None:
        return None
    jour_s, mois_s, annee_s = correspondance.groups()
    mois = _MOIS_FR.get(mois_s)
    if mois is None:
        return None
    try:
        return date(int(annee_s), mois, int(jour_s))
    except ValueError:
        return None


def date_bl(brut: str | None) -> date | None:
    """Convertit une date annotée `JJ/MM/AAAA` ou `JJ/MM/AA` (-> 20AA),
    séparateurs `/`, `.` ou `-` ; ou, à défaut, une date en toutes lettres
    (L3-D26, constat 11 : une des photos réelles n'imprime la date que sous
    cette forme) — voir `_date_bl_mots`. `None` si mal formée ou impossible
    (ex. « 31/02/2026 », « 31 février 2026 »).
    """
    if brut is None:
        return None
    texte = brut.strip()
    if not texte:
        return None
    correspondance = _DATE_BL_RE.match(texte)
    if correspondance is not None:
        jour_s, mois_s, annee_s = correspondance.groups()
        annee = int(annee_s) if len(annee_s) == 4 else 2000 + int(annee_s)
        try:
            return date(annee, int(mois_s), int(jour_s))
        except ValueError:
            return None
    return _date_bl_mots(texte)


def normaliser_numero_bl(brut: str | None) -> str | None:
    """Numéro de BL normalisé pour comparaison ou export
    (`extraction_en_json`) : tous les espaces retirés, majuscules. `None`
    si `brut` est `None` ou vide après normalisation.
    """
    if brut is None:
        return None
    texte = re.sub(r"\s+", "", brut).upper()
    return texte or None


_MOTIFS_ECO = (
    "ECO-PARTICIPATION",
    "ECO PARTICIPATION",
    "ECO-CONTRIBUTION",
    "ECO CONTRIBUTION",
)


def est_ligne_eco(designation: str | None) -> bool:
    """Vrai si `designation` (L3-D26, constat 11) désigne une ligne
    d'éco-participation ou d'éco-contribution portant son propre montant :
    la désignation normalisée (majuscules, sans accents) contient l'une des
    mentions `_MOTIFS_ECO`. `False` si `designation` est `None` (jamais
    deviné à partir d'un champ absent)."""
    if designation is None:
        return False
    normalisee = _sans_accents_minuscule(designation).upper()
    return any(motif in normalisee for motif in _MOTIFS_ECO)


# --------------------------------------------------------------------------
# Lecture de l'annotation
# --------------------------------------------------------------------------


def _valeur_brute(valeur: Any) -> str | None:
    """Une valeur JSON de l'annotation -> texte brut, ou `None` : absente ou
    `null` -> `None` ; chaîne blanche -> `None` (compte comme absente) ;
    nombre ou booléen (le modèle peut s'écarter du schéma malgré `strict`)
    -> `str(valeur)`.
    """
    if valeur is None:
        return None
    texte = valeur if isinstance(valeur, str) else str(valeur)
    return texte if texte.strip() else None


def _texte_lu(brut: str | None, confiance: Decimal | None) -> TexteLu:
    return TexteLu(brut=brut, confiance=confiance)


def _nombre_lu(brut: str | None, confiance: Decimal | None) -> NombreLu:
    return NombreLu(brut=brut, valeur=nombre_bl(brut), confiance=confiance)


def _date_lue(brut: str | None, confiance: Decimal | None) -> DateLue:
    return DateLue(brut=brut, valeur=date_bl(brut), confiance=confiance)


def _charger_annotation(brute: Any) -> dict[str, Any]:
    """`document_annotation` -> `dict` Python : accepte une chaîne JSON ou
    un `dict` déjà décodé (décision du contrôleur). Lève
    `AnnotationIllisible` pour toute autre forme (absente, `null`, JSON
    invalide, JSON qui n'est pas un objet).
    """
    if isinstance(brute, str):
        try:
            brute = json.loads(brute)
        except json.JSONDecodeError:
            raise AnnotationIllisible("document_annotation illisible") from None
    if not isinstance(brute, dict):
        raise AnnotationIllisible("document_annotation illisible")
    return brute


def _lire_lignes(brutes: Any, index: IndexConfiance) -> tuple[LigneBL, ...]:
    """Lignes de l'annotation -> `LigneBL` : `lignes` absente ou non liste
    -> `()` ; une entrée qui n'est pas un objet, ou dont les 7 champs
    (L3-D24 : `quantite_conditionnements` compris) sont tous vides, est
    ignorée ; `ordre` = position parmi les lignes gardées (pas l'index
    d'origine dans l'annotation).
    """
    if not isinstance(brutes, list):
        return ()

    lignes: list[LigneBL] = []
    for brute in brutes:
        if not isinstance(brute, dict):
            continue
        valeurs = [_valeur_brute(brute.get(champ)) for champ in CHAMPS_LIGNE_BL]
        if all(valeur is None for valeur in valeurs):
            continue
        confiances = confiances_ligne(index, valeurs)
        champs = dict(zip(CHAMPS_LIGNE_BL, valeurs, strict=True))
        confs = dict(zip(CHAMPS_LIGNE_BL, confiances, strict=True))
        lignes.append(
            LigneBL(
                ordre=len(lignes),
                code=_texte_lu(champs["code"], confs["code"]),
                designation=_texte_lu(champs["designation"], confs["designation"]),
                quantite_conditionnements=_nombre_lu(
                    champs["quantite_conditionnements"],
                    confs["quantite_conditionnements"],
                ),
                quantite=_nombre_lu(champs["quantite"], confs["quantite"]),
                unite=_texte_lu(champs["unite"], confs["unite"]),
                pu_ht=_nombre_lu(champs["pu_ht"], confs["pu_ht"]),
                montant_ht=_nombre_lu(champs["montant_ht"], confs["montant_ht"]),
            )
        )
    return tuple(lignes)


def analyser_bl(reponse: dict[str, Any]) -> BLExtrait:
    """Lit une réponse OCR Mistral (options `OPTIONS_OCR_BL`) en `BLExtrait`
    (L3-D1). Lève `AnnotationIllisible` si `document_annotation` est
    inexploitable ; une réponse sans `pages` donne un `BLExtrait` complet
    mais sans aucune confiance (décision du contrôleur).
    """
    annotation = _charger_annotation(reponse.get("document_annotation"))
    index = indexer_confiance(reponse)

    bruts = {champ: _valeur_brute(annotation.get(champ)) for champ in CHAMPS_ENTETE_BL}
    confiances = {
        champ: confiance_valeur(index, bruts[champ]) for champ in CHAMPS_ENTETE_BL
    }
    lignes = _lire_lignes(annotation.get("lignes"), index)
    numero_detecte = detecter_numero_bl(texte_ocr(reponse))

    return BLExtrait(
        type_bon=_texte_lu(bruts["type_bon"], confiances["type_bon"]),
        fournisseur=_texte_lu(bruts["fournisseur"], confiances["fournisseur"]),
        agence_fournisseur=_texte_lu(
            bruts["agence_fournisseur"], confiances["agence_fournisseur"]
        ),
        siret=_texte_lu(bruts["siret"], confiances["siret"]),
        tva_intracommunautaire=_texte_lu(
            bruts["tva_intracommunautaire"], confiances["tva_intracommunautaire"]
        ),
        numero=_texte_lu(bruts["numero"], confiances["numero"]),
        date_doc=_date_lue(bruts["date_doc"], confiances["date_doc"]),
        chantier_brut=_texte_lu(bruts["chantier_brut"], confiances["chantier_brut"]),
        numero_commande=_texte_lu(
            bruts["numero_commande"], confiances["numero_commande"]
        ),
        enleve_par=_texte_lu(bruts["enleve_par"], confiances["enleve_par"]),
        total_ht=_nombre_lu(bruts["total_ht"], confiances["total_ht"]),
        total_tva=_nombre_lu(bruts["total_tva"], confiances["total_tva"]),
        total_ttc=_nombre_lu(bruts["total_ttc"], confiances["total_ttc"]),
        lignes=lignes,
        numero_detecte=numero_detecte,
    )


# --------------------------------------------------------------------------
# Instantané JSON de l'extraction (L3-D5 : colonne `document.extraction`)
# --------------------------------------------------------------------------


def _espaces_reduits(brut: str | None) -> str | None:
    """Texte débarrassé des espaces multiples et de bord, sans autre
    normalisation (la casse et la ponctuation restent celles de
    l'annotation)."""
    if brut is None:
        return None
    return re.sub(r"\s+", " ", brut).strip()


def _serialiser_champ(
    nom: str, champ: TexteLu | NombreLu | DateLue
) -> dict[str, str | None]:
    """Sérialise un champ lu en `{"brut", "valeur", "confiance"}`,
    entièrement composé de chaînes ou de `None` (prêt pour `json.dumps`) :
    `Decimal` -> chaîne, `date` -> ISO, texte -> espaces multiples réduits,
    sauf `numero` -> `normaliser_numero_bl` (décision de la fiche T2).
    """
    confiance = str(champ.confiance) if champ.confiance is not None else None
    if isinstance(champ, DateLue):
        valeur = champ.valeur.isoformat() if champ.valeur is not None else None
    elif isinstance(champ, NombreLu):
        valeur = str(champ.valeur) if champ.valeur is not None else None
    elif nom == "numero":
        valeur = normaliser_numero_bl(champ.brut)
    else:
        valeur = _espaces_reduits(champ.brut)
    return {"brut": champ.brut, "valeur": valeur, "confiance": confiance}


def extraction_en_json(extrait: BLExtrait) -> dict[str, Any]:
    """Instantané JSON immuable de l'extraction (L3-D5) : valeurs brutes,
    valeurs converties et confiances, entièrement sérialisable par
    `json.dumps` (aucun `Decimal` ni `date` nu dans le résultat).
    """
    champs: dict[str, Any] = {
        nom: _serialiser_champ(nom, getattr(extrait, nom)) for nom in CHAMPS_ENTETE_BL
    }
    lignes: list[dict[str, Any]] = [
        {
            "ordre": ligne.ordre,
            **{
                nom: _serialiser_champ(nom, getattr(ligne, nom))
                for nom in CHAMPS_LIGNE_BL
            },
        }
        for ligne in extrait.lignes
    ]
    return {
        "version": 1,
        "champs": champs,
        "lignes": lignes,
        "numero_detecte": (
            extrait.numero_detecte.numero
            if extrait.numero_detecte is not None
            else None
        ),
    }
