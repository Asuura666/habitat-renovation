"""Décomposition du libellé chantier fournisseur et rattachement automatique
d'un chantier (module pur, L3-D6, avenant du 27/09/2026 — décision d'Ilane,
spec §2.2-2.3).

La clé d'alias chantier est `(fournisseur_id, libellé normalisé)` : le code
chantier fournisseur ne peut pas être une clé, il change d'une commande à
l'autre (constat 6, CDC §4.4). `decomposer_chantier` isole ce code s'il
existe (un groupe final entre parenthèses) sans qu'il participe à la clé, et
normalise le reste via `normaliser_libelle`. Le libellé brut complet, lui,
reste stocké tel quel par l'appelant (`document.chantier_brut`).

Exemple public du CDC (§4.4, donnée publique, jamais une donnée client) :
« ORMEAUX (9944126862) » -> `LibelleChantier(libelle="ormeaux",
code="9944126862")`.

Le reste du module identifie automatiquement le chantier d'un bon ou d'un
bloc de facture à partir de deux sources indépendantes (nom lu sur le
document, légende Telegram) : `reconnaitre_chantier` compare un libellé à
l'ensemble des noms connus (`NomConnu`, `ressemblance` de `texte.py`) et
renvoie une `Correspondance` (vide/inconnu/reconnu/ambigu) ;
`correspondance_exacte` court-circuite la comparaison quand un alias exact
du fournisseur est déjà rattaché (score 100, comportement actuel conservé) ;
`decider_chantier` combine les deux `Correspondance` (nom lu, légende) en
une `DecisionChantier` selon la table de décision de la spec §2.3 ;
`nom_pour_creation` calcule le nom lisible d'un chantier créé
automatiquement."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .texte import normaliser_libelle, ressemblance

# `(?=$|[:\s])` : ne retire « chantier » que comme mot entier (fin de
# chaîne, « : » ou espace juste après), jamais comme simple préfixe d'un
# autre mot (« Chantiers Réunis » ne doit pas perdre son « s » initial,
# fix round 1, finding 2).
_PREFIXE_CHANTIER_RE = re.compile(r"^\s*chantier(?=$|[:\s])\s*:?\s*", re.IGNORECASE)
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


@dataclass(frozen=True)
class NomConnu:
    """Un nom d'un chantier (canonique ou alias), pour la comparaison de
    ressemblance. `chantier_id` est le chantier **effectif** : déjà redirigé
    si ce chantier a été fusionné dans un autre (les noms d'un chantier
    fusionné restent des noms de la cible)."""

    chantier_id: uuid.UUID
    libelle: str


class EtatCorrespondance(StrEnum):
    VIDE = "vide"
    INCONNU = "inconnu"
    RECONNU = "reconnu"
    AMBIGU = "ambigu"


@dataclass(frozen=True)
class Correspondance:
    etat: EtatCorrespondance
    libelle: str | None = None  # forme normalisée cherchée (None si VIDE)
    chantier_id: uuid.UUID | None = None  # RECONNU
    score: int | None = None  # RECONNU / AMBIGU : meilleur score
    candidats: tuple[uuid.UUID, ...] = ()  # AMBIGU : triés par str(uuid)


class TypeDecision(StrEnum):
    RATTACHER = "rattacher"
    CREER = "creer"
    ALERTE = "alerte"
    AUCUN = "aucun"


class SourceNom(StrEnum):
    NOM_LU = "nom_lu"
    LEGENDE = "legende"


@dataclass(frozen=True)
class DecisionChantier:
    type: TypeDecision
    chantier_id: uuid.UUID | None = None  # RATTACHER
    source: SourceNom | None = None  # RATTACHER / CREER
    candidats: tuple[uuid.UUID, ...] = ()  # ALERTE, sans doublon, ordre d'apparition
    apprendre: bool = False  # enregistrer le nom lu comme nom du chantier


def reconnaitre_chantier(
    brut: str | None, noms: Sequence[NomConnu], seuil: int
) -> Correspondance:
    """Compare le libellé décomposé de `brut` à chaque nom connu (meilleur
    score par chantier, spec §2.2). Libellé vide -> `VIDE` ; aucun nom connu
    ou meilleur score < `seuil` -> `INCONNU` ; un seul chantier au meilleur
    score -> `RECONNU` ; plusieurs chantiers différents à égalité ->
    `AMBIGU` (candidats triés par `str(uuid)`, comparaison indépendante de
    l'ordre d'insertion)."""
    decompose = decomposer_chantier(brut)
    if decompose is None:
        return Correspondance(EtatCorrespondance.VIDE)
    meilleurs: dict[uuid.UUID, int] = {}
    for nom in noms:
        score = ressemblance(decompose.libelle, nom.libelle)
        if score > meilleurs.get(nom.chantier_id, -1):
            meilleurs[nom.chantier_id] = score
    if not meilleurs:
        return Correspondance(EtatCorrespondance.INCONNU, libelle=decompose.libelle)
    meilleur = max(meilleurs.values())
    if meilleur < seuil:
        return Correspondance(EtatCorrespondance.INCONNU, libelle=decompose.libelle)
    gagnants = sorted((cid for cid, s in meilleurs.items() if s == meilleur), key=str)
    if len(gagnants) == 1:
        return Correspondance(
            EtatCorrespondance.RECONNU,
            libelle=decompose.libelle,
            chantier_id=gagnants[0],
            score=meilleur,
        )
    return Correspondance(
        EtatCorrespondance.AMBIGU,
        libelle=decompose.libelle,
        score=meilleur,
        candidats=tuple(gagnants),
    )


def correspondance_exacte(brut: str | None, chantier_id: uuid.UUID) -> Correspondance:
    """Nom lu déjà connu tel quel chez ce fournisseur (alias exact rattaché) :
    reconnu à 100 sans comparaison de ressemblance (comportement actuel
    conservé, spec §2.2)."""
    decompose = decomposer_chantier(brut)
    libelle = decompose.libelle if decompose is not None else None
    return Correspondance(
        EtatCorrespondance.RECONNU, libelle=libelle, chantier_id=chantier_id, score=100
    )


def _sans_doublon(*groupes: Sequence[uuid.UUID]) -> tuple[uuid.UUID, ...]:
    """Concatène des groupes de candidats en retirant les doublons, dans
    l'ordre d'apparition (spec §2.3 : ordre d'apparition des candidats
    d'alerte)."""
    vus: list[uuid.UUID] = []
    for groupe in groupes:
        for cid in groupe:
            if cid not in vus:
                vus.append(cid)
    return tuple(vus)


def decider_chantier(lu: Correspondance, legende: Correspondance) -> DecisionChantier:
    """Table de décision de la spec §2.3 (avenant du 27/09/2026, décision
    d'Ilane) — un test par ligne dans `tests/test_chantier.py`. Les gardes
    explicites sur `chantier_id` (au lieu d'`assert`) remplacent le typage
    par narrowing : `S101` (flake8-bandit) interdit `assert` hors tests.
    (`R`/`A`/`I` du brief renommés : `E741` interdit `I`, ambigu avec `l`/`1`.)
    """
    RECONNU, AMBIGU, INCONNU = (
        EtatCorrespondance.RECONNU,
        EtatCorrespondance.AMBIGU,
        EtatCorrespondance.INCONNU,
    )
    if lu.etat is RECONNU:
        lu_id = lu.chantier_id
        if lu_id is None:
            raise ValueError("Correspondance RECONNU sans chantier_id")
        if legende.etat is RECONNU and legende.chantier_id != lu_id:
            return DecisionChantier(
                TypeDecision.ALERTE,
                candidats=_sans_doublon(
                    (lu_id,),
                    (legende.chantier_id,) if legende.chantier_id else (),
                ),
            )
        if legende.etat is AMBIGU and lu_id not in legende.candidats:
            return DecisionChantier(
                TypeDecision.ALERTE,
                candidats=_sans_doublon((lu_id,), legende.candidats),
            )
        return DecisionChantier(
            TypeDecision.RATTACHER,
            chantier_id=lu_id,
            source=SourceNom.NOM_LU,
            apprendre=True,
        )
    if lu.etat is AMBIGU:
        extra = (
            (legende.chantier_id,)
            if legende.etat is RECONNU and legende.chantier_id
            else ()
        )
        return DecisionChantier(
            TypeDecision.ALERTE, candidats=_sans_doublon(lu.candidats, extra)
        )
    if lu.etat is INCONNU:
        if legende.etat is RECONNU:
            return DecisionChantier(
                TypeDecision.RATTACHER,
                chantier_id=legende.chantier_id,
                source=SourceNom.LEGENDE,
                apprendre=True,
            )
        if legende.etat is AMBIGU:
            return DecisionChantier(TypeDecision.ALERTE, candidats=legende.candidats)
        return DecisionChantier(
            TypeDecision.CREER, source=SourceNom.NOM_LU, apprendre=True
        )
    # lu.etat is EtatCorrespondance.VIDE
    if legende.etat is RECONNU:
        return DecisionChantier(
            TypeDecision.RATTACHER,
            chantier_id=legende.chantier_id,
            source=SourceNom.LEGENDE,
        )
    if legende.etat is INCONNU:
        return DecisionChantier(TypeDecision.CREER, source=SourceNom.LEGENDE)
    if legende.etat is AMBIGU:
        return DecisionChantier(TypeDecision.ALERTE, candidats=legende.candidats)
    return DecisionChantier(TypeDecision.AUCUN)


def nom_pour_creation(brut: str | None) -> str | None:
    """Nom lisible d'un chantier créé automatiquement : le brut sans le
    préfixe « chantier : » ni le code final entre parenthèses, casse d'origine
    conservée, espaces réduits. `None` s'il ne reste rien (spec §2.3,
    « Création »)."""
    if brut is None:
        return None
    sans_prefixe = _PREFIXE_CHANTIER_RE.sub("", brut)
    code = _CODE_FINAL_RE.search(sans_prefixe)
    reste = sans_prefixe[: code.start()] if code is not None else sans_prefixe
    nom = " ".join(reste.split())
    return nom or None
