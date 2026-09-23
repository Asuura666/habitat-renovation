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
`ingest.bilan.bilan_detail`/`_anomalies_par_ligne_et_bloc`).

`nb_problemes` (tour de correction 1, Task 8 -- constat de revue : « le
front décide lui-même du verdict à partir de données partielles ») compte,
lui, le nombre d'anomalies *distinctes* ouvertes concernant ce BL au sens
large, pas seulement celles rattachées à une ligne du périmètre ci-dessus :
s'y ajoutent celles portées par une ligne de facture du bloc jamais
appariée (R05 -- « facturée mais absente du bon », `ligne_id` = la ligne de
facture, jamais une ligne du BL), celles portées par le bloc lui-même
(`bloc_id`, ligne_id absent -- ex. R12, doublon de facturation) et celles
portées par le BL lui-même (`document_id`, ex. R11, incohérence
arithmétique du BL). C'est ce compte, jamais une somme refaite côté front
à partir de `regles_ouvertes`, qui doit fonder le nombre affiché par la
page BL -- décision du contrôleur."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
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
    nb_problemes: int


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
    # Identifiant du bloc qui cite ce BL, gardé à part de `facture_id` pour
    # la requête des anomalies ci-dessous (tour de correction 1) -- `None`
    # tant qu'aucun bloc ne cite ce BL, comme les trois champs ci-dessus.
    bloc_id_cible: uuid.UUID | None = None
    # Toutes les lignes de facture du bloc (appariées ou non) -- `None`
    # (l'appariement) exclut R03-R09/R13/R17 d'une ligne non appariée, mais
    # `nb_problemes` doit quand même compter R05 (« facturée mais absente
    # du bon »), qui porte justement sur une ligne de facture jamais
    # appariée à une ligne de BL.
    ids_lignes_facture: set[uuid.UUID] = set()
    # Ligne de facture appariée, par identifiant de ligne BL (`rapprochement
    # _ligne`) -- vide tant qu'aucun bloc ne cite ce BL.
    ligne_facture_par_ligne_bl: dict[uuid.UUID, Ligne] = {}

    if ligne_bloc is not None:
        bloc, numero_facture = ligne_bloc
        facture_id = bloc.facture_id
        bloc_id_cible = bloc.id

        lignes_facture = (
            (await session.execute(select(Ligne).where(Ligne.bloc_id == bloc.id)))
            .scalars()
            .all()
        )
        ids_lignes_facture = {ligne.id for ligne in lignes_facture}
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

    # Périmètre de `regles_ouvertes` (par ligne) : les lignes du BL et
    # *toutes* les lignes de facture du bloc, appariées ou non (`ids_lignes
    # _facture`, ci-dessus) -- une ligne de facture jamais appariée n'est
    # jamais la ligne d'une `LigneComparee`, mais son anomalie (R05) doit
    # quand même compter dans `nb_problemes`, voir la condition `bloc_id`
    # ci-dessous pour les anomalies qui ne portent sur aucune ligne du tout
    # (R01/R02/R12).
    ids_lignes_concernees = {ligne.id for ligne in lignes_bl} | ids_lignes_facture
    conditions_anomalies = [Anomalie.document_id == document_id]
    if ids_lignes_concernees:
        conditions_anomalies.append(Anomalie.ligne_id.in_(ids_lignes_concernees))
    if bloc_id_cible is not None:
        conditions_anomalies.append(Anomalie.bloc_id == bloc_id_cible)

    resultat_anomalies = await session.execute(
        select(Anomalie.id, Anomalie.ligne_id, Anomalie.regle)
        .where(Anomalie.statut == "ouverte", or_(*conditions_anomalies))
        .order_by(Anomalie.regle.asc())
    )
    anomalies_par_ligne: dict[uuid.UUID, list[str]] = {}
    ids_anomalies_ouvertes: set[uuid.UUID] = set()
    for anomalie_id, ligne_id, regle in resultat_anomalies.all():
        ids_anomalies_ouvertes.add(anomalie_id)
        if ligne_id is not None:
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
        nb_problemes=len(ids_anomalies_ouvertes),
    )
