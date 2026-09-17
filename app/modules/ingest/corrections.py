"""Détail, correction, validation, archivage et relance d'un BL
(`ingest/corrections.py`, L3-T8a) : service consommé par les routes JSON de
`api/documents.py`, dont les écrans de correction du lot 3 (tâches
suivantes) consomment le détail.

Après l'extraction automatique (`ingest/extraction_bl.py`), un BL peut être
`a_verifier` : l'admin doit voir chaque champ avec sa valeur OCR d'origine
et sa confiance (`detail_document`), corriger l'en-tête (`corriger_entete`)
ou les lignes (`corriger_lignes`) — chaque écriture journalisée, la valeur
OCR toujours conservée dans `document.extraction` (instantané immuable,
L3-D5) —, valider le document une fois les contrôles structurels au vert
(`valider_document`), archiver un doublon (`archiver_document`) ou relancer
l'extraction (`relancer_extraction`, L3-D15).

Décisions du contrôleur (L3-T8a) :
- Une **facture** est introuvable pour toutes les routes de cette tâche
  (lecture et écritures) : `DocumentIntrouvable` (404), jamais un 409 —
  seuls les documents `bl`/`enlevement` existent pour ce service
  (`_document_pour_lecture`/`_document_pour_ecriture`).
- Les motifs structurels recalculés après une correction ou pour la
  validation (`_recalculer_motifs_structurels`) réutilisent `extract
  .verification.verifier_bl`, mais avec `confiances=None`, `illisibles=
  frozenset()` et `numero_detecte=None` : l'admin a revu le document, ni la
  confiance ni le recoupement du numéro ne comptent plus (un fournisseur
  non rattaché donne toujours `CHAMP_ABSENT` sur `fournisseur`).
- `corrige`/`corrige_par`/`corrige_le` d'un champ (`ChampLu`) viennent de la
  dernière entrée de journal `document_corrige` de ce document dont
  `apres` contient ce champ — une seule requête pour tout le document,
  jamais une par champ (`_corrections_document`).
- Réutilise au lieu de dupliquer : `ingest.lecture.confirmation_document`
  (calcul de `confirmation`, extrait de `lister_documents` pour cette
  tâche) et `ingest.lecture.fichier_document` (résolution sûre du chemin de
  fichier, pour `relancer_extraction`) — aucune règle de droits ni de
  chemin n'est réécrite ici.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extract.verification import (
    SEUIL_CONFIANCE_DEFAUT,
    TOLERANCE_TOTAL_DEFAUT,
    BLAVerifier,
    LigneAVerifier,
    Motif,
    motif_en_json,
    verifier_bl,
)
from app.modules.ingest.extraction_bl import (
    CLE_SEUIL_CONFIANCE_OCR,
    CLE_TOLERANCE_TOTAL_HT,
    enregistrer_extraction_bl,
)
from app.modules.ingest.factures import LectureImpossible
from app.modules.ingest.lecture import (
    DocumentIntrouvable,
    MotifLu,
    confirmation_document,
    fichier_document,
    motifs_lus,
)
from app.modules.ingest.mistral import ErreurOCR
from app.modules.ingest.models import (
    AgenceFournisseur,
    Chantier,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    Utilisateur,
)
from app.modules.ingest.referentiels import (
    lire_parametre_decimal,
    rattacher_article,
    resoudre_chantier,
)
from app.modules.normalize.article import proposer_article_bl

# --------------------------------------------------------------------------
# Champs correctibles d'un BL (L3-D13)
# --------------------------------------------------------------------------

CHAMPS_CORRIGEABLES: tuple[str, ...] = (
    "type",
    "fournisseur_id",
    "numero",
    "date_doc",
    "chantier_brut",
    "numero_commande",
    "enleve_par",
    "total_ht",
    "total_tva",
    "total_ttc",
)

# Champs exposés dans `DocumentDetail.champs` (ChampLu) : sous-ensemble de
# `CHAMPS_CORRIGEABLES` moins `type` (pas de ChampLu dédié, exposé tel quel
# via `DocumentDetail.type`) et `fournisseur_id` -> `fournisseur` (valeur
# affichée = nom du référentiel, décision du contrôleur).
CHAMPS_DOCUMENT_DETAIL: tuple[str, ...] = (
    "fournisseur",
    "numero",
    "date_doc",
    "chantier_brut",
    "numero_commande",
    "enleve_par",
    "total_ht",
    "total_tva",
    "total_ttc",
)

# Traduction clé de journal (`CorrectionEntete.valeurs`/`CHAMPS_CORRIGEABLES`)
# -> clé d'affichage (`CHAMPS_DOCUMENT_DETAIL`) : seul `fournisseur_id`
# diffère, tous les autres champs partagent le même nom des deux côtés.
_CHAMP_JOURNAL_VERS_AFFICHAGE: dict[str, str] = {"fournisseur_id": "fournisseur"}


# --------------------------------------------------------------------------
# Dataclasses exposées (L3-T8a)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChampLu:
    """Un champ d'en-tête du détail d'un BL : valeur courante, valeur OCR
    d'origine et confiance, et qui l'a corrigé en dernier le cas échéant."""

    valeur: str | None
    valeur_ocr: str | None
    confiance: Decimal | None
    corrige: bool
    corrige_par: str | None
    corrige_le: datetime | None


@dataclass(frozen=True)
class LigneLue:
    """Une ligne d'articles du détail d'un BL, telle qu'en base."""

    id: uuid.UUID
    ordre: int
    code_brut: str | None
    article_brut: str | None
    type_ligne: str
    qte_livree: Decimal | None
    qte_totale: Decimal | None
    unite_brut: str | None
    pu_ht: Decimal | None
    montant_ht: Decimal | None
    confiance: Decimal | None
    article_id: uuid.UUID | None


