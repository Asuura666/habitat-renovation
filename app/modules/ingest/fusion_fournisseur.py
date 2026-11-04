"""Fusion de deux fournisseurs (lot 4 du 02/11/2026, commande
`fournisseur-fusionner`).

Constat : un fournisseur a été créé à tort (le nom du pied de page d'un bon
pris pour le fournisseur), et aucun écran ne permet de le supprimer. Cette
fonction reporte tout ce que porte la **source** sur la **cible**, puis
supprime la source.

- Les tables qui référencent `fournisseur.id` sont trouvées par les
  métadonnées SQLAlchemy (`tables_referencant_fournisseur`), jamais par une
  liste en dur : une table ajoutée plus tard est déplacée sans qu'on y pense.
  `test_fusion_fournisseur.py` échoue si l'ensemble change sans que le test
  soit relu.
- Conflit d'unicité (même clé chez la cible : alias de chantier, article,
  agence de même libellé) : la ligne de la cible est gardée, tout ce qui
  dépendait de la ligne de la source (clés étrangères trouvées de la même
  façon) est rattaché à la ligne gardée, puis le doublon est supprimé.
  Exception : un `document` en conflit (même numéro chez les deux
  fournisseurs) n'est jamais supprimé ni fusionné automatiquement -- refus
  clair (`FusionFournisseurImpossible`), avant toute écriture.
- Le nom de la source et ses alias deviennent des alias de la cible ; SIRET et
  TVA de la cible ne changent pas (ceux de la source disparaissent avec elle).
- `grille_prix` est un historique inaltérable (déclencheur de la migration
  0013) : son déclencheur est désactivé le temps de la fusion, dans la même
  transaction (le DDL de PostgreSQL est transactionnel : un échec le remet en
  place), puis réactivé avant la fin. Les prix de la source rejoignent
  l'historique de la cible, ordonnés par leur date d'effet.
- Une seule transaction, commitée par l'appelant. Verrou
  `VERROU_CHANTIERS` (les alias de chantier bougent).
- Simulation : mêmes comptes, aucune écriture.

Journal `fournisseur_fusionne` (auteur vide) : avant/après (noms, alias,
nombres de lignes déplacées par table)."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import (
    Column,
    Index,
    Table,
    UniqueConstraint,
    and_,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base
from app.modules.ingest.commun import VERROU_CHANTIERS
from app.modules.ingest.models import AgenceFournisseur, Fournisseur, Journal
from app.modules.normalize.texte import normaliser_libelle

# Table -> déclencheur qui refuse les modifications (migration 0013).
_DECLENCHEURS_INALTERABLES: dict[str, str] = {"grille_prix": "grille_prix_inalterable"}

# Tables dont un doublon ne peut pas être supprimé sans perdre des données :
# un conflit y est un refus, pas une fusion.
_TABLES_SANS_DOUBLON_AUTOMATIQUE: frozenset[str] = frozenset({"document"})


# Libellés lisibles des tables pour le journal (affiché tel quel à l'écran,
# sans jargon) ; une table absente garde son nom technique.
_LIBELLES_TABLES: dict[str, str] = {
    "agence_fournisseur": "agences",
    "article": "articles",
    "chantier_alias": "noms de chantier",
    "document": "documents",
    "grille_import": "imports de grille",
    "grille_prix": "prix de grille",
    "prix_internet": "prix internet",
    "prix_observe": "prix déjà vus",
}


def _pour_journal(nombres: dict[str, int]) -> dict[str, int]:
    return {_LIBELLES_TABLES.get(t, t): n for t, n in nombres.items()}


class FusionFournisseurImpossible(Exception):
    """Fusion refusée : message lisible, affiché tel quel par la CLI."""


@dataclass(frozen=True)
class ResultatFusionFournisseur:
    source_nom: str
    cible_nom: str
    simulation: bool
    # Lignes dont `fournisseur_id` passe de la source à la cible, par table
    # (sans les doublons fusionnés).
    deplacees: dict[str, int] = field(default_factory=dict)
    # Doublons de la source supprimés au profit de la ligne de la cible.
    doublons: dict[str, int] = field(default_factory=dict)
    # Lignes d'autres tables rattachées à la ligne gardée de la cible.
    reconduites: dict[str, int] = field(default_factory=dict)
    alias_ajoutes: tuple[str, ...] = ()


def tables_referencant_fournisseur() -> list[tuple[Table, Column[Any]]]:
    """Toutes les colonnes qui sont une clé étrangère vers `fournisseur.id`,
    d'après les métadonnées (ordre déterministe)."""
    fournisseur = Fournisseur.__table__
    trouvees: list[tuple[Table, Column[Any]]] = []
    for table in Base.metadata.sorted_tables:
        for cle in table.foreign_keys:
            if cle.column.table is fournisseur:
                trouvees.append((table, cle.parent))
    return sorted(trouvees, key=lambda t: (t[0].name, t[1].name))


