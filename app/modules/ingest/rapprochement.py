"""Rapprochement des factures (`ingest/rapprochement.py`, L4-T7) : cœur du
lot 4 — pour une facture, rapproche chaque bloc « Concerne le B.L. » avec le
BL déposé, apparie les lignes de chaque bloc, convertit les quantités dans
l'unité de facturation, alimente le moteur de règles pur
(`app.modules.rules`, déjà commité, non modifié ici) et persiste le
résultat (statut de bloc, lignes de `rapprochement_ligne`, `qte_fact`,
anomalies via `ingest.anomalies.synchroniser_anomalies`, journal) —
idempotent (L4-D3) : une photo de BL arrive souvent après la facture, le
rapprochement est alors rejoué.

Décisions du contrôleur (à distinguer de la fiche, qui fait foi en cas
d'écart) :
- Ruling R3 : un bloc est `recu` dès qu'un BL non archivé du même
  fournisseur porte son numéro, quel que soit le statut de ce BL — le
  moteur, lui, ne compare les quantités que si ce BL est lui-même `recu`
  (il reçoit `DocumentControle.statut`, `rules.engine._evaluer_bloc`).
- Conversion (Ruling R10, `normalize.unites.convertir_en_unite_fact`) :
  `unite_absente_acceptee=True` pour une ligne de facture (Unikalo n'imprime
  aucune unité), `False` (défaut) pour une ligne de BL. Ruling R14 (fix
  round 1 de cette tâche, implémenté dans `convertir_en_unite_fact`
  elle-même — `_ligne_controlee` ci-dessous ne change pas, elle délègue déjà
  tout à cette fonction) : quand ni l'unité lue ni l'unité de facturation de
  l'article ne sont connues, la quantité est renvoyée inchangée quel que
  soit ce drapeau — sans quoi `qte_fact` restait `NULL` sur toutes les
  lignes d'un fournisseur qui n'imprime d'unité nulle part (constat réel sur
  la facture Unikalo d'août), rendant R03/R04 muettes en permanence.
- Ruling R16 (fix round 2 de cette tâche, `normalize.unites
  .unite_implicite`) : une quantité rendue inchangée par le cas 2 ci-dessus
  n'est comparable (R03/R04) qu'à une autre quantité rendue de la même
  façon — `_ligne_controlee` porte ce drapeau (`LigneControlee
  .unite_implicite`) depuis la même source que l'appel à
  `convertir_en_unite_fact`, la garde elle-même vit dans `rules.rules.R03
  .ecart_qte_fact` (module pur).
- Ruling R17 (fix round 2 de cette tâche) : les règles pures ne connaissent
  qu'un bloc ou une ligne, jamais l'identifiant du document — seules
  R10/R11/R15 portent nativement `document_id`. Juste avant l'appel à
  `synchroniser_anomalies`, toute anomalie produite ici dont `document_id`
  est `None` reçoit `document_id = facture_id` (`dataclasses.replace`,
  `Anomalie` est un dataclass gelé) : sans cela, l'écran Anomalies
  (CDC §4.6) ne peut pas remonter à la pièce pour la plupart des règles.
  Sans danger pour l'idempotence (la valeur est stable d'un rejeu à
  l'autre) ni pour la portée de suppression (`_conditions_portee` couvre
  déjà « `document_id` = la facture » **ou** « bloc de cette facture »).
  Les anomalies de suivi (R06, R14, R15, R16), produites hors
  `rapprocher_facture`, ne sont jamais concernées.
- Ruling L5-R3 (tour de correction 1 de L5-T1) : même idiome que le Ruling
  R17 ci-dessus, pour `bloc_id` cette fois. R07, R08, R09, R13 et R17 ne
  posent que `ligne_id` sur leur anomalie (la règle pure ne reçoit que la
  ligne, jamais le bloc) ; juste après le complément de `document_id`,
  toute anomalie qui porte un `ligne_id` mais pas de `bloc_id` reçoit celui
  de sa ligne (`lignes_facture_db`, déjà chargée pour cette facture). Sans
  cela, `ingest.anomalies.CHANTIER_ID_RESOLU` ne pouvait résoudre le
  chantier d'aucune de ces cinq règles (il ne passe jamais par la ligne) et
  retombait sur `Document.chantier_id`, presque toujours vide pour une
  facture — l'anomalie s'affichait sans chantier et échappait au filtre par
  chantier de l'écran Anomalies (constat fait en préparant L5-T1). Même
  garantie d'idempotence que le Ruling R17 (la ligne ne change pas de bloc
  d'un rejeu à l'autre).
- Historique des prix (L4-D9) : une seule requête pour toute la facture,
  agrégée en Python (médiane par article).
- Transaction : `rapprocher_facture` fait un seul `commit()` à la fin ; en
  cas d'exception, rien n'est écrit. Les déclenchements (dépôt de facture,
  validation d'un BL, extraction d'un BL) ne doivent jamais faire échouer
  l'action appelante : `rapprocher_facture_sans_echec`/
  `rapprocher_factures_du_bl` encapsulent l'appel, journalisent l'échec
  (`_journaliser_echec`, même prudence que `ingest.commun._journaliser_echec` :
  jamais le contenu de l'exception) et avalent l'erreur.
- Idempotence : les lignes de `rapprochement_ligne` de la facture sont
  remplacées à chaque rejeu ; `synchroniser_anomalies` (déjà commité, L4-T8)
  fait le reste pour les anomalies.
"""