@dataclass(frozen=True)
class DocumentDetail:
    """Détail complet d'un BL/enlèvement (`GET /api/documents/{id}`)."""

    id: uuid.UUID
    numero_interne: int
    type: str
    statut: str
    deposant: str | None
    cree_le: datetime
    confirme_le: datetime | None
    confirme_par: str | None
    confirmation: str | None
    photo_compressee: bool | None
    fournisseur_id: uuid.UUID | None
    agence_fournisseur: str | None
    chantier_id: uuid.UUID | None
    chantier: str | None
    champs: dict[str, ChampLu]
    lignes: list[LigneLue]
    motifs: list[MotifLu]
    seuil_confiance: Decimal
    modifiable: bool


@dataclass(frozen=True)
class CorrectionEntete:
    """Correction d'en-tête reçue (`PATCH /api/documents/{id}`) : seuls les
    champs envoyés par l'admin, clés ⊂ `CHAMPS_CORRIGEABLES`."""

    valeurs: dict[str, object]


@dataclass(frozen=True)
class LigneSaisie:
    """Une ligne reçue (`PUT /api/documents/{id}/lignes`) : `id` absent
    (`None`) -> insertion, sinon mise à jour de la ligne existante."""

    id: uuid.UUID | None
    code_brut: str | None
    article_brut: str | None
    qte_livree: Decimal | None
    qte_totale: Decimal | None
    unite_brut: str | None
    pu_ht: Decimal | None
    montant_ht: Decimal | None


class DocumentNonModifiable(Exception):
    """Le document est archivé, ou son statut ne permet pas l'action demandée
    (relance/validation hors `a_verifier`)."""


class NumeroDejaUtilise(Exception):
    """Le numéro corrigé est déjà porté par un autre document du même
    fournisseur (`id` de l'original, comme `ingest.factures.FactureEnDouble`)."""

    def __init__(self, original_id: uuid.UUID) -> None:
        super().__init__("numéro déjà utilisé")
        self.original_id = original_id


class ValidationRefusee(Exception):
    """Des motifs structurels subsistent : la validation est refusée."""

    def __init__(self, motifs: list[MotifLu]) -> None:
        super().__init__("validation refusée")
        self.motifs = motifs


class LigneInconnue(Exception):
    """Un `id` de ligne envoyé n'appartient pas à ce document."""


class FournisseurIntrouvable(Exception):
    """Le `fournisseur_id` corrigé ne correspond à aucun fournisseur."""


# --------------------------------------------------------------------------
# Lecture d'un champ de l'instantané `document.extraction` (L3-D5) :
# défensif — un instantané absent ou mal formé ne lève jamais (décision du
# contrôleur), il vaut simplement (None, None).
# --------------------------------------------------------------------------


def _lire_champ_extraction(
    extraction: object, nom: str
) -> tuple[str | None, Decimal | None]:
    if not isinstance(extraction, Mapping):
        return None, None
    champs = extraction.get("champs")
    if not isinstance(champs, Mapping):
        return None, None
    champ = champs.get(nom)
    if not isinstance(champ, Mapping):
        return None, None
    brut = champ.get("brut")
    valeur_ocr = brut if isinstance(brut, str) else None
    confiance_brute = champ.get("confiance")
    confiance: Decimal | None = None
    if isinstance(confiance_brute, str):
        try:
            confiance = Decimal(confiance_brute)
        except InvalidOperation:
            confiance = None
    return valeur_ocr, confiance


