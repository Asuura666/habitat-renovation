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

Lignes groupées (B-06, cas 2/1 et 2/2) : plusieurs lignes de facture peuvent
être reliées à une ligne de bon, et plusieurs lignes de bon à une même ligne
de facture. Les lignes reliées entre elles, et celles de même code reliées par
code, forment un groupe (comme l'appariement) : `qte_facturee`/`montant_
facture` sont la somme des lignes de facture du groupe, montrée une fois
(première ligne de bon du groupe), et `regles_ouvertes`/`controle` tiennent
compte des anomalies ouvertes sur n'importe quelle ligne du groupe (l'écart
R03/R04 est porté par la ligne de tête). `pu_facture` n'est montré que si
toutes les lignes du groupe ont le même prix. Un groupe de plusieurs lignes de
bon montre sur sa ligne de tête le livré du groupe (somme, détail « 10 + 10 »)
face au facturé du groupe ; les suivantes sont marquées
`inclus_dans_precedente` (le front y écrit « incluse dans la ligne
précédente » au lieu d'un verdict).

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
- `conforme` : ligne appariée, comparée, sans anomalie ouverte (affichée
  « Identique » : « Conforme » est réservé à la livraison, pastille du haut).

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
from collections.abc import Sequence
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
from app.modules.normalize.texte import normaliser_libelle

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
    # Groupe de plusieurs lignes de bon (constat final 1) : sur la ligne de
    # tête, `qte_livree` est la somme du groupe et `detail_livre` la montre
    # (« 10 + 10 ») ; sur les suivantes `inclus_dans_precedente` vaut vrai
    # (quantité de la ligne conservée, facturé et verdict portés par la tête).
    detail_livre: str | None = None
    inclus_dans_precedente: bool = False


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
    # Constat final 6 : quand la pastille dit « À vérifier » sans problème
    # ouvert, la cause en mots simples (« bon à valider », « facture à
    # vérifier »), sinon `None`.
    raison_a_verifier: str | None = None


def _controle(
    *,
    facture_connue: bool,
    lignes_facture: Sequence[Ligne],
    regles_ouvertes: list[str],
) -> Controle:
    """Verdict d'une ligne -- voir le docstring de module. `lignes_facture` :
    toutes les lignes de facture reliées à la ligne (ou à son groupe)."""
    if not facture_connue:
        return "pas_encore_facture"
    if regles_ouvertes:
        return "ecart"
    if not lignes_facture:
        return "non_facture"
    if all(
        ligne.qte_totale is None and ligne.pu_ht is None for ligne in lignes_facture
    ):
        return "non_controle"
    return "conforme"


def _cle_code(valeur: str | None) -> str:
    """Même clé que l'appariement par code (`normalize.appariement`) : une
    clé vide ne regroupe personne."""
    return normaliser_libelle(valeur).replace(" ", "")


class _Groupes:
    """Union-find sur des identifiants de lignes."""

    def __init__(self) -> None:
        self._parent: dict[uuid.UUID, uuid.UUID] = {}

    def racine(self, x: uuid.UUID) -> uuid.UUID:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def unir(self, a: uuid.UUID, b: uuid.UUID) -> None:
        self._parent[self.racine(a)] = self.racine(b)


def _somme_optionnelle(valeurs: list[Decimal | None]) -> Decimal | None:
    presentes = [v for v in valeurs if v is not None]
    return sum(presentes, Decimal("0")) if presentes else None


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
    # Liens (ligne BL, ligne de facture, méthode) du bloc affiché -- vide
    # tant qu'aucun bloc ne cite ce bon.
    liens: list[tuple[Ligne, Ligne, str]] = []
    lignes_bl_par_id = {ligne.id: ligne for ligne in lignes_bl}

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
        if lignes_bl_par_id:
            rapprochements = (
                (
                    await session.execute(
                        select(RapprochementLigne).where(
                            RapprochementLigne.ligne_bl_id.in_(list(lignes_bl_par_id))
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
                    liens.append(
                        (
                            lignes_bl_par_id[rapprochement.ligne_bl_id],
                            ligne_facture,
                            rapprochement.methode,
                        )
                    )

    # Groupes de lignes (B-06, cas 2/1 et 2/2) : deux lignes reliées entre
    # elles font un groupe, et toutes les lignes reliées par code de même
    # code aussi (c'est ainsi que l'appariement forme ses groupes ; l'écart
    # R03/R04 est porté par la ligne de tête). L'affichage et le verdict se
    # décident sur le groupe, jamais sur une ligne tirée au sort.
    groupes = _Groupes()
    par_code: dict[str, uuid.UUID] = {}
    for ligne_bl, ligne_facture, methode in liens:
        groupes.unir(ligne_bl.id, ligne_facture.id)
        if methode == "code":
            for ligne in (ligne_bl, ligne_facture):
                cle = _cle_code(ligne.code_brut)
                if not cle:
                    continue
                if cle in par_code:
                    groupes.unir(par_code[cle], ligne.id)
                else:
                    par_code[cle] = ligne.id
    membres_par_groupe: dict[uuid.UUID, dict[uuid.UUID, Ligne]] = {}
    bons_par_groupe: dict[uuid.UUID, list[Ligne]] = {}
    factures_par_groupe: dict[uuid.UUID, dict[uuid.UUID, Ligne]] = {}
    for ligne_bl, ligne_facture, _methode in liens:
        racine = groupes.racine(ligne_bl.id)
        bons_du_groupe = bons_par_groupe.setdefault(racine, [])
        if ligne_bl not in bons_du_groupe:
            bons_du_groupe.append(ligne_bl)
        membres_par_groupe.setdefault(racine, {})[ligne_bl.id] = ligne_bl
        membres_par_groupe[racine][ligne_facture.id] = ligne_facture
        factures_par_groupe.setdefault(racine, {})[ligne_facture.id] = ligne_facture

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
    groupes_deja_montres: set[uuid.UUID] = set()
    for ligne_bl in lignes_bl:
        groupe_bl = groupes.racine(ligne_bl.id)
        groupe = groupe_bl if groupe_bl in membres_par_groupe else None
        membres = membres_par_groupe[groupe] if groupe is not None else {}
        lignes_facture_groupe = (
            sorted(
                factures_par_groupe[groupe].values(),
                key=lambda ligne: (ligne.ordre, str(ligne.id)),
            )
            if groupe is not None
            else []
        )
        # Le total facturé du groupe n'est montré qu'une fois (première
        # ligne de BL du groupe) ; les suivantes gardent le verdict.
        montrer = groupe is not None and groupe not in groupes_deja_montres
        bons_du_groupe = (
            sorted(bons_par_groupe[groupe], key=lambda ligne: ligne.ordre)
            if groupe is not None
            else []
        )
        plusieurs_bons = len(bons_du_groupe) > 1
        qte_livree = ligne_bl.qte_totale
        detail_livre: str | None = None
        if plusieurs_bons and montrer:
            qte_livree = _somme_optionnelle([b.qte_totale for b in bons_du_groupe])
            detail_livre = " + ".join(
                f"{b.qte_totale:f}" for b in bons_du_groupe if b.qte_totale is not None
            )
        if groupe is not None:
            groupes_deja_montres.add(groupe)
        regles_ouvertes: list[str] = []
        for identifiant in (ligne_bl.id, *membres):
            for regle in anomalies_par_ligne.get(identifiant, ()):
                if regle not in regles_ouvertes:
                    regles_ouvertes.append(regle)
        prix = {
            ligne.pu_ht for ligne in lignes_facture_groupe if ligne.pu_ht is not None
        }
        lignes.append(
            LigneComparee(
                ordre=ligne_bl.ordre,
                code=ligne_bl.code_brut,
                article=ligne_bl.article_brut,
                qte_livree=qte_livree,
                qte_facturee=(
                    _somme_optionnelle([f.qte_totale for f in lignes_facture_groupe])
                    if montrer
                    else None
                ),
                pu_facture=next(iter(prix)) if montrer and len(prix) == 1 else None,
                montant_facture=(
                    _somme_optionnelle([f.montant_ht for f in lignes_facture_groupe])
                    if montrer
                    else None
                ),
                regles_ouvertes=regles_ouvertes,
                controle=_controle(
                    facture_connue=facture_id is not None,
                    lignes_facture=lignes_facture_groupe,
                    regles_ouvertes=regles_ouvertes,
                ),
                detail_livre=detail_livre,
                inclus_dans_precedente=plusieurs_bons and not montrer,
            )
        )

    categorie: CategorieBon = "pas_encore_facture"
    raison_a_verifier: str | None = None
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
        if categorie == "a_verifier" and not ids_anomalies_ouvertes:
            if document.statut == "a_verifier":
                raison_a_verifier = "bon à valider"
            elif (
                await session.execute(
                    select(BlocFacture.id)
                    .join(Document, Document.id == BlocFacture.facture_id)
                    .where(
                        BlocFacture.id.in_(ids_blocs_du_bon),
                        Document.statut == "a_verifier",
                    )
                    .limit(1)
                )
            ).first():
                raison_a_verifier = "facture à vérifier"

    return ComparaisonBl(
        document_id=document_id,
        facture_id=facture_id,
        bloc_id=bloc_id,
        numero_facture=numero_facture,
        montant_facture_ht=montant_facture_ht,
        lignes=lignes,
        nb_problemes=len(ids_anomalies_ouvertes),
        categorie=categorie,
        raison_a_verifier=raison_a_verifier,
    )
