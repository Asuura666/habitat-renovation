"""Contrôles différés : R06, R14, R15, R16 (`ingest/suivi.py`, L4-T11).

Quatre des dix-sept règles du CDC §5 dépendent du temps écoulé plutôt que
d'un document nouvellement déposé (L4-D14) : une ligne de BL toujours pas
facturée 45 jours après le BL (R06), un alias de chantier toujours pas
validé 48h après sa création (R14), un BL déposé sans confirmation 24h après
son dépôt (R15), un chantier actif silencieux depuis 7 jours alors que des
factures continuent d'y référencer des BL (R16). Elles ne sont donc jamais
évaluées par `ingest.rapprochement.rapprocher_facture` (qui ne recalcule que
`rules.engine.REGLES_FACTURE`), mais par la commande quotidienne
`python -m app.cli controles-differes` (pas de worker, CDC §7) — ce module
construit son `ContexteSuivi` depuis la base, appelle `rules.engine
.evaluer_suivi`, puis délègue la persistance à `ingest.anomalies
.synchroniser_anomalies` (déjà commité).

Décisions du contrôleur (fiche de cette tâche) :
- `controles_differes` passe `portee_regles=REGLES_SUIVI` et **aucune**
  portée de document (`portee_document_id` omis, donc `None`) : le balayage
  de suppression porte alors sur *toutes* les anomalies ouvertes de ces
  quatre règles, quel que soit leur document ou chantier — jamais sur les
  règles de facture (`REGLES_FACTURE`), déjà couvertes par
  `rapprocher_facture`. C'est exactement le comportement que
  `test_synchroniser_anomalies_portee_suivi_restreint_aux_regles_donnees`
  (`ingest/tests/test_anomalies.py`, déjà commité en L4-T8) anticipait pour
  cette tâche.
- `lignes_bl_non_facturees` (R06) : blocs dont `statut_rapprochement =
  "recu"` et dont le BL rapproché est lui-même `statut = "recu"` (Ruling R3
  du rapprochement : un bloc peut être `recu` alors que son BL est encore
  « à vérifier », auquel cas ses quantités ne sont jamais comparées). Pour
  chaque bloc retenu, les lignes du BL qui n'apparaissent dans aucune
  `rapprochement_ligne` de la base (même requête que celle qui alimente
  `BlocControle.lignes_bl_non_facturees` pendant `rapprocher_facture`, mais
  relue ici depuis la base plutôt que recalculée en mémoire, puisque
  `controles_differes` ne rejoue jamais le rapprochement lui-même).
- `alias_en_attente` (R14) : `chantier_alias` dont `chantier_id IS NULL`.
- `bl_sans_confirmation` (R15) : documents `bl`/`enlevement` non archivés,
  `confirme_le IS NULL`.
- `chantiers` (R16) : chantiers `actif`, avec la date du document
  `bl`/`enlevement` non archivé le plus récent qui leur est rattaché
  (`dernier_depot`, `None` si aucun n'existe jamais — R16 ne peut alors rien
  comparer) et le nombre de blocs de facture non archivée rattachés à ce
  chantier dont `date_bl` est postérieure à cette date
  (`nb_bl_factures_depuis`).
- Aucun journal global pour l'exécution de `controles_differes` elle-même
  (décision du contrôleur) : contrairement à `rapprocher_facture`, cette
  commande ne porte sur aucun document ou chantier unique qui pourrait
  servir de cible (`journal.cible_id`) — la traçabilité utile (une anomalie
  qui apparaît ou disparaît) est déjà couverte par `synchroniser_anomalies`
  (`anomalie_levee`) et par les entrées `Rxx` elles-mêmes, visibles à
  l'écran Anomalies.
- Un seul `commit()` à la fin, comme `rapprocher_facture` : `controles_
  differes` est idempotente (L4-D3), un rejeu à l'identique ne change rien.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.anomalies import synchroniser_anomalies
from app.modules.ingest.models import (
    BlocFacture,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Ligne,
    RapprochementLigne,
    Utilisateur,
)
from app.modules.ingest.rapprochement import (
    _charger_parametres,
    _document_controle,
    _ligne_controlee,
)
from app.modules.rules.engine import REGLES_SUIVI, evaluer_suivi
from app.modules.rules.modeles import (
    AliasEnAttenteControle,
    BlocControle,
    ChantierSuiviControle,
    ContexteSuivi,
    DocumentControle,
    LigneControlee,
)

__all__ = ["controles_differes"]

# Types de document traités comme un BL (CDC §4.5 : « Bons d'enlèvement
# (Point.P) : traités comme des BL »), même constante que `rapprochement.py`.
_TYPES_BL: tuple[str, ...] = ("bl", "enlevement")


def _bloc_controle_minimal(bloc_db: BlocFacture) -> BlocControle:
    """Vue minimale d'un bloc pour R06 (décision du contrôleur) : seuls
    `id` et `date_bl` sont lus par `rules.rules.R06.R06`. Les autres champs
    de `BlocControle` sont neutres (jamais lus par cette règle) plutôt que
    de reconstruire tout le rapprochement d'une facture juste pour évaluer
    un contrôle différé qui ne porte que sur une ligne de BL isolée."""
    return BlocControle(
        id=bloc_db.id,
        numero_bl=bloc_db.numero_bl,
        date_bl=bloc_db.date_bl,
        chantier_brut=bloc_db.chantier_brut,
        chantier=None,
        commentaire=bloc_db.commentaire,
        montant_ht=Decimal("0"),
        bl=None,
        lignes=(),
        lignes_bl_non_facturees=(),
        autre_facture_numero=None,
        autre_facture_id=None,
    )


async def _lignes_bl_non_facturees(
    session: AsyncSession,
) -> tuple[tuple[BlocControle, LigneControlee], ...]:
    """Matière de R06 (décision du contrôleur) : blocs `recu` dont le BL
    rapproché est lui-même `recu`, croisés avec les lignes de ce BL absentes
    de `rapprochement_ligne`."""
    blocs_db = (
        (
            await session.execute(
                select(BlocFacture)
                .join(Document, Document.id == BlocFacture.bl_document_id)
                .where(
                    BlocFacture.statut_rapprochement == "recu",
                    BlocFacture.bl_document_id.is_not(None),
                    Document.statut == "recu",
                )
            )
        )
        .scalars()
        .all()
    )
    if not blocs_db:
        return ()

    bl_doc_ids = {
        bloc.bl_document_id for bloc in blocs_db if bloc.bl_document_id is not None
    }
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
    if not lignes_bl_db:
        return ()

    ligne_bl_ids = [ligne.id for ligne in lignes_bl_db]
    lignes_appariees_ids = {
        ligne_bl_id
        for (ligne_bl_id,) in (
            await session.execute(
                select(RapprochementLigne.ligne_bl_id).where(
                    RapprochementLigne.ligne_bl_id.in_(ligne_bl_ids)
                )
            )
        ).all()
    }

    lignes_non_facturees_par_document: dict[UUID, list[Ligne]] = defaultdict(list)
    for ligne in lignes_bl_db:
        if ligne.id not in lignes_appariees_ids:
            lignes_non_facturees_par_document[ligne.document_id].append(ligne)

    resultat: list[tuple[BlocControle, LigneControlee]] = []
    for bloc_db in blocs_db:
        if bloc_db.bl_document_id is None:
            continue
        bloc_controle = _bloc_controle_minimal(bloc_db)
        for ligne_db in lignes_non_facturees_par_document.get(
            bloc_db.bl_document_id, []
        ):
            resultat.append(
                (
                    bloc_controle,
                    _ligne_controlee(ligne_db, {}, unite_absente_acceptee=False),
                )
            )
    return tuple(resultat)


async def _alias_en_attente(
    session: AsyncSession,
) -> tuple[AliasEnAttenteControle, ...]:
    """Matière de R14 (décision du contrôleur) : alias `chantier_id IS
    NULL`, avec le nom du fournisseur pour la justification chiffrée."""
    lignes = await session.execute(
        select(
            ChantierAlias.id,
            ChantierAlias.libelle_brut,
            ChantierAlias.created_at,
            Fournisseur.nom,
        )
        .join(Fournisseur, Fournisseur.id == ChantierAlias.fournisseur_id)
        .where(ChantierAlias.chantier_id.is_(None))
    )
    return tuple(
        AliasEnAttenteControle(
            id=id_, libelle=libelle, fournisseur=nom, cree_le=cree_le
        )
        for id_, libelle, cree_le, nom in lignes.all()
    )


async def _bl_sans_confirmation(
    session: AsyncSession,
) -> tuple[DocumentControle, ...]:
    """Matière de R15 (décision du contrôleur) : documents `bl`/`enlevement`
    non archivés, jamais confirmés."""
    documents_db = (
        (
            await session.execute(
                select(Document).where(
                    Document.type.in_(_TYPES_BL),
                    Document.statut != "archive",
                    Document.confirme_le.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not documents_db:
        return ()

    deposant_ids = {
        document.deposant_id
        for document in documents_db
        if document.deposant_id is not None
    }
    deposants_map: dict[UUID, str] = {}
    if deposant_ids:
        lignes = await session.execute(
            select(Utilisateur.id, Utilisateur.nom, Utilisateur.email).where(
                Utilisateur.id.in_(deposant_ids)
            )
        )
        deposants_map = {
            utilisateur_id: nom or email for utilisateur_id, nom, email in lignes.all()
        }

    return tuple(
        _document_controle(
            document,
            deposants_map.get(document.deposant_id)
            if document.deposant_id is not None
            else None,
        )
        for document in documents_db
    )


async def _chantiers_suivis(session: AsyncSession) -> tuple[ChantierSuiviControle, ...]:
    """Matière de R16 (décision du contrôleur) : chantiers `actif`, avec la
    date du document `bl`/`enlevement` non archivé le plus récent qui leur
    est rattaché (`dernier_depot`) et le nombre de blocs de facture non
    archivée rattachés à ce chantier dont `date_bl` est postérieure à cette
    date (`nb_bl_factures_depuis`) — une seule requête par grandeur, agrégée
    en Python (même principe que `rapprochement._construire_historiques`),
    plutôt qu'une requête par chantier (CDC §9 : référentiel chantier de
    volume faible, mais pas de raison de ne pas rester en une seule
    requête)."""
    chantiers_actifs = (
        (await session.execute(select(Chantier).where(Chantier.actif.is_(True))))
        .scalars()
        .all()
    )
    if not chantiers_actifs:
        return ()

    chantier_ids = [chantier.id for chantier in chantiers_actifs]

    lignes_derniers_depots = await session.execute(
        select(Document.chantier_id, func.max(Document.created_at))
        .where(
            Document.type.in_(_TYPES_BL),
            Document.statut != "archive",
            Document.chantier_id.in_(chantier_ids),
        )
        .group_by(Document.chantier_id)
    )
    derniers_depots: dict[UUID, datetime] = {
        chantier_id: date_max
        for chantier_id, date_max in lignes_derniers_depots.all()
        if chantier_id is not None
    }

    lignes_blocs = await session.execute(
        select(BlocFacture.chantier_id, BlocFacture.date_bl)
        .join(Document, Document.id == BlocFacture.facture_id)
        .where(
            BlocFacture.chantier_id.in_(chantier_ids),
            BlocFacture.date_bl.is_not(None),
            Document.statut != "archive",
        )
    )
    dates_bl_par_chantier: dict[UUID, list[date]] = defaultdict(list)
    for chantier_id, date_bl in lignes_blocs.all():
        dates_bl_par_chantier[chantier_id].append(date_bl)

    resultat: list[ChantierSuiviControle] = []
    for chantier in chantiers_actifs:
        dernier_depot = derniers_depots.get(chantier.id)
        nb_bl_factures_depuis = 0
        if dernier_depot is not None:
            seuil = dernier_depot.date()
            nb_bl_factures_depuis = sum(
                1
                for date_bl in dates_bl_par_chantier.get(chantier.id, [])
                if date_bl > seuil
            )
        resultat.append(
            ChantierSuiviControle(
                id=chantier.id,
                nom=chantier.nom_canonique,
                dernier_depot=dernier_depot,
                nb_bl_factures_depuis=nb_bl_factures_depuis,
            )
        )
    return tuple(resultat)


async def controles_differes(session: AsyncSession, *, maintenant: datetime) -> int:
    """Évalue les règles de suivi (R06, R14, R15, R16, L4-D14) et synchronise
    leurs anomalies (idempotent, L4-D3). `maintenant` est injecté par
    l'appelant (jamais `datetime.now()` lu ici) pour rester testable
    (décision du contrôleur, même principe que les autres règles pures qui
    reçoivent `aujourdhui` en paramètre).

    Renvoie le nombre d'anomalies de suivi ouvertes après synchronisation
    (`synchroniser_anomalies`, valeur utile pour le retour de la CLI
    `controles-differes`, L4-T11)."""
    parametres = await _charger_parametres(session)
    contexte = ContexteSuivi(
        aujourdhui=maintenant,
        lignes_bl_non_facturees=await _lignes_bl_non_facturees(session),
        alias_en_attente=await _alias_en_attente(session),
        bl_sans_confirmation=await _bl_sans_confirmation(session),
        chantiers=await _chantiers_suivis(session),
    )
    anomalies = evaluer_suivi(contexte, parametres)

    nb_ouvertes = await synchroniser_anomalies(
        session,
        anomalies=anomalies,
        portee_regles=tuple(REGLES_SUIVI),
    )
    await session.commit()
    return nb_ouvertes