# --------------------------------------------------------------------------
# Valeurs courantes d'un document, en chaîne (deux usages distincts) :
# - `_valeurs_courantes` (affichage, `ChampLu.valeur`) : `fournisseur`
#   plutôt que `fournisseur_id`, nom du référentiel ;
# - `_valeurs_document_pour_journal` (comparaison de correction et `avant`
#   du journal) : `fournisseur_id` (UUID) et `type`, jamais résolus en nom.
# --------------------------------------------------------------------------


def _valeurs_courantes(
    document: Document, nom_fournisseur: str | None
) -> dict[str, str | None]:
    return {
        "fournisseur": nom_fournisseur,
        "numero": document.numero,
        "date_doc": document.date_doc.isoformat() if document.date_doc else None,
        "chantier_brut": document.chantier_brut,
        "numero_commande": document.numero_commande,
        "enleve_par": document.enleve_par,
        "total_ht": str(document.total_ht) if document.total_ht is not None else None,
        "total_tva": (
            str(document.total_tva) if document.total_tva is not None else None
        ),
        "total_ttc": (
            str(document.total_ttc) if document.total_ttc is not None else None
        ),
    }


def _valeurs_document_pour_journal(document: Document) -> dict[str, str | None]:
    return {
        "type": document.type,
        "fournisseur_id": (
            str(document.fournisseur_id)
            if document.fournisseur_id is not None
            else None
        ),
        "numero": document.numero,
        "date_doc": document.date_doc.isoformat() if document.date_doc else None,
        "chantier_brut": document.chantier_brut,
        "numero_commande": document.numero_commande,
        "enleve_par": document.enleve_par,
        "total_ht": str(document.total_ht) if document.total_ht is not None else None,
        "total_tva": (
            str(document.total_tva) if document.total_tva is not None else None
        ),
        "total_ttc": (
            str(document.total_ttc) if document.total_ttc is not None else None
        ),
    }


def _valeur_normalisee(valeur: object) -> object:
    """Valeur prête à être assignée à la colonne : une chaîne blanche
    devient `None` (décision du contrôleur), tout le reste (`None`,
    `Decimal`, `date`, `uuid.UUID`, chaîne non blanche) passe tel quel."""
    if isinstance(valeur, str):
        texte = valeur.strip()
        return texte or None
    return valeur


def _valeur_en_chaine(valeur: object) -> str | None:
    """Représentation canonique (chaîne) d'une valeur déjà normalisée, dans
    le même format que `_valeurs_document_pour_journal` — sert à la fois à
    détecter un changement effectif et à écrire le journal."""
    if valeur is None:
        return None
    if isinstance(valeur, uuid.UUID):
        return str(valeur)
    if isinstance(valeur, date):
        return valeur.isoformat()
    if isinstance(valeur, Decimal):
        return str(valeur)
    return str(valeur)


# --------------------------------------------------------------------------
# Petites lectures d'appoint (nom d'un fournisseur/agence/chantier/
# utilisateur), utilisées par `_charger_detail` — une requête chacune, sans
# souci de N+1 : ce service ne lit jamais qu'un seul document à la fois.
# --------------------------------------------------------------------------


async def _nom_utilisateur(
    session: AsyncSession, utilisateur_id: uuid.UUID | None
) -> str | None:
    if utilisateur_id is None:
        return None
    return (
        await session.execute(
            select(func.coalesce(Utilisateur.nom, Utilisateur.email)).where(
                Utilisateur.id == utilisateur_id
            )
        )
    ).scalar_one_or_none()


async def _nom_fournisseur(
    session: AsyncSession, fournisseur_id: uuid.UUID | None
) -> str | None:
    if fournisseur_id is None:
        return None
    return (
        await session.execute(
            select(Fournisseur.nom).where(Fournisseur.id == fournisseur_id)
        )
    ).scalar_one_or_none()


async def _nom_agence(session: AsyncSession, agence_id: uuid.UUID | None) -> str | None:
    if agence_id is None:
        return None
    return (
        await session.execute(
            select(AgenceFournisseur.nom).where(AgenceFournisseur.id == agence_id)
        )
    ).scalar_one_or_none()


async def _nom_chantier(
    session: AsyncSession, chantier_id: uuid.UUID | None
) -> str | None:
    if chantier_id is None:
        return None
    return (
        await session.execute(
            select(Chantier.nom_canonique).where(Chantier.id == chantier_id)
        )
    ).scalar_one_or_none()


