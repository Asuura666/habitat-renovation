"""Outil de mesure du taux d'erreur OCR (`ingest/rapport_ocr.py`, L3-T11,
L3-D20) : le livrable du lot (rapport de taux d'erreur sur au moins 30 BL
réels, CDC) devient une commande dès que les photos et leurs valeurs
attendues existent, au lieu d'une mesure manuelle refaite à chaque essai.

Ce module compare, pour chaque photo d'un dossier, ce que l'annotation
Mistral OCR (`extract.bl.analyser_bl`) a lu à une valeur attendue écrite à
la main (`<nom>.attendu.json`, format figé par le contrôleur, cf.
`docs/protocole-mesure-ocr.md`), puis agrège les résultats en taux (CDC
§10 : au moins 95 % des documents avec les 4 champs justes, au moins 90 %
des lignes avec code et quantité justes, zéro erreur silencieuse).

Comme `ingest/extraction_bl.py`, ce module orchestre (`ingest` est le seul
autorisé à importer plusieurs modules métier, L2-D3) mais reste sans état
et sans écriture en base : il ne touche ni SQLAlchemy ni FastAPI, et ne
fait lui-même aucun appel réseau (R17) — `mesurer_dossier` reçoit l'OCR
comme fonction injectée (`ocr: Callable[[bytes, str], Awaitable[dict]]`,
même principe que `depot_telegram.traiter_fichier`/`ingest.router
._construire_ocr`), jamais un client HTTP construit ici.

Décisions du contrôleur (fiche L3-T11) :
- Une réponse en cache (`<nom>.mistral-ocr.json`) dont l'annotation est
  illisible compte comme un document dont les 4 champs et toutes les lignes
  sont faux, avec le seul motif `annotation_illisible` — jamais silencieux
  (un motif est posé).
- Une ligne attendue à `code: null` (éco-participation) s'apparie à la
  première ligne lue non appariée dont le code est lui aussi absent : le
  code d'appariement traite `None` comme une valeur de code comme une
  autre (`_code_normalise`).
- Le rapport Markdown peut contenir des valeurs attendues et lues (destiné
  au client, écrit là où l'utilisateur le demande) ; la sortie standard de
  la CLI n'affiche que des comptes et des taux (`app/cli.py::_rapport_ocr`).

Fix round 1 (revue de tâche, finding 1) : isolation par document. Un
`<nom>.attendu.json` invalide (JSON illisible ou `ValueError` de
`lire_attendu`), une réponse en cache invalide (JSON illisible ou JSON qui
n'est pas un objet) ou un échec d'appel `ocr` (n'importe quelle exception,
réseau ou applicative) ne font plus jamais échouer tout le lot : le
document est classé (`RapportOCR.attendus_invalides` /
`RapportOCR.echecs_ocr`, noms de fichiers seulement) et la mesure continue
sur les documents suivants. Le cache n'est jamais écrit après un échec
d'appel `ocr` (décision de la revue). Ce que cette isolation ne couvre pas
volontairement (erreur de listage du dossier, échec d'écriture du cache
après un appel `ocr` réussi) est documenté dans `docs/dette.md` (section
L3-T11).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.modules.extract.bl import AnnotationIllisible, BLExtrait, LigneBL, analyser_bl
from app.modules.extract.bl import normaliser_numero_bl as _normaliser_numero_bl
from app.modules.extract.verification import CodeMotif, bl_a_verifier, verifier_bl
from app.modules.normalize.texte import normaliser_libelle

# --------------------------------------------------------------------------
# Dataclasses (fiche L3-T11, valeurs exactes)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LigneAttendue:
    code: str | None
    quantite: Decimal | None


@dataclass(frozen=True)
class BLAttendu:
    """Valeurs attendues d'une photo, lues à la main (`<nom>.attendu.json`,
    format figé par le contrôleur — cf. `docs/protocole-mesure-ocr.md`)."""

    nom: str
    numero: str
    fournisseur: str
    date_doc: date
    chantier_brut: str
    lignes: tuple[LigneAttendue, ...]
    degradee: bool


@dataclass(frozen=True)
class ChampCompare:
    champ: str
    juste: bool
    confiance: Decimal | None


@dataclass(frozen=True)
class LigneComparee:
    code_attendu: str | None
    trouvee: bool
    juste: bool
    confiance: Decimal | None


@dataclass(frozen=True)
class ComparaisonBL:
    """Comparaison d'une photo entre attendu et lu. `motifs` : codes des
    motifs de `verifier_bl` (`+ fournisseur_inconnu` non évalué ici, cette
    résolution n'existe que dans `ingest.extraction_bl`, hors de portée
    d'une comparaison purement OCR)."""

    nom: str
    degradee: bool
    champs: tuple[ChampCompare, ...]  # numero, fournisseur, date_doc, chantier_brut
    lignes: tuple[LigneComparee, ...]
    lignes_en_trop: int
    motifs: tuple[str, ...]
    silencieuse: bool  # au moins une erreur et aucun motif


@dataclass(frozen=True)
class RapportOCR:
    nb_documents: int
    nb_degrades: int
    taux_champs: dict[str, Decimal]  # par champ, en proportion 0..1
    taux_documents_4_champs: Decimal  # documents dont les 4 champs sont justes
    taux_lignes: Decimal
    nb_erreurs_silencieuses: int
    lignes_fausses_confiance_haute: tuple[tuple[str, str | None, Decimal], ...]
    confiances_justes: tuple[Decimal, ...]
    confiances_fausses: tuple[Decimal, ...]
    documents_sans_ocr: tuple[str, ...]
    # Fix round 1 (finding 1) : documents exclus de la mesure par un
    # problème de fichier, jamais par une valeur fausse — noms de fichiers
    # seulement, jamais leur contenu.
    attendus_invalides: tuple[str, ...]  # <nom>.attendu.json illisible/mal formé
    echecs_ocr: tuple[str, ...]  # cache illisible/non-objet, ou appel `ocr` en échec


# Ordre de la fiche L3-T11 (différent de `verification.CHAMPS_OBLIGATOIRES_BL`,
# qui commence par `fournisseur` : celui-ci fait foi pour `ComparaisonBL.champs`).
CHAMPS_COMPARES: tuple[str, ...] = (
    "numero",
    "fournisseur",
    "date_doc",
    "chantier_brut",
)

_QUANTUM_TAUX = Decimal("0.0001")
# Objectifs CDC §10 (rappelés dans `rapport_markdown`), repris ici pour ne
# pas les dupliquer entre les deux fonctions.
_CDC_SEUIL_CHAMPS = Decimal("0.95")
_CDC_SEUIL_LIGNES = Decimal("0.90")


# --------------------------------------------------------------------------
# lire_attendu — `<nom>.attendu.json`
# --------------------------------------------------------------------------

_CLES_OBLIGATOIRES: tuple[str, ...] = (
    "numero",
    "fournisseur",
    "date_doc",
    "chantier_brut",
    "lignes",
    "degradee",
)


def _erreur(nom: str, message: str) -> ValueError:
    return ValueError(f"{nom} : {message}")


def _lire_chaine_non_vide(nom: str, cle: str, valeur: Any) -> str:
    if not isinstance(valeur, str) or not valeur.strip():
        raise _erreur(nom, f"'{cle}' doit être une chaîne non vide")
    return valeur


def _lire_ligne_attendue(nom: str, indice: int, donnees: Any) -> LigneAttendue:
    if not isinstance(donnees, Mapping):
        raise _erreur(nom, f"ligne {indice} mal formée (objet requis)")
    if "code" not in donnees or "quantite" not in donnees:
        raise _erreur(nom, f"ligne {indice} : clé 'code' ou 'quantite' manquante")

    code = donnees["code"]
    if code is not None and not isinstance(code, str):
        raise _erreur(nom, f"ligne {indice} : 'code' doit être une chaîne ou null")

    quantite_brute = donnees["quantite"]
    quantite: Decimal | None
    if quantite_brute is None:
        quantite = None
    elif isinstance(quantite_brute, str):
        try:
            quantite = Decimal(quantite_brute)
        except InvalidOperation:
            raise _erreur(
                nom, f"ligne {indice} : 'quantite' mal formée : {quantite_brute!r}"
            ) from None
    else:
        raise _erreur(nom, f"ligne {indice} : 'quantite' doit être une chaîne ou null")

    return LigneAttendue(code=code, quantite=quantite)


def lire_attendu(donnees: Mapping[str, Any], nom: str) -> BLAttendu:
    """`<nom>.attendu.json` (déjà décodé) -> `BLAttendu`. Lève `ValueError`
    si mal formé (clé obligatoire manquante ou de type incorrect, date non
    ISO, quantité non convertible). Une clé inconnue (ex. `total_ht`,
    facultatif et ignoré par la comparaison) n'est jamais une erreur."""
    if not isinstance(donnees, Mapping):
        raise _erreur(nom, "attendu JSON mal formé (objet requis)")

    manquantes = [cle for cle in _CLES_OBLIGATOIRES if cle not in donnees]
    if manquantes:
        raise _erreur(nom, f"clé(s) manquante(s) : {', '.join(manquantes)}")

    numero = _lire_chaine_non_vide(nom, "numero", donnees["numero"])
    fournisseur = _lire_chaine_non_vide(nom, "fournisseur", donnees["fournisseur"])
    chantier_brut = _lire_chaine_non_vide(
        nom, "chantier_brut", donnees["chantier_brut"]
    )

    degradee = donnees["degradee"]
    if not isinstance(degradee, bool):
        raise _erreur(nom, "'degradee' doit être un booléen")

    date_brute = donnees["date_doc"]
    if not isinstance(date_brute, str):
        raise _erreur(nom, "'date_doc' doit être une chaîne ISO")
    try:
        date_doc = date.fromisoformat(date_brute)
    except ValueError:
        raise _erreur(
            nom, f"'date_doc' mal formée (ISO attendu) : {date_brute!r}"
        ) from None

    lignes_brutes = donnees["lignes"]
    if not isinstance(lignes_brutes, list):
        raise _erreur(nom, "'lignes' doit être une liste")
    lignes = tuple(
        _lire_ligne_attendue(nom, indice, ligne)
        for indice, ligne in enumerate(lignes_brutes)
    )

    return BLAttendu(
        nom=nom,
        numero=numero,
        fournisseur=fournisseur,
        date_doc=date_doc,
        chantier_brut=chantier_brut,
        lignes=lignes,
        degradee=degradee,
    )


# --------------------------------------------------------------------------
# comparer_bl
# --------------------------------------------------------------------------


def _juste_numero(attendu: str, extrait: BLExtrait) -> bool:
    return _normaliser_numero_bl(attendu) == _normaliser_numero_bl(extrait.numero.brut)


def _juste_fournisseur(attendu: str, extrait: BLExtrait) -> bool:
    """Juste si tous les mots normalisés de `attendu` (décision de la fiche)
    se retrouvent dans ceux du fournisseur lu — même principe que
    `normalize.fournisseur._correspond_par_nom`, sans référentiel ici : on
    compare directement à la valeur attendue."""
    mots_attendus = set(normaliser_libelle(attendu).split())
    mots_lus = set(normaliser_libelle(extrait.fournisseur.brut).split())
    return bool(mots_attendus) and mots_attendus.issubset(mots_lus)


def _juste_chantier(attendu: str, extrait: BLExtrait) -> bool:
    return normaliser_libelle(attendu) == normaliser_libelle(extrait.chantier_brut.brut)


def _code_normalise(brut: str | None) -> str | None:
    """Code d'article normalisé pour l'appariement d'une ligne (décision de
    la fiche) : `normaliser_libelle` puis retrait des espaces (ignore la
    ponctuation et la casse d'un code comme `AB-1234`/`ab 1234`). `None` si
    `brut` est `None` ou vide après normalisation — deux lignes sans code
    s'apparient donc entre elles (première ligne lue non appariée dont le
    code est lui aussi absent)."""
    normalise = normaliser_libelle(brut).replace(" ", "")
    return normalise or None


def _confiance_ligne_lue(ligne: LigneBL) -> Decimal | None:
    """Confiance d'une ligne lue (fiche L3-T11) : minimum des confiances non
    nulles de `code` et `quantite` seulement (contrairement à
    `verification._confiance_ligne`, qui inclut aussi `montant_ht` : ce
    module ne compare que code et quantité à l'attendu). `None` si aucune
    des deux n'a de score."""
    confiances = [
        c for c in (ligne.code.confiance, ligne.quantite.confiance) if c is not None
    ]
    return min(confiances) if confiances else None


def _apparier_lignes(
    attendues: Sequence[LigneAttendue], lues: Sequence[LigneBL]
) -> tuple[tuple[LigneComparee, ...], int]:
    """Apparie chaque ligne attendue à la première ligne lue non encore
    appariée de même code normalisé (décision de la fiche, y compris quand
    les deux codes sont absents) ; `lignes_en_trop` = lignes lues jamais
    appariées."""
    disponibles: list[LigneBL] = list(lues)
    comparees: list[LigneComparee] = []
    for attendue in attendues:
        code_attendu = _code_normalise(attendue.code)
        indice = next(
            (
                i
                for i, lue in enumerate(disponibles)
                if _code_normalise(lue.code.brut) == code_attendu
            ),
            None,
        )
        if indice is None:
            comparees.append(
                LigneComparee(
                    code_attendu=attendue.code,
                    trouvee=False,
                    juste=False,
                    confiance=None,
                )
            )
            continue
        lue = disponibles.pop(indice)
        comparees.append(
            LigneComparee(
                code_attendu=attendue.code,
                trouvee=True,
                juste=lue.quantite.valeur == attendue.quantite,
                confiance=_confiance_ligne_lue(lue),
            )
        )
    return tuple(comparees), len(disponibles)


def _erreur_presente(
    champs: Sequence[ChampCompare], lignes: Sequence[LigneComparee], lignes_en_trop: int
) -> bool:
    """Au moins un champ faux, une ligne non juste (fausse ou manquante) ou
    une ligne en trop : la moitié de la définition de « erreur silencieuse »
    (l'autre moitié — aucun motif — est vérifiée par l'appelant)."""
    return (
        any(not champ.juste for champ in champs)
        or any(not ligne.juste for ligne in lignes)
        or lignes_en_trop > 0
    )


def comparer_bl(
    extrait: BLExtrait, attendu: BLAttendu, *, seuil: Decimal, tolerance: Decimal
) -> ComparaisonBL:
    """Compare un `BLExtrait` (annotation déjà lue, `extract.bl.analyser_bl`)
    à l'attendu écrit à la main. Les motifs viennent de `verifier_bl
    (bl_a_verifier(extrait), ...)` — la même vérification que
    `ingest.extraction_bl`, jamais recalculée différemment ici."""
    champs = (
        ChampCompare(
            "numero", _juste_numero(attendu.numero, extrait), extrait.numero.confiance
        ),
        ChampCompare(
            "fournisseur",
            _juste_fournisseur(attendu.fournisseur, extrait),
            extrait.fournisseur.confiance,
        ),
        ChampCompare(
            "date_doc",
            extrait.date_doc.valeur == attendu.date_doc,
            extrait.date_doc.confiance,
        ),
        ChampCompare(
            "chantier_brut",
            _juste_chantier(attendu.chantier_brut, extrait),
            extrait.chantier_brut.confiance,
        ),
    )
    lignes, lignes_en_trop = _apparier_lignes(attendu.lignes, extrait.lignes)

    motifs = tuple(
        motif.code.value
        for motif in verifier_bl(
            bl_a_verifier(extrait), seuil_confiance=seuil, tolerance=tolerance
        )
    )
    silencieuse = _erreur_presente(champs, lignes, lignes_en_trop) and not motifs

    return ComparaisonBL(
        nom=attendu.nom,
        degradee=attendu.degradee,
        champs=champs,
        lignes=lignes,
        lignes_en_trop=lignes_en_trop,
        motifs=motifs,
        silencieuse=silencieuse,
    )


def _comparaison_illisible(attendu: BLAttendu) -> ComparaisonBL:
    """Réponse en cache dont l'annotation est illisible (décision de la
    fiche) : les 4 champs et toutes les lignes comptent faux, avec le seul
    motif `annotation_illisible` — jamais silencieux (un motif est posé)."""
    champs = tuple(
        ChampCompare(champ=nom, juste=False, confiance=None) for nom in CHAMPS_COMPARES
    )
    lignes = tuple(
        LigneComparee(
            code_attendu=ligne.code, trouvee=False, juste=False, confiance=None
        )
        for ligne in attendu.lignes
    )
    motifs = (CodeMotif.ANNOTATION_ILLISIBLE.value,)
    silencieuse = _erreur_presente(champs, lignes, 0) and not motifs
    return ComparaisonBL(
        nom=attendu.nom,
        degradee=attendu.degradee,
        champs=champs,
        lignes=lignes,
        lignes_en_trop=0,
        motifs=motifs,
        silencieuse=silencieuse,
    )


# --------------------------------------------------------------------------
# agreger
# --------------------------------------------------------------------------


def _taux(numerateur: int, denominateur: int) -> Decimal:
    """Proportion `numerateur/denominateur` arrondie à 4 décimales
    (`ROUND_HALF_UP`, même quantum que `extract.confiance`) ; `0` si
    `denominateur` est nul (rien à mesurer, jamais une division par zéro)."""
    if denominateur == 0:
        return Decimal("0").quantize(_QUANTUM_TAUX)
    return (Decimal(numerateur) / Decimal(denominateur)).quantize(
        _QUANTUM_TAUX, rounding=ROUND_HALF_UP
    )


def agreger(
    comparaisons: Sequence[ComparaisonBL],
    documents_sans_ocr: Sequence[str],
    *,
    seuil: Decimal,
    attendus_invalides: Sequence[str] = (),
    echecs_ocr: Sequence[str] = (),
) -> RapportOCR:
    nb_documents = len(comparaisons)
    nb_degrades = sum(1 for comp in comparaisons if comp.degradee)

    taux_champs: dict[str, Decimal] = {}
    for nom_champ in CHAMPS_COMPARES:
        valeurs = [
            champ
            for comp in comparaisons
            for champ in comp.champs
            if champ.champ == nom_champ
        ]
        taux_champs[nom_champ] = _taux(sum(1 for v in valeurs if v.juste), len(valeurs))

    taux_documents_4_champs = _taux(
        sum(1 for comp in comparaisons if all(champ.juste for champ in comp.champs)),
        nb_documents,
    )

    toutes_lignes = [ligne for comp in comparaisons for ligne in comp.lignes]
    taux_lignes = _taux(
        sum(1 for ligne in toutes_lignes if ligne.juste), len(toutes_lignes)
    )

    nb_erreurs_silencieuses = sum(1 for comp in comparaisons if comp.silencieuse)

    lignes_fausses_confiance_haute = tuple(
        (comp.nom, ligne.code_attendu, ligne.confiance)
        for comp in comparaisons
        for ligne in comp.lignes
        if not ligne.juste and ligne.confiance is not None and ligne.confiance >= seuil
    )

    confiances_justes: list[Decimal] = []
    confiances_fausses: list[Decimal] = []
    for comp in comparaisons:
        for champ in comp.champs:
            if champ.confiance is not None:
                (confiances_justes if champ.juste else confiances_fausses).append(
                    champ.confiance
                )
        for ligne in comp.lignes:
            if ligne.confiance is not None:
                (confiances_justes if ligne.juste else confiances_fausses).append(
                    ligne.confiance
                )

    return RapportOCR(
        nb_documents=nb_documents,
        nb_degrades=nb_degrades,
        taux_champs=taux_champs,
        taux_documents_4_champs=taux_documents_4_champs,
        taux_lignes=taux_lignes,
        nb_erreurs_silencieuses=nb_erreurs_silencieuses,
        lignes_fausses_confiance_haute=lignes_fausses_confiance_haute,
        confiances_justes=tuple(sorted(confiances_justes)),
        confiances_fausses=tuple(sorted(confiances_fausses)),
        documents_sans_ocr=tuple(documents_sans_ocr),
        attendus_invalides=tuple(attendus_invalides),
        echecs_ocr=tuple(echecs_ocr),
    )


# --------------------------------------------------------------------------
# rapport_markdown
# --------------------------------------------------------------------------


def _pourcentage(taux: Decimal) -> str:
    return f"{taux * 100:.1f} %"


def _mediane(valeurs: Sequence[Decimal]) -> Decimal:
    triees = sorted(valeurs)
    milieu = len(triees) // 2
    if len(triees) % 2 == 1:
        return triees[milieu]
    return (triees[milieu - 1] + triees[milieu]) / 2


def _distribution(valeurs: Sequence[Decimal]) -> str:
    if not valeurs:
        return "aucune valeur"
    return f"min {min(valeurs)}, médiane {_mediane(valeurs)}, max {max(valeurs)}"


def rapport_markdown(rapport: RapportOCR, comparaisons: Sequence[ComparaisonBL]) -> str:
    """Rapport Markdown destiné au client (peut contenir des valeurs
    attendues et lues, décision de la fiche) : documents non mesurés,
    synthèse avec les objectifs CDC §10, détail par document, lignes
    fausses à confiance haute, distribution des confiances justes/fausses.

    Fix round 1 (finding 2, ruling R13) : dans la synthèse, seules les
    lignes « Documents avec les 4 champs justes » (≥ 95 %), « Lignes
    justes » (≥ 90 %) et « Erreurs silencieuses » (0) portent un objectif
    CDC — les quatre lignes par champ sont indicatives (elles composent le
    premier taux, mais aucune n'a individuellement d'objectif CDC séparé)."""
    lignes: list[str] = ["# Rapport de mesure du taux d'erreur OCR", ""]

    lignes.append(
        f"Documents mesurés : {rapport.nb_documents} "
        f"(dont {rapport.nb_degrades} dégradés)."
    )
    lignes.append("")

    if rapport.documents_sans_ocr or rapport.attendus_invalides or rapport.echecs_ocr:
        lignes.append("## Documents non mesurés")
        lignes.append("")
        if rapport.documents_sans_ocr:
            lignes.append(
                "- Sans réponse OCR (aucun cache, aucun appel demandé) : "
                f"{', '.join(rapport.documents_sans_ocr)}"
            )
        if rapport.attendus_invalides:
            lignes.append(
                "- Attendu invalide (`<nom>.attendu.json` illisible ou mal "
                f"formé) : {', '.join(rapport.attendus_invalides)}"
            )
        if rapport.echecs_ocr:
            lignes.append(
                "- Échec OCR (cache illisible/non-objet, ou appel à l'OCR en "
                f"échec) : {', '.join(rapport.echecs_ocr)}"
            )
        lignes.append("")

    lignes.append("## Synthèse")
    lignes.append("")
    lignes.append("| Critère | Valeur | Objectif CDC | Atteint |")
    lignes.append("| --- | --- | --- | --- |")
    for champ in CHAMPS_COMPARES:
        taux = rapport.taux_champs[champ]
        lignes.append(
            f"| Champ « {champ} » juste (indicatif) | {_pourcentage(taux)} "
            "| (indicatif) | — |"
        )
    atteint_4 = "oui" if rapport.taux_documents_4_champs >= _CDC_SEUIL_CHAMPS else "non"
    lignes.append(
        "| Documents avec les 4 champs justes | "
        f"{_pourcentage(rapport.taux_documents_4_champs)} | ≥ 95 % | {atteint_4} |"
    )
    atteint_lignes = "oui" if rapport.taux_lignes >= _CDC_SEUIL_LIGNES else "non"
    lignes.append(
        f"| Lignes justes (code et quantité) | {_pourcentage(rapport.taux_lignes)} "
        f"| ≥ 90 % | {atteint_lignes} |"
    )
    atteint_silencieuse = "oui" if rapport.nb_erreurs_silencieuses == 0 else "non"
    lignes.append(
        f"| Erreurs silencieuses | {rapport.nb_erreurs_silencieuses} | 0 | "
        f"{atteint_silencieuse} |"
    )
    lignes.append("")

    lignes.append("## Détail par document")
    lignes.append("")
    lignes.append(
        "| Document | Dégradée | Champs faux | Lignes justes | Motifs | Silencieuse |"
    )
    lignes.append("| --- | --- | --- | --- | --- | --- |")
    for comp in comparaisons:
        champs_faux = (
            ", ".join(champ.champ for champ in comp.champs if not champ.juste) or "—"
        )
        lignes_justes_txt = (
            f"{sum(1 for ligne in comp.lignes if ligne.juste)}/{len(comp.lignes)}"
        )
        motifs_txt = ", ".join(comp.motifs) or "—"
        silencieuse_txt = "oui" if comp.silencieuse else "non"
        lignes.append(
            f"| {comp.nom} | {'oui' if comp.degradee else 'non'} | {champs_faux} "
            f"| {lignes_justes_txt} | {motifs_txt} | {silencieuse_txt} |"
        )
    lignes.append("")

    lignes.append("## Lignes fausses à confiance haute")
    lignes.append("")
    if rapport.lignes_fausses_confiance_haute:
        lignes.append("| Document | Code attendu | Confiance |")
        lignes.append("| --- | --- | --- |")
        for document, code, confiance in rapport.lignes_fausses_confiance_haute:
            lignes.append(
                f"| {document} | {code if code is not None else '—'} | {confiance} |"
            )
    else:
        lignes.append("Aucune.")
    lignes.append("")

    lignes.append("## Distribution des confiances")
    lignes.append("")
    lignes.append(f"- Valeurs justes : {_distribution(rapport.confiances_justes)}")
    lignes.append(f"- Valeurs fausses : {_distribution(rapport.confiances_fausses)}")

    return "\n".join(lignes) + "\n"


# --------------------------------------------------------------------------
# mesurer_dossier
# --------------------------------------------------------------------------

_EXTENSIONS_PHOTO: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf")
_MIME_PAR_EXTENSION: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".pdf": "application/pdf",
}


