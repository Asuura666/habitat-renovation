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

Concurrence : `pg_advisory_xact_lock(VERROU_CHANTIERS)` (défini dans
`ingest.commun`, Ruling 16 de la revue finale du 27/09/2026 — ce module
l'importe plutôt que le définir, pour que `referentiels.creer_chantier`/
`modifier_chantier` puissent le prendre eux aussi sans cycle d'import)
sérialise toute décision de chantier (lecture des noms connus, création,
apprentissage d'alias) — sans lui, deux dépôts concurrents du même nom
inconnu créeraient chacun leur chantier. Le verrou est pris en tout début de
`rattacher_chantier_document`/`rattacher_chantier_bloc` et tenu jusqu'au
commit de l'appelant (ni l'une ni l'autre fonction ne commite jamais, même
principe que `referentiels.resoudre_chantier`/`rattacher_article` et
`anomalies.synchroniser_anomalies`).

Décision humaine conservée (Ruling 15 de la revue finale du 27/09/2026,
A1) : quand une correction rouvre un désaccord nom lu/légende sur un bon
dont la R18 a déjà été traitée par un humain (`choisir_chantier_document`,
« traitee ») ou volontairement ignorée (`anomalies.traiter_anomalie`,
« ignoree »), `rattacher_chantier_document` ne touche plus au chantier du
document ni ne resynchronise R18 — elle renvoie `methode="décision humaine
conservée"`. Sans ce garde-fou, le document perdait silencieusement son
chantier (`document.chantier_id = None`, la ligne suivante de l'ancien
code) alors que `synchroniser_anomalies` n'aurait jamais rouvert la R18
`traitee`/`ignoree` (upsert qui ignore toute anomalie hors `ouverte`,
`anomalies.py` L4-D12) : le bon se retrouvait sans chantier et sans aucune
alerte visible. Le cycle de vie d'une anomalie (`ouverte` -> `traitee`/
`ignoree`, jamais l'inverse) est un invariant de `anomalies.py`, jamais
contourné ici.

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

Reprise (Task 8, spec §2.8) : `reprendre_chantiers` fait passer par cette
même logique les données de production laissées par l'ancien flux (alias
« en attente », bons sans chantier) — commande `python -m app.cli
rattacher-chantiers`, lancée une fois au déploiement, idempotente.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.anomalies import synchroniser_anomalies
from app.modules.ingest.commun import VERROU_CHANTIERS
from app.modules.ingest.lecture import DocumentIntrouvable
from app.modules.ingest.models import (
    Anomalie,
    Chantier,
    ChantierAlias,
    Document,
    Journal,
)
from app.modules.ingest.parametres import CLE_SEUIL_RESSEMBLANCE_CHANTIER
from app.modules.ingest.referentiels import (
    ChantierIntrouvable,
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
from app.modules.normalize.texte import nombres_differents, normaliser_libelle
from app.modules.rules.engine import REGLES_CHANTIER, evaluer_chantier
from app.modules.rules.modeles import ChantierIncertainControle

SEUIL_RESSEMBLANCE_DEFAUT = Decimal("80")


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
    # Lot 2 du 31/10/2026 : le chantier retenu par un rattachement (nom connu,
    # ressemblance, légende), pour confirmer la lecture (`ajustement_motifs`).
    chantier_nom: str | None = None
    chantier_a_completer: bool = False


@dataclass(frozen=True)
class BilanReprise:
    """Bilan de `reprendre_chantiers` (Task 8, spec §2.8), affiché tel quel
    par `python -m app.cli rattacher-chantiers`."""

    alias_rattaches: int  # alias en attente rattachés (existant ou créé).
    chantiers_crees: int  # chantiers créés, alias + bons confondus.
    alias_ambigus: int  # alias en attente restés ambigus (inchangés).
    bons_rattaches: int  # bons rattachés par la seconde passe (documents).
    bons_en_alerte: int  # bons ayant ouvert une R18 (désaccord nom lu/légende).


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


async def _r18_deja_decidee(session: AsyncSession, document_id: uuid.UUID) -> bool:
    """Vrai si ce bon porte déjà une R18 `traitee` (choisie par
    `choisir_chantier_document`) ou `ignoree` (`anomalies.traiter_anomalie`)
    -- décision humaine déjà prise, à conserver (Ruling 15, A1). Une R18
    `ouverte` ne compte pas : elle suit le flux normal, mise à jour par
    `synchroniser_anomalies` plus bas."""
    resultat = await session.execute(
        select(Anomalie.id).where(
            Anomalie.regle == "R18",
            Anomalie.document_id == document_id,
            Anomalie.statut.in_(("traitee", "ignoree")),
        )
    )
    return resultat.first() is not None


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
        if await _r18_deja_decidee(session, document.id):
            # Ruling 15 (A1, revue finale du 27/09/2026) : une décision
            # humaine déjà prise sur ce bon (choix d'un candidat ou R18
            # ignorée) n'est jamais reperdue par un nouveau désaccord nom
            # lu/légende -- on laisse le bon tel quel (voir docstring de
            # module). Sortie anticipée avant `document.chantier_id =
            # chantier_id` (qui vaudrait `None` ici) et avant
            # `synchroniser_anomalies` (qui ne rouvrirait de toute façon
            # jamais une R18 `traitee`/`ignoree`, L4-D12).
            return ResultatRattachement(
                chantier_id=document.chantier_id,
                methode="décision humaine conservée",
                score=None,
                cree=False,
                alerte=False,
            )
        methode = "alerte"
        alerte = True
    # TypeDecision.AUCUN : chantier_id/methode restent `None` (comme aujourd'hui).

    document.chantier_id = chantier_id

    chantier_nom: str | None = None
    chantier_a_completer = False
    if decision.type is TypeDecision.RATTACHER and chantier_id is not None:
        retenu = (
            await session.execute(
                select(Chantier.nom_canonique, Chantier.a_completer).where(
                    Chantier.id == chantier_id
                )
            )
        ).first()
        if retenu is not None:
            chantier_nom, chantier_a_completer = retenu

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
        chantier_id=chantier_id,
        methode=methode,
        score=score,
        cree=cree,
        alerte=alerte,
        chantier_nom=chantier_nom,
        chantier_a_completer=chantier_a_completer,
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


async def _exemple_brut_alias(
    session: AsyncSession, alias: ChantierAlias
) -> str | None:
    """Libellé brut le plus récent parmi les documents/blocs qui attendent
    encore `alias` (même sélection que `ingest.a_traiter
    ._lister_alias_en_attente`, qui calcule `exemple_brut` de la même façon
    -- décision du contrôleur, ruling Task 8 : jamais dupliquer cette
    sélection, `referentiels.candidats_alias` en est l'unique source).
    `None` si plus aucun document/bloc n'attend cet alias (improbable pour
    un alias encore en attente, mais jamais bloquant : l'appelant se replie
    alors sur le libellé normalisé de l'alias)."""
    documents, blocs = await candidats_alias(
        session, alias.fournisseur_id, alias.libelle_brut
    )
    brut_par_date = [(d.chantier_brut, d.created_at) for d in documents] + [
        (b.chantier_brut, b.created_at) for b in blocs
    ]
    if not brut_par_date:
        return None
    return max(brut_par_date, key=lambda paire: paire[1])[0]


async def reprendre_chantiers(session: AsyncSession) -> BilanReprise:
    """Reprise, au déploiement, des données laissées par l'ancien flux
    (spec §2.8, brief Task 8) : `python -m app.cli rattacher-chantiers`,
    idempotente, appelle cette fonction une seule fois.

    Deux passes séquentielles (la seconde profite des rattachements et
    propagations de la première, `_apprendre_alias` pouvant déjà avoir posé
    le chantier de certains bons) :

    1. chaque alias chantier `chantier_id IS NULL` (ordre `created_at`)
       repasse par `rattacher_chantier_bloc` (rattache à un chantier connu,
       en crée un « à compléter », ou laisse l'alias en attente s'il reste
       ambigu -- comportement déjà idempotent, inchangé ici). Ruling du
       contrôleur (27/09/2026) : quand cet appel crée un chantier, son nom
       ne doit jamais être le libellé normalisé de l'alias (minuscule,
       ex. « villa test ») mais le libellé BRUT le plus récent qui attendait
       cet alias (`_exemple_brut_alias`, ex. « VILLA TEST (123) » ->
       « VILLA TEST ») -- obtenu en passant ce brut à `rattacher_chantier_bloc`
       (qui le décompose lui-même) plutôt qu'en dupliquant sa logique de
       création ; repli sur le libellé de l'alias si plus aucun document/bloc
       ne l'attend.
    2. chaque bon (BL/enlèvement) non archivé, encore sans chantier, dont le
       nom lu ou la légende est renseigné, repasse par la logique complète
       (`rattacher_chantier_document`) -- rattache, crée, ou ouvre une R18.

    Un chantier est compté « créé » par comparaison à l'ensemble des
    chantiers connus avant l'appel (mis à jour au fil des deux passes) :
    aucune des deux fonctions rattachées n'expose elle-même ce booléen pour
    un alias (seul `ResultatRattachement.cree` le fait pour un bon).

    Idempotent : un second appel ne retrouve plus d'alias/bon à traiter --
    seuls les alias restés ambigus (et les bons restés en R18) sont
    réévalués sans effet, les deux fonctions rattachées l'étant déjà.
    Commite une fois à la fin (reprise ponctuelle au déploiement, pas un
    flux par document)."""
    chantiers_connus = set((await session.execute(select(Chantier.id))).scalars().all())

    alias_rattaches = 0
    alias_ambigus = 0
    chantiers_crees = 0
    aliases_en_attente = (
        (
            await session.execute(
                select(ChantierAlias)
                .where(ChantierAlias.chantier_id.is_(None))
                .order_by(ChantierAlias.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    for alias in aliases_en_attente:
        brut = await _exemple_brut_alias(session, alias)
        chantier_id = await rattacher_chantier_bloc(
            session,
            alias.fournisseur_id,
            brut if brut is not None else alias.libelle_brut,
        )
        if chantier_id is None:
            alias_ambigus += 1
            continue
        alias_rattaches += 1
        if chantier_id not in chantiers_connus:
            chantiers_connus.add(chantier_id)
            chantiers_crees += 1

    bons_rattaches = 0
    bons_en_alerte = 0
    documents_en_attente = (
        (
            await session.execute(
                select(Document)
                .where(
                    Document.type.in_(("bl", "enlevement")),
                    Document.statut != "archive",
                    Document.chantier_id.is_(None),
                    or_(
                        Document.chantier_brut.is_not(None),
                        Document.legende.is_not(None),
                    ),
                )
                .order_by(Document.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    for document in documents_en_attente:
        resultat = await rattacher_chantier_document(session, document)
        if resultat.cree:
            chantiers_crees += 1
        if resultat.alerte:
            bons_en_alerte += 1
        elif resultat.chantier_id is not None:
            bons_rattaches += 1

    await session.commit()

    return BilanReprise(
        alias_rattaches=alias_rattaches,
        chantiers_crees=chantiers_crees,
        alias_ambigus=alias_ambigus,
        bons_rattaches=bons_rattaches,
        bons_en_alerte=bons_en_alerte,
    )


async def choisir_chantier_document(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    chantier_id: uuid.UUID,
    auteur_id: uuid.UUID,
) -> uuid.UUID:
    """Pose le chantier d'un bon (BL/enlèvement) choisi par un humain --
    `PUT /api/documents/{id}/chantier` (Task 6, spec §2.4/§2.6). Deux
    usages : régler l'alerte R18 (« C'est <nom> »/« Autre chantier… ») ou
    corriger a posteriori le chantier d'un bon depuis sa fiche (« Chantier
    du bon » de l'admin, DocumentDetail) -- même route, même fonction, la
    présence d'une R18 ouverte n'est jamais une condition d'entrée.

    Lève `DocumentIntrouvable` (document absent, ni BL ni enlèvement, ou
    déjà archivé -- même périmètre que `corrections._document_pour_ecriture`,
    mais toujours ce même 404, jamais un 409 : décision du contrôleur, cette
    route n'a pas de notion de document « non modifiable » distincte d'un
    document qui n'existe plus pour elle) et `ChantierIntrouvable`.

    Pose `document.chantier_id = chantier_effectif(chantier_id)` (Task 7,
    une fusion éventuelle du chantier choisi est toujours suivie). Ferme la
    R18 ouverte du bon si elle existe (`statut="traitee"`, commentaire
    automatique « Chantier choisi : <nom> », `traitee_par`/`traitee_le`,
    journal `anomalie_traitee` -- mêmes champs que `anomalies
    .traiter_anomalie`, mais sans repasser par elle : pas de commentaire
    saisi par un humain ici) ; absente (choix depuis la fiche du bon, hors
    alerte), rien n'est touché côté anomalie. Journalise ensuite
    `chantier_choisi` (avant/après `chantier_id`) et commite -- action admin
    de premier niveau, comme `referentiels.valider_article`."""
    document = await session.get(Document, document_id)
    if (
        document is None
        or document.type not in ("bl", "enlevement")
        or document.statut == "archive"
    ):
        raise DocumentIntrouvable(str(document_id))

    if await session.get(Chantier, chantier_id) is None:
        raise ChantierIntrouvable(str(chantier_id))

    effectif = await chantier_effectif(session, chantier_id)
    nom_chantier = (
        await session.execute(
            select(Chantier.nom_canonique).where(Chantier.id == effectif)
        )
    ).scalar_one()

    avant_chantier_id = document.chantier_id
    document.chantier_id = effectif

    anomalie_r18 = (
        await session.execute(
            select(Anomalie).where(
                Anomalie.regle == "R18",
                Anomalie.document_id == document_id,
                Anomalie.statut == "ouverte",
            )
        )
    ).scalar_one_or_none()
    if anomalie_r18 is not None:
        avant_anomalie = {
            "statut": anomalie_r18.statut,
            "commentaire": anomalie_r18.commentaire,
        }
        commentaire = f"Chantier choisi : {nom_chantier}"
        anomalie_r18.statut = "traitee"
        anomalie_r18.commentaire = commentaire
        anomalie_r18.traitee_par = auteur_id
        anomalie_r18.traitee_le = datetime.now(UTC)
        session.add(
            Journal(
                utilisateur_id=auteur_id,
                action="anomalie_traitee",
                cible_table="anomalie",
                cible_id=str(anomalie_r18.id),
                avant=avant_anomalie,
                apres={"statut": "traitee", "commentaire": commentaire},
            )
        )

    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="chantier_choisi",
            cible_table="document",
            cible_id=str(document_id),
            avant={
                "chantier_id": str(avant_chantier_id)
                if avant_chantier_id is not None
                else None
            },
            apres={"chantier_id": str(effectif)},
        )
    )
    await session.commit()
    return effectif


@dataclass(frozen=True)
class AliasSuspect:
    """Alias appris dont les nombres diffèrent de ceux du chantier (B-05)."""

    libelle: str
    chantier: str
    appris_le: datetime | None
    nb_documents: int


async def lister_alias_suspects(session: AsyncSession) -> list[AliasSuspect]:
    """Diagnostic en LECTURE SEULE (B-05) : alias rattachés à un chantier dont
    les nombres diffèrent de ceux du nom du chantier (« … 13 » appris sur
    « … 12 » par l'ancienne ressemblance). Rien n'est modifié : Ilane relit
    la liste. `nb_documents` = documents du même fournisseur, rattachés à ce
    chantier, dont le nom lu décomposé est ce libellé."""
    alias_list = (
        (
            await session.execute(
                select(ChantierAlias)
                .where(ChantierAlias.chantier_id.is_not(None))
                .order_by(ChantierAlias.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    resultat: list[AliasSuspect] = []
    for alias in alias_list:
        if alias.chantier_id is None:
            continue
        effectif = await chantier_effectif(session, alias.chantier_id)
        nom = (
            await session.execute(
                select(Chantier.nom_canonique).where(Chantier.id == effectif)
            )
        ).scalar_one_or_none()
        if nom is None or not nombres_differents(alias.libelle_brut, nom):
            continue
        noms_lus = (
            (
                await session.execute(
                    select(Document.chantier_brut).where(
                        Document.fournisseur_id == alias.fournisseur_id,
                        Document.chantier_id == effectif,
                    )
                )
            )
            .scalars()
            .all()
        )
        nb = 0
        for brut in noms_lus:
            decompose = decomposer_chantier(brut)
            if decompose is not None and decompose.libelle == alias.libelle_brut:
                nb += 1
        resultat.append(
            AliasSuspect(
                libelle=alias.libelle_brut,
                chantier=nom,
                appris_le=alias.created_at,
                nb_documents=nb,
            )
        )
    return resultat
