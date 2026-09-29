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
404 côté routeur) si le document est absent ou n'est ni un BL ni un bon
d'enlèvement. Revue finale de la refonte du front (constat SERVEUR-5) : le
CDC §4.5 dit « Bons d'enlèvement : traités comme des BL », et le
rapprochement relie bien un enlèvement à un bloc de facture
(`ingest.lecture.TYPES_BL`, même couple que `rapprochement._TYPES_BL`) --
un enlèvement a donc, lui aussi, sa comparaison.

Blocs qui citent ce bon (revue finale, constat SERVEUR-4) : **tous** les
blocs d'une facture non archivée (même garde que le bilan et le
rapprochement : `type == "facture"`, `statut != "archive"`) dont
`bl_document_id` vaut ce bon. Le bloc affiché (facture, montant, lignes
appariées) est le plus ancien d'entre eux (`created_at`, puis `id` pour
départager) : la facturation d'origine. Un bon facturé deux fois porte son
R12 sur le bloc de la seconde facture : il reste compté dans
`nb_problemes`, qui couvre tous ces blocs (voir plus bas). Une facture
archivée garde son `bl_document_id` (`corrections.archiver_document` ne le
remet pas à zéro) mais n'est plus jamais présentée comme « la » facture du
bon : le bilan l'exclut déjà.

`qte_facturee`/`pu_facture` d'une ligne appariée viennent des colonnes
brutes de la ligne de facture (`Ligne.qte_totale`/`Ligne.pu_ht`) -- même
convention que `ingest.bilan.LigneBilanDetail.qte_facturee` (« valeurs
brutes de la ligne, pas la quantité convertie en unité de facturation »).
`montant_facture_ht` est la somme des `montant_ht` non nuls des lignes du
bloc affiché, même calcul que `ingest.lecture.facture_detail` (jamais une
colonne stockée sur `bloc_facture`, qui n'en a pas).

`regles_ouvertes` d'une ligne BL rassemble les codes des anomalies ouvertes
(`statut == "ouverte"`) dont `ligne_id` vaut soit celui de la ligne BL
elle-même (ex. R06, qui porte sur la ligne de BL absente de la facture),
soit celui de sa ligne facture appariée (ex. R03-R09/R13/R17).

`controle` d'une ligne (revue finale, constats SERVEUR-6/ECRAN-3) : verdict
calculé ici, affiché tel quel par la page BL -- jamais déduit par le front
du seul fait que `regles_ouvertes` est vide :
- `pas_encore_facture` : aucune facture ne cite encore ce bon, rien n'a été
  comparé ;
- `ecart` : au moins une anomalie ouverte porte sur la ligne ;
- `non_facture` : la ligne n'a été appariée à aucune ligne de la facture
  affichée (« non retrouvée sur la facture ») -- elle n'est pas pour autant
  « conforme » ;
- `non_controle` : la ligne est appariée à une ligne de facture qui ne
  porte ni quantité ni prix unitaire (ex. une éco-participation facturée
  au seul montant) -- rien n'a pu être comparé, ce n'est pas un
  « conforme » ; son montant facturé (`montant_facture`) est exposé pour
  que la page le montre tel quel ;
- `conforme` : ligne appariée, comparée, sans anomalie ouverte.

`nb_problemes` (tour de correction 1, Task 8 -- constat de revue : « le
front décide lui-même du verdict à partir de données partielles ») compte
le nombre d'anomalies *distinctes* ouvertes concernant ce BL au sens large,
selon `ingest.anomalies.condition_anomalies_du_bl` : portées par le bon
lui-même (R11/R15), par l'un des blocs qui le citent (R01/R02/R12) ou par
une ligne de l'un ou de l'autre (R05 sur une ligne de facture jamais
appariée, R03-R09, R06...). C'est exactement le périmètre de la liste
ouverte par « Régler les problèmes » (`GET /api/anomalies?bl_document_id=`,
revue finale, constat LIENS-1) : le nombre annoncé et la liste ne peuvent
plus diverger."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.anomalies import (
    condition_anomalies_du_bl,
    condition_regles_actives,
)
from app.modules.ingest.bilan import categories_des_blocs
from app.modules.ingest.commun import regles_masquees
from app.modules.ingest.lecture import TYPES_BL, DocumentIntrouvable
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Document,
    Ligne,
    RapprochementLigne,
)

