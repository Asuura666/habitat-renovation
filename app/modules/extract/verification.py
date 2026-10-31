"""Motifs de mise « à vérifier » d'un BL et d'une facture (module PUR, L3-T3).

Ce module ne décide de rien de nouveau : il applique mécaniquement les
règles déterministes du CDC §4.3/§10 (« aucune erreur silencieuse ») à
partir des valeurs déjà lues par `extract/bl.py` (L3-T2) et `extract/
confiance.py` (L3-T1), et fournit les mêmes règles pour une `Facture`
(`facture.py`/`unikalo.py`). L'IA (annotation Mistral) a extrait les
valeurs ; ce module ne fait que les contrôler (CLAUDE.md : « l'IA extrait
et normalise, elle ne décide jamais »).

`ingest` (L3-T6 et suivantes) pose lui-même quatre motifs supplémentaires,
qui n'ont pas de logique ici (`OCR_ECHEC`, `ANNOTATION_ILLISIBLE`,
`FOURNISSEUR_INCONNU`, `NUMERO_EN_DOUBLE`, L3-D3, L3-D10, L3-D11) : ils
existent dans `CodeMotif` pour que `motif_en_json`/`motif_depuis_json`
sachent les sérialiser au même format, mais ce module ne les émet jamais.

Aucune dépendance d'infrastructure (`fastapi`, `sqlalchemy`, `httpx`),
aucun log, aucun appel réseau (R17) : entrées et sorties en dataclasses.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from .bl import BLExtrait, LigneBL, normaliser_numero_bl
from .facture import Facture

# --------------------------------------------------------------------------
# Motifs (L3-D3)
# --------------------------------------------------------------------------


class CodeMotif(StrEnum):
    """Code d'un motif de mise « à vérifier » (CDC §4.3, §10)."""

    CHAMP_ABSENT = "champ_absent"
    VALEUR_ILLISIBLE = "valeur_illisible"
    CONFIANCE_FAIBLE = "confiance_faible"
    SOMME_INCOHERENTE = "somme_incoherente"
    TOTAL_ABSENT = "total_absent"
    LIGNES_ABSENTES = "lignes_absentes"
    NUMERO_INCOHERENT = "numero_incoherent"
    OCR_ECHEC = "ocr_echec"  # posé par ingest
    ANNOTATION_ILLISIBLE = "annotation_illisible"  # posé par ingest
    FOURNISSEUR_INCONNU = "fournisseur_inconnu"  # posé par ingest
    NUMERO_EN_DOUBLE = "numero_en_double"  # posé par ingest


@dataclass(frozen=True)
class Motif:
    """Un motif de mise « à vérifier », avec la justification chiffrée qui
    l'accompagne (CDC §10). `detail` n'est jamais vide pour les motifs
    chiffrés par ce module ; ses valeurs sont toujours des chaînes (`str
    (Decimal)`, sans formatage français — décision du contrôleur), jamais
    une valeur brute potentiellement client mise en forme différemment
    d'un log applicatif.

    Un `dict` n'est pas hachable : cette dataclass gelée ne l'est donc pas
    non plus (l'égalité structurelle suffit pour le test d'aller-retour
    JSON, décision du contrôleur — ne pas chercher à la rendre hachable).
    """

    code: CodeMotif
    champ: str | None
    detail: dict[str, str]


CHAMPS_OBLIGATOIRES_BL: tuple[str, ...] = (
    "fournisseur",
    "numero",
    "date_doc",
    "chantier_brut",
)
SEUIL_CONFIANCE_DEFAUT = Decimal("0.80")
TOLERANCE_TOTAL_DEFAUT = Decimal("0.05")


# --------------------------------------------------------------------------
# Vue « à vérifier » d'un BL (L3-D3)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LigneAVerifier:
    """Une ligne d'articles réduite aux valeurs dont `verifier_bl` a besoin."""

    ordre: int
    montant_ht: Decimal | None
    confiance: (
        Decimal | None
    )  # minimum des confiances non nulles de code, quantité, montant