@dataclass(frozen=True)
class _EntreeDossier:
    """Une photo appariée à son `<nom>.attendu.json` — chemins seulement,
    aucune lecture de contenu ici (fix round 1, finding 1) : chaque lecture
    et son décodage JSON sont isolés dans la boucle de `mesurer_dossier`,
    pour qu'un fichier invalide n'interrompe jamais la mesure des autres
    documents."""

    nom: str
    chemin_photo: Path
    chemin_attendu: Path
    chemin_cache: Path


def _lister_entrees(dossier: Path) -> list[_EntreeDossier]:
    """Photos de `dossier` appariées à un `<nom>.attendu.json` existant
    (aucune lecture de contenu, décision fix round 1 ci-dessus). Une erreur
    de listage du dossier lui-même (permissions, dossier disparu) n'est pas
    isolée : voir `docs/dette.md` (section L3-T11)."""
    entrees: list[_EntreeDossier] = []
    for photo in sorted(dossier.iterdir()):
        if not photo.is_file() or photo.suffix.lower() not in _EXTENSIONS_PHOTO:
            continue
        nom = photo.stem
        chemin_attendu = photo.with_name(f"{nom}.attendu.json")
        if not chemin_attendu.is_file():
            continue
        chemin_cache = photo.with_name(f"{nom}.mistral-ocr.json")
        entrees.append(_EntreeDossier(nom, photo, chemin_attendu, chemin_cache))
    return entrees