async def _lignes_du_document(
    session: AsyncSession, document_id: uuid.UUID
) -> Sequence[Ligne]:
    return (
        (
            await session.execute(
                select(Ligne)
                .where(Ligne.document_id == document_id)
                .order_by(Ligne.ordre)
            )
        )
        .scalars()
        .all()
    )


async def _corrections_document(
    session: AsyncSession, document_id: uuid.UUID
) -> dict[str, tuple[datetime, str | None]]:
    """Dernière correction (`document_corrige`) par champ affiché
    (`CHAMPS_DOCUMENT_DETAIL`), une seule requête pour tout le document
    (décision du contrôleur) : triée de la plus récente à la plus ancienne,
    le premier journal qui mentionne un champ dans son `apres` fait foi pour
    ce champ."""
    lignes = (
        await session.execute(
            select(Journal, func.coalesce(Utilisateur.nom, Utilisateur.email))
            .outerjoin(Utilisateur, Utilisateur.id == Journal.utilisateur_id)
            .where(
                Journal.cible_table == "document",
                Journal.cible_id == str(document_id),
                Journal.action == "document_corrige",
            )
            .order_by(Journal.horodatage.desc())
        )
    ).all()
    resultat: dict[str, tuple[datetime, str | None]] = {}
    for journal, nom_correcteur in lignes:
        apres = journal.apres if isinstance(journal.apres, dict) else {}
        for champ_journal in apres:
            cle = _CHAMP_JOURNAL_VERS_AFFICHAGE.get(champ_journal, champ_journal)
            if cle in CHAMPS_DOCUMENT_DETAIL and cle not in resultat:
                resultat[cle] = (journal.horodatage, nom_correcteur)
    return resultat


def _construire_champs(
    document: Document,
    nom_fournisseur: str | None,
    corrections: Mapping[str, tuple[datetime, str | None]],
) -> dict[str, ChampLu]:
    valeurs = _valeurs_courantes(document, nom_fournisseur)
    champs: dict[str, ChampLu] = {}
    for nom in CHAMPS_DOCUMENT_DETAIL:
        valeur_ocr, confiance = _lire_champ_extraction(document.extraction, nom)
        correction = corrections.get(nom)
        champs[nom] = ChampLu(
            valeur=valeurs[nom],
            valeur_ocr=valeur_ocr,
            confiance=confiance,
            corrige=correction is not None,
            corrige_par=correction[1] if correction is not None else None,
            corrige_le=correction[0] if correction is not None else None,
        )
    return champs


def _ligne_lue(ligne: Ligne) -> LigneLue:
    return LigneLue(
        id=ligne.id,
        ordre=ligne.ordre,
        code_brut=ligne.code_brut,
        article_brut=ligne.article_brut,
        type_ligne=ligne.type_ligne,
        qte_livree=ligne.qte_livree,
        qte_totale=ligne.qte_totale,
        unite_brut=ligne.unite_brut,
        pu_ht=ligne.pu_ht,
        montant_ht=ligne.montant_ht,
        confiance=ligne.confiance,
        article_id=ligne.article_id,
    )


async def _charger_detail(
    session: AsyncSession, document: Document, *, role: str
) -> DocumentDetail:
    """Assemble le `DocumentDetail` complet à partir d'un `Document` déjà
    chargé (et déjà autorisé par l'appelant, `detail_document` ou l'une des
    fonctions d'écriture ci-dessous)."""
    nom_fournisseur = await _nom_fournisseur(session, document.fournisseur_id)
    nom_agence = await _nom_agence(session, document.agence_fournisseur_id)
    nom_chantier = await _nom_chantier(session, document.chantier_id)
    nom_deposant = await _nom_utilisateur(session, document.deposant_id)
    nom_confirmateur = await _nom_utilisateur(session, document.confirme_par)
    confirmation = await confirmation_document(session, document.id)
    seuil = await lire_parametre_decimal(
        session, CLE_SEUIL_CONFIANCE_OCR, SEUIL_CONFIANCE_DEFAUT
    )
    corrections = await _corrections_document(session, document.id)
    lignes_db = await _lignes_du_document(session, document.id)

    return DocumentDetail(
        id=document.id,
        numero_interne=document.numero_interne,
        type=document.type,
        statut=document.statut,
        deposant=nom_deposant,
        cree_le=document.created_at,
        confirme_le=document.confirme_le,
        confirme_par=nom_confirmateur,
        confirmation=confirmation,
        photo_compressee=document.photo_compressee,
        fournisseur_id=document.fournisseur_id,
        agence_fournisseur=nom_agence,
        chantier_id=document.chantier_id,
        chantier=nom_chantier,
        champs=_construire_champs(document, nom_fournisseur, corrections),
        lignes=[_ligne_lue(ligne) for ligne in lignes_db],
        motifs=motifs_lus(document.motifs),
        seuil_confiance=seuil,
        modifiable=(role == "admin" and document.statut != "archive"),
    )