@dataclass(frozen=True)
class BLAVerifier:
    """Vue d'un BL prête pour `verifier_bl` : valeurs converties, confiances
    et champs illisibles, indépendante de la forme exacte de `BLExtrait`
    (`verifier_bl` reste testable sans reconstruire un `BLExtrait` complet).
    """

    fournisseur: str | None
    numero: str | None
    date_doc: date | None
    chantier_brut: str | None
    total_ht: Decimal | None
    lignes: tuple[LigneAVerifier, ...]
    confiances: (
        Mapping[str, Decimal | None] | None
    )  # None : vérification structurelle seule
    illisibles: frozenset[str] = (
        frozenset()
    )  # champs au brut présent mais non convertible
    numero_detecte: str | None = None


def _confiance_ligne(ligne: LigneBL) -> Decimal | None:
    """Confiance d'une ligne (L3-D3) : minimum des confiances non nulles de
    `code`, `quantite` et `montant_ht` (la désignation, l'unité et le prix
    unitaire ne comptent pas). `None` si les trois sont nulles (aucun score
    disponible, ou aucune des trois valeurs n'a été retrouvée pour l'une
    d'elles alors que les autres n'ont pas de score — cas très improbable,
    mais on ne distingue pas ces deux origines ici)."""
    confiances = [
        c
        for c in (
            ligne.code.confiance,
            ligne.quantite.confiance,
            ligne.montant_ht.confiance,
        )
        if c is not None
    ]
    return min(confiances) if confiances else None


def bl_a_verifier(extrait: BLExtrait) -> BLAVerifier:
    """`BLExtrait` (L3-T2) -> `BLAVerifier`, prêt pour `verifier_bl` (L3-D3).

    `illisibles` ne porte que `date_doc`/`total_ht` : ce sont les deux seuls
    champs obligatoires ou chiffrés qui peuvent avoir un `brut` présent et
    une `valeur` non convertible (`fournisseur`, `chantier_brut` sont du
    texte brut toujours "convertible" ; `numero` n'a pas d'échec de
    conversion possible une fois `brut` non vide, `normaliser_numero_bl`
    ne renvoie `None` que si `brut` est `None` ou blanc, et un `brut`
    blanc a déjà été réduit à `None` en amont par `extract/bl.py`).
    """
    illisibles: set[str] = set()
    if extrait.date_doc.brut is not None and extrait.date_doc.valeur is None:
        illisibles.add("date_doc")
    if extrait.total_ht.brut is not None and extrait.total_ht.valeur is None:
        illisibles.add("total_ht")

    confiances: dict[str, Decimal | None] = {
        "fournisseur": extrait.fournisseur.confiance,
        "numero": extrait.numero.confiance,
        "date_doc": extrait.date_doc.confiance,
        "chantier_brut": extrait.chantier_brut.confiance,
        "total_ht": extrait.total_ht.confiance,
    }

    lignes = tuple(
        LigneAVerifier(
            ordre=ligne.ordre,
            montant_ht=ligne.montant_ht.valeur,
            confiance=_confiance_ligne(ligne),
        )
        for ligne in extrait.lignes
    )

    return BLAVerifier(
        fournisseur=extrait.fournisseur.brut,
        numero=normaliser_numero_bl(extrait.numero.brut),
        date_doc=extrait.date_doc.valeur,
        chantier_brut=extrait.chantier_brut.brut,
        total_ht=extrait.total_ht.valeur,
        lignes=lignes,
        confiances=confiances,
        illisibles=frozenset(illisibles),
        numero_detecte=(
            extrait.numero_detecte.numero
            if extrait.numero_detecte is not None
            else None
        ),
    )


# --------------------------------------------------------------------------
# verifier_bl (L3-D3) — ordre des règles = ordre des motifs en sortie
# --------------------------------------------------------------------------


def _motif_confiance_faible(
    champ: str, confiance: Decimal | None, seuil: Decimal
) -> Motif:
    return Motif(
        code=CodeMotif.CONFIANCE_FAIBLE,
        champ=champ,
        detail={
            "confiance": str(confiance) if confiance is not None else "inconnue",
            "seuil": str(seuil),
        },
    )


