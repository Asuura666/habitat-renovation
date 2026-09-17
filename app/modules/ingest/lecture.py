"""Lecture des factures et documents (`GET /api/factures`,
`GET /api/factures/{id}`, `GET /api/documents`, fichiers servis, L2-T5) et
correspondance numéro de BL -> document reçu, partagée avec `ingest/
factures.py` (`blocs_avec_reception`, T7) et `ingest/depot_telegram.py`
indirectement (aucun import direct, `lister_documents` lit le journal
alimenté par `depot_telegram.traiter_clic`).

Sous-module de `ingest`, issu du découpage de l'ancien `ingest/service.py`
(vague finale du lot 2, point 1 : simple déplacement de code, aucun
changement de comportement, sauf le point 5 explicitement noté ci-dessous
sur `documents_bl_par_numeros`). Toute la requête SQL et toute règle
(droits, correspondance BL) vivent ici, jamais dans les routeurs
(décision du contrôleur) — `app/modules/api/documents.py` et
`app/modules/api/factures.py` ne font que traduire les exceptions ci-dessous
en codes HTTP.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, defer

from app.modules.extract.verification import motif_depuis_json
from app.modules.ingest.commun import _mime_pour_extension, logger
from app.modules.ingest.models import (
    BlocFacture,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    Utilisateur,
)

# Caractères considérés comme des espaces de bord (point 5, vague finale
# du lot 2) : espace ASCII, tabulation, espace insécable (U+00A0) — les
# mêmes que `str.strip()` retire côté Python dans `_normaliser_numero`.
_CARACTERES_DE_BORD = " \t\u00a0"


def _normaliser_numero(numero: str) -> str:
    """`strip()` puis majuscules (décision du contrôleur T7, reprise telle
    quelle par L2-T5) : le préfixe `L` est parfois en minuscule sur les OCR,
    aucune autre normalisation (cf. `docs/dette.md`)."""
    return numero.strip().upper()


async def documents_bl_par_numeros(
    session: AsyncSession, numeros: Iterable[str]
) -> dict[str, uuid.UUID]:
    """Correspondance numéro de BL -> `id` du `document` reçu (BL ou
    enlèvement), factorisée pour être partagée par `blocs_avec_reception`
    (CLI `bl-non-recus`, T7) et `facture_detail`/`lister_factures` (L2-T5).

    Clé = numéro normalisé (`_normaliser_numero`, décision du contrôleur
    T7/L2-T5). Ne considère que les documents de type `bl`/`enlevement`, de
    statut différent de `archive` (L2-D12 : la correspondance est calculée à
    la lecture, jamais persistée dans `bloc_facture.bl_document_id`). En cas
    de plusieurs documents pour un même numéro normalisé (décision du
    contrôleur L2-T5), le plus ancien (`created_at` croissant) fait foi.

    Une seule requête, filtrée en SQL sur les numéros normalisés
    (`upper(btrim(...))`) plutôt qu'en récupérant tous les documents reçus
    de l'application : reste correct même si le nombre de BL/enlèvements
    déposés grossit avec le temps. `numeros` vide -> aucune requête, `{}`.

    Correction (dette L2-T5, vague finale du lot 2, point 5) : `btrim` avec
    une liste explicite de caractères de bord (espace, tabulation, espace
    insécable U+00A0) plutôt que `trim()` (qui n'enlève que l'espace ASCII
    côté PostgreSQL) — aligné sur `_normaliser_numero` (`str.strip()`
    Python, qui enlève déjà ces trois caractères). Un numéro stocké avec un
    espace insécable de bord n'échappe donc plus au filtre SQL avant même
    d'atteindre la comparaison Python.
    """
    normalises = {_normaliser_numero(numero) for numero in numeros if numero}
    if not normalises:
        return {}

    resultat = await session.execute(
        select(Document.numero, Document.id)
        .where(
            Document.type.in_(("bl", "enlevement")),
            Document.statut != "archive",
            Document.numero.is_not(None),
            func.upper(func.btrim(Document.numero, _CARACTERES_DE_BORD)).in_(
                normalises
            ),
        )
        .order_by(Document.created_at.asc())
    )
    documents_par_numero: dict[str, uuid.UUID] = {}
    for numero, document_id in resultat.all():
        cle = _normaliser_numero(numero)
        # Premier vu (le plus ancien, grâce à l'`ORDER BY` ci-dessus) fait
        # foi : ne jamais écraser par un document plus récent du même numéro.
        documents_par_numero.setdefault(cle, document_id)
    return documents_par_numero


# Ruling L2-R8 (revue L2-T7, tour 1/5, correction) : `GET /api/documents`
# expose un champ `confirmation` explicite, dérivé de la **dernière** entrée
# de `journal` ciblant ce document parmi les deux actions ci-dessus — jamais
# de `statut` (constat de revue : un document passé `a_verifier` par l'OCR,
# faute de numéro de BL détecté, peut tout à fait recevoir « Quantités
# vérifiées » ensuite ; `statut == "a_verifier"` ne permet pas de distinguer
# ce cas d'un « Écart constaté », le front affichait alors « Écart signalé »
# à tort). Les clés reprennent les valeurs de `depot_telegram._ACTIONS_JOURNAL`
# (`"quantites_verifiees"` / `"ecart_constate"`, action journalisée par
# `depot_telegram._decider_clic`) — pas d'import croisé pour ces deux
# constantes de chaîne, simple déplacement de code (vague finale du lot 2,
# point 1).
_CONFIRMATION_PAR_ACTION: dict[str, str] = {
    "quantites_verifiees": "verifiee",
    "ecart_constate": "ecart",
}


# --------------------------------------------------------------------------
# L2-T5 — `api/factures.py` et `api/documents.py` (lecture seule) : toute la
# requête SQL et toute règle (droits, correspondance BL) vivent ici, jamais
# dans les routeurs (décision du contrôleur) — les routeurs ne font que
# traduire les exceptions ci-dessous en codes HTTP.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MotifLu:
    """Un motif de mise « à vérifier », tel qu'exposé par l'API (L3-T7) —
    mêmes champs qu'`extract.verification.Motif`, mais un type propre à
    `ingest` (`api` ne peut pas importer `extract` directement, L2-D3) :
    réutilisée par `L3-T8a`/`L3-T8b`."""

    code: str
    champ: str | None
    detail: dict[str, str]


def motifs_lus(valeur: object) -> list[MotifLu]:
    """Décode une colonne JSON (`document.motifs`) en `MotifLu` (L3-T7,
    décision du contrôleur) : chaque élément passe par `extract.verification
    .motif_depuis_json` — un élément mal formé (`ValueError`, y compris un
    élément qui n'est pas un objet) est simplement ignoré, jamais une erreur
    500 sur une donnée déjà en base. `None` ou toute valeur qui n'est pas une
    liste -> `[]`."""
    if not isinstance(valeur, list):
        return []
    motifs: list[MotifLu] = []
    for element in valeur:
        try:
            motif = motif_depuis_json(element)
        except ValueError:
            continue
        motifs.append(
            MotifLu(code=motif.code.value, champ=motif.champ, detail=motif.detail)
        )
    return motifs


@dataclass(frozen=True)
class FactureResume:
    """Une ligne de `GET /api/factures` (L2-T5 ; statut/confiance/motifs
    L3-T7)."""

    id: uuid.UUID
    numero: str
    fournisseur: str
    date_doc: date | None
    total_ht: Decimal | None
    nb_blocs: int
    nb_blocs_recus: int
    cree_le: datetime
    statut: str
    confiance_reduite: bool
    confiance_min: Decimal | None
    motifs: list[MotifLu]


async def lister_factures(session: AsyncSession) -> list[FactureResume]:
    """Liste des factures, triée par `date_doc` puis `created_at`
    décroissants (décision du contrôleur L2-T5).

    `nb_blocs`/`nb_blocs_recus` sans N+1 : trois requêtes au total, quel que
    soit le nombre de factures ou de blocs — une pour les factures (jointure
    fournisseur), une pour tous leurs blocs, une pour la correspondance BL
    (`documents_bl_par_numeros`, elle-même une seule requête).

    `confiance_reduite` (L3-T7, décision du contrôleur) : `Document.ocr_brut
    .is_not(None)` sélectionnée comme expression booléenne, colonne
    `ocr_brut` elle-même déférée (`defer`, jamais chargée ici) — la réponse
    OCR brute d'une facture pèse plusieurs centaines de Ko, inutile pour une
    liste.
    """
    resultat_factures = await session.execute(
        select(
            Document,
            Fournisseur.nom,
            Document.ocr_brut.is_not(None).label("confiance_reduite"),
        )
        .options(defer(Document.ocr_brut))
        .join(Fournisseur, Fournisseur.id == Document.fournisseur_id)
        .where(Document.type == "facture")
        .order_by(Document.date_doc.desc(), Document.created_at.desc())
    )
    lignes_factures = resultat_factures.all()
    if not lignes_factures:
        return []

    facture_ids = [document.id for document, _nom, _reduite in lignes_factures]
    resultat_blocs = await session.execute(
        select(BlocFacture.facture_id, BlocFacture.numero_bl).where(
            BlocFacture.facture_id.in_(facture_ids)
        )
    )
    numeros_par_facture: dict[uuid.UUID, list[str | None]] = defaultdict(list)
    for facture_id, numero_bl in resultat_blocs.all():
        numeros_par_facture[facture_id].append(numero_bl)

    tous_numeros = (
        numero_bl
        for numeros in numeros_par_facture.values()
        for numero_bl in numeros
        if numero_bl is not None
    )
    documents_par_numero = await documents_bl_par_numeros(session, tous_numeros)

    resumes: list[FactureResume] = []
    for document, nom_fournisseur, confiance_reduite in lignes_factures:
        numeros_bloc = numeros_par_facture.get(document.id, [])
        nb_blocs_recus = sum(
            1
            for numero_bl in numeros_bloc
            if numero_bl is not None
            and _normaliser_numero(numero_bl) in documents_par_numero
        )
        resumes.append(
            FactureResume(
                id=document.id,
                numero=document.numero or "",
                fournisseur=nom_fournisseur,
                date_doc=document.date_doc,
                total_ht=document.total_ht,
                nb_blocs=len(numeros_bloc),
                nb_blocs_recus=nb_blocs_recus,
                cree_le=document.created_at,
                statut=document.statut,
                confiance_reduite=confiance_reduite,
                confiance_min=document.confiance_min,
                motifs=motifs_lus(document.motifs),
            )
        )
    return resumes


class FactureIntrouvable(Exception):
    """Aucun document de type `facture` avec cet identifiant."""


@dataclass(frozen=True)
class LigneFactureLue:
    """Une ligne d'un bloc, telle que lue en base (`GET /api/factures/{id}`)."""

    ordre: int
    type_ligne: str
    code_brut: str | None
    article_brut: str | None
    qte_livree: Decimal | None
    qte_totale: Decimal | None
    pu_ht: Decimal | None
    pu_cdt: Decimal | None
    remise_pct: Decimal | None
    montant_ht: Decimal | None
    tva: Decimal | None


@dataclass(frozen=True)
class BlocFactureLu:
    """Un bloc, avec ses lignes et son indicateur « BL reçu » calculé à la
    lecture (L2-D12, jamais persisté dans `bl_document_id`). `chantier_id`
    (L3-T7) : résolu par `ingest/factures.py::deposer_facture`."""

    id: uuid.UUID
    numero_bl: str | None
    date_bl: date | None
    numero_commande: str | None
    chantier_brut: str | None
    chantier_id: uuid.UUID | None
    commentaire: str | None
    montant_ht: Decimal
    bl_recu: bool
    bl_document_id: uuid.UUID | None
    lignes: list[LigneFactureLue]


@dataclass(frozen=True)
class FactureDetail:
    """En-tête et blocs d'une facture (`GET /api/factures/{id}`, L2-T5 ;
    statut/confiance/motifs L3-T7)."""

    id: uuid.UUID
    numero: str
    fournisseur: str
    date_doc: date | None
    total_ht: Decimal | None
    cree_le: datetime
    deposant: str | None
    statut: str
    confiance_reduite: bool
    confiance_min: Decimal | None
    motifs: list[MotifLu]
    blocs: list[BlocFactureLu]


async def facture_detail(session: AsyncSession, facture_id: uuid.UUID) -> FactureDetail:
    """En-tête puis blocs (avec leurs lignes) d'une facture, blocs et lignes
    dans l'ordre (`BlocFacture.ordre`, `Ligne.ordre` — jamais `created_at`,
    identique pour toutes les lignes d'une même facture insérées dans la
    même transaction par `deposer_facture`, voir le commentaire de
    `BlocFacture.ordre` dans `ingest/models.py`). `montant_ht` de chaque bloc
    recalculé comme la somme des montants non nuls de ses lignes (décision du
    contrôleur L2-T5 : jamais une colonne stockée, toujours à jour).

    Lève `FactureIntrouvable` si `facture_id` est absent ou si le document
    n'est pas de type `facture` (décision du contrôleur : même 404 dans les
    deux cas, pour ne jamais distinguer un id inexistant d'un BL/enlèvement
    existant). Quatre requêtes au total (en-tête, blocs, lignes,
    correspondance BL), jamais une par bloc ni par ligne.
    """
    deposant_alias = aliased(Utilisateur)
    ligne_entete = (
        await session.execute(
            select(
                Document,
                Fournisseur.nom,
                func.coalesce(deposant_alias.nom, deposant_alias.email),
            )
            .join(Fournisseur, Fournisseur.id == Document.fournisseur_id)
            .outerjoin(deposant_alias, deposant_alias.id == Document.deposant_id)
            .where(Document.id == facture_id, Document.type == "facture")
        )
    ).first()
    if ligne_entete is None:
        raise FactureIntrouvable(str(facture_id))
    document, nom_fournisseur, nom_deposant = ligne_entete

    blocs_db = (
        (
            await session.execute(
                select(BlocFacture)
                .where(BlocFacture.facture_id == facture_id)
                .order_by(BlocFacture.ordre.asc())
            )
        )
        .scalars()
        .all()
    )

    lignes_db = (
        (
            await session.execute(
                select(Ligne)
                .where(Ligne.document_id == facture_id)
                .order_by(Ligne.ordre.asc())
            )
        )
        .scalars()
        .all()
    )
    lignes_par_bloc: dict[uuid.UUID, list[Ligne]] = defaultdict(list)
    for ligne in lignes_db:
        if ligne.bloc_id is not None:
            lignes_par_bloc[ligne.bloc_id].append(ligne)

    documents_par_numero = await documents_bl_par_numeros(
        session, (bloc.numero_bl for bloc in blocs_db if bloc.numero_bl is not None)
    )

    blocs: list[BlocFactureLu] = []
    for bloc in blocs_db:
        bl_document_id = (
            documents_par_numero.get(_normaliser_numero(bloc.numero_bl))
            if bloc.numero_bl is not None
            else None
        )
        blocs.append(
            BlocFactureLu(
                id=bloc.id,
                numero_bl=bloc.numero_bl,
                date_bl=bloc.date_bl,
                numero_commande=bloc.numero_commande,
                chantier_brut=bloc.chantier_brut,
                chantier_id=bloc.chantier_id,
                commentaire=bloc.commentaire,
                montant_ht=sum(
                    (
                        ligne.montant_ht
                        for ligne in lignes_par_bloc.get(bloc.id, [])
                        if ligne.montant_ht is not None
                    ),
                    Decimal("0"),
                ),
                bl_recu=bl_document_id is not None,
                bl_document_id=bl_document_id,
                lignes=[
                    LigneFactureLue(
                        ordre=ligne.ordre,
                        type_ligne=ligne.type_ligne,
                        code_brut=ligne.code_brut,
                        article_brut=ligne.article_brut,
                        qte_livree=ligne.qte_livree,
                        qte_totale=ligne.qte_totale,
                        pu_ht=ligne.pu_ht,
                        pu_cdt=ligne.pu_cdt,
                        remise_pct=ligne.remise_pct,
                        montant_ht=ligne.montant_ht,
                        tva=ligne.tva,
                    )
                    for ligne in lignes_par_bloc.get(bloc.id, [])
                ],
            )
        )

    return FactureDetail(
        id=document.id,
        numero=document.numero or "",
        fournisseur=nom_fournisseur,
        date_doc=document.date_doc,
        total_ht=document.total_ht,
        cree_le=document.created_at,
        deposant=nom_deposant,
        # L3-T7 : un seul document chargé ici (contrairement à `lister_
        # factures`) — pas besoin de déférer `ocr_brut` pour cette seule
        # vérification de nullité.
        statut=document.statut,
        confiance_reduite=document.ocr_brut is not None,
        confiance_min=document.confiance_min,
        motifs=motifs_lus(document.motifs),
        blocs=blocs,
    )


@dataclass(frozen=True)
class DocumentResume:
    """Une ligne de `GET /api/documents` (L2-T5, `confirmation` ajouté au
    Ruling L2-R8 ; `fournisseur`/`chantier_brut` ajoutés en L3-T8a pour un
    aperçu utile dans la liste, sans ouvrir le détail de chaque document)."""

    id: uuid.UUID
    numero_interne: int
    type: str
    numero: str | None
    statut: str
    deposant: str | None
    cree_le: datetime
    confirme_le: datetime | None
    confirme_par: str | None
    photo_compressee: bool | None
    # "verifiee" | "ecart" | None (Ruling L2-R8) — jamais dérivé de `statut`
    # côté front, voir `_CONFIRMATION_PAR_ACTION` ci-dessus.
    confirmation: str | None
    fournisseur: str | None
    chantier_brut: str | None


LIMITE_DOCUMENTS_MIN = 1
LIMITE_DOCUMENTS_MAX = 500
LIMITE_DOCUMENTS_DEFAUT = 100


async def lister_documents(
    session: AsyncSession,
    *,
    utilisateur_id: uuid.UUID,
    role: str,
    depuis: datetime | None = None,
    limite: int = LIMITE_DOCUMENTS_DEFAUT,
) -> list[DocumentResume]:
    """BL et enlèvements visibles par l'appelant — droit vérifié ici, jamais
    dans le routeur (décision du contrôleur L2-T5) : un admin voit tous les
    documents `bl`/`enlevement` non archivés, un agent seulement ceux qu'il a
    déposés. Triés par `created_at` décroissant ; `depuis` filtre sur
    `created_at >= depuis` (borne incluse) ; `limite` borne le nombre de
    lignes (validée par le routeur, `1..500`). Une seule requête (jointures
    sur le déposant, le confirmateur et la confirmation), jamais de N+1.

    `confirmation` (Ruling L2-R8, correction de revue L2-T7) : dérivée du
    **journal**, jamais de `statut` — `_DERNIER_JOURNAL_CONFIRMATION`
    présélectionne, par document (`DISTINCT ON`, PostgreSQL), la dernière
    action `quantites_verifiees`/`ecart_constate` le ciblant ; en pratique au
    plus une seule existe déjà (le premier clic fait foi, `_decider_clic`),
    mais `DISTINCT ON ... ORDER BY horodatage DESC` reste correct si cela
    changeait. Une jointure externe sur cette sous-requête, pas une requête
    par document.
    """
    deposant_alias = aliased(Utilisateur)
    confirmateur_alias = aliased(Utilisateur)

    dernier_journal_confirmation = (
        select(Journal.cible_id, Journal.action)
        .where(
            Journal.cible_table == "document",
            Journal.action.in_(tuple(_CONFIRMATION_PAR_ACTION)),
        )
        .distinct(Journal.cible_id)
        .order_by(Journal.cible_id, Journal.horodatage.desc())
        .subquery()
    )

    conditions = [
        Document.type.in_(("bl", "enlevement")),
        Document.statut != "archive",
    ]
    if role != "admin":
        conditions.append(Document.deposant_id == utilisateur_id)
    if depuis is not None:
        conditions.append(Document.created_at >= depuis)

    resultat = await session.execute(
        select(
            Document,
            func.coalesce(deposant_alias.nom, deposant_alias.email),
            func.coalesce(confirmateur_alias.nom, confirmateur_alias.email),
            dernier_journal_confirmation.c.action,
            Fournisseur.nom,
        )
        .outerjoin(deposant_alias, deposant_alias.id == Document.deposant_id)
        .outerjoin(confirmateur_alias, confirmateur_alias.id == Document.confirme_par)
        .outerjoin(
            dernier_journal_confirmation,
            dernier_journal_confirmation.c.cible_id == cast(Document.id, String),
        )
        # L3-T8a : nom du fournisseur pour l'aperçu de liste (`fournisseur`) —
        # jointure externe (un BL/enlèvement peut ne pas avoir de fournisseur
        # résolu), jamais de requête supplémentaire par document.
        .outerjoin(Fournisseur, Fournisseur.id == Document.fournisseur_id)
        .where(*conditions)
        .order_by(Document.created_at.desc())
        .limit(limite)
    )
    return [
        DocumentResume(
            id=document.id,
            numero_interne=document.numero_interne,
            type=document.type,
            numero=document.numero,
            statut=document.statut,
            deposant=nom_deposant,
            cree_le=document.created_at,
            confirme_le=document.confirme_le,
            confirme_par=nom_confirmateur,
            photo_compressee=document.photo_compressee,
            confirmation=_CONFIRMATION_PAR_ACTION.get(action_journal)
            if action_journal is not None
            else None,
            fournisseur=nom_fournisseur,
            chantier_brut=document.chantier_brut,
        )
        for (
            document,
            nom_deposant,
            nom_confirmateur,
            action_journal,
            nom_fournisseur,
        ) in resultat.all()
    ]


async def confirmation_document(
    session: AsyncSession, document_id: uuid.UUID
) -> str | None:
    """Dernière confirmation (`quantites_verifiees`/`ecart_constate`) d'un
    document, pour son détail (`ingest/corrections.py::detail_document`,
    L3-T8a) — même mapping action -> confirmation que `lister_documents`
    (`_CONFIRMATION_PAR_ACTION`), extrait ici pour être réutilisé sans le
    dupliquer. Une seule ligne (`ORDER BY horodatage DESC LIMIT 1`), sans la
    sous-requête `DISTINCT ON` de `lister_documents` (utile seulement pour
    éviter le N+1 sur une liste entière, superflue ici)."""
    action = (
        await session.execute(
            select(Journal.action)
            .where(
                Journal.cible_table == "document",
                Journal.cible_id == str(document_id),
                Journal.action.in_(tuple(_CONFIRMATION_PAR_ACTION)),
            )
            .order_by(Journal.horodatage.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _CONFIRMATION_PAR_ACTION.get(action) if action is not None else None


class DocumentIntrouvable(Exception):
    """Document absent, non autorisé pour l'appelant, ou fichier inaccessible
    (chemin hors `docs_dir`, ou absent du disque) — toujours le même 404
    côté routeur, pour ne jamais distinguer ces cas (décision du contrôleur
    L2-T5)."""


@dataclass(frozen=True)
class FichierDocument:
    """Chemin (résolu, garanti à l'intérieur de `docs_dir`) et type MIME d'un
    fichier de document, prêt pour `fastapi.responses.FileResponse`."""

    chemin: Path
    type_mime: str


def _chemin_dans_docs_dir(document: Document, docs_dir: Path) -> Path | None:
    """`None` si le chemin enregistré (`document.fichier_path`) ne résout pas
    à l'intérieur de `docs_dir` (défense en profondeur, décision du
    contrôleur L2-T5 : jamais un chemin arbitraire servi) ou si le fichier
    n'existe plus sur disque. Jamais d'exception : l'appelant traduit `None`
    en `DocumentIntrouvable`, sans jamais journaliser le chemin lui-même."""
    chemin = Path(document.fichier_path).resolve()
    racine = docs_dir.resolve()
    if not chemin.is_relative_to(racine):
        return None
    if not chemin.is_file():
        return None
    return chemin


def _fichier_ou_404(document: Document, docs_dir: Path) -> FichierDocument:
    chemin = _chemin_dans_docs_dir(document, docs_dir)
    if chemin is None:
        # Décision du contrôleur : jamais le chemin en clair dans le journal.
        logger.error(
            "fichier inaccessible pour document %s (hors docs_dir ou absent du disque)",
            document.id,
        )
        raise DocumentIntrouvable(str(document.id))
    return FichierDocument(
        chemin=chemin,
        type_mime=_mime_pour_extension(chemin.suffix.lstrip(".").lower()),
    )


async def fichier_facture(
    session: AsyncSession, facture_id: uuid.UUID, docs_dir: Path
) -> FichierDocument:
    """Fichier PDF d'une facture (admin uniquement, vérifié par le routeur
    via `admin_requis`). Lève `DocumentIntrouvable` si absente, si le
    document n'est pas de type `facture`, ou si son chemin ne résout pas à
    l'intérieur de `docs_dir`."""
    document = await session.get(Document, facture_id)
    if document is None or document.type != "facture":
        raise DocumentIntrouvable(str(facture_id))
    return _fichier_ou_404(document, docs_dir)


async def fichier_document(
    session: AsyncSession,
    document_id: uuid.UUID,
    docs_dir: Path,
    *,
    utilisateur_id: uuid.UUID,
    role: str,
) -> FichierDocument:
    """Fichier d'un document (droit vérifié ici, décision du contrôleur
    L2-T5) : un admin peut télécharger n'importe quel document, un agent
    seulement ceux qu'il a déposés. Lève `DocumentIntrouvable` (404) dans
    tous les autres cas — absent, déposé par un autre agent, ou chemin hors
    `docs_dir` — sans jamais distinguer ces cas dans la réponse."""
    document = await session.get(Document, document_id)
    if document is None:
        raise DocumentIntrouvable(str(document_id))
    if role != "admin" and document.deposant_id != utilisateur_id:
        raise DocumentIntrouvable(str(document_id))
    return _fichier_ou_404(document, docs_dir)