def _cles_uniques(
    table: Table, colonne: Column[Any]
) -> list[tuple[list[Column[Any]], bool]]:
    """Contraintes et index uniques de `table` qui contiennent `colonne` :
    (autres colonnes de la clé, `NULL` égal à `NULL`)."""
    cles: list[tuple[list[Column[Any]], bool]] = []
    candidats: list[Any] = [
        c for c in table.constraints if isinstance(c, UniqueConstraint)
    ] + [i for i in table.indexes if isinstance(i, Index) and i.unique]
    for contrainte in candidats:
        colonnes = list(contrainte.columns)
        if colonne not in colonnes:
            continue
        nulls_egaux = bool(
            contrainte.dialect_options["postgresql"].get("nulls_not_distinct")
        )
        cles.append(([c for c in colonnes if c is not colonne], nulls_egaux))
    return cles


async def _doublons_generiques(
    session: AsyncSession,
    table: Table,
    colonne: Column[Any],
    source_id: uuid.UUID,
    cible_id: uuid.UUID,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Couples (ligne de la source, ligne de la cible) qui portent la même clé
    unique une fois la source rattachée à la cible."""
    couples: dict[uuid.UUID, uuid.UUID] = {}
    cible = table.alias("cible")
    source = table.alias("source")
    for autres, nulls_egaux in _cles_uniques(table, colonne):
        if not autres:
            continue
        conditions = [
            source.c[c.name].is_not_distinct_from(cible.c[c.name])
            if nulls_egaux
            else source.c[c.name] == cible.c[c.name]
            for c in autres
        ]
        requete = (
            select(source.c.id, cible.c.id)
            .select_from(source.join(cible, and_(*conditions)))
            .where(source.c[colonne.name] == source_id)
            .where(cible.c[colonne.name] == cible_id)
        )
        for ligne in (await session.execute(requete)).all():
            couples.setdefault(ligne[0], ligne[1])
    return sorted(couples.items(), key=lambda c: str(c[0]))


async def _doublons_agences(
    session: AsyncSession, source_id: uuid.UUID, cible_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Agences de même libellé (comparaison `normaliser_libelle`, comme
    `definir_fournisseur`) : aucune contrainte en base, mais deux agences au
    même nom chez le même fournisseur seraient un doublon."""
    chez_cible: dict[str, uuid.UUID] = {}
    for ag in (
        await session.execute(
            select(AgenceFournisseur)
            .where(AgenceFournisseur.fournisseur_id == cible_id)
            .order_by(AgenceFournisseur.created_at, AgenceFournisseur.id)
        )
    ).scalars():
        chez_cible.setdefault(normaliser_libelle(ag.nom), ag.id)
    couples: list[tuple[uuid.UUID, uuid.UUID]] = []
    for ag in (
        await session.execute(
            select(AgenceFournisseur)
            .where(AgenceFournisseur.fournisseur_id == source_id)
            .order_by(AgenceFournisseur.created_at, AgenceFournisseur.id)
        )
    ).scalars():
        gardee = chez_cible.get(normaliser_libelle(ag.nom))
        if gardee is not None:
            couples.append((ag.id, gardee))
    return couples


async def _compter(
    session: AsyncSession, table: Table, colonne: Column[Any], valeur: uuid.UUID
) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(table).where(colonne == valeur)
        )
    ).scalar_one()


async def _trouver(session: AsyncSession, nom: str) -> Fournisseur | None:
    return (
        await session.execute(
            select(Fournisseur).where(
                func.lower(Fournisseur.nom) == nom.strip().lower()
            )
        )
    ).scalar_one_or_none()