def verifier_bl(
    bl: BLAVerifier, *, seuil_confiance: Decimal, tolerance: Decimal
) -> tuple[Motif, ...]:
    """Motifs de mise « à vérifier » d'un BL, dans l'ordre de la fiche L3-T3
    (règle 1 à 4, complétée L3-T6b d'une règle 3bis `LIGNES_ABSENTES`).
    Aucune exception levée : une `BLAVerifier` incohérente (construite à la
    main, par exemple en test) produit simplement les motifs correspondants,
    jamais une erreur.
    """
    motifs: list[Motif] = []

    # 1. Champs obligatoires : absent (jamais lu) ou illisible (lu mais
    # non convertible) — `total_ht` n'est pas obligatoire mais suit la même
    # règle d'illisibilité (décision de la fiche).
    for champ in CHAMPS_OBLIGATOIRES_BL:
        if getattr(bl, champ) is None:
            code = (
                CodeMotif.VALEUR_ILLISIBLE
                if champ in bl.illisibles
                else CodeMotif.CHAMP_ABSENT
            )
            motifs.append(Motif(code=code, champ=champ, detail={"champ": champ}))
    if bl.total_ht is None and "total_ht" in bl.illisibles:
        motifs.append(
            Motif(
                code=CodeMotif.VALEUR_ILLISIBLE,
                champ="total_ht",
                detail={"champ": "total_ht"},
            )
        )

    # 2. Confiance sous le seuil — seulement si des scores sont disponibles
    # (`confiances is None` : vérification structurelle seule, ex. après
    # correction humaine, L3-D13).
    if bl.confiances is not None:
        for champ in (*CHAMPS_OBLIGATOIRES_BL, "total_ht"):
            if getattr(bl, champ) is None:
                continue
            confiance = bl.confiances.get(champ)
            if confiance is None or confiance < seuil_confiance:
                motifs.append(
                    _motif_confiance_faible(champ, confiance, seuil_confiance)
                )
        for ligne in bl.lignes:
            if ligne.confiance is None or ligne.confiance < seuil_confiance:
                motifs.append(
                    _motif_confiance_faible(
                        f"ligne:{ligne.ordre}", ligne.confiance, seuil_confiance
                    )
                )

    # 3. Réconciliation somme des lignes / total (L3-D25, constat 11 : un BL
    # sans total lu part toujours « à vérifier », qu'il ait ou non des
    # lignes chiffrées — un document mal cadré ne doit jamais produire un
    # BLExtrait silencieusement cohérent). `total_ht` illisible est déjà
    # signalé par VALEUR_ILLISIBLE (règle 1) : ne pas doubler avec
    # TOTAL_ABSENT dans ce cas.
    somme = sum(
        (ligne.montant_ht for ligne in bl.lignes if ligne.montant_ht is not None),
        Decimal("0"),
    )
    if bl.total_ht is None:
        if "total_ht" not in bl.illisibles:
            motifs.append(
                Motif(
                    code=CodeMotif.TOTAL_ABSENT,
                    champ="total_ht",
                    detail={"somme": str(somme)},
                )
            )
    else:
        ecart = somme - bl.total_ht
        if abs(ecart) > tolerance:
            motifs.append(
                Motif(
                    code=CodeMotif.SOMME_INCOHERENTE,
                    champ="total_ht",
                    detail={
                        "somme": str(somme),
                        "total": str(bl.total_ht),
                        "ecart": str(ecart),
                        "tolerance": str(tolerance),
                    },
                )
            )

    # 3bis. Aucune ligne du tout (L3-D25, constat 11 : la photo mal cadrée
    # n'a produit ni tableau ni ligne) — posé après les motifs de somme.
    if not bl.lignes:
        motifs.append(
            Motif(
                code=CodeMotif.LIGNES_ABSENTES,
                champ="lignes",
                detail={"nb_lignes": "0"},
            )
        )

    # 4. Numéro lu par l'annotation vs numéro détecté par le motif
    # déterministe existant (`ocr.detecter_numero_bl`).
    if bl.numero is not None and bl.numero_detecte is not None:
        lu = normaliser_numero_bl(bl.numero)
        detecte = normaliser_numero_bl(bl.numero_detecte)
        if lu != detecte:
            motifs.append(
                Motif(
                    code=CodeMotif.NUMERO_INCOHERENT,
                    champ="numero",
                    detail={"lu": bl.numero, "detecte": bl.numero_detecte},
                )
            )

    return tuple(motifs)