# --------------------------------------------------------------------------
# Chargement + contrôle d'accès communs (lecture et écriture)
# --------------------------------------------------------------------------


async def _document_pour_lecture(
    session: AsyncSession, document_id: uuid.UUID
) -> Document:
    """Un BL/enlèvement (jamais une facture, ni tout autre type) — sinon
    `DocumentIntrouvable` (décision du contrôleur : une facture est
    introuvable pour toutes les routes de cette tâche)."""
    document = await session.get(Document, document_id)
    if document is None or document.type not in ("bl", "enlevement"):
        raise DocumentIntrouvable(str(document_id))
    return document


async def _document_pour_ecriture(
    session: AsyncSession, document_id: uuid.UUID
) -> Document:
    """`_document_pour_lecture`, plus `DocumentNonModifiable` si le document
    est déjà archivé."""
    document = await _document_pour_lecture(session, document_id)
    if document.statut == "archive":
        raise DocumentNonModifiable(str(document_id))
    return document


# --------------------------------------------------------------------------
# Motifs structurels après une correction humaine (L3-D13/L3-D14)
# --------------------------------------------------------------------------


async def _recalculer_motifs_structurels(
    session: AsyncSession, document: Document
) -> tuple[Motif, ...]:
    """Mêmes règles que l'extraction automatique (`verifier_bl`), mais
    confiances et recoupement de numéro désactivés : l'admin a revu le
    document (décision du contrôleur)."""
    lignes = await _lignes_du_document(session, document.id)
    nom_fournisseur = await _nom_fournisseur(session, document.fournisseur_id)
    seuil = await lire_parametre_decimal(
        session, CLE_SEUIL_CONFIANCE_OCR, SEUIL_CONFIANCE_DEFAUT
    )
    tolerance = await lire_parametre_decimal(
        session, CLE_TOLERANCE_TOTAL_HT, TOLERANCE_TOTAL_DEFAUT
    )
    vue = BLAVerifier(
        fournisseur=nom_fournisseur,
        numero=document.numero,
        date_doc=document.date_doc,
        chantier_brut=document.chantier_brut,
        total_ht=document.total_ht,
        lignes=tuple(
            LigneAVerifier(
                ordre=ligne.ordre, montant_ht=ligne.montant_ht, confiance=None
            )
            for ligne in lignes
        ),
        confiances=None,
        illisibles=frozenset(),
        numero_detecte=None,
    )
    return verifier_bl(vue, seuil_confiance=seuil, tolerance=tolerance)


def _statut_apres_correction(statut_actuel: str, motifs: tuple[Motif, ...]) -> str:
    if statut_actuel == "recu":
        return "a_verifier" if motifs else "recu"
    return statut_actuel


async def _appliquer_recalcul_motifs(session: AsyncSession, document: Document) -> None:
    motifs = await _recalculer_motifs_structurels(session, document)
    document.motifs = [motif_en_json(m) for m in motifs]
    document.statut = _statut_apres_correction(document.statut, motifs)


def _motifs_vers_motiflu(motifs: Sequence[Motif]) -> list[MotifLu]:
    """`extract.verification.Motif` (calculé ici) -> `ingest.lecture.MotifLu`
    (exposé, pour `ValidationRefusee.motifs`) — pas à confondre avec
    `ingest.lecture.motifs_lus`, qui décode la colonne JSON `document.motifs`
    déjà persistée."""
    return [MotifLu(code=m.code.value, champ=m.champ, detail=m.detail) for m in motifs]


# --------------------------------------------------------------------------
# detail_document
# --------------------------------------------------------------------------


async def detail_document(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    utilisateur_id: uuid.UUID,
    role: str,
) -> DocumentDetail:
    """Détail d'un BL/enlèvement (L3-D19) : un admin voit tous les
    documents, un agent seulement ceux qu'il a déposés (sinon
    `DocumentIntrouvable`, jamais un 403 — même principe que
    `ingest.lecture.fichier_document`)."""
    document = await _document_pour_lecture(session, document_id)
    if role != "admin" and document.deposant_id != utilisateur_id:
        raise DocumentIntrouvable(str(document_id))
    return await _charger_detail(session, document, role=role)


