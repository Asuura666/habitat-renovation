"""Comparaison d'un BL avec la facture qui le cite (`ingest/comparaison_bl.py`,
Task 3 de la refonte du front — `GET /api/documents/{id}/comparaison`).

Lecture seule : ne modifie jamais `rapprochement_ligne` ni `anomalie`,
n'écrit rien. Le lien BL -> bloc de facture réutilise
`BlocFacture.bl_document_id`, déjà porté par `ingest.bilan.bilan_par_bl`
(L4-D4) -- jamais recalculé par correspondance de numéro
(`ingest.lecture.documents_bl_par_numeros`), contrairement à
`ingest.lecture.facture_detail`, qui, lui, retombe sur ce calcul tant
qu'aucun rapprochement n'a encore tourné pour la facture (`bloc
.statut_rapprochement is None`). Cette tâche suit `bilan_par_bl` : la
photo n'est comparée qu'à la facture que le rapprochement lui a
effectivement associée, jamais à une facture simplement homonyme par
numéro.

`DocumentIntrouvable` (réutilisée depuis `ingest.lecture`, même exception
que `fichier_document`/`facture_detail` -- décision du contrôleur, un seul
404 côté routeur) si le document est absent ou n'est pas de type `bl` (un
enlèvement n'a pas de comparaison, CDC : seul un BL porte des lignes
comparables à un bloc de facture).

`qte_facturee`/`pu_facture` d'une ligne appariée viennent des colonnes
brutes de la ligne de facture (`Ligne.qte_totale`/`Ligne.pu_ht`) -- même
convention que `ingest.bilan.LigneBilanDetail.qte_facturee` (« valeurs
brutes de la ligne, pas la quantité convertie en unité de facturation »).
`montant_facture_ht` est la somme des `montant_ht` non nuls des lignes du
bloc, même calcul que `ingest.lecture.facture_detail` (jamais une colonne
stockée sur `bloc_facture`, qui n'en a pas).

`regles_ouvertes` d'une ligne BL rassemble les codes des anomalies ouvertes
(`statut == "ouverte"`) dont `ligne_id` vaut soit celui de la ligne BL
elle-même (ex. R06, qui porte sur la ligne de BL absente de la facture),
soit celui de sa ligne facture appariée (ex. R03-R09/R13/R17) -- jamais un
JOIN direct sur `ligne`/`anomalie` (une seule requête supplémentaire,
bornée aux identifiants déjà connus du périmètre, même piège que
`ingest.bilan.bilan_detail`/`_anomalies_par_ligne_et_bloc`)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.lecture import DocumentIntrouvable
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Document,
    Ligne,
    RapprochementLigne,
)


@dataclass(frozen=True)
class LigneComparee:
    """Une ligne du BL, avec sa ligne de facture appariée (si `rapprochement
    _ligne` en connaît une) -- `qte_facturee`/`pu_facture` valent `None` si
    la ligne n'a jamais été appariée à une ligne de facture (BL non
    rapproché, ou ligne sans correspondance)."""

    ordre: int
    code: str | None
    article: str | None
    qte_livree: Decimal | None
    qte_facturee: Decimal | None
    pu_facture: Decimal | None
    regles_ouvertes: list[str]


@dataclass(frozen=True)
class ComparaisonBl:
    """`facture_id`/`numero_facture`/`montant_facture_ht` valent `None`
    quand aucun bloc de facture ne cite ce BL (`bl_document_id`, décision du
    contrôleur -- même principe que `LigneBilanBl.bl_document_id` côté
    bilan, mais vu depuis le BL plutôt que depuis le bloc)."""

    document_id: uuid.UUID
    facture_id: uuid.UUID | None
    numero_facture: str | None
    montant_facture_ht: Decimal | None
    lignes: list[LigneComparee]


async def comparer_bl(session: AsyncSession, document_id: uuid.UUID) -> ComparaisonBl:
    """Lève `DocumentIntrouvable` si `document_id` est absent ou si le
    document n'est pas de type `bl`."""
    document = await session.get(Document, document_id)
    if document is None or document.type != "bl":
        raise DocumentIntrouvable(str(document_id))

    lignes_bl = (
        (
            await session.execute(
                select(Ligne)
                .where(Ligne.document_id == document_id)
                .order_by(Ligne.ordre.asc())
            )
        )
        .scalars()
        .all()
    )

    ligne_bloc = (
        await session.execute(
            select(BlocFacture, Document.numero)
            .join(Document, Document.id == BlocFacture.facture_id)
            .where(BlocFacture.bl_document_id == document_id)
            .order_by(BlocFacture.created_at.asc(), BlocFacture.id.asc())
            .limit(1)
        )
    ).first()

    facture_id: uuid.UUID | None = None
    numero_facture: str | None = None
    montant_facture_ht: Decimal | None = None
    # Ligne de facture appariée, par identifiant de ligne BL (`rapprochement
    # _ligne`) -- vide tant qu'aucun bloc ne cite ce BL.
    ligne_facture_par_ligne_bl: dict[uuid.UUID, Ligne] = {}

    if ligne_bloc is not None:
        bloc, numero_facture = ligne_bloc
        facture_id = bloc.facture_id

        lignes_facture = (
            (await session.execute(select(Ligne).where(Ligne.bloc_id == bloc.id)))
            .scalars()
            .all()
        )
        montant_facture_ht = sum(
            (
                ligne.montant_ht
                for ligne in lignes_facture
                if ligne.montant_ht is not None
            ),
            Decimal("0"),
        )

        lignes_facture_par_id = {ligne.id: ligne for ligne in lignes_facture}
        ids_lignes_bl = {ligne.id for ligne in lignes_bl}
        if ids_lignes_bl:
            rapprochements = (
                (
                    await session.execute(
                        select(RapprochementLigne).where(
                            RapprochementLigne.ligne_bl_id.in_(ids_lignes_bl)
                        )
                    )
                )
                .scalars()
                .all()
            )
            for rapprochement in rapprochements:
                ligne_facture = lignes_facture_par_id.get(
                    rapprochement.ligne_facture_id
                )
                if ligne_facture is not None:
                    ligne_facture_par_ligne_bl[rapprochement.ligne_bl_id] = (
                        ligne_facture
                    )

    ids_lignes_concernees = {ligne.id for ligne in lignes_bl} | {
        ligne_facture.id for ligne_facture in ligne_facture_par_ligne_bl.values()
    }
    anomalies_par_ligne: dict[uuid.UUID, list[str]] = {}
    if ids_lignes_concernees:
        resultat_anomalies = await session.execute(
            select(Anomalie.ligne_id, Anomalie.regle)
            .where(
                Anomalie.statut == "ouverte",
                Anomalie.ligne_id.in_(ids_lignes_concernees),
            )
            .order_by(Anomalie.regle.asc())
        )
        for ligne_id, regle in resultat_anomalies.all():
            anomalies_par_ligne.setdefault(ligne_id, []).append(regle)

    lignes: list[LigneComparee] = []
    for ligne_bl in lignes_bl:
        ligne_facture = ligne_facture_par_ligne_bl.get(ligne_bl.id)
        regles_ouvertes = list(anomalies_par_ligne.get(ligne_bl.id, ()))
        if ligne_facture is not None:
            regles_ouvertes += anomalies_par_ligne.get(ligne_facture.id, ())
        lignes.append(
            LigneComparee(
                ordre=ligne_bl.ordre,
                code=ligne_bl.code_brut,
                article=ligne_bl.article_brut,
                qte_livree=ligne_bl.qte_livree,
                qte_facturee=(
                    ligne_facture.qte_totale if ligne_facture is not None else None
                ),
                pu_facture=ligne_facture.pu_ht if ligne_facture is not None else None,
                regles_ouvertes=regles_ouvertes,
            )
        )

    return ComparaisonBl(
        document_id=document_id,
        facture_id=facture_id,
        numero_facture=numero_facture,
        montant_facture_ht=montant_facture_ht,
        lignes=lignes,
    )