from __future__ import annotations

import calendar
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.anomalies import synchroniser_anomalies
from app.modules.ingest.commun import logger
from app.modules.ingest.lecture import (
    FactureIntrouvable,
    MotifLu,
    _normaliser_numero,
    documents_bl_par_numeros,
    motifs_lus,
)
from app.modules.ingest.models import (
    Article,
    BlocFacture,
    Chantier,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    Parametre,
    RapprochementLigne,
    Utilisateur,
)
from app.modules.ingest.parametres import PARAMETRES_DEFAUT
from app.modules.ingest.referentiels import lire_parametre_decimal
from app.modules.normalize.appariement import LigneAApparier, apparier_lignes
from app.modules.normalize.unites import convertir_en_unite_fact, unite_implicite
from app.modules.rules.engine import REGLES_FACTURE, evaluer_facture
from app.modules.rules.modeles import (
    ArticleControle,
    BlocControle,
    DocumentControle,
    FactureControlee,
    HistoriqueArticle,
    LigneControlee,
    LigneRapprochee,
    Parametres,
)
from app.modules.rules.rules.R02 import mention_pas_de_bon

__all__ = [
    "FactureIntrouvable",
    "ResultatRapprochement",
    "factures_recues",
    "rapprocher_facture",
    "rapprocher_facture_sans_echec",
    "rapprocher_factures_du_bl",
]

# Types de document traités comme un BL pour le rapprochement (CDC §4.5 :
# « Bons d'enlèvement (Point.P) : traités comme des BL »).
_TYPES_BL: tuple[str, ...] = ("bl", "enlevement")


@dataclass(frozen=True)
class ResultatRapprochement:
    """Issue de `rapprocher_facture`/`rapprocher_factures_du_bl` (fiche
    L4-T7) : compteurs pour le journal `facture_rapprochee` et pour un
    retour de CLI, sans requête supplémentaire de l'appelant."""

    facture_id: uuid.UUID
    nb_blocs: int
    nb_blocs_recus: int
    nb_blocs_pas_de_bon: int
    nb_lignes_appariees: int
    nb_anomalies: int


# --------------------------------------------------------------------------
# Seuils (L4-D10) : créés avec leur valeur par défaut au premier
# rapprochement, lus ensuite via `referentiels.lire_parametre_decimal`.
# --------------------------------------------------------------------------


async def _charger_parametres(session: AsyncSession) -> Parametres:
    """Seuils modifiables par l'admin (CDC §5, L4-D10) : créés avec leur
    valeur par défaut s'ils sont absents (`INSERT ... ON CONFLICT DO
    NOTHING`, même mécanisme que `referentiels.resoudre_chantier`/
    `rattacher_article`), puis lus via `lire_parametre_decimal` — jamais de
    commit ici, l'appelant (`rapprocher_facture`) décide du périmètre
    transactionnel."""
    for cle, defaut in PARAMETRES_DEFAUT:
        await session.execute(
            insert(Parametre)
            .values(cle=cle, valeur=str(defaut))
            .on_conflict_do_nothing(index_elements=[Parametre.cle])
        )

    valeurs = {
        cle: await lire_parametre_decimal(session, cle, defaut)
        for cle, defaut in PARAMETRES_DEFAUT
    }
    return Parametres(
        tolerance_total_ht=valeurs["tolerance_total_ht"],
        seuil_prix_pct=valeurs["seuil_prix_pct"],
        seuil_prix_fort_pct=valeurs["seuil_prix_fort_pct"],
        occurrences_prix_min=int(valeurs["occurrences_prix_min"]),
        delai_ligne_bl_non_facturee_j=int(valeurs["delai_ligne_bl_non_facturee_j"]),
        delai_alias_non_resolu_h=int(valeurs["delai_alias_non_resolu_h"]),
        delai_confirmation_bl_h=int(valeurs["delai_confirmation_bl_h"]),
        delai_chantier_silencieux_j=int(valeurs["delai_chantier_silencieux_j"]),
        duree_ignorance_j=int(valeurs["duree_ignorance_j"]),
    )


# --------------------------------------------------------------------------
# Historique des prix (L4-D9)
# --------------------------------------------------------------------------


def _six_mois_avant(reference: date) -> date:
    """`reference` moins 6 mois civils, jour borné à la fin du mois cible
    (ex. 31 août -> dernier jour de février) — calcul en stdlib pur,
    `python-dateutil` n'est pas dans la stack (CLAUDE.md)."""
    mois_total = reference.month - 1 - 6
    annee = reference.year + mois_total // 12
    mois = mois_total % 12 + 1
    dernier_jour = calendar.monthrange(annee, mois)[1]
    return date(annee, mois, min(reference.day, dernier_jour))


def _mediane(valeurs: list[Decimal]) -> Decimal | None:
    """Médiane (moyenne des deux valeurs centrales si le nombre est pair,
    L4-D9/décision du contrôleur), `None` si `valeurs` est vide."""
    if not valeurs:
        return None
    triees = sorted(valeurs)
    milieu = len(triees) // 2
    if len(triees) % 2 == 1:
        return triees[milieu]
    return (triees[milieu - 1] + triees[milieu]) / 2