def retirer_motifs_confirmes(
    motifs: Sequence[Motif], champs_confirmes: frozenset[str]
) -> tuple[Motif, ...]:
    """Retire les motifs `CONFIANCE_FAIBLE` des champs dont la lecture est
    confirmée par ailleurs (lot 2 du 31/10/2026) : fournisseur reconnu par
    son SIREN ou sa TVA, chantier reconnu dans le référentiel. Les autres
    motifs du champ (absent, illisible, inconnu…) et ceux des autres champs
    sont conservés tels quels, dans le même ordre."""
    return tuple(
        motif
        for motif in motifs
        if not (
            motif.code is CodeMotif.CONFIANCE_FAIBLE and motif.champ in champs_confirmes
        )
    )


# --------------------------------------------------------------------------
# verifier_facture (L3-D16)
# --------------------------------------------------------------------------


def verifier_facture(facture: Facture, *, tolerance: Decimal) -> tuple[Motif, ...]:
    """Seule règle appliquée à une facture au lot 3 (L3-D16) : somme des
    `montant_ht` des blocs B.L. comparée au total HT de la facture, même
    clés de détail que pour un BL."""
    somme = sum((bloc.montant_ht for bloc in facture.blocs), Decimal("0"))
    ecart = somme - facture.total_ht
    if abs(ecart) <= tolerance:
        return ()
    return (
        Motif(
            code=CodeMotif.SOMME_INCOHERENTE,
            champ="total_ht",
            detail={
                "somme": str(somme),
                "total": str(facture.total_ht),
                "ecart": str(ecart),
                "tolerance": str(tolerance),
            },
        ),
    )


# --------------------------------------------------------------------------
# JSON (colonne `document.motifs`, L3-D5)
# --------------------------------------------------------------------------


def motif_en_json(motif: Motif) -> dict[str, Any]:
    """`Motif` -> `dict` sérialisable par `json.dumps` (aucun type qui ne
    soit pas déjà une chaîne, un `None` ou un dict de chaînes)."""
    return {
        "code": motif.code.value,
        "champ": motif.champ,
        "detail": dict(motif.detail),
    }


def motif_depuis_json(donnees: Mapping[str, Any]) -> Motif:
    """Symétrique de `motif_en_json`. Lève `ValueError` si `donnees`
    n'est pas un `Mapping`, si `code` est absent ou inconnu de `CodeMotif`,
    si `champ` n'est ni une chaîne ni `None`, ou si `detail` n'est pas un
    `dict` de chaînes — jamais d'exception d'un autre type (notamment pas
    de `TypeError` sur un `donnees` non indexable comme `None` ou une
    liste), pour que l'appelant (base de données, L3-D5) n'ait qu'une
    seule exception à traiter."""
    if not isinstance(donnees, Mapping):
        raise ValueError("motif JSON mal formé : donnees n'est pas un objet")
    try:
        code = CodeMotif(donnees["code"])
    except KeyError:
        raise ValueError("motif JSON mal formé : champ 'code' absent") from None
    except ValueError:
        raise ValueError(
            f"motif JSON mal formé : code inconnu {donnees['code']!r}"
        ) from None

    champ = donnees.get("champ")
    if champ is not None and not isinstance(champ, str):
        raise ValueError("motif JSON mal formé : 'champ' doit être une chaîne ou null")

    detail = donnees.get("detail")
    if not isinstance(detail, dict) or not all(
        isinstance(cle, str) and isinstance(valeur, str)
        for cle, valeur in detail.items()
    ):
        raise ValueError("motif JSON mal formé : 'detail' doit être un dict de chaînes")

    return Motif(code=code, champ=champ, detail=dict(detail))
