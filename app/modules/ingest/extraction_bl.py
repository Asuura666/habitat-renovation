"""Extraction et enregistrement d'un bon de livraison (`ingest/extraction_bl.py`,
L3-T6) : cœur de l'orchestration du lot 3.

À partir d'une réponse OCR Mistral (options `extract.bl.OPTIONS_OCR_BL`,
annotation structurée + scores de confiance par mot), ce module lit le BL
avec les modules purs (`extract.bl.analyser_bl`, `extract.verification
.verifier_bl`), résout fournisseur/agence/chantier/articles via
`ingest.referentiels`, puis persiste tout : colonnes de `document`
(migration 0005, L3-D5), lignes, instantané immuable de l'extraction
(`document.extraction`), motifs courants (`document.motifs`), statut, et une
entrée `journal` (`action="extraction_bl"`, `utilisateur_id=NULL` : résolution
automatique, comme `depot_telegram`/`referentiels.resoudre_chantier`).

Deux points d'entrée, appelés par `depot_telegram._executer_ocr` :
- `enregistrer_extraction_bl` : chemin normal, et relance (`relance=True`,
  L3-D15 — le document reste `a_verifier` même sans motif, décision du
  contrôleur : seul « Valider » le repasse `recu`) ;
- `enregistrer_echec_ocr` : l'appel OCR lui-même a échoué, ou sa réponse est
  structurellement inexploitable (L3-D10 : le document ne reste plus jamais
  `recu` sans extraction, contrairement au lot 2).

Une `document_annotation` illisible (`AnnotationIllisible`, L3-T2) n'est pas
un échec d'OCR : le texte OCR existe, seule l'annotation ne l'est pas. Le
motif déterministe existant (`extract.ocr.detecter_numero_bl`, indépendant de
l'annotation) reste la seule source du numéro dans ce cas (L3-D3).

Aucun fournisseur, aucune agence, aucun chantier n'est jamais créé
automatiquement à partir du texte OCR (Q7/L3-D8, L3-D7) — seuls les articles
le sont (L3-D9, non validés).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extract.bl import (
    AnnotationIllisible,
    BLExtrait,
    analyser_bl,
    extraction_en_json,
    normaliser_numero_bl,
)
from app.modules.extract.ocr import TypeBL, detecter_numero_bl, texte_ocr
from app.modules.extract.verification import (
    CHAMPS_OBLIGATOIRES_BL,
    SEUIL_CONFIANCE_DEFAUT,
    TOLERANCE_TOTAL_DEFAUT,
    CodeMotif,
    Motif,
    bl_a_verifier,
    motif_en_json,
    verifier_bl,
)
from app.modules.ingest.models import Document, Journal, Ligne
from app.modules.ingest.referentiels import (
    charger_agences,
    charger_fournisseurs,
    lire_parametre_decimal,
    rattacher_article,
    resoudre_chantier,
)
from app.modules.normalize.article import proposer_article_bl
from app.modules.normalize.fournisseur import resoudre_agence, resoudre_fournisseur
from app.modules.normalize.texte import normaliser_libelle

# L3-D4 : clés `parametre` des seuils modifiables par l'admin (écran de
# paramétrage au lot 5), valeurs par défaut de `extract/verification.py`.
CLE_SEUIL_CONFIANCE_OCR = "seuil_confiance_ocr"
CLE_TOLERANCE_TOTAL_HT = "tolerance_total_ht"


@dataclass(frozen=True)
class ResultatExtraction:
    """Issue d'`enregistrer_extraction_bl`/`enregistrer_echec_ocr`, pour la
    ligne de supervision (`depot_telegram._ligne_supervision`) sans relire le
    document en base une nouvelle fois. `fournisseur_nom` est toujours le nom
    du référentiel (`Fournisseur.nom`), jamais le brut lu (décision du
    contrôleur)."""

    numero: str | None
    statut: str
    fournisseur_nom: str | None
    chantier_brut: str | None
    nb_motifs: int


def _resultat_document_introuvable() -> ResultatExtraction:
    """Document supprimé entre son insertion et l'exécution de cette
    fonction (cas défensif, jamais rencontré en pratique) : rien n'est écrit,
    même résultat neutre que l'ancien comportement de `_executer_ocr`."""
    return ResultatExtraction(
        numero=None,
        statut="recu",
        fournisseur_nom=None,
        chantier_brut=None,
        nb_motifs=0,
    )


