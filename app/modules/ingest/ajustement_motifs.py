"""Ajustement des motifs « à vérifier » d'un bon une fois ses référentiels
résolus (lot 2 du 31/10/2026, décisions d'Ilane).

`verifier_bl` (module pur) ne connaît que la lecture : un nom mal lu par
l'OCR donne un motif « lecture incertaine ». Mais quand le référentiel
confirme la lecture, ce motif ne sert plus à rien et encombre « À régler » :

- fournisseur reconnu par son SIREN ou sa TVA (pas par son nom) : le motif de
  confiance du champ `fournisseur` est retiré ;
- chantier reconnu dans le référentiel (nom connu, ressemblance) : le motif de
  confiance du champ `chantier_brut` est retiré, sauf si le chantier retenu est
  « à compléter » (un chantier créé automatiquement ne confirme pas une
  lecture) ;
- chantier vide retrouvé par la « Référence commande client » : le motif
  d'absence du champ `chantier_brut` est retiré ; si la référence ne
  correspond à aucun chantier connu, il est remplacé par un motif qui la
  nomme (`reference_chantier_inconnue`) -- aucun chantier n'est créé ;
- chantier donné par la légende de l'employé : le chantier est identifié, les
  motifs de confiance et d'absence du champ `chantier_brut` sont retirés
  (même garde).

Une seule fonction, `ajuster_motifs`, appelée par l'extraction d'un bon
(`extraction_bl`) ; la relance d'extraction et la commande de recalcul passent
par ce même chemin. Chaque motif levé est rendu avec sa raison, pour le
journal et l'historique du bon à l'écran.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.extract.verification import (
    CodeMotif,
    Motif,
    retirer_motifs_confirmes,
)
from app.modules.ingest.rattachement_chantier import ResultatRattachement
from app.modules.normalize.fournisseur import MethodeFournisseur

_RAISON_FOURNISSEUR = {
    MethodeFournisseur.SIRET: "Fournisseur confirmé par son SIREN",
    MethodeFournisseur.TVA: "Fournisseur confirmé par son numéro de TVA",
}


@dataclass(frozen=True)
class MotifsAjustes:
    motifs: tuple[Motif, ...]
    # Une entrée par champ dont un motif a été levé : `{"champ", "raison"}`
    # (la raison est la phrase affichée telle quelle dans le journal).
    leves: tuple[dict[str, str], ...]


def ajuster_motifs(
    motifs: Sequence[Motif],
    *,
    methode_fournisseur: MethodeFournisseur | None,
    chantier: ResultatRattachement | None = None,
) -> MotifsAjustes:
    """Motifs restants après confirmation de la lecture par les référentiels,
    et les motifs levés avec leur raison (jamais d'entrée si rien n'a été
    retiré)."""
    restants = tuple(motifs)
    leves: list[dict[str, str]] = []

    raison = (
        _RAISON_FOURNISSEUR.get(methode_fournisseur)
        if methode_fournisseur is not None
        else None
    )
    if raison is not None:
        apres = retirer_motifs_confirmes(restants, frozenset({"fournisseur"}))
        if len(apres) != len(restants):
            leves.append({"champ": "fournisseur", "raison": raison})
        restants = apres

    if (
        chantier is not None
        and chantier.chantier_id is not None
        and chantier.chantier_nom is not None
        and not chantier.chantier_a_completer
        and chantier.methode in ("nom connu", "ressemblance", "légende")
    ):
        legende = chantier.methode == "légende"
        codes = {CodeMotif.CONFIANCE_FAIBLE}
        if legende:
            codes.add(CodeMotif.CHAMP_ABSENT)
        apres = tuple(
            m for m in restants if not (m.champ == "chantier_brut" and m.code in codes)
        )
        if len(apres) != len(restants):
            if legende:
                raison_chantier = (
                    f"Chantier donné par la légende : {chantier.chantier_nom}"
                )
            else:
                score = chantier.score if chantier.score is not None else 100
                raison_chantier = (
                    f"Lecture du chantier confirmée : "
                    f"{chantier.chantier_nom} ({score} %)"
                )
            leves.append({"champ": "chantier_brut", "raison": raison_chantier})
        restants = apres

    if (
        chantier is not None
        and chantier.methode == "décision humaine conservée"
        and chantier.chantier_nom is not None
    ):
        # Un humain a choisi : pas de garde « à compléter ».
        apres = tuple(
            m
            for m in restants
            if not (
                m.champ == "chantier_brut"
                and m.code in (CodeMotif.CONFIANCE_FAIBLE, CodeMotif.CHAMP_ABSENT)
            )
        )
        if len(apres) != len(restants):
            leves.append(
                {
                    "champ": "chantier_brut",
                    "raison": f"Chantier choisi à la main : {chantier.chantier_nom}",
                }
            )
        restants = apres
    elif chantier is not None and chantier.methode == "référence de commande":
        if chantier.chantier_nom is not None:
            apres = tuple(
                m
                for m in restants
                if not (m.champ == "chantier_brut" and m.code is CodeMotif.CHAMP_ABSENT)
            )
            if len(apres) != len(restants):
                leves.append(
                    {
                        "champ": "chantier_brut",
                        "raison": "Chantier retrouvé par la référence de commande : "
                        + chantier.chantier_nom,
                    }
                )
            restants = apres
    elif chantier is not None and chantier.reference_inconnue is not None:
        detail = {"reference": chantier.reference_inconnue}
        if chantier.reference_candidats:
            detail["candidats"] = ", ".join(chantier.reference_candidats)
        restants = tuple(
            Motif(
                code=CodeMotif.REFERENCE_CHANTIER_INCONNUE,
                champ="chantier_brut",
                detail=detail,
            )
            if m.champ == "chantier_brut" and m.code is CodeMotif.CHAMP_ABSENT
            else m
            for m in restants
        )

    return MotifsAjustes(motifs=restants, leves=tuple(leves))


def motifs_chantier_apres_correction(
    motifs: Sequence[Motif],
    *,
    chantier_brut: str | None,
    chantier_identifie: bool,
    motif_reference_precedent: Motif | None,
) -> tuple[Motif, ...]:
    """Motifs recalculés après une correction humaine (`verifier_bl` sans les
    confiances) : sans nom écrit sur le bon, `champ_absent` revient à chaque
    recalcul. Si le chantier a pourtant été identifié (référence de commande,
    légende), il ne manque plus ; sinon, si une référence de commande inconnue
    avait été signalée, ce motif est conservé à sa place."""
    if chantier_brut is not None and chantier_brut.strip():
        return tuple(motifs)
    resultat: list[Motif] = []
    for motif in motifs:
        if motif.champ == "chantier_brut" and motif.code is CodeMotif.CHAMP_ABSENT:
            if chantier_identifie:
                continue
            if motif_reference_precedent is not None:
                resultat.append(motif_reference_precedent)
                continue
        resultat.append(motif)
    return tuple(resultat)