async def _construire_historiques(
    session: AsyncSession,
    *,
    fournisseur_id: uuid.UUID | None,
    facture_id: uuid.UUID,
    date_facture: date | None,
    article_ids: set[uuid.UUID],
) -> dict[uuid.UUID, HistoriqueArticle]:
    """Historique des prix/remises de chaque article de `article_ids», sur
    les 6 mois précédant `date_facture` chez `fournisseur_id`, facture
    contrôlée exclue (L4-D9, décision du contrôleur : une seule requête,
    agrégée en Python). `{}` si `fournisseur_id`/`date_facture` sont absents
    ou si `article_ids` est vide (rien à comparer)."""
    if fournisseur_id is None or date_facture is None or not article_ids:
        return {}

    borne_inf = _six_mois_avant(date_facture)
    lignes = (
        await session.execute(
            select(Ligne.article_id, Ligne.pu_ht, Ligne.remise_pct)
            .join(Document, Document.id == Ligne.document_id)
            .where(
                Document.type == "facture",
                Document.fournisseur_id == fournisseur_id,
                Document.id != facture_id,
                Ligne.type_ligne == "article",
                Ligne.article_id.in_(article_ids),
                Document.date_doc >= borne_inf,
                Document.date_doc < date_facture,
            )
        )
    ).all()

    prix_par_article: dict[uuid.UUID, list[Decimal]] = defaultdict(list)
    remises_par_article: dict[uuid.UUID, list[Decimal]] = defaultdict(list)
    for article_id, pu_ht, remise_pct in lignes:
        if article_id is None:
            continue
        if pu_ht is not None:
            prix_par_article[article_id].append(pu_ht)
        if remise_pct is not None and remise_pct > 0:
            remises_par_article[article_id].append(remise_pct)

    historiques: dict[uuid.UUID, HistoriqueArticle] = {}
    for article_id in article_ids:
        prix = prix_par_article.get(article_id, [])
        remises = remises_par_article.get(article_id, [])
        historiques[article_id] = HistoriqueArticle(
            article_id=article_id,
            mediane_pu=_mediane(prix),
            occurrences=len(prix),
            remise_habituelle=_mediane(remises),
            occurrences_remise=len(remises),
        )
    return historiques


# --------------------------------------------------------------------------
# Vues du moteur (`DocumentControle`, `LigneControlee`)
# --------------------------------------------------------------------------


