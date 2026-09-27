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

Ajustements L3-T6b (constat 11, premier essai réel) : `Ligne.qte_livree` /
`Ligne.qte_totale` reprennent respectivement `quantite_conditionnements` et
`quantite` de la ligne extraite (L3-D24 — même sens que les colonnes QTÉ
LIVRÉE / QTÉ TOTALE de la facture Unikalo, pour la comparaison du lot 4) ;
une ligne d'éco-participation (`extract.bl.est_ligne_eco`) est typée `eco`
et ne déclenche jamais de proposition d'article (L3-D26).

Concurrence (fix round 1, finding 3) : deux dépôts du même numéro pour le
même fournisseur, traités en même temps, peuvent tous les deux passer
`_numero_interne_doublon` avant que l'un des deux commit — le second lève
alors `IntegrityError` sur `UniqueConstraint("fournisseur_id", "numero")`
plutôt que de produire le motif applicatif `NUMERO_EN_DOUBLE`.
`enregistrer_extraction_bl` rejoue alors l'extraction une seule fois après
`rollback` : la ligne concurrente est désormais visible en base,
`_numero_interne_doublon` la trouve et pose `NUMERO_EN_DOUBLE` normalement.
Un second `IntegrityError` (course encore plus improbable) n'est pas
rattrapé : il remonte à `depot_telegram._executer_ocr`, dont le garde-fou
R5 prend le relais (`enregistrer_echec_ocr`).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extract.bl import (
    AnnotationIllisible,
    BLExtrait,
    analyser_bl,
    est_ligne_eco,
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
from app.modules.ingest.rapprochement import rapprocher_factures_du_bl
from app.modules.ingest.rattachement_chantier import rattacher_chantier_document
from app.modules.ingest.referentiels import (
    charger_agences,
    charger_fournisseurs,
    lire_parametre_decimal,
    rattacher_article,
)
from app.modules.normalize.article import proposer_article_bl
from app.modules.normalize.chantier import decomposer_chantier
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
    principal (L3-D11), avec `document.fournisseur_id` (Ruling R11, revue
    L3-T8a) : jamais résolu par cette branche elle-même (faute d'annotation à
    lire), mais une **relance** (`enregistrer_extraction_bl(...,
    relance=True)`) garde le `fournisseur_id` déjà résolu ou corrigé avant —
    un `fournisseur_id=None` figé ici manquerait alors un doublon réel et
    ferait échouer le commit sur l'unicité `(fournisseur_id, numero)` avec
    une `IntegrityError` brute plutôt que le motif applicatif attendu."""
    numero_detecte = detecter_numero_bl(texte_ocr(reponse))
    numero: str | None = numero_detecte.numero if numero_detecte is not None else None

    motifs: list[Motif] = [
        Motif(code=CodeMotif.ANNOTATION_ILLISIBLE, champ=None, detail={})
    ]

    if numero is not None:
        numero_interne_existant = await _numero_interne_doublon(
            session, document.id, document.fournisseur_id, numero
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


async def _avec_reprise_doublon(
    session: AsyncSession,
    document_id: uuid.UUID,
    executer: Callable[[], Awaitable[ResultatExtraction]],
) -> ResultatExtraction:
    """Rejoue une seule fois `executer` (qui doit committer) si son commit
    lève `IntegrityError` (Finding 3, fix round 1 ; Ruling R11, revue
    L3-T8a) : partagé par le flux principal (`_extraire_et_committer`) et
    l'annotation illisible (`_enregistrer_annotation_illisible`) — dans les
    deux cas, une course entre deux écritures concurrentes du même
    `(fournisseur_id, numero)` peut faire manquer le contrôle applicatif de
    doublon avant que l'une des deux commit ; après `rollback`, la ligne
    concurrente est désormais visible et `_numero_interne_doublon` la
    détecte normalement. Un second échec (course encore plus improbable)
    n'est pas rattrapé, il remonte tel quel."""
    try:
        return await executer()
    except IntegrityError:
        await session.rollback()
        # Les lignes supprimées avant la première tentative ont, elles
        # aussi, été annulées par le `rollback` : on les resupprime avant de
        # rejouer (un `DELETE` sans ligne à supprimer ne fait rien).
        await session.execute(delete(Ligne).where(Ligne.document_id == document_id))
        return await executer()


async def _rapprocher_si_numero(
    session: AsyncSession, document_id: uuid.UUID, resultat: ResultatExtraction
) -> None:
    """L4-T7 (décision du contrôleur) : une extraction qui résout un numéro
    de BL (chemin normal ou annotation illisible dont le motif déterministe
    `detecter_numero_bl` a quand même donné un numéro) peut faire
    correspondre une ou plusieurs factures déjà déposées — rejeu encapsulé
    (`rapprocher_factures_du_bl`), ne fait jamais échouer l'extraction
    elle-même (déjà commitée). Rien si `resultat.numero` est absent (aucun
    numéro à chercher)."""
    if resultat.numero is not None:
        await rapprocher_factures_du_bl(session, document_id)


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

    Finding 3 (fix round 1) / Ruling R11 (revue L3-T8a) : la résolution des
    référentiels et l'écriture (`_extraire_et_committer`, ou
    `_enregistrer_annotation_illisible` si l'annotation est illisible) sont
    rejouées une seule fois si le commit lève `IntegrityError` (course entre
    deux écritures concurrentes du même numéro pour le même fournisseur, cf.
    docstring du module et `_avec_reprise_doublon`) ; un second échec remonte
    tel quel.
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
        resultat = await _avec_reprise_doublon(
            session,
            document_id,
            lambda: _enregistrer_annotation_illisible(session, document, reponse),
        )
        await _rapprocher_si_numero(session, document_id, resultat)
        return resultat

    resultat = await _avec_reprise_doublon(
        session,
        document_id,
        lambda: _extraire_et_committer(
            session, document, document_id, extrait, reponse, seuil, tolerance, relance
        ),
    )
    await _rapprocher_si_numero(session, document_id, resultat)
    return resultat


async def _extraire_et_committer(
    session: AsyncSession,
    document: Document,
    document_id: uuid.UUID,
    extrait: BLExtrait,
    reponse: dict[str, Any],
    seuil: Decimal,
    tolerance: Decimal,
    relance: bool,
) -> ResultatExtraction:
    """Résolution des référentiels, calcul des motifs, écriture des colonnes
    et des lignes, puis commit (finding 3, fix round 1) : isolé du reste
    d'`enregistrer_extraction_bl` pour être rejouable une fois par son
    appelant si le commit lève `IntegrityError`."""
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

    # Avenant du 27/09/2026 (décision d'Ilane, spec §2.3) : rattachement
    # automatique du chantier (nom lu + légende Telegram déjà posée par le
    # dépôt) — après `document.chantier_brut`/`fournisseur_id`, avant le
    # journal (`rattachement_chantier.rattacher_chantier_document` pose déjà
    # `document.chantier_id`, apprend un alias le cas échéant et
    # synchronise R18).
    resultat_chantier = await rattacher_chantier_document(session, document)
    decompose_chantier = decomposer_chantier(document.chantier_brut)
    chantier_libelle = (
        decompose_chantier.libelle if decompose_chantier is not None else None
    )

    for ligne_extraite, ligne_vue in zip(extrait.lignes, vue.lignes, strict=True):
        # L3-D26 : une ligne d'éco-participation/contribution n'est jamais
        # proposée comme article (elle n'a pas de code article à valider).
        type_ligne = (
            "eco" if est_ligne_eco(ligne_extraite.designation.brut) else "article"
        )
        article_id: uuid.UUID | None = None
        if fournisseur_id is not None and type_ligne != "eco":
            proposition = proposer_article_bl(
                ligne_extraite.code.brut,
                ligne_extraite.designation.brut,
                ligne_extraite.unite.brut,
                qte_conditionnements=ligne_extraite.quantite_conditionnements.valeur,
                qte_facturee=ligne_extraite.quantite.valeur,
            )
            article_id = await rattacher_article(session, fournisseur_id, proposition)
        session.add(
            Ligne(
                document_id=document_id,
                type_ligne=type_ligne,
                code_brut=ligne_extraite.code.brut,
                article_brut=ligne_extraite.designation.brut,
                article_id=article_id,
                # L3-D24 : même sens que les colonnes QTÉ LIVRÉE (nombre de
                # conditionnements) / QTÉ TOTALE (quantité facturée) de la
                # facture Unikalo.
                qte_livree=ligne_extraite.quantite_conditionnements.valeur,
                qte_totale=ligne_extraite.quantite.valeur,
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
                "chantier_id": (
                    str(resultat_chantier.chantier_id)
                    if resultat_chantier.chantier_id is not None
                    else None
                ),
                "methode_chantier": resultat_chantier.methode,
                "score_chantier": resultat_chantier.score,
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