Controle = Literal[
    "conforme", "ecart", "non_facture", "non_controle", "pas_encore_facture"
]

# Verdict d'ensemble du bon (décision d'Ilane du 29/09/2026) : « conforme » ou
# « a_verifier » selon la définition unique `ingest.bilan._sous_requete_
# categories` (toutes les factures qui citent ce bon, ce bon validé, aucun
# problème ouvert) ; « pas_encore_facture » tant qu'aucune facture ne le cite ;
# « sans_bon » n'existe pas ici (un bon qu'on regarde existe).
CategorieBon = Literal["conforme", "a_verifier", "pas_encore_facture"]


@dataclass(frozen=True)
class LigneComparee:
    """Une ligne du BL, avec sa ligne de facture appariée (si `rapprochement
    _ligne` en connaît une) -- `qte_facturee`/`pu_facture` valent `None` si
    la ligne n'a jamais été appariée à une ligne de facture (BL non
    rapproché, ou ligne sans correspondance).

    `qte_livree` vaut `Ligne.qte_totale` de la ligne BL (tour de correction
    2, Task 8 -- constat de revue) : `Ligne.qte_livree` est le nombre de
    conditionnements (souvent nul, L3-D24), pas la quantité comparable à
    `qte_facturee` -- même convention que R03 (`rules/R03.py`) et le bilan
    (`ingest.bilan`, `bl_ligne.qte_totale` -> `qte_bl_appariee`).

    `controle` et `montant_facture` (montant HT de la ligne de facture
    appariée, `None` sans appariement) : voir le docstring de module."""

    ordre: int
    code: str | None
    article: str | None
    qte_livree: Decimal | None
    qte_facturee: Decimal | None
    pu_facture: Decimal | None
    montant_facture: Decimal | None
    regles_ouvertes: list[str]
    controle: Controle


@dataclass(frozen=True)
class ComparaisonBl:
    """`facture_id`/`bloc_id`/`numero_facture`/`montant_facture_ht` valent
    `None` quand aucun bloc de facture non archivée ne cite ce BL
    (`bl_document_id`, décision du contrôleur -- même principe que
    `LigneBilanBl.bl_document_id` côté bilan, mais vu depuis le BL plutôt
    que depuis le bloc). `bloc_id` (revue finale) identifie le bloc affiché
    dans sa facture : ancre `#bloc-<id>` du lien « Voir la facture »."""

    document_id: uuid.UUID
    facture_id: uuid.UUID | None
    bloc_id: uuid.UUID | None
    numero_facture: str | None
    montant_facture_ht: Decimal | None
    lignes: list[LigneComparee]
    nb_problemes: int
    categorie: CategorieBon


def _controle(
    *,
    facture_connue: bool,
    ligne_facture: Ligne | None,
    regles_ouvertes: list[str],
) -> Controle:
    """Verdict d'une ligne -- voir le docstring de module."""
    if not facture_connue:
        return "pas_encore_facture"
    if regles_ouvertes:
        return "ecart"
    if ligne_facture is None:
        return "non_facture"
    if ligne_facture.qte_totale is None and ligne_facture.pu_ht is None:
        return "non_controle"
    return "conforme"