def _lire_json(chemin: Path) -> Any:
    """Lit et décode `chemin` en JSON. Lève `OSError` (fichier illisible)
    ou `ValueError` (dont `json.JSONDecodeError`, encodage invalide) —
    laissé à l'appelant de classer l'échec (fix round 1 : isolation par
    document, jamais une exception qui remonte jusqu'à `mesurer_dossier`)."""
    return json.loads(chemin.read_text(encoding="utf-8"))


def _ecrire_cache(chemin: Path, reponse: Mapping[str, Any]) -> None:
    chemin.write_text(json.dumps(reponse, ensure_ascii=False), encoding="utf-8")


async def _lire_attendu_isole(entree: _EntreeDossier) -> BLAttendu | None:
    """`None` si `<nom>.attendu.json` est illisible, mal encodé, JSON
    invalide, ou rejeté par `lire_attendu` (fix round 1, finding 1) —
    l'appelant classe alors le document dans `attendus_invalides`."""
    try:
        donnees = await asyncio.to_thread(_lire_json, entree.chemin_attendu)
        return lire_attendu(donnees, entree.nom)
    except (OSError, ValueError):
        return None


async def _reponse_cache_isolee(entree: _EntreeDossier) -> dict[str, Any] | None:
    """Réponse déjà en cache, ou `None` si le fichier est illisible, mal
    encodé, JSON invalide, ou si le JSON décodé n'est pas un objet (fix
    round 1, finding 1) — l'appelant classe alors le document dans
    `echecs_ocr`. Distinct de « pas de cache du tout » : voir l'appelant
    (`chemin_cache.is_file()` vérifié avant l'appel)."""
    try:
        donnees = await asyncio.to_thread(_lire_json, entree.chemin_cache)
    except (OSError, ValueError):
        return None
    return donnees if isinstance(donnees, dict) else None