# --------------------------------------------------------------------------
# corriger_entete
# --------------------------------------------------------------------------


async def _document_en_double(
    session: AsyncSession,
    document_id: uuid.UUID,
    fournisseur_id: uuid.UUID | None,
    numero: str,
) -> uuid.UUID | None:
    """`id` d'un autre document du même fournisseur portant déjà `numero`
    (pour `NumeroDejaUtilise`) — même clé que l'unicité `(fournisseur_id,
    numero)`, mais renvoie l'UUID du document (le corps HTTP 409 porte
    `original_id`, comme `ingest.factures.FactureEnDouble`)."""
    resultat = await session.execute(
        select(Document.id).where(
            Document.fournisseur_id == fournisseur_id,
            Document.numero == numero,
            Document.id != document_id,
        )
    )
    return resultat.scalars().first()


async def _resoudre_chantier_document(
    session: AsyncSession, document: Document
) -> None:
    """Renseigne `document.chantier_id` à partir de `document.chantier_brut`
    et `document.fournisseur_id` courants (nouvelle résolution après une
    correction qui touche l'un des deux, L3-D13)."""
    if document.fournisseur_id is None:
        document.chantier_id = None
        return
    resolution = await resoudre_chantier(
        session, document.fournisseur_id, document.chantier_brut
    )
    document.chantier_id = resolution.chantier_id


async def _rattacher_articles_du_document(
    session: AsyncSession, document: Document
) -> None:
    """Ré-essaie de rattacher un article à chaque ligne `article` du document
    (fournisseur modifié, L3-D13) — jamais une ligne `eco`. Si le document
    n'a plus de fournisseur, les rattachements existants sont détachés (plus
    aucun référentiel à consulter)."""
    lignes = await _lignes_du_document(session, document.id)
    if document.fournisseur_id is None:
        for ligne in lignes:
            ligne.article_id = None
        return
    for ligne in lignes:
        if ligne.type_ligne != "article":
            continue
        proposition = proposer_article_bl(
            ligne.code_brut,
            ligne.article_brut,
            ligne.unite_brut,
            qte_conditionnements=ligne.qte_livree,
            qte_facturee=ligne.qte_totale,
        )
        ligne.article_id = await rattacher_article(
            session, document.fournisseur_id, proposition
        )


async def corriger_entete(
    session: AsyncSession,
    document_id: uuid.UUID,
    correction: CorrectionEntete,
    *,
    auteur_id: uuid.UUID,
) -> DocumentDetail:
    document = await _document_pour_ecriture(session, document_id)
    valeurs_avant = _valeurs_document_pour_journal(document)

    changements: dict[str, str | None] = {}
    valeurs_a_appliquer: dict[str, object] = {}
    for champ, valeur in correction.valeurs.items():
        if champ not in CHAMPS_CORRIGEABLES:
            # Défensif : le contrat de `CorrectionEntete.valeurs` (clés ⊂
            # `CHAMPS_CORRIGEABLES`) est déjà respecté par le seul appelant
            # (le routeur, construit depuis `CorrectionEnteteRequete`), mais
            # ne jamais faire confiance aveuglément à `setattr` plus bas sur
            # une clé arbitraire.
            continue
        valeur_normalisee = _valeur_normalisee(valeur)
        nouvelle_chaine = _valeur_en_chaine(valeur_normalisee)
        if nouvelle_chaine != valeurs_avant.get(champ):
            changements[champ] = nouvelle_chaine
            valeurs_a_appliquer[champ] = valeur_normalisee

    if not changements:
        return await _charger_detail(session, document, role="admin")

    fournisseur_id_brut = valeurs_a_appliquer.get(
        "fournisseur_id", document.fournisseur_id
    )
    fournisseur_id_final = (
        fournisseur_id_brut if isinstance(fournisseur_id_brut, uuid.UUID) else None
    )
    if (
        "fournisseur_id" in changements
        and fournisseur_id_final is not None
        and await session.get(Fournisseur, fournisseur_id_final) is None
    ):
        raise FournisseurIntrouvable(str(fournisseur_id_final))

    numero_brut = valeurs_a_appliquer.get("numero", document.numero)
    numero_final = numero_brut if isinstance(numero_brut, str) else None
    if (
        "numero" in changements or "fournisseur_id" in changements
    ) and numero_final is not None:
        original_id = await _document_en_double(
            session, document_id, fournisseur_id_final, numero_final
        )
        if original_id is not None:
            raise NumeroDejaUtilise(original_id)

    for champ, valeur in valeurs_a_appliquer.items():
        setattr(document, champ, valeur)

    if "fournisseur_id" in changements or "chantier_brut" in changements:
        await _resoudre_chantier_document(session, document)
    if "fournisseur_id" in changements:
        await _rattacher_articles_du_document(session, document)

    await _appliquer_recalcul_motifs(session, document)

    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="document_corrige",
            cible_table="document",
            cible_id=str(document_id),
            avant={champ: valeurs_avant.get(champ) for champ in changements},
            apres=changements,
        )
    )
    await session.commit()
    await session.refresh(document)
    return await _charger_detail(session, document, role="admin")