async def fusionner_fournisseurs(
    session: AsyncSession,
    *,
    source_nom: str,
    cible_nom: str,
    simulation: bool = False,
) -> ResultatFusionFournisseur:
    """Voir le module. Lève `FusionFournisseurImpossible` (rien d'écrit) si la
    source ou la cible n'existe pas, si c'est le même fournisseur, ou si deux
    documents portent le même numéro chez les deux fournisseurs. Le commit est
    à la charge de l'appelant, qui doit aussi faire `session.expire_all()` s'il
    relit des objets déjà chargés (les mises à jour en bloc contournent l'ORM)."""
    if not simulation:
        await session.execute(select(func.pg_advisory_xact_lock(VERROU_CHANTIERS)))
    source = await _trouver(session, source_nom)
    if source is None:
        raise FusionFournisseurImpossible(f"Fournisseur introuvable : {source_nom}")
    cible = await _trouver(session, cible_nom)
    if cible is None:
        raise FusionFournisseurImpossible(f"Fournisseur introuvable : {cible_nom}")
    if source.id == cible.id:
        raise FusionFournisseurImpossible(
            "La source et la cible sont le même fournisseur."
        )
    source_id, cible_id = source.id, cible.id
    # Journal à plat (l'écran Journal affiche clé par clé) : `avant` = la cible
    # telle qu'elle était et le fournisseur absorbé.
    avant: dict[str, Any] = {
        "nom": cible.nom,
        "aliases": list(cible.aliases or []),
        "fournisseur_absorbe": source.nom,
        "aliases_absorbe": list(source.aliases or []),
    }

    # 1. Doublons (avant toute écriture, pour pouvoir refuser).
    doublons_par_table: dict[str, list[tuple[uuid.UUID, uuid.UUID]]] = {}
    cibles = tables_referencant_fournisseur()
    for table, colonne in cibles:
        if table.name == "agence_fournisseur":
            couples = await _doublons_agences(session, source_id, cible_id)
        else:
            couples = await _doublons_generiques(
                session, table, colonne, source_id, cible_id
            )
        if not couples:
            continue
        if table.name in _TABLES_SANS_DOUBLON_AUTOMATIQUE:
            raise FusionFournisseurImpossible(
                f"{len(couples)} ligne(s) de « {table.name} » existent chez les deux "
                "fournisseurs avec la même clé : à régler à la main avant la fusion."
            )
        doublons_par_table[table.name] = couples

    # 2. Dénombrement (et écriture hors simulation).
    deplacees: Counter[str] = Counter()
    doublons: Counter[str] = Counter()
    reconduites: Counter[str] = Counter()

    for nom_table, couples in doublons_par_table.items():
        table = Base.metadata.tables[nom_table]
        ids_source = [c[0] for c in couples]
        doublons[nom_table] = len(couples)
        for dependante in Base.metadata.sorted_tables:
            for cle in dependante.foreign_keys:
                if cle.column.table is not table:
                    continue
                colonne_dep = cle.parent
                for id_source, id_gardee in couples:
                    if simulation:
                        n = await _compter(session, dependante, colonne_dep, id_source)
                    else:
                        resultat = await session.execute(
                            dependante.update()
                            .where(colonne_dep == id_source)
                            .values({colonne_dep.name: id_gardee})
                        )
                        n = resultat.rowcount  # type: ignore[attr-defined]
                    if n:
                        reconduites[dependante.name] += n
        if not simulation:
            await session.execute(table.delete().where(table.c.id.in_(ids_source)))

    for table, colonne in cibles:
        restant = (
            await _compter(session, table, colonne, source_id)
            - doublons.get(table.name, 0)
            if simulation
            else await _compter(session, table, colonne, source_id)
        )
        if not simulation:
            declencheur = _DECLENCHEURS_INALTERABLES.get(table.name)
            if declencheur and restant:
                await session.execute(
                    text(f'ALTER TABLE "{table.name}" DISABLE TRIGGER {declencheur}')
                )
            await session.execute(
                table.update()
                .where(colonne == source_id)
                .values({colonne.name: cible_id})
            )
            if declencheur and restant:
                await session.execute(
                    text(f'ALTER TABLE "{table.name}" ENABLE TRIGGER {declencheur}')
                )
        if restant:
            deplacees[table.name] = restant

    # 3. Alias : nom et alias de la source deviennent des alias de la cible.
    aliases = list(cible.aliases or [])
    connus = {normaliser_libelle(a) for a in aliases}
    connus.add(normaliser_libelle(cible.nom))
    ajoutes: list[str] = []
    for candidat in [source.nom, *(source.aliases or [])]:
        cle_alias = normaliser_libelle(candidat)
        if cle_alias and cle_alias not in connus:
            aliases.append(candidat)
            ajoutes.append(candidat)
            connus.add(cle_alias)

    resultat_final = ResultatFusionFournisseur(
        source_nom=source.nom,
        cible_nom=cible.nom,
        simulation=simulation,
        deplacees=dict(deplacees),
        doublons=dict(doublons),
        reconduites=dict(reconduites),
        alias_ajoutes=tuple(ajoutes),
    )
    if simulation:
        return resultat_final

    cible.aliases = aliases or None
    await session.flush()
    await session.delete(source)
    await session.flush()
    session.add(
        Journal(
            utilisateur_id=None,
            action="fournisseur_fusionne",
            cible_table="fournisseur",
            cible_id=str(cible_id),
            avant=avant,
            apres={
                "nom": cible.nom,
                "aliases": aliases,
                "lignes_deplacees": _pour_journal(dict(deplacees)),
                "doublons_supprimes": _pour_journal(dict(doublons)),
                "lignes_reconduites": _pour_journal(dict(reconduites)),
            },
        )
    )
    await session.flush()
    return resultat_final
