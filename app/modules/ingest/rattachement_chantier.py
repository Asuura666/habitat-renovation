"""Rattachement automatique du chantier d'un bon (BL/enlèvement) ou d'un
bloc de facture (avenant du 27/09/2026 — décision d'Ilane, spec §2.2-2.4).

Deux sources indépendantes désignent le chantier d'un bon : le nom lu par
l'OCR (`document.chantier_brut`) et la légende Telegram tapée par l'employé
au dépôt (`document.legende`, tâche 4). `normalize.chantier.decider_chantier`
combine leurs deux `Correspondance` (`normalize.chantier.reconnaitre_chantier`,
ressemblance de nom) en une décision unique (table de décision §2.3) :
rattacher à un chantier reconnu, créer un chantier « à compléter » quand le
nom lu (ou la légende) n'en évoque aucun, ou lever une alerte R18 quand les
deux sources se contredisent. Un bloc de facture n'a pas de légende : seule
la ressemblance du nom lu s'applique (`rattacher_chantier_bloc`), et un nom
ambigu retombe sur l'ancien flux (`referentiels.resoudre_chantier`, alias en
attente, écran « Noms à rattacher », R14) plutôt que sur R18 (spec §2.4,
« Factures »).

Concurrence : `pg_advisory_xact_lock(VERROU_CHANTIERS)` sérialise toute
décision de chantier (lecture des noms connus, création, apprentissage
d'alias) — sans lui, deux dépôts concurrents du même nom inconnu créeraient
chacun leur chantier. Le verrou est pris en tout début de
`rattacher_chantier_document`/`rattacher_chantier_bloc` et tenu jusqu'au
commit de l'appelant (ni l'une ni l'autre fonction ne commite jamais, même
principe que `referentiels.resoudre_chantier`/`rattacher_article` et
`anomalies.synchroniser_anomalies`).

Apprentissage (spec §2.3) : dès qu'un nom lu non vide sert à rattacher ou à
créer un chantier (fournisseur connu), l'alias `(fournisseur_id, libellé lu,
code_brut=NULL)` est enregistré vers ce chantier (`valide_par` nul,
`valide_le` = maintenant). Si cet alias existait déjà « en attente »
(`chantier_id` nul, ancien flux), il est rattaché et son `chantier_id`
propagé aux bons/blocs qui l'attendaient (`referentiels.candidats_alias`,
même sélection que `referentiels.valider_alias`) — jamais un alias déjà
rattaché à un autre chantier n'est modifié.

Chantier fusionné (Task 7, avenant du 27/09/2026) : un chantier fusionné
(`Chantier.fusionne_dans_id`) compte pour sa cible — `charger_noms_chantiers`
et `chantier_effectif` suivent la chaîne de fusion, au plus deux sauts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.anomalies import synchroniser_anomalies
from app.modules.ingest.models import Chantier, ChantierAlias, Document, Journal
from app.modules.ingest.parametres import CLE_SEUIL_RESSEMBLANCE_CHANTIER
from app.modules.ingest.referentiels import (
    candidats_alias,
    lire_parametre_decimal,
    resoudre_chantier,
)
from app.modules.normalize.chantier import (
    Correspondance,
    EtatCorrespondance,
    NomConnu,
    SourceNom,
    TypeDecision,
    correspondance_exacte,
    decider_chantier,
    decomposer_chantier,
    nom_pour_creation,
    reconnaitre_chantier,
)
from app.modules.normalize.texte import normaliser_libelle
from app.modules.rules.engine import REGLES_CHANTIER, evaluer_chantier
from app.modules.rules.modeles import ChantierIncertainControle

# Clé de verrou consultatif (`pg_advisory_xact_lock`) qui sérialise toute
# décision de chantier (lecture des noms connus, création, apprentissage) —
# valeur arbitraire mais fixe, jamais réutilisée ailleurs dans le projet
# (voir `app/modules/jobs/drive_sync.py` pour le seul autre verrou du dépôt,
# une paire d'entiers 32 bits distincte).
VERROU_CHANTIERS = 727_000_018

SEUIL_RESSEMBLANCE_DEFAUT = Decimal("90")


@dataclass(frozen=True)
class ResultatRattachement:
    """Issue de `rattacher_chantier_document` (spec §2.3, §2.9 du brief)."""

    chantier_id: uuid.UUID | None
    # "nom connu" (alias exact) | "ressemblance" (nom lu) | "légende" |
    # "création" | "alerte" | `None` (aucune des deux sources n'est
    # exploitable, comme aujourd'hui).
    methode: str | None
    score: int | None
    cree: bool  # un chantier vient d'être créé (jamais vrai en cas de doublon repris).
    alerte: bool  # R18 ouverte sur le bon (`document.chantier_id` reste `None`).


async def chantier_effectif(session: AsyncSession, chantier_id: uuid.UUID) -> uuid.UUID:
    """Chantier effectif de `chantier_id` : lui-même, ou la cible de sa
    fusion (`Chantier.fusionne_dans_id`, Task 7) si ce chantier a été
    fusionné — au plus deux sauts (décision du plan, une chaîne de fusion
    plus longue n'est jamais censée se produire)."""
    courant = chantier_id
    for _ in range(2):
        cible = (
            await session.execute(
                select(Chantier.fusionne_dans_id).where(Chantier.id == courant)
            )
        ).scalar_one_or_none()
        if cible is None:
            break
        courant = cible
    return courant


async def charger_noms_chantiers(session: AsyncSession) -> list[NomConnu]:
    """Tous les noms connus (canoniques et alias rattachés), chantier
    effectif déjà résolu (Task 7) — deux requêtes seulement, jamais une par
    chantier (spec §2.3, brief étape 3)."""
    chantiers = (
        await session.execute(
            select(Chantier.id, Chantier.nom_canonique, Chantier.fusionne_dans_id)
        )
    ).all()
    fusion_directe = {ligne.id: ligne.fusionne_dans_id for ligne in chantiers}

    def _effectif(chantier_id: uuid.UUID) -> uuid.UUID:
        courant = chantier_id
        for _ in range(2):
            cible = fusion_directe.get(courant)
            if cible is None:
                break
            courant = cible
        return courant

    noms = [
        NomConnu(chantier_id=_effectif(ligne.id), libelle=ligne.nom_canonique)
        for ligne in chantiers
    ]

    alias_rattaches = (
        await session.execute(
            select(ChantierAlias.chantier_id, ChantierAlias.libelle_brut).where(
                ChantierAlias.chantier_id.is_not(None)
            )
        )
    ).all()
    noms.extend(
        NomConnu(chantier_id=_effectif(chantier_id), libelle=libelle_brut)
        for chantier_id, libelle_brut in alias_rattaches
        if chantier_id is not None
    )
    return noms


async def _correspondance_exacte_ou_ressemblance(
    session: AsyncSession,
    fournisseur_id: uuid.UUID | None,
    brut: str | None,
    noms: list[NomConnu],
    seuil: int,
) -> tuple[Correspondance, bool]:
    """Correspondance d'un libellé lu (brief étape 4/`rattacher_chantier_bloc`) :
    un alias exact déjà rattaché de ce fournisseur court-circuite la
    ressemblance (`correspondance_exacte`, score 100, méthode « nom connu »,
    comportement actuel conservé) ; sinon `reconnaitre_chantier`. Renvoie
    aussi si le résultat vient de l'alias exact (pour le libellé de méthode
    de l'appelant)."""
    if fournisseur_id is not None:
        decompose = decomposer_chantier(brut)
        if decompose is not None:
            chantier_alias_id = (
                await session.execute(
                    select(ChantierAlias.chantier_id).where(
                        ChantierAlias.fournisseur_id == fournisseur_id,
                        ChantierAlias.libelle_brut == decompose.libelle,
                        ChantierAlias.code_brut.is_(None),
                        ChantierAlias.chantier_id.is_not(None),
                    )
                )
            ).scalar_one_or_none()
            if chantier_alias_id is not None:
                effectif = await chantier_effectif(session, chantier_alias_id)
                return correspondance_exacte(brut, effectif), True
    return reconnaitre_chantier(brut, noms, seuil), False


async def _noms_canoniques(
    session: AsyncSession, ids: tuple[uuid.UUID, ...]
) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    lignes = await session.execute(
        select(Chantier.id, Chantier.nom_canonique).where(Chantier.id.in_(ids))
    )
    return {chantier_id: nom for chantier_id, nom in lignes.all()}


async def _apprendre_alias(
    session: AsyncSession,
    *,
    fournisseur_id: uuid.UUID,
    libelle: str,
    chantier_id: uuid.UUID,
    methode: str,
) -> None:
    """Upsert de l'alias `(fournisseur_id, libelle, code_brut=NULL)` vers
    `chantier_id` (spec §2.3, brief étape 7) : insertion directement
    rattachée (`ON CONFLICT DO NOTHING`, même mécanisme que
    `referentiels.resoudre_chantier`) ; si l'alias existait déjà « en
    attente » (`chantier_id` nul, ancien flux), il est rattaché et son
    `chantier_id` propagé aux bons/blocs qui l'attendaient
    (`referentiels.candidats_alias`), journal `alias_rattache_auto`. Un
    alias déjà rattaché (à ce chantier ou à un autre) n'est jamais modifié
    ni journalisé de nouveau."""
    maintenant = datetime.now(UTC)
    resultat = await session.execute(
        insert(ChantierAlias)
        .values(
            fournisseur_id=fournisseur_id,
            libelle_brut=libelle,
            code_brut=None,
            chantier_id=chantier_id,
            valide_par=None,
            valide_le=maintenant,
        )
        .on_conflict_do_nothing(
            index_elements=[
                ChantierAlias.fournisseur_id,
                ChantierAlias.libelle_brut,
                ChantierAlias.code_brut,
            ]
        )
        .returning(ChantierAlias.id)
    )
    if resultat.first() is not None:
        return  # alias créé directement rattaché : rien à propager.

    alias = (
        await session.execute(
            select(ChantierAlias).where(
                ChantierAlias.fournisseur_id == fournisseur_id,
                ChantierAlias.libelle_brut == libelle,
                ChantierAlias.code_brut.is_(None),
            )
        )
    ).scalar_one()
    if alias.chantier_id is not None:
        return  # déjà rattaché (à ce chantier ou à un autre) : jamais modifié.

    documents, blocs = await candidats_alias(session, fournisseur_id, libelle)
    for document in documents:
        document.chantier_id = chantier_id
    for bloc in blocs:
        bloc.chantier_id = chantier_id

    alias.chantier_id = chantier_id
    alias.valide_par = None
    alias.valide_le = maintenant

    session.add(
        Journal(
            utilisateur_id=None,
            action="alias_rattache_auto",
            cible_table="chantier_alias",
            cible_id=str(alias.id),
            avant=None,
            apres={
                "libelle": libelle,
                "chantier_id": str(chantier_id),
                "methode": methode,
                "nb_mis_a_jour": len(documents) + len(blocs),
            },
        )
    )


async def _creer_chantier_auto(
    session: AsyncSession,
    nom: str,
    *,
    source_libelle: str,
    contexte: dict[str, str],
) -> uuid.UUID:
    chantier = Chantier(
        nom_canonique=nom, agence=None, client=None, actif=True, a_completer=True
    )
    session.add(chantier)
    await session.flush()
    session.add(
        Journal(
            utilisateur_id=None,
            action="chantier_cree_auto",
            cible_table="chantier",
            cible_id=str(chantier.id),
            avant=None,
            apres={"nom_canonique": nom, "source": source_libelle, **contexte},
        )
    )
    return chantier.id


async def _obtenir_ou_creer_chantier(
    session: AsyncSession,
    nom: str | None,
    *,
    source_libelle: str,
    contexte: dict[str, str],
) -> tuple[uuid.UUID | None, bool]:
    """Chantier retenu pour une décision `CREER` (brief étape 6) : reprend
    un chantier non fusionné dont le nom canonique normalisé est déjà
    identique (`ChantierEnDouble` côté validation humaine, même principe de
    déduplication ici, sans lever d'exception -- un rattachement automatique
    ne doit jamais échouer), sinon en crée un nouveau, « à compléter »."""
    if nom is None:
        return None, False
    normalise = normaliser_libelle(nom)
    existants = (
        await session.execute(
            select(Chantier.id, Chantier.nom_canonique).where(
                Chantier.fusionne_dans_id.is_(None)
            )
        )
    ).all()
    for chantier_id, nom_canonique in existants:
        if normaliser_libelle(nom_canonique) == normalise:
            return chantier_id, False
    chantier_id = await _creer_chantier_auto(
        session, nom, source_libelle=source_libelle, contexte=contexte
    )
    return chantier_id, True


async def rattacher_chantier_document(
    session: AsyncSession, document: Document
) -> ResultatRattachement:
    """Rattache (ou crée, ou signale) le chantier d'un bon (BL/enlèvement),
    à partir du nom lu (`document.chantier_brut`) et de la légende Telegram
    (`document.legende`) — spec §2.3, brief étapes 1 à 9. Ne commite jamais :
    c'est l'appelant qui décide du périmètre transactionnel."""
    await session.execute(select(func.pg_advisory_xact_lock(VERROU_CHANTIERS)))

    seuil = int(
        await lire_parametre_decimal(
            session, CLE_SEUIL_RESSEMBLANCE_CHANTIER, SEUIL_RESSEMBLANCE_DEFAUT
        )
    )
    noms = await charger_noms_chantiers(session)

    lu, lu_exact = await _correspondance_exacte_ou_ressemblance(
        session, document.fournisseur_id, document.chantier_brut, noms, seuil
    )
    legende = reconnaitre_chantier(document.legende, noms, seuil)

    decision = decider_chantier(lu, legende)

    chantier_id: uuid.UUID | None = None
    methode: str | None = None
    score: int | None = None
    cree = False
    alerte = False

    if decision.type is TypeDecision.RATTACHER:
        chantier_id = decision.chantier_id
        if decision.source is SourceNom.NOM_LU:
            methode = "nom connu" if lu_exact else "ressemblance"
            score = lu.score
        else:
            methode = "légende"
            score = legende.score
    elif decision.type is TypeDecision.CREER:
        methode = "création"
        source_brut = (
            document.chantier_brut
            if decision.source is SourceNom.NOM_LU
            else document.legende
        )
        nom = nom_pour_creation(source_brut)
        source_libelle = "nom lu" if decision.source is SourceNom.NOM_LU else "légende"
        if nom is not None:
            chantier_id, cree = await _obtenir_ou_creer_chantier(
                session,
                nom,
                source_libelle=source_libelle,
                contexte={"document_id": str(document.id)},
            )
    elif decision.type is TypeDecision.ALERTE:
        methode = "alerte"
        alerte = True
    # TypeDecision.AUCUN : chantier_id/methode restent `None` (comme aujourd'hui).

    document.chantier_id = chantier_id

    if (
        decision.apprendre
        and document.fournisseur_id is not None
        and lu.libelle
        and chantier_id is not None
    ):
        await _apprendre_alias(
            session,
            fournisseur_id=document.fournisseur_id,
            libelle=lu.libelle,
            chantier_id=chantier_id,
            methode=methode or "",
        )

    noms_candidats = await _noms_canoniques(session, decision.candidats)
    controle = ChantierIncertainControle(
        document_id=document.id,
        nom_lu=document.chantier_brut,
        legende=document.legende,
        candidats=tuple(
            noms_candidats[c] for c in decision.candidats if c in noms_candidats
        ),
        candidats_ids=decision.candidats,
        incertain=alerte,
    )
    await synchroniser_anomalies(
        session,
        anomalies=evaluer_chantier(controle),
        portee_document_id=document.id,
        portee_regles=sorted(REGLES_CHANTIER),
    )

    return ResultatRattachement(
        chantier_id=chantier_id, methode=methode, score=score, cree=cree, alerte=alerte
    )


async def rattacher_chantier_bloc(
    session: AsyncSession, fournisseur_id: uuid.UUID, chantier_brut: str | None
) -> uuid.UUID | None:
    """Rattache (ou crée) le chantier d'un bloc de facture, à partir du seul
    nom lu (pas de légende sur une facture) — spec §2.4 « Factures ». Un nom
    ambigu retombe sur l'ancien flux (`referentiels.resoudre_chantier`, alias
    en attente) plutôt que sur R18, jamais posée sur un bloc. Ne commite
    jamais."""
    await session.execute(select(func.pg_advisory_xact_lock(VERROU_CHANTIERS)))

    seuil = int(
        await lire_parametre_decimal(
            session, CLE_SEUIL_RESSEMBLANCE_CHANTIER, SEUIL_RESSEMBLANCE_DEFAUT
        )
    )
    noms = await charger_noms_chantiers(session)

    corr, via_alias_exact = await _correspondance_exacte_ou_ressemblance(
        session, fournisseur_id, chantier_brut, noms, seuil
    )

    if corr.etat is EtatCorrespondance.VIDE:
        return None

    if corr.etat is EtatCorrespondance.AMBIGU:
        # Ancien flux (spec §2.4) : alias « en attente », écran « Noms à
        # rattacher », R14 -- jamais de création ni d'alerte R18 sur un bloc.
        resolution = await resoudre_chantier(session, fournisseur_id, chantier_brut)
        return resolution.chantier_id

    chantier_id: uuid.UUID | None
    methode: str
    if corr.etat is EtatCorrespondance.RECONNU:
        chantier_id = corr.chantier_id
        methode = "nom connu" if via_alias_exact else "ressemblance"
    else:  # INCONNU
        nom = nom_pour_creation(chantier_brut)
        methode = "création"
        chantier_id = None
        if nom is not None:
            chantier_id, _ = await _obtenir_ou_creer_chantier(
                session,
                nom,
                source_libelle="nom lu",
                contexte={"fournisseur_id": str(fournisseur_id)},
            )

    if chantier_id is not None and corr.libelle:
        await _apprendre_alias(
            session,
            fournisseur_id=fournisseur_id,
            libelle=corr.libelle,
            chantier_id=chantier_id,
            methode=methode,
        )

    return chantier_id