# --------------------------------------------------------------------------
# corriger_lignes
# --------------------------------------------------------------------------


def _contenu_ligne_db(ligne: Ligne) -> tuple[object, ...]:
    return (
        ligne.code_brut,
        ligne.article_brut,
        ligne.qte_livree,
        ligne.qte_totale,
        ligne.unite_brut,
        ligne.pu_ht,
        ligne.montant_ht,
    )


def _contenu_ligne_saisie(saisie: LigneSaisie) -> tuple[object, ...]:
    return (
        saisie.code_brut,
        saisie.article_brut,
        saisie.qte_livree,
        saisie.qte_totale,
        saisie.unite_brut,
        saisie.pu_ht,
        saisie.montant_ht,
    )


def _ligne_en_chaine(ligne: Ligne) -> dict[str, str | None]:
    return {
        "id": str(ligne.id),
        "code_brut": ligne.code_brut,
        "article_brut": ligne.article_brut,
        "qte_livree": str(ligne.qte_livree) if ligne.qte_livree is not None else None,
        "qte_totale": str(ligne.qte_totale) if ligne.qte_totale is not None else None,
        "unite_brut": ligne.unite_brut,
        "pu_ht": str(ligne.pu_ht) if ligne.pu_ht is not None else None,
        "montant_ht": str(ligne.montant_ht) if ligne.montant_ht is not None else None,
    }


async def corriger_lignes(
    session: AsyncSession,
    document_id: uuid.UUID,
    lignes: list[LigneSaisie],
    *,
    auteur_id: uuid.UUID,
) -> DocumentDetail:
    document = await _document_pour_ecriture(session, document_id)
    lignes_existantes = await _lignes_du_document(session, document_id)

    ids_connus = {ligne.id for ligne in lignes_existantes}
    ids_recus = {saisie.id for saisie in lignes if saisie.id is not None}
    inconnues = ids_recus - ids_connus
    if inconnues:
        raise LigneInconnue(str(next(iter(inconnues))))

    avant_signatures = [
        (ligne.id, *_contenu_ligne_db(ligne)) for ligne in lignes_existantes
    ]
    apres_signatures = [
        (saisie.id, *_contenu_ligne_saisie(saisie)) for saisie in lignes
    ]
    if avant_signatures == apres_signatures:
        return await _charger_detail(session, document, role="admin")

    avant_journal = [_ligne_en_chaine(ligne) for ligne in lignes_existantes]

    existantes_par_id = {ligne.id: ligne for ligne in lignes_existantes}
    for ligne in lignes_existantes:
        if ligne.id not in ids_recus:
            await session.delete(ligne)

    nouvelles_lignes: list[Ligne] = []
    for position, saisie in enumerate(lignes):
        if saisie.id is not None:
            ligne = existantes_par_id[saisie.id]
            if _contenu_ligne_saisie(saisie) != _contenu_ligne_db(ligne):
                ligne.confiance = None
            ligne.code_brut = saisie.code_brut
            ligne.article_brut = saisie.article_brut
            ligne.qte_livree = saisie.qte_livree
            ligne.qte_totale = saisie.qte_totale
            ligne.unite_brut = saisie.unite_brut
            ligne.pu_ht = saisie.pu_ht
            ligne.montant_ht = saisie.montant_ht
        else:
            ligne = Ligne(
                document_id=document_id,
                type_ligne="article",
                code_brut=saisie.code_brut,
                article_brut=saisie.article_brut,
                qte_livree=saisie.qte_livree,
                qte_totale=saisie.qte_totale,
                unite_brut=saisie.unite_brut,
                pu_ht=saisie.pu_ht,
                montant_ht=saisie.montant_ht,
                confiance=None,
            )
            session.add(ligne)
        ligne.ordre = position
        nouvelles_lignes.append(ligne)

    if document.fournisseur_id is not None:
        for ligne in nouvelles_lignes:
            if ligne.type_ligne != "article":
                continue
            proposition = proposer_article_bl(
                ligne.code_brut,
                ligne.article_brut,
                ligne.unite_brut,
                qte_conditionnements=ligne.qte_livree,
                qte_facturee=ligne.qte_totale,
            )
            ligne.article_id = await rattacher_article(
                session, document.fournisseur_id, proposition
            )

    await session.flush()

    await _appliquer_recalcul_motifs(session, document)

    apres_journal = [_ligne_en_chaine(ligne) for ligne in nouvelles_lignes]
    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="lignes_corrigees",
            cible_table="document",
            cible_id=str(document_id),
            avant={"lignes": avant_journal},
            apres={"lignes": apres_journal},
        )
    )
    await session.commit()
    await session.refresh(document)
    return await _charger_detail(session, document, role="admin")