def _type_document(extrait: BLExtrait) -> str:
    """Type du document (L3-D12) : motif déterministe `detecter_numero_bl`
    d'abord (indépendant de l'annotation, donc plus fiable), sinon le champ
    `type_bon` de l'annotation, sinon `bl` par défaut."""
    if extrait.numero_detecte is not None:
        return extrait.numero_detecte.type_bl.value
    normalise = normaliser_libelle(extrait.type_bon.brut)
    if normalise == "enlevement":
        return TypeBL.ENLEVEMENT.value
    return TypeBL.LIVRAISON.value


async def _numero_interne_doublon(
    session: AsyncSession,
    document_id: uuid.UUID,
    fournisseur_id: uuid.UUID | None,
    numero: str,
) -> int | None:
    """Numéro interne d'un autre document portant déjà `numero` pour le même
    `fournisseur_id` (L3-D11), tous types et statuts confondus, archivés
    compris (décision du contrôleur : la contrainte d'unicité
    `(fournisseur_id, numero)` ne les distingue pas). `fournisseur_id` peut
    être `None` (fournisseur non résolu) : deux documents sans fournisseur
    résolu partageant le même numéro sont alors traités eux aussi comme un
    doublon (même mécanisme, réutilisé par l'annotation illisible)."""
    resultat = await session.execute(
        select(Document.numero_interne).where(
            Document.fournisseur_id == fournisseur_id,
            Document.numero == numero,
            Document.id != document_id,
        )
    )
    return resultat.scalars().first()


async def _enregistrer_annotation_illisible(
    session: AsyncSession, document: Document, reponse: dict[str, Any]
) -> ResultatExtraction:
    """`AnnotationIllisible` (L3-D3/L3-D10) : aucune extraction n'est
    possible, seul le numéro éventuellement détecté par le motif
    déterministe existant (`detecter_numero_bl`, indépendant de l'annotation)
    est conservé. Le doublon est traité par le même mécanisme que le flux
    principal (L3-D11), avec `fournisseur_id=None` (jamais résolu ici, faute
    d'annotation à lire)."""
    numero_detecte = detecter_numero_bl(texte_ocr(reponse))
    numero: str | None = numero_detecte.numero if numero_detecte is not None else None

    motifs: list[Motif] = [
        Motif(code=CodeMotif.ANNOTATION_ILLISIBLE, champ=None, detail={})
    ]

    if numero is not None:
        numero_interne_existant = await _numero_interne_doublon(
            session, document.id, None, numero
        )
        if numero_interne_existant is not None:
            motifs.append(
                Motif(
                    code=CodeMotif.NUMERO_EN_DOUBLE,
                    champ="numero",
                    detail={
                        "numero": numero,
                        "numero_interne_existant": str(numero_interne_existant),
                    },
                )
            )
            numero = None

    if numero is not None and numero_detecte is not None:
        document.numero = numero
        document.type = numero_detecte.type_bl.value

    document.ocr_brut = reponse
    document.extraction = {
        "version": 1,
        "champs": {},
        "lignes": [],
        "numero_detecte": (
            numero_detecte.numero if numero_detecte is not None else None
        ),
        "motifs": [motif_en_json(m) for m in motifs],
    }
    document.motifs = [motif_en_json(m) for m in motifs]
    document.confiance_min = None
    document.statut = "a_verifier"

    session.add(
        Journal(
            utilisateur_id=None,
            action="extraction_bl",
            cible_table="document",
            cible_id=str(document.id),
            avant=None,
            apres={
                "statut": "a_verifier",
                "nb_lignes": 0,
                "motifs": [m.code.value for m in motifs],
                "fournisseur_id": None,
                "methode_fournisseur": None,
                "chantier_libelle": None,
                "chantier_id": None,
                "methode_chantier": None,
            },
        )
    )

    await session.commit()

    return ResultatExtraction(
        numero=document.numero,
        statut="a_verifier",
        fournisseur_nom=None,
        chantier_brut=None,
        nb_motifs=len(motifs),
    )