async def comparer_bl(session: AsyncSession, document_id: uuid.UUID) -> ComparaisonBl:
    """Lève `DocumentIntrouvable` si `document_id` est absent ou si le
    document n'est ni un BL ni un bon d'enlèvement."""
    document = await session.get(Document, document_id)
    if document is None or document.type not in TYPES_BL:
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
            .where(
                BlocFacture.bl_document_id == document_id,
                Document.type == "facture",
                Document.statut != "archive",
            )
            .order_by(BlocFacture.created_at.asc(), BlocFacture.id.asc())
            .limit(1)
        )
    ).first()

    facture_id: uuid.UUID | None = None
    bloc_id: uuid.UUID | None = None
    numero_facture: str | None = None
    montant_facture_ht: Decimal | None = None
    # Ligne de facture appariée, par identifiant de ligne BL (`rapprochement
    # _ligne`) -- vide tant qu'aucun bloc ne cite ce BL.
    ligne_facture_par_ligne_bl: dict[uuid.UUID, Ligne] = {}

    if ligne_bloc is not None:
        bloc, numero_facture = ligne_bloc
        facture_id = bloc.facture_id
        bloc_id = bloc.id

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
                        select(RapprochementLigne)
                        .where(RapprochementLigne.ligne_bl_id.in_(ids_lignes_bl))
                        # Départage déterministe (mineur de la Task 3 :
                        # « plusieurs rapprochements par ligne BL sans
                        # ORDER BY ») -- le plus ancien fait foi.
                        .order_by(
                            RapprochementLigne.created_at.asc(),
                            RapprochementLigne.id.asc(),
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
                if (
                    ligne_facture is not None
                    and rapprochement.ligne_bl_id not in ligne_facture_par_ligne_bl
                ):
                    ligne_facture_par_ligne_bl[rapprochement.ligne_bl_id] = (
                        ligne_facture
                    )

    exclues = await regles_masquees(session)
    resultat_anomalies = await session.execute(
        select(Anomalie.id, Anomalie.ligne_id, Anomalie.regle)
        .where(
            condition_regles_actives(exclues),
            Anomalie.statut == "ouverte",
            condition_anomalies_du_bl(document_id),
        )
        .order_by(Anomalie.regle.asc())
    )
    anomalies_par_ligne: dict[uuid.UUID, list[str]] = {}
    ids_anomalies_ouvertes: set[uuid.UUID] = set()
    for anomalie_id, ligne_id, regle in resultat_anomalies.all():
        ids_anomalies_ouvertes.add(anomalie_id)
        if ligne_id is not None:
            anomalies_par_ligne.setdefault(ligne_id, []).append(regle)

    lignes: list[LigneComparee] = []
    # B-06 : plusieurs lignes de BL de même code peuvent être reliées à la
    # même ligne de facture ; ses quantités et son montant ne sont montrés
    # qu'une fois (première ligne de BL), les suivantes gardent le verdict.
    lignes_facture_deja_montrees: set[uuid.UUID] = set()
    for ligne_bl in lignes_bl:
        ligne_facture = ligne_facture_par_ligne_bl.get(ligne_bl.id)
        deja_montree = (
            ligne_facture is not None
            and ligne_facture.id in lignes_facture_deja_montrees
        )
        if ligne_facture is not None:
            lignes_facture_deja_montrees.add(ligne_facture.id)
        regles_ouvertes = list(anomalies_par_ligne.get(ligne_bl.id, ()))
        if ligne_facture is not None:
            regles_ouvertes += anomalies_par_ligne.get(ligne_facture.id, ())
        lignes.append(
            LigneComparee(
                ordre=ligne_bl.ordre,
                code=ligne_bl.code_brut,
                article=ligne_bl.article_brut,
                qte_livree=ligne_bl.qte_totale,
                qte_facturee=(
                    ligne_facture.qte_totale
                    if ligne_facture is not None and not deja_montree
                    else None
                ),
                pu_facture=(
                    ligne_facture.pu_ht
                    if ligne_facture is not None and not deja_montree
                    else None
                ),
                montant_facture=(
                    ligne_facture.montant_ht
                    if ligne_facture is not None and not deja_montree
                    else None
                ),
                regles_ouvertes=regles_ouvertes,
                controle=_controle(
                    facture_connue=facture_id is not None,
                    ligne_facture=ligne_facture,
                    regles_ouvertes=regles_ouvertes,
                ),
            )
        )

    categorie: CategorieBon = "pas_encore_facture"
    ids_blocs_du_bon = (
        (
            await session.execute(
                select(BlocFacture.id)
                .join(Document, Document.id == BlocFacture.facture_id)
                .where(
                    BlocFacture.bl_document_id == document_id,
                    Document.type == "facture",
                    Document.statut != "archive",
                )
            )
        )
        .scalars()
        .all()
    )
    if ids_blocs_du_bon:
        categories = await categories_des_blocs(session, ids_blocs_du_bon)
        tous_conformes = all(c == "conforme" for c in categories.values())
        categorie = (
            "conforme"
            if tous_conformes and not ids_anomalies_ouvertes and categories
            else "a_verifier"
        )

    return ComparaisonBl(
        document_id=document_id,
        facture_id=facture_id,
        bloc_id=bloc_id,
        numero_facture=numero_facture,
        montant_facture_ht=montant_facture_ht,
        lignes=lignes,
        nb_problemes=len(ids_anomalies_ouvertes),
        categorie=categorie,
    )