async def mesurer_dossier(
    dossier: Path,
    *,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]] | None,
    seuil: Decimal,
    tolerance: Decimal,
) -> tuple[RapportOCR, list[ComparaisonBL]]:
    """Mesure le taux d'erreur OCR sur `dossier` (photos `*.jpg|*.jpeg|*.png
    |*.webp|*.heic|*.pdf` ayant un `<nom>.attendu.json`, décision de la
    fiche). Pour chaque photo : le cache `<nom>.mistral-ocr.json` est lu
    s'il existe ; sinon `ocr` est appelé si fourni (réponse écrite dans le
    cache, jamais si l'appel échoue) ; sinon le document est listé dans
    `documents_sans_ocr`, exclu du calcul des taux.

    Fix round 1 (finding 1) : un `<nom>.attendu.json` invalide part dans
    `RapportOCR.attendus_invalides` ; une réponse en cache invalide ou un
    appel `ocr` en échec partent dans `RapportOCR.echecs_ocr` — dans les
    deux cas, la mesure continue sur les documents suivants (isolation par
    document, jamais un `traceback` qui interrompt tout le lot).

    Jamais appelé sur les photos réelles ni sur un appel Mistral réel par ce
    dépôt (R17, décision du contrôleur) : `ocr` n'est construit que par
    `app/cli.py::_rapport_ocr` (`--appeler-ocr`), jamais ici."""
    entrees = await asyncio.to_thread(_lister_entrees, dossier)

    comparaisons: list[ComparaisonBL] = []
    documents_sans_ocr: list[str] = []
    attendus_invalides: list[str] = []
    echecs_ocr: list[str] = []

    for entree in entrees:
        attendu = await _lire_attendu_isole(entree)
        if attendu is None:
            attendus_invalides.append(entree.nom)
            continue

        a_un_cache = await asyncio.to_thread(entree.chemin_cache.is_file)
        if a_un_cache:
            reponse_cache = await _reponse_cache_isolee(entree)
            if reponse_cache is None:
                echecs_ocr.append(entree.nom)
                continue
            reponse = reponse_cache
        elif ocr is not None:
            contenu = await asyncio.to_thread(entree.chemin_photo.read_bytes)
            mime = _MIME_PAR_EXTENSION.get(
                entree.chemin_photo.suffix.lower(), "application/octet-stream"
            )
            try:
                reponse = await ocr(contenu, mime)
            except Exception:
                # Isolation par document (fix round 1, finding 1) : n'importe
                # quelle exception de l'appel `ocr` injecté (réseau, `ErreurOCR`
                # applicative) classe seulement ce document en échec, sans
                # jamais interrompre la mesure des documents suivants ni
                # laisser remonter une exception hors de cette fonction.
                echecs_ocr.append(entree.nom)
                continue
            await asyncio.to_thread(_ecrire_cache, entree.chemin_cache, reponse)
        else:
            documents_sans_ocr.append(entree.nom)
            continue

        try:
            extrait = analyser_bl(reponse)
        except AnnotationIllisible:
            comparaisons.append(_comparaison_illisible(attendu))
            continue

        comparaisons.append(
            comparer_bl(extrait, attendu, seuil=seuil, tolerance=tolerance)
        )

    rapport = agreger(
        comparaisons,
        documents_sans_ocr,
        seuil=seuil,
        attendus_invalides=attendus_invalides,
        echecs_ocr=echecs_ocr,
    )
    return rapport, comparaisons
