"""Fusion de deux chantiers (Task 7, avenant du 27/09/2026, spec §2.7) :
bouton « Fusionner avec… » de la fiche chantier, pour résorber les
doublons produits par le rattachement automatique (Task 5) — un même
chantier lu sous deux noms différents (« Ormeaux » / « Résidence les
Ormeaux ») crée deux chantiers « à compléter » distincts tant qu'un humain
ne les a pas rapprochés.

Le chantier source n'est **jamais** supprimé physiquement (CDC : aucune
donnée métier n'est perdue) : tout ce qu'il portait est déplacé vers la
cible, puis il est désactivé et marqué `fusionne_dans_id` -- toujours
atteignable par son lien direct (`GET /api/chantiers/{id}`,
`referentiels.obtenir_chantier`), mais exclu de `referentiels
.lister_chantiers` (Task 6) et donc de tout sélecteur.

Déplacé vers la cible (`UPDATE ... WHERE chantier_id = source`, même
principe que le `UPDATE Document` déjà en place dans `depot_telegram.py` --
un seul aller-retour base, jamais une boucle Python sur des centaines de
lignes) :
- `document.chantier_id` (bons/enlèvements) ;
- `bloc_facture.chantier_id` (blocs de facture) ;
- `chantier_alias.chantier_id` (noms appris pour ce chantier, Task 5) --
  après la fusion, un nom qui ressemblait au chantier source ressemble
  directement à la cible (`rattachement_chantier.charger_noms_chantiers`
  n'a même plus besoin de suivre `fusionne_dans_id` pour cet alias-là).

`anomalie.chantier_id` (portée d'une anomalie de suivi non rattachée à un
document/bloc précis -- en pratique seule R16 « chantier silencieux » en
pose un, voir `ingest/models.py::Anomalie`) suit une règle différente :
seules les anomalies **ouvertes** de la source sont considérées (une
anomalie `traitee`/`ignoree` est un historique, elle reste sur la source,
comme n'importe quelle anomalie fermée d'un document qui ne bouge pas non
plus). Une anomalie ouverte dont l'identité `(regle, document_id, bloc_id,
ligne_id, alias_id)` existe déjà côté cible (`chantier_id = cible`, même
scénario que deux chantiers silencieux fusionnés) ne peut pas être
déplacée telle quelle -- l'index unique `NULLS NOT DISTINCT` de la
migration 0007 l'interdirait -- elle est donc levée (supprimée, journal
`anomalie_levee`, même geste qu'`anomalies.synchroniser_anomalies`) plutôt
que déplacée ; la reprise (Task 8) ou le prochain contrôle différé la
recréera sur la cible si le silence continue.

Un chantier déjà fusionné dans la source (`fusionne_dans_id = source`, une
fusion antérieure) est redirigé directement vers la nouvelle cible --
jamais de chaîne à plus d'un saut (décision du contrôleur, cohérente avec
`rattachement_chantier.chantier_effectif`, qui ne suit que deux sauts par
prudence mais ne devrait jamais en avoir besoin après cette redirection).

Verrou `commun.VERROU_CHANTIERS` (déplacé de `rattachement_chantier.py` à
`ingest.commun` par le Ruling 16 de la revue finale du 27/09/2026, pour que
`referentiels.creer_chantier`/`modifier_chantier` puissent le prendre eux
aussi sans cycle d'import) : une fusion touche les mêmes données qu'un
rattachement automatique (chantier, alias, documents)
-- sans le même verrou, un dépôt concurrent pourrait apprendre un alias sur
le chantier source pendant que cette fonction le fusionne, et le perdre.
Pris en tout début de fonction, relâché par le `commit` de cette même
fonction (contrairement à `rattacher_chantier_document`, la fusion est une
action admin de premier niveau qui décide elle-même de son périmètre
transactionnel, comme `referentiels.modifier_chantier`)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.anomalies import _trouver_par_cle
from app.modules.ingest.commun import VERROU_CHANTIERS
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Chantier,
    ChantierAlias,
    Document,
    Journal,
)
from app.modules.ingest.referentiels import ChantierIntrouvable


@dataclass(frozen=True)
class ResultatFusion:
    """Issue de `fusionner_chantiers`, pour la confirmation côté front et le
    journal (`apres`, hors `cible_nom` déjà dans `avant`/`apres` du
    journal)."""

    cible_id: uuid.UUID
    nb_documents: int
    nb_blocs: int
    nb_alias: int
    nb_anomalies: int  # anomalies ouvertes de la source déplacées OU levées.
    # Task 9 (spec §5) : identifiants des documents déplacés (`nb_documents`
    # d'entre eux), pour que l'appelant (`api.referentiels`) renomme leur
    # lien physique sur le serveur une fois la fusion commitée -- jamais
    # sérialisé côté front (absent de `ResultatFusionReponse`, qui ne reprend
    # que les compteurs).
    documents_ids: tuple[uuid.UUID, ...]


class FusionImpossible(Exception):
    """Fusion refusée (409) : message déjà lisible par un humain, affiché
    tel quel côté front (décision du contrôleur, comme `str(exc)` pour
    `AliasDejaValide` ailleurs) -- distingue les trois refus du plan (« même
    chantier », source déjà fusionnée, cible fusionnée)."""


async def _deplacer_ou_lever_anomalies(
    session: AsyncSession, *, source_id: uuid.UUID, cible_id: uuid.UUID
) -> int:
    """Anomalies **ouvertes** dont `chantier_id = source_id` : déplacées
    vers `cible_id`, sauf si une anomalie de même identité existe déjà côté
    cible (`_trouver_par_cle`, réutilise la comparaison `NULLS NOT
    DISTINCT` d'`anomalies.py` -- deux `NULL` sont égaux, comme l'index
    unique de la migration 0007), auquel cas celle de la source est levée
    (journal `anomalie_levee`, même forme qu'`anomalies
    .synchroniser_anomalies`). Les anomalies fermées ne sont jamais
    sélectionnées : elles restent sur la source (spec §2.7, historique).
    Renvoie le nombre d'anomalies ouvertes traitées (déplacées + levées)."""
    anomalies_source = (
        (
            await session.execute(
                select(Anomalie).where(
                    Anomalie.chantier_id == source_id,
                    Anomalie.statut == "ouverte",
                )
            )
        )
        .scalars()
        .all()
    )

    for anomalie in anomalies_source:
        conflit = await _trouver_par_cle(
            session,
            anomalie.regle,
            anomalie.document_id,
            anomalie.bloc_id,
            anomalie.ligne_id,
            cible_id,
            anomalie.alias_id,
        )
        if conflit is not None:
            session.add(
                Journal(
                    utilisateur_id=None,
                    action="anomalie_levee",
                    cible_table="anomalie",
                    cible_id=str(anomalie.id),
                    avant={
                        "regle": anomalie.regle,
                        "gravite": anomalie.gravite,
                        "detail": anomalie.detail,
                    },
                    apres=None,
                )
            )
            await session.delete(anomalie)
        else:
            anomalie.chantier_id = cible_id

    return len(anomalies_source)


async def fusionner_chantiers(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    cible_id: uuid.UUID,
    auteur_id: uuid.UUID,
) -> ResultatFusion:
    """Fusionne `source_id` dans `cible_id` (« Fusionner avec… », spec
    §2.7) : déplace bons, blocs, alias et anomalies ouvertes (voir
    docstring de module), redirige les chantiers déjà fusionnés dans la
    source, désactive la source (`actif=False`, `a_completer=False`,
    `fusionne_dans_id=cible_id`) sans jamais la supprimer, journalise
    `chantier_fusionne` et commite (action admin de premier niveau, ne
    commite jamais pour le compte d'un appelant).

    Lève `ChantierIntrouvable` si `source_id` ou `cible_id` n'existe pas,
    `FusionImpossible` (409, message lisible) si `source_id == cible_id`,
    si la source est déjà fusionnée, ou si la cible l'est elle-même --
    jamais de chaîne de fusion créée par cette fonction."""
    await session.execute(select(func.pg_advisory_xact_lock(VERROU_CHANTIERS)))

    source = await session.get(Chantier, source_id)
    if source is None:
        raise ChantierIntrouvable(str(source_id))
    cible = await session.get(Chantier, cible_id)
    if cible is None:
        raise ChantierIntrouvable(str(cible_id))

    if source_id == cible_id:
        raise FusionImpossible(
            "le chantier à fusionner et le chantier cible sont le même chantier"
        )
    if source.fusionne_dans_id is not None:
        raise FusionImpossible(
            "ce chantier est déjà fusionné, il ne peut pas être fusionné une "
            "seconde fois"
        )
    if cible.fusionne_dans_id is not None:
        raise FusionImpossible(
            "le chantier cible est déjà fusionné dans un autre chantier"
        )

    nom_source = source.nom_canonique
    nom_cible = cible.nom_canonique

    documents_deplaces = (
        (
            await session.execute(
                update(Document)
                .where(Document.chantier_id == source_id)
                .values(chantier_id=cible_id)
                .returning(Document.id)
            )
        )
        .scalars()
        .all()
    )
    blocs_deplaces = (
        (
            await session.execute(
                update(BlocFacture)
                .where(BlocFacture.chantier_id == source_id)
                .values(chantier_id=cible_id)
                .returning(BlocFacture.id)
            )
        )
        .scalars()
        .all()
    )
    alias_deplaces = (
        (
            await session.execute(
                update(ChantierAlias)
                .where(ChantierAlias.chantier_id == source_id)
                .values(chantier_id=cible_id)
                .returning(ChantierAlias.id)
            )
        )
        .scalars()
        .all()
    )
    nb_anomalies = await _deplacer_ou_lever_anomalies(
        session, source_id=source_id, cible_id=cible_id
    )

    # Chantiers déjà fusionnés dans la source (fusions antérieures) :
    # redirigés directement vers la nouvelle cible, jamais de chaîne.
    await session.execute(
        update(Chantier)
        .where(Chantier.fusionne_dans_id == source_id)
        .values(fusionne_dans_id=cible_id)
    )

    source.actif = False
    source.a_completer = False
    source.fusionne_dans_id = cible_id
    source.updated_by = auteur_id

    nb_documents = len(documents_deplaces)
    nb_blocs = len(blocs_deplaces)
    nb_alias = len(alias_deplaces)

    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="chantier_fusionne",
            cible_table="chantier",
            cible_id=str(source_id),
            avant={"chantier_id": str(source_id), "nom": nom_source},
            apres={
                "cible_id": str(cible_id),
                "cible_nom": nom_cible,
                "nb_documents": nb_documents,
                "nb_blocs": nb_blocs,
                "nb_alias": nb_alias,
                "nb_anomalies": nb_anomalies,
            },
        )
    )
    await session.commit()

    return ResultatFusion(
        cible_id=cible_id,
        nb_documents=nb_documents,
        nb_blocs=nb_blocs,
        nb_alias=nb_alias,
        nb_anomalies=nb_anomalies,
        documents_ids=tuple(documents_deplaces),
    )