# --------------------------------------------------------------------------
# valider_document
# --------------------------------------------------------------------------


async def valider_document(
    session: AsyncSession, document_id: uuid.UUID, *, auteur_id: uuid.UUID
) -> DocumentDetail:
    document = await _document_pour_ecriture(session, document_id)
    if document.statut != "a_verifier":
        raise DocumentNonModifiable(str(document_id))

    motifs = await _recalculer_motifs_structurels(session, document)
    if motifs:
        raise ValidationRefusee(_motifs_vers_motiflu(motifs))

    document.motifs = []
    document.statut = "recu"
    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="document_valide",
            cible_table="document",
            cible_id=str(document_id),
            avant={"statut": "a_verifier"},
            apres={"statut": "recu"},
        )
    )
    await session.commit()
    await session.refresh(document)
    return await _charger_detail(session, document, role="admin")


# --------------------------------------------------------------------------
# archiver_document
# --------------------------------------------------------------------------


async def archiver_document(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    commentaire: str,
    auteur_id: uuid.UUID,
) -> DocumentDetail:
    document = await _document_pour_ecriture(session, document_id)
    statut_avant = document.statut
    document.statut = "archive"
    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="document_archive",
            cible_table="document",
            cible_id=str(document_id),
            avant={"statut": statut_avant},
            apres={"statut": "archive", "commentaire": commentaire},
        )
    )
    await session.commit()
    await session.refresh(document)
    return await _charger_detail(session, document, role="admin")


# --------------------------------------------------------------------------
# relancer_extraction (L3-D15)
# --------------------------------------------------------------------------


async def _nombre_lignes(session: AsyncSession, document_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(Ligne)
            .where(Ligne.document_id == document_id)
        )
    ).scalar_one()


_MESSAGE_LECTURE_IMPOSSIBLE = "Lecture du document impossible, réessayez."


async def relancer_extraction(
    session: AsyncSession,
    document_id: uuid.UUID,
    docs_dir: Path,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
    *,
    auteur_id: uuid.UUID,
) -> DocumentDetail:
    document = await _document_pour_ecriture(session, document_id)
    if document.statut != "a_verifier":
        raise DocumentNonModifiable(str(document_id))

    # Résolution sûre du chemin de fichier réutilisée telle quelle
    # (`ingest.lecture.fichier_document`, décision du contrôleur) : `role`
    # forcé à `"admin"`, cette fonction n'étant appelée que par une route
    # admin (`fichier_document` lève `DocumentIntrouvable` si le fichier est
    # absent du disque ou hors `docs_dir`, code 404 identique à celui de
    # cette tâche).
    fichier = await fichier_document(
        session, document_id, docs_dir, utilisateur_id=auteur_id, role="admin"
    )
    contenu = await asyncio.to_thread(fichier.chemin.read_bytes)

    try:
        reponse = await ocr(contenu, fichier.type_mime)
    except ErreurOCR as exc:
        raise LectureImpossible(_MESSAGE_LECTURE_IMPOSSIBLE) from exc
    if not isinstance(reponse, dict) or not isinstance(reponse.get("pages"), list):
        raise LectureImpossible(_MESSAGE_LECTURE_IMPOSSIBLE)

    nb_lignes_avant = await _nombre_lignes(session, document_id)
    avant = {
        **_valeurs_document_pour_journal(document),
        "nb_lignes": str(nb_lignes_avant),
    }
    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="extraction_relancee",
            cible_table="document",
            cible_id=str(document_id),
            avant=avant,
            apres=None,
        )
    )

    await enregistrer_extraction_bl(session, document_id, reponse, relance=True)

    await session.refresh(document)
    return await _charger_detail(session, document, role="admin")