def _ecarts_depuis_motifs(
    motifs: list[MotifLu],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """`(somme_lignes, total_ht, ecart_somme)` depuis le motif
    `somme_incoherente` déjà produit par l'extraction et persisté dans
    `document.motifs` (L4-D8 : R10/R11 ne recalculent jamais la somme).
    `(None, None, None)` si le motif est absent ou mal formé."""
    motif_somme = next((m for m in motifs if m.code == "somme_incoherente"), None)
    if motif_somme is None:
        return None, None, None
    try:
        return (
            Decimal(motif_somme.detail["somme"]),
            Decimal(motif_somme.detail["total"]),
            Decimal(motif_somme.detail["ecart"]),
        )
    except (KeyError, InvalidOperation):
        return None, None, None


def _document_controle(
    document: Document, deposant_nom: str | None
) -> DocumentControle:
    somme_lignes, total_ht, ecart_somme = _ecarts_depuis_motifs(
        motifs_lus(document.motifs)
    )
    return DocumentControle(
        id=document.id,
        numero_interne=document.numero_interne,
        numero=document.numero,
        date_doc=document.date_doc,
        statut=document.statut,
        somme_lignes=somme_lignes,
        total_ht=total_ht,
        ecart_somme=ecart_somme,
        depose_le=document.created_at,
        deposant=deposant_nom,
        confirme_le=document.confirme_le,
    )


def _ligne_controlee(
    ligne: Ligne,
    articles: dict[uuid.UUID, Article],
    *,
    unite_absente_acceptee: bool,
) -> LigneControlee:
    """Vue du moteur d'une ligne de facture ou de BL (L4-D7, Ruling R10) :
    `qte_fact` = conversion dans l'unité de facturation de l'article,
    `unite_absente_acceptee=True` pour une ligne de facture, `False`
    (défaut de `convertir_en_unite_fact`) pour une ligne de BL.
    `conversion_impossible` vaut vrai quand la conversion renvoie `None`
    alors que la ligne porte une quantité (décision du contrôleur).

    `unite_implicite` (Ruling R16, fix round 2 de L4-T7) est calculé à
    partir de la même source que l'appel à `convertir_en_unite_fact`
    ci-dessus (`ligne.unite_brut`, `article.unite_fact`) : la comparabilité
    de deux lignes appariées (R03/R04) ne se décide pas ligne par ligne, il
    faut donc porter l'information sur chacune plutôt que de la déduire
    a posteriori de `qte_fact`."""
    article = articles.get(ligne.article_id) if ligne.article_id is not None else None
    unite_fact_article = article.unite_fact if article is not None else None
    qte_fact = convertir_en_unite_fact(
        ligne.qte_totale,
        ligne.unite_brut,
        article.unite_cdt if article is not None else None,
        unite_fact_article,
        article.ratio if article is not None else None,
        article.valide if article is not None else False,
        unite_absente_acceptee=unite_absente_acceptee,
    )
    conversion_impossible = ligne.qte_totale is not None and qte_fact is None
    return LigneControlee(
        id=ligne.id,
        ordre=ligne.ordre,
        code=ligne.code_brut,
        designation=ligne.article_brut,
        article_id=ligne.article_id,
        qte_conditionnements=ligne.qte_livree,
        qte_facturee=ligne.qte_totale,
        qte_fact=qte_fact,
        unite=ligne.unite_brut,
        pu_ht=ligne.pu_ht,
        remise_pct=ligne.remise_pct,
        montant_ht=ligne.montant_ht,
        type_ligne=ligne.type_ligne,
        conversion_impossible=conversion_impossible,
        unite_implicite=unite_implicite(ligne.unite_brut, unite_fact_article),
    )


# --------------------------------------------------------------------------
# Candidats BL (L4-D5) et doublons de facturation (R12)
# --------------------------------------------------------------------------


async def _candidats_bl(
    session: AsyncSession,
    fournisseur_id: uuid.UUID | None,
    numeros_bruts: list[str],
) -> dict[str, Document]:
    """BL/enlèvement candidats (L4-D5 : même fournisseur, même numéro
    normalisé, non archivé ; le plus ancien fait foi), indexés par numéro
    normalisé. `{}` si `fournisseur_id` est absent ou si aucun bloc n'a de
    numéro."""
    if fournisseur_id is None or not numeros_bruts:
        return {}
    ids_par_numero = await documents_bl_par_numeros(
        session, numeros_bruts, fournisseur_id=fournisseur_id
    )
    if not ids_par_numero:
        return {}
    documents = (
        (
            await session.execute(
                select(Document).where(Document.id.in_(ids_par_numero.values()))
            )
        )
        .scalars()
        .all()
    )
    documents_par_id = {document.id: document for document in documents}
    return {
        numero: documents_par_id[document_id]
        for numero, document_id in ids_par_numero.items()
    }


async def _autres_blocs_meme_numero(
    session: AsyncSession,
    *,
    fournisseur_id: uuid.UUID | None,
    facture_id: uuid.UUID,
    numeros_normalises: set[str],
) -> dict[str, tuple[uuid.UUID, str | None]]:
    """R12 (L4-D5) : pour chaque numéro de BL normalisé de cette facture, la
    plus ancienne **autre** facture **non archivée** du même fournisseur
    dont un bloc porte ce numéro -> `(autre_facture_id,
    autre_facture_numero)`.

    Exclusion des factures `archive` (fix round 1, finding 1 de la revue de
    cette tâche) : un archivage est une action corrective normale de
    l'admin (ex. facture déposée deux fois par erreur) — sans cette
    exclusion, toute facture légitime réutilisant le même numéro de BL
    resterait signalée « doublon de facturation » (gravité haute) contre la
    facture archivée, indéfiniment. Même garde que `_candidats_bl` (L4-D5)
    et `_lignes_negatives_sans_origine` (R13) : un document archivé ne
    compte jamais comme une donnée active pour une autre règle."""
    if fournisseur_id is None or not numeros_normalises:
        return {}
    lignes = (
        await session.execute(
            select(BlocFacture.numero_bl, BlocFacture.facture_id, Document.numero)
            .join(Document, Document.id == BlocFacture.facture_id)
            .where(
                Document.type == "facture",
                Document.fournisseur_id == fournisseur_id,
                Document.id != facture_id,
                Document.statut != "archive",
                BlocFacture.numero_bl.is_not(None),
            )
            .order_by(Document.created_at.asc())
        )
    ).all()
    resultat: dict[str, tuple[uuid.UUID, str | None]] = {}
    for numero_bl, autre_facture_id, autre_facture_numero in lignes:
        if numero_bl is None:
            continue
        cle = _normaliser_numero(numero_bl)
        if cle not in numeros_normalises:
            continue
        resultat.setdefault(cle, (autre_facture_id, autre_facture_numero))
    return resultat


# --------------------------------------------------------------------------
# Avoirs sans origine (R13)
# --------------------------------------------------------------------------


async def _lignes_negatives_sans_origine(
    session: AsyncSession,
    *,
    facture_doc: Document,
    lignes_facture: Sequence[Ligne],
    blocs_par_id: dict[uuid.UUID, BlocFacture],
    chantiers_map: dict[uuid.UUID, str],
    articles_map: dict[uuid.UUID, Article],
) -> tuple[tuple[LigneControlee, str | None], ...]:
    """Pour chaque ligne de la facture dont `montant_ht < 0`, cherche une
    ligne positive antérieure ou égale en date de même article (ou même
    `code_brut` si l'article n'est pas résolu), sur un document du même
    fournisseur, **et de même chantier** (décision du contrôleur : chantier
    du bloc pour une facture, du document pour un BL) — si aucune, la ligne
    part avec le nom du chantier cherché."""
    negatives = [
        ligne
        for ligne in lignes_facture
        if ligne.montant_ht is not None and ligne.montant_ht < 0
    ]
    if not negatives:
        return ()

    conditions = [
        Document.fournisseur_id == facture_doc.fournisseur_id,
        Document.statut != "archive",
        Ligne.montant_ht > 0,
    ]
    if facture_doc.date_doc is not None:
        conditions.append(Document.date_doc <= facture_doc.date_doc)

    positives = (
        await session.execute(
            select(
                Ligne.article_id,
                Ligne.code_brut,
                func.coalesce(BlocFacture.chantier_id, Document.chantier_id),
            )
            .select_from(Ligne)
            .join(Document, Document.id == Ligne.document_id)
            .outerjoin(BlocFacture, BlocFacture.id == Ligne.bloc_id)
            .where(*conditions)
        )
    ).all()

    resultat: list[tuple[LigneControlee, str | None]] = []
    for ligne in negatives:
        bloc = blocs_par_id.get(ligne.bloc_id) if ligne.bloc_id is not None else None
        chantier_recherche_id = bloc.chantier_id if bloc is not None else None
        chantier_nom = (
            chantiers_map.get(chantier_recherche_id)
            if chantier_recherche_id is not None
            else None
        )

        origine_trouvee = False
        if chantier_recherche_id is not None:
            for article_id, code_brut, chantier_id in positives:
                if chantier_id != chantier_recherche_id:
                    continue
                if ligne.article_id is not None:
                    if article_id == ligne.article_id:
                        origine_trouvee = True
                        break
                elif (
                    ligne.code_brut is not None
                    and code_brut is not None
                    and code_brut == ligne.code_brut
                ):
                    origine_trouvee = True
                    break

        if not origine_trouvee:
            controlee = _ligne_controlee(
                ligne, articles_map, unite_absente_acceptee=True
            )
            resultat.append((controlee, chantier_nom))

    return tuple(resultat)


# --------------------------------------------------------------------------
# factures_recues (matière de `rapprocher --tout`, CLI, L4-T11)
# --------------------------------------------------------------------------


async def factures_recues(session: AsyncSession) -> list[tuple[uuid.UUID, int]]:
    """`(id, numero_interne)` de chaque facture `recu`, du plus ancien au
    plus récent (`Document.created_at` croissant) — matière de `rapprocher
    --tout` (CLI, décision du contrôleur de la tâche L4-T11 : « traite les
    factures reçues de la plus ancienne à la plus récente »).

    `numero_interne` (jamais une valeur du document client, L2-D5 : généré
    par notre propre séquence, distinct de `Document.numero` lu sur la
    facture) permet à la CLI d'afficher un repère par facture traitée sans
    révéler de donnée du document source."""
    resultat = await session.execute(
        select(Document.id, Document.numero_interne)
        .where(Document.type == "facture", Document.statut == "recu")
        .order_by(Document.created_at.asc())
    )
    return [(id_, numero_interne) for id_, numero_interne in resultat.all()]


# --------------------------------------------------------------------------
# rapprocher_facture
# --------------------------------------------------------------------------


async def rapprocher_facture(
    session: AsyncSession, facture_id: uuid.UUID
) -> ResultatRapprochement:
    """Rapproche une facture avec les BL déposés (L4-D3, idempotent) :
    charge la facture, ses blocs et lignes, les BL candidats (L4-D5), les
    articles, l'historique de prix (L4-D9), les doublons de facturation
    (R12) et les lignes négatives sans origine (R13) ; écrit
    `bloc_facture.bl_document_id`/`statut_rapprochement`, `ligne.qte_fact`
    (facture et BL) et les lignes de `rapprochement_ligne` (remplacées) ;
    évalue le moteur de règles pur puis délègue la persistance des
    anomalies à `ingest.anomalies.synchroniser_anomalies` ; journalise
    `facture_rapprochee` (auteur `NULL`). Un seul `commit()` à la fin.

    Lève `FactureIntrouvable` si `facture_id` est absent ou n'est pas une
    facture. Ne fait rien et renvoie un résultat vide (tous les compteurs à
    zéro, rien écrit) si la facture n'est pas `recu` (document « à
    vérifier » : CDC §5, ordre d'exécution — R10/R11 d'abord, les règles de
    rapprochement n'exécutent pas tant que l'admin n'a pas corrigé)."""
    facture_doc = await session.get(Document, facture_id)
    if facture_doc is None or facture_doc.type != "facture":
        raise FactureIntrouvable(str(facture_id))

    if facture_doc.statut != "recu":
        return ResultatRapprochement(
            facture_id=facture_id,
            nb_blocs=0,
            nb_blocs_recus=0,
            nb_blocs_pas_de_bon=0,
            nb_lignes_appariees=0,
            nb_anomalies=0,
        )

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
    blocs_par_id = {bloc.id: bloc for bloc in blocs_db}

    lignes_facture_db = (
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
    for ligne in lignes_facture_db:
        if ligne.bloc_id is not None:
            lignes_par_bloc[ligne.bloc_id].append(ligne)

    numeros_bruts = [bloc.numero_bl for bloc in blocs_db if bloc.numero_bl]
    numeros_normalises = {_normaliser_numero(n) for n in numeros_bruts}

    candidats_bl = await _candidats_bl(
        session, facture_doc.fournisseur_id, numeros_bruts
    )
    autres_blocs = await _autres_blocs_meme_numero(
        session,
        fournisseur_id=facture_doc.fournisseur_id,
        facture_id=facture_id,
        numeros_normalises=numeros_normalises,
    )

    bl_doc_ids = {document.id for document in candidats_bl.values()}
    lignes_bl_par_document: dict[uuid.UUID, list[Ligne]] = defaultdict(list)
    if bl_doc_ids:
        lignes_bl_db = (
            (
                await session.execute(
                    select(Ligne)
                    .where(Ligne.document_id.in_(bl_doc_ids))
                    .order_by(Ligne.ordre.asc())
                )
            )
            .scalars()
            .all()
        )
        for ligne in lignes_bl_db:
            lignes_bl_par_document[ligne.document_id].append(ligne)

    article_ids = {
        ligne.article_id for ligne in lignes_facture_db if ligne.article_id is not None
    }
    articles_map: dict[uuid.UUID, Article] = {}
    if article_ids:
        articles_db = (
            (await session.execute(select(Article).where(Article.id.in_(article_ids))))
            .scalars()
            .all()
        )
        articles_map = {article.id: article for article in articles_db}
    articles_controle = {
        article.id: ArticleControle(
            id=article.id,
            code=article.code,
            libelle=article.libelle,
            unite_cdt=article.unite_cdt,
            unite_fact=article.unite_fact,
            ratio=article.ratio,
            valide=article.valide,
        )
        for article in articles_map.values()
    }

    chantier_ids = {
        bloc.chantier_id for bloc in blocs_db if bloc.chantier_id is not None
    }
    chantier_ids |= {
        document.chantier_id
        for document in candidats_bl.values()
        if document.chantier_id is not None
    }
    chantiers_map: dict[uuid.UUID, str] = {}
    if chantier_ids:
        lignes_chantiers = await session.execute(
            select(Chantier.id, Chantier.nom_canonique).where(
                Chantier.id.in_(chantier_ids)
            )
        )
        chantiers_map = {id_: nom for id_, nom in lignes_chantiers.all()}

    deposant_ids = {
        document.deposant_id
        for document in (facture_doc, *candidats_bl.values())
        if document.deposant_id is not None
    }
    deposants_map: dict[uuid.UUID, str] = {}
    if deposant_ids:
        lignes_deposants = await session.execute(
            select(Utilisateur.id, Utilisateur.nom, Utilisateur.email).where(
                Utilisateur.id.in_(deposant_ids)
            )
        )
        deposants_map = {
            utilisateur_id: nom or email
            for utilisateur_id, nom, email in lignes_deposants.all()
        }

    nom_fournisseur = "—"
    if facture_doc.fournisseur_id is not None:
        fournisseur = await session.get(Fournisseur, facture_doc.fournisseur_id)
        if fournisseur is not None:
            nom_fournisseur = fournisseur.nom

    facture_document_controle = _document_controle(
        facture_doc,
        deposants_map.get(facture_doc.deposant_id)
        if facture_doc.deposant_id is not None
        else None,
    )
    bl_documentcontrole_par_id = {
        document.id: _document_controle(
            document,
            deposants_map.get(document.deposant_id)
            if document.deposant_id is not None
            else None,
        )
        for document in candidats_bl.values()
    }

    resultat_blocs: list[BlocControle] = []
    nouvelles_rapprochement_ligne: list[RapprochementLigne] = []
    nb_lignes_appariees = 0

    for bloc_db in blocs_db:
        lignes_bloc_db = lignes_par_bloc.get(bloc_db.id, [])
        numero_normalise = (
            _normaliser_numero(bloc_db.numero_bl) if bloc_db.numero_bl else None
        )
        bl_doc = (
            candidats_bl.get(numero_normalise) if numero_normalise is not None else None
        )

        if bl_doc is not None:
            bloc_db.statut_rapprochement = "recu"
            bloc_db.bl_document_id = bl_doc.id
        elif mention_pas_de_bon(bloc_db.commentaire) is not None:
            bloc_db.statut_rapprochement = "pas_de_bon"
            bloc_db.bl_document_id = None
        else:
            bloc_db.statut_rapprochement = "non_recu"
            bloc_db.bl_document_id = None

        lignes_bl_bloc_db = (
            lignes_bl_par_document.get(bl_doc.id, []) if bl_doc is not None else []
        )

        lignes_controlees_facture = [
            _ligne_controlee(ligne, articles_map, unite_absente_acceptee=True)
            for ligne in lignes_bloc_db
        ]
        lignes_controlees_bl = [
            _ligne_controlee(ligne, articles_map, unite_absente_acceptee=False)
            for ligne in lignes_bl_bloc_db
        ]

        for ligne_db, controlee in zip(
            lignes_bloc_db, lignes_controlees_facture, strict=True
        ):
            ligne_db.qte_fact = controlee.qte_fact
        for ligne_db, controlee in zip(
            lignes_bl_bloc_db, lignes_controlees_bl, strict=True
        ):
            ligne_db.qte_fact = controlee.qte_fact

        appariements = apparier_lignes(
            [
                LigneAApparier(
                    cle=ligne.id, code=ligne.code_brut, designation=ligne.article_brut
                )
                for ligne in lignes_bloc_db
            ],
            [
                LigneAApparier(
                    cle=ligne.id, code=ligne.code_brut, designation=ligne.article_brut
                )
                for ligne in lignes_bl_bloc_db
            ],
        )

        bl_controlee_par_id = {
            controlee.id: controlee for controlee in lignes_controlees_bl
        }
        cles_bl_matchees: set[uuid.UUID] = set()
        lignes_rapprochees: list[LigneRapprochee] = []
        for ligne_controlee_facture, appariement in zip(
            lignes_controlees_facture, appariements, strict=True
        ):
            bl_controlee = (
                bl_controlee_par_id.get(appariement.cle_bl)
                if appariement.cle_bl is not None
                else None
            )
            lignes_rapprochees.append(
                LigneRapprochee(
                    facture=ligne_controlee_facture,
                    bl=bl_controlee,
                    methode=appariement.methode,
                )
            )
            methode = appariement.methode
            # `methode` est toujours renseigné quand `bl_controlee` ne l'est
            # pas (contrat de `apparier_lignes`) : la garde ci-dessous est
            # défensive, jamais un `assert` (S101) sur une donnée qui reste
            # sous le contrôle d'un module tiers.
            if bl_controlee is not None and methode is not None:
                cles_bl_matchees.add(bl_controlee.id)
                nb_lignes_appariees += 1
                ecart_qte: Decimal | None = None
                if (
                    ligne_controlee_facture.qte_fact is not None
                    and bl_controlee.qte_fact is not None
                ):
                    ecart_qte = ligne_controlee_facture.qte_fact - bl_controlee.qte_fact
                nouvelles_rapprochement_ligne.append(
                    RapprochementLigne(
                        ligne_facture_id=ligne_controlee_facture.id,
                        ligne_bl_id=bl_controlee.id,
                        methode=methode,
                        ecart_qte=ecart_qte,
                    )
                )

        lignes_bl_non_facturees = tuple(
            controlee
            for controlee in lignes_controlees_bl
            if controlee.id not in cles_bl_matchees
        )

        montant_ht_bloc = sum(
            (
                ligne.montant_ht
                for ligne in lignes_bloc_db
                if ligne.montant_ht is not None
            ),
            Decimal("0"),
        )
        chantier_canonique = (
            chantiers_map.get(bloc_db.chantier_id)
            if bloc_db.chantier_id is not None
            else None
        )
        bl_controle_doc = (
            bl_documentcontrole_par_id.get(bl_doc.id) if bl_doc is not None else None
        )
        autre = (
            autres_blocs.get(numero_normalise) if numero_normalise is not None else None
        )

        resultat_blocs.append(
            BlocControle(
                id=bloc_db.id,
                numero_bl=bloc_db.numero_bl,
                date_bl=bloc_db.date_bl,
                chantier_brut=bloc_db.chantier_brut,
                chantier=chantier_canonique,
                commentaire=bloc_db.commentaire,
                montant_ht=montant_ht_bloc,
                bl=bl_controle_doc,
                lignes=tuple(lignes_rapprochees),
                lignes_bl_non_facturees=lignes_bl_non_facturees,
                autre_facture_numero=autre[1] if autre is not None else None,
                autre_facture_id=autre[0] if autre is not None else None,
            )
        )

    lignes_negatives = await _lignes_negatives_sans_origine(
        session,
        facture_doc=facture_doc,
        lignes_facture=lignes_facture_db,
        blocs_par_id=blocs_par_id,
        chantiers_map=chantiers_map,
        articles_map=articles_map,
    )

    historiques = await _construire_historiques(
        session,
        fournisseur_id=facture_doc.fournisseur_id,
        facture_id=facture_id,
        date_facture=facture_doc.date_doc,
        article_ids=article_ids,
    )

    facture_controlee = FactureControlee(
        document=facture_document_controle,
        fournisseur=nom_fournisseur,
        blocs=tuple(resultat_blocs),
        articles=articles_controle,
        historiques=historiques,
        lignes_negatives_sans_origine=lignes_negatives,
    )

    parametres = await _charger_parametres(session)
    anomalies = evaluer_facture(facture_controlee, parametres)

    await session.execute(
        delete(RapprochementLigne).where(
            RapprochementLigne.ligne_facture_id.in_(
                select(Ligne.id).where(Ligne.document_id == facture_id)
            )
        )
    )
    for rapprochement in nouvelles_rapprochement_ligne:
        session.add(rapprochement)

    # Ruling R17 (fix round 2, L4-T7) : les règles pures (R01-R09, R12,
    # R13, R17) ne connaissent qu'un bloc ou une ligne, jamais l'identifiant
    # du document -- seules R10/R11/R15 portent nativement `document_id`.
    # `rapprocher_facture` évalue une facture à la fois : toute anomalie
    # qu'il produit lui appartient, `dataclasses.replace` la complète donc
    # ici (`Anomalie` est un dataclass gelé) pour que l'écran Anomalies
    # (CDC §4.6) puisse toujours remonter à la pièce.
    anomalies = tuple(
        anomalie
        if anomalie.document_id is not None
        else replace(anomalie, document_id=facture_id)
        for anomalie in anomalies
    )

    # Ruling L5-R3 (tour de correction 1, L5-T1) : R07, R08, R09, R13 et R17
    # ne posent que `ligne_id` sur l'anomalie qu'elles produisent, jamais
    # `bloc_id` -- la règle pure ne reçoit que la ligne (`LigneControlee`),
    # elle ne peut pas connaître le bloc. Conséquence, déjà dans `main`
    # depuis le lot 4 : `CHANTIER_ID_RESOLU` (`ingest/anomalies.py`) ne
    # passe jamais par la ligne, retombe sur `Document.chantier_id`
    # (presque toujours vide pour une facture), et une telle anomalie
    # s'affichait sans chantier, en échappant au filtre par chantier de
    # l'écran Anomalies. Même idiome que le complément de `document_id`
    # ci-dessus (Ruling R17 du lot 4) : l'orchestrateur complète ce que le
    # module pur ignore, jamais l'inverse. Valeur stable d'un rejeu à
    # l'autre (la ligne ne change pas de bloc) : l'idempotence tient.
    bloc_id_par_ligne = {ligne.id: ligne.bloc_id for ligne in lignes_facture_db}
    anomalies = tuple(
        anomalie
        if anomalie.bloc_id is not None or anomalie.ligne_id is None
        else replace(anomalie, bloc_id=bloc_id_par_ligne.get(anomalie.ligne_id))
        for anomalie in anomalies
    )

    nb_anomalies = await synchroniser_anomalies(
        session,
        anomalies=anomalies,
        portee_document_id=facture_id,
        # `synchroniser_anomalies` attend une `Sequence` ; `REGLES_FACTURE`
        # (source de vérité, `rules.engine`) est un `frozenset` — converti en
        # tuple ici, jamais retypé à la main (Ruling R8, `ingest/anomalies.py`).
        portee_regles=tuple(REGLES_FACTURE),
    )

    nb_blocs_recus = sum(1 for bloc in blocs_db if bloc.statut_rapprochement == "recu")
    nb_blocs_pas_de_bon = sum(
        1 for bloc in blocs_db if bloc.statut_rapprochement == "pas_de_bon"
    )

    session.add(
        Journal(
            utilisateur_id=None,
            action="facture_rapprochee",
            cible_table="document",
            cible_id=str(facture_id),
            avant=None,
            apres={
                "nb_blocs": str(len(blocs_db)),
                "nb_blocs_recus": str(nb_blocs_recus),
                "nb_blocs_pas_de_bon": str(nb_blocs_pas_de_bon),
                "nb_lignes_appariees": str(nb_lignes_appariees),
                "nb_anomalies": str(nb_anomalies),
            },
        )
    )

    await session.commit()

    return ResultatRapprochement(
        facture_id=facture_id,
        nb_blocs=len(blocs_db),
        nb_blocs_recus=nb_blocs_recus,
        nb_blocs_pas_de_bon=nb_blocs_pas_de_bon,
        nb_lignes_appariees=nb_lignes_appariees,
        nb_anomalies=nb_anomalies,
    )


# --------------------------------------------------------------------------
# Déclenchements sûrs (dépôt de facture, validation d'un BL, extraction)
# --------------------------------------------------------------------------


def _journaliser_echec(etape: str, identifiant: uuid.UUID, exc: Exception) -> None:
    """Trace un échec de rapprochement sans jamais le faire remonter à
    l'action appelante (décision du contrôleur) — même prudence que
    `ingest.commun._journaliser_echec` : uniquement le type de l'exception,
    jamais son contenu (qui pourrait porter une valeur du document)."""
    logger.error(
        "échec rapprochement (%s) pour %s : %s", etape, identifiant, type(exc).__name__
    )


async def rapprocher_facture_sans_echec(
    session: AsyncSession, facture_id: uuid.UUID
) -> ResultatRapprochement | None:
    """Encapsule `rapprocher_facture` pour un déclenchement automatique (fin
    de `ingest.factures.deposer_facture`, même transaction logique) : ne
    doit jamais faire échouer l'action appelante — toute exception est
    journalisée (`_journaliser_echec`) puis avalée, `None` en retour."""
    try:
        return await rapprocher_facture(session, facture_id)
    except Exception as exc:
        await session.rollback()
        _journaliser_echec("rapprochement", facture_id, exc)
        return None


async def _factures_portant_numero(
    session: AsyncSession, fournisseur_id: uuid.UUID, numero: str
) -> list[uuid.UUID]:
    """`id` de chaque facture du fournisseur dont un bloc porte `numero`
    (numéro normalisé), dans l'ordre de dépôt (`Document.created_at`
    croissant), sans doublon."""
    numero_normalise = _normaliser_numero(numero)
    lignes = (
        await session.execute(
            select(BlocFacture.facture_id, BlocFacture.numero_bl, Document.created_at)
            .join(Document, Document.id == BlocFacture.facture_id)
            .where(
                Document.type == "facture",
                Document.fournisseur_id == fournisseur_id,
                BlocFacture.numero_bl.is_not(None),
            )
            .order_by(Document.created_at.asc())
        )
    ).all()
    facture_ids: list[uuid.UUID] = []
    for facture_id, numero_bl, _created_at in lignes:
        if numero_bl is None:
            continue
        if (
            _normaliser_numero(numero_bl) == numero_normalise
            and facture_id not in facture_ids
        ):
            facture_ids.append(facture_id)
    return facture_ids


async def rapprocher_factures_du_bl(
    session: AsyncSession, document_id: uuid.UUID
) -> list[ResultatRapprochement]:
    """Rejoue le rapprochement de chaque facture dont un bloc porte le
    numéro du BL/enlèvement `document_id` (déclenché après la validation
    d'un BL ou une extraction qui donne un numéro — décision du
    contrôleur). `[]` si le document est introuvable, n'a pas de numéro, n'a
    pas de fournisseur résolu, ou n'est pas un BL/enlèvement.

    Ne fait jamais échouer l'action appelante : la recherche des factures
    candidates comme chaque rapprochement individuel
    (`rapprocher_facture_sans_echec`) sont protégés, toute exception est
    journalisée et avalée."""
    try:
        bl_doc = await session.get(Document, document_id)
        if (
            bl_doc is None
            or bl_doc.numero is None
            or bl_doc.fournisseur_id is None
            or bl_doc.type not in _TYPES_BL
        ):
            return []
        facture_ids = await _factures_portant_numero(
            session, bl_doc.fournisseur_id, bl_doc.numero
        )
    except Exception as exc:
        await session.rollback()
        _journaliser_echec("recherche factures", document_id, exc)
        return []

    resultats: list[ResultatRapprochement] = []
    for facture_id in facture_ids:
        resultat = await rapprocher_facture_sans_echec(session, facture_id)
        if resultat is not None:
            resultats.append(resultat)
    return resultats