async def enregistrer_extraction_bl(
    session: AsyncSession,
    document_id: uuid.UUID,
    reponse: dict[str, Any],
    *,
    relance: bool = False,
) -> ResultatExtraction:
    """Lit, contrôle et persiste l'extraction complète d'un BL (L3-T6),
    dans une transaction (commit à la fin, quel que soit le chemin suivi).

    `relance` (L3-D15, `POST /api/documents/{id}/extraction`) : le document
    reste `a_verifier` même sans aucun motif — seul « Valider »
    (`ingest/corrections.py`, L3-T8a) le repasse `recu`.
    """
    document = await session.get(Document, document_id)
    if document is None:
        return _resultat_document_introuvable()

    seuil = await lire_parametre_decimal(
        session, CLE_SEUIL_CONFIANCE_OCR, SEUIL_CONFIANCE_DEFAUT
    )
    tolerance = await lire_parametre_decimal(
        session, CLE_TOLERANCE_TOTAL_HT, TOLERANCE_TOTAL_DEFAUT
    )
    # Une relance (L3-D15) comme un premier passage remplacent entièrement
    # les lignes existantes — y compris quand l'annotation s'avère illisible.
    await session.execute(delete(Ligne).where(Ligne.document_id == document_id))

    try:
        extrait = analyser_bl(reponse)
    except AnnotationIllisible:
        return await _enregistrer_annotation_illisible(session, document, reponse)

    referentiel = await charger_fournisseurs(session)
    resolution_fournisseur = resoudre_fournisseur(
        siret=extrait.siret.brut,
        tva=extrait.tva_intracommunautaire.brut,
        nom=extrait.fournisseur.brut,
        referentiel=referentiel,
    )
    fournisseur_id = resolution_fournisseur.fournisseur_id
    fournisseur_nom = (
        next((f.nom for f in referentiel if f.id == fournisseur_id), None)
        if fournisseur_id is not None
        else None
    )

    agence_id: uuid.UUID | None = None
    if fournisseur_id is not None:
        agences = await charger_agences(session, fournisseur_id)
        agence_id = resoudre_agence(extrait.agence_fournisseur.brut, agences)

    vue = bl_a_verifier(extrait)
    motifs: list[Motif] = list(
        verifier_bl(vue, seuil_confiance=seuil, tolerance=tolerance)
    )
    if extrait.fournisseur.brut is not None and fournisseur_id is None:
        # Seulement si le brut est présent : sinon `verifier_bl` a déjà posé
        # `champ_absent` pour `fournisseur` (décision du contrôleur).
        motifs.append(
            Motif(
                code=CodeMotif.FOURNISSEUR_INCONNU,
                champ="fournisseur",
                detail={"brut_present": "oui"},
            )
        )

    type_doc = _type_document(extrait)
    numero = normaliser_numero_bl(extrait.numero.brut)
    if numero is None and extrait.numero_detecte is not None:
        numero = extrait.numero_detecte.numero

    if numero is not None:
        numero_interne_existant = await _numero_interne_doublon(
            session, document_id, fournisseur_id, numero
        )
        if numero_interne_existant is not None:
            motifs.append(
                Motif(
                    code=CodeMotif.NUMERO_EN_DOUBLE,
                    champ="numero",
                    detail={
                        "numero": numero,
                        "numero_interne_existant": str(numero_interne_existant),
                    },
                )
            )
            numero = None

    chantier_id: uuid.UUID | None = None
    chantier_libelle: str | None = None
    methode_chantier: str | None = None
    if fournisseur_id is not None:
        resolution_chantier = await resoudre_chantier(
            session, fournisseur_id, extrait.chantier_brut.brut
        )
        chantier_id = resolution_chantier.chantier_id
        chantier_libelle = resolution_chantier.libelle
        if chantier_libelle is not None:
            methode_chantier = "alias"

    confiances_champs = (
        getattr(extrait, champ).confiance for champ in CHAMPS_OBLIGATOIRES_BL
    )
    confiances_non_nulles: list[Decimal] = [
        c
        for c in (
            *confiances_champs,
            extrait.total_ht.confiance,
            *(ligne.confiance for ligne in vue.lignes),
        )
        if c is not None
    ]
    confiance_min = min(confiances_non_nulles) if confiances_non_nulles else None

    statut = "a_verifier" if relance or motifs else "recu"

    document.type = type_doc
    document.numero = numero
    document.fournisseur_id = fournisseur_id
    document.agence_fournisseur_id = agence_id
    document.date_doc = extrait.date_doc.valeur
    document.chantier_brut = extrait.chantier_brut.brut
    document.chantier_id = chantier_id
    document.numero_commande = extrait.numero_commande.brut
    document.enleve_par = extrait.enleve_par.brut
    document.total_ht = extrait.total_ht.valeur
    document.total_tva = extrait.total_tva.valeur
    document.total_ttc = extrait.total_ttc.valeur
    document.ocr_brut = reponse
    document.extraction = {
        **extraction_en_json(extrait),
        "motifs": [motif_en_json(m) for m in motifs],
    }
    document.motifs = [motif_en_json(m) for m in motifs]
    document.confiance_min = confiance_min
    document.statut = statut

    for ligne_extraite, ligne_vue in zip(extrait.lignes, vue.lignes, strict=True):
        article_id: uuid.UUID | None = None
        if fournisseur_id is not None:
            proposition = proposer_article_bl(
                ligne_extraite.code.brut,
                ligne_extraite.designation.brut,
                ligne_extraite.unite.brut,
            )
            article_id = await rattacher_article(session, fournisseur_id, proposition)
        session.add(
            Ligne(
                document_id=document_id,
                type_ligne="article",
                code_brut=ligne_extraite.code.brut,
                article_brut=ligne_extraite.designation.brut,
                article_id=article_id,
                qte_livree=ligne_extraite.quantite.valeur,
                unite_brut=ligne_extraite.unite.brut,
                pu_ht=ligne_extraite.pu_ht.valeur,
                montant_ht=ligne_extraite.montant_ht.valeur,
                confiance=ligne_vue.confiance,
                ordre=ligne_extraite.ordre,
            )
        )

    session.add(
        Journal(
            utilisateur_id=None,
            action="extraction_bl",
            cible_table="document",
            cible_id=str(document_id),
            avant=None,
            apres={
                "statut": statut,
                "nb_lignes": len(extrait.lignes),
                "motifs": [m.code.value for m in motifs],
                "fournisseur_id": (
                    str(fournisseur_id) if fournisseur_id is not None else None
                ),
                "methode_fournisseur": (
                    resolution_fournisseur.methode.value
                    if resolution_fournisseur.methode is not None
                    else None
                ),
                "chantier_libelle": chantier_libelle,
                "chantier_id": str(chantier_id) if chantier_id is not None else None,
                "methode_chantier": methode_chantier,
            },
        )
    )

    await session.commit()

    return ResultatExtraction(
        numero=document.numero,
        statut=document.statut,
        fournisseur_nom=fournisseur_nom,
        chantier_brut=extrait.chantier_brut.brut,
        nb_motifs=len(motifs),
    )


async def enregistrer_echec_ocr(
    session: AsyncSession, document_id: uuid.UUID
) -> ResultatExtraction:
    """L'appel OCR lui-même a échoué, ou sa réponse est structurellement
    inexploitable (`depot_telegram._executer_ocr`) : le document part
    `a_verifier` avec le seul motif `OCR_ECHEC` (L3-D10 — plus jamais `recu`
    sans extraction, contrairement au lot 2), sans toucher aux colonnes
    d'extraction (aucune réponse OCR à en tirer)."""
    document = await session.get(Document, document_id)
    if document is None:
        return _resultat_document_introuvable()

    motif = Motif(code=CodeMotif.OCR_ECHEC, champ=None, detail={})
    document.statut = "a_verifier"
    document.motifs = [motif_en_json(motif)]

    session.add(
        Journal(
            utilisateur_id=None,
            action="extraction_bl",
            cible_table="document",
            cible_id=str(document_id),
            avant=None,
            apres={"motifs": [motif.code.value]},
        )
    )

    await session.commit()

    return ResultatExtraction(
        numero=document.numero,
        statut="a_verifier",
        fournisseur_nom=None,
        chantier_brut=None,
        nb_motifs=1,
    )
