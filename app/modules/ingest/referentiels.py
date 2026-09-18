"""Chargement et résolution des référentiels (fournisseur, agence, chantier,
article), et lecture des paramètres modifiables (`parametre`, L3-D4).

Sous-module de `ingest` : chaque fonction ici consulte ou complète un
référentiel à partir des modules purs de `normalize` (`app.modules
.normalize.fournisseur`/`chantier`/`article`), qui n'ont eux-mêmes aucun
accès base — la résolution proprement dite (correspondance SIRET/TVA/nom,
décomposition du libellé chantier, proposition d'article) reste dans
`normalize`, ce fichier ne fait que charger les données nécessaires et
persister leur résultat (L3-D8, L3-D6, L3-D9).

- `charger_fournisseurs`/`charger_agences` : lecture seule, alimentent
  `normalize.fournisseur.resoudre_fournisseur`/`resoudre_agence` (appelés
  par l'orchestrateur d'extraction, L3-T6/L3-T7 — jamais un fournisseur créé
  automatiquement, Q7/L3-D8).
- `resoudre_chantier` : alias chantier « demande de validation » (L3-D7) —
  un alias inconnu obtient une ligne `chantier_alias` avec `chantier_id
  NULL`, jamais un motif de mise « à vérifier » (CDC §10).
- `rattacher_article` : article créé automatiquement non validé à la
  première ligne portant un code, complété (jamais écrasé) tant qu'il n'est
  pas validé (L3-D9).
- `lire_parametre_decimal` : seuils modifiables par l'admin (CDC §5),
  valeur par défaut si absente ou non convertible (L3-D4).

`resoudre_chantier` et `rattacher_article` ne commitent jamais : c'est
l'appelant (l'orchestrateur d'extraction) qui décide du périmètre de la
transaction. `sqlalchemy.dialects.postgresql.insert(...)
.on_conflict_do_nothing(...)` est le même mécanisme que
`depot_telegram.enregistrer_update` (dédoublonnage atomique côté base).

`definir_fournisseur` alimente le référentiel fournisseur pour le compte de
la CLI `fournisseur-definir` (`app/cli.py`, L3-T5) : seul point d'écriture
du référentiel fournisseur (Q7/L3-D8, « jamais créé automatiquement »).
Contrairement à `resoudre_chantier`/`rattacher_article`, c'est une action
déclenchée par un humain (l'admin qui lance la CLI) sur une donnée métier :
journalisée (`journal`, `utilisateur_id=NULL` faute de session utilisateur
dans une CLI, action `fournisseur_defini`), même organisation que
`creer_utilisateur`/`desactiver_utilisateur` (`app/core/auth.py`) — fix
round 1 de la revue de cette tâche.

Opérations admin de l'écran « À traiter » (L3-T8b, en bas de fichier) :
`lister_chantiers`/`creer_chantier`/`lister_fournisseurs` (référentiels
consommés par le formulaire de validation d'un alias), `valider_alias`
(rattache un alias à un chantier existant et propage `chantier_id` aux
documents/blocs concernés) et `valider_article` (fige unités et ratio).
`candidats_alias` est la sélection des documents/blocs candidats à la
propagation d'un alias, partagée par `ingest.a_traiter.lister_a_traiter`
(comptage/exemple) et `valider_alias` (propagation) — décision du
contrôleur : ne jamais la dupliquer entre les deux.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import (
    AgenceFournisseur,
    Article,
    BlocFacture,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Parametre,
)
from app.modules.normalize.article import PropositionArticle, completer_article
from app.modules.normalize.chantier import decomposer_chantier
from app.modules.normalize.fournisseur import AgenceRef, FournisseurRef
from app.modules.normalize.texte import normaliser_libelle
from app.modules.normalize.unites import normaliser_unite


@dataclass(frozen=True)
class ResolutionChantier:
    """Issue de `resoudre_chantier` (L3-D7)."""

    chantier_id: uuid.UUID | None
    libelle: str | None  # clé d'alias ; `None` si le brut est vide.
    alias_id: uuid.UUID | None  # `None` si le brut est vide.
    demande_creee: bool  # `True` si l'alias vient d'être créé en attente.


async def charger_fournisseurs(session: AsyncSession) -> list[FournisseurRef]:
    """Référentiel fournisseur complet, pour `normalize.fournisseur
    .resoudre_fournisseur`."""
    resultat = await session.execute(
        select(
            Fournisseur.id,
            Fournisseur.nom,
            Fournisseur.siret,
            Fournisseur.tva,
            Fournisseur.aliases,
        )
    )
    return [
        FournisseurRef(
            id=ligne.id,
            nom=ligne.nom,
            siret=ligne.siret,
            tva=ligne.tva,
            aliases=tuple(ligne.aliases or ()),
        )
        for ligne in resultat
    ]


async def charger_agences(
    session: AsyncSession, fournisseur_id: uuid.UUID
) -> list[AgenceRef]:
    """Agences d'un fournisseur, pour `normalize.fournisseur.resoudre_agence`."""
    resultat = await session.execute(
        select(AgenceFournisseur.id, AgenceFournisseur.nom).where(
            AgenceFournisseur.fournisseur_id == fournisseur_id
        )
    )
    return [AgenceRef(id=ligne.id, nom=ligne.nom) for ligne in resultat]


async def resoudre_chantier(
    session: AsyncSession,
    fournisseur_id: uuid.UUID,
    chantier_brut: str | None,
) -> ResolutionChantier:
    """Résout (ou crée) l'alias chantier d'un libellé brut (L3-D6/L3-D7).

    `chantier_brut` vide (`decomposer_chantier` renvoie `None` : absent,
    blanc, ou réduit à un code entre parenthèses sans libellé) -> rien
    n'est créé, `ResolutionChantier` entièrement `None`/`False`.

    Sinon, tentative d'insertion `ON CONFLICT DO NOTHING` sur la clé
    d'alias `(fournisseur_id, libelle_brut, code_brut=NULL)` — atomique
    côté base, comme `depot_telegram.enregistrer_update` : deux appels
    concurrents pour le même libellé ne créent jamais deux alias. Si
    l'insertion n'a rien renvoyé (alias déjà existant, éventuellement déjà
    validé par un admin), l'alias existant est relu ; `chantier_id` est
    alors celui de cet alias (`NULL` tant qu'aucun admin ne l'a validé).
    Ne commite pas : c'est l'appelant qui décide du périmètre transactionnel.
    """
    decompose = decomposer_chantier(chantier_brut)
    if decompose is None:
        return ResolutionChantier(
            chantier_id=None, libelle=None, alias_id=None, demande_creee=False
        )

    resultat = await session.execute(
        insert(ChantierAlias)
        .values(
            fournisseur_id=fournisseur_id,
            libelle_brut=decompose.libelle,
            code_brut=None,
        )
        .on_conflict_do_nothing(
            index_elements=[
                ChantierAlias.fournisseur_id,
                ChantierAlias.libelle_brut,
                ChantierAlias.code_brut,
            ]
        )
        .returning(ChantierAlias.id, ChantierAlias.chantier_id)
    )
    ligne = resultat.first()
    if ligne is not None:
        return ResolutionChantier(
            chantier_id=ligne.chantier_id,
            libelle=decompose.libelle,
            alias_id=ligne.id,
            demande_creee=True,
        )

    ligne_existante = (
        await session.execute(
            select(ChantierAlias.id, ChantierAlias.chantier_id).where(
                ChantierAlias.fournisseur_id == fournisseur_id,
                ChantierAlias.libelle_brut == decompose.libelle,
                ChantierAlias.code_brut.is_(None),
            )
        )
    ).one()
    return ResolutionChantier(
        chantier_id=ligne_existante.chantier_id,
        libelle=decompose.libelle,
        alias_id=ligne_existante.id,
        demande_creee=False,
    )


async def rattacher_article(
    session: AsyncSession,
    fournisseur_id: uuid.UUID,
    proposition: PropositionArticle | None,
) -> uuid.UUID | None:
    """Crée ou complète un article `(fournisseur_id, code)` (L3-D9).

    `proposition` absente -> `None`. Sinon, tentative d'insertion `ON
    CONFLICT DO NOTHING` (même mécanisme que `resoudre_chantier`) :
    - aucun article existant -> créé non validé (`valide=false`) avec les
      champs de `proposition` ;
    - article existant déjà validé -> inchangé (l'admin a arbitré) ;
    - article existant non validé -> complété par `normalize.article
      .completer_article` (seuls les champs vides de l'article sont
      remplis, jamais un champ déjà renseigné écrasé).
    Renvoie l'`id` de l'article dans tous les cas. Ne commite pas.
    """
    if proposition is None:
        return None

    resultat = await session.execute(
        insert(Article)
        .values(
            fournisseur_id=fournisseur_id,
            code=proposition.code,
            libelle=proposition.libelle,
            unite_cdt=proposition.unite_cdt,
            unite_fact=proposition.unite_fact,
            ratio=proposition.ratio,
            valide=False,
        )
        .on_conflict_do_nothing(index_elements=[Article.fournisseur_id, Article.code])
        .returning(Article.id)
    )
    article_id = resultat.scalar_one_or_none()
    if article_id is not None:
        return article_id

    article = (
        await session.execute(
            select(Article).where(
                Article.fournisseur_id == fournisseur_id,
                Article.code == proposition.code,
            )
        )
    ).scalar_one()

    if article.valide:
        return article.id

    complete = completer_article(
        PropositionArticle(
            code=article.code,
            libelle=article.libelle,
            unite_cdt=article.unite_cdt,
            unite_fact=article.unite_fact,
            ratio=article.ratio,
        ),
        proposition,
    )
    # Seuls les champs vides sont écrits (`completer_article` ne remplace
    # déjà que ceux-là) : une réaffectation à l'identique des champs déjà
    # renseignés ne produit aucun UPDATE superflu (SQLAlchemy ne marque un
    # attribut modifié que si sa valeur change réellement).
    article.libelle = complete.libelle
    article.unite_cdt = complete.unite_cdt
    article.unite_fact = complete.unite_fact
    article.ratio = complete.ratio

    return article.id


async def lire_parametre_decimal(
    session: AsyncSession, cle: str, defaut: Decimal
) -> Decimal:
    """Valeur décimale d'un paramètre (`parametre.valeur`), ou `defaut` si
    la clé est absente ou si sa valeur n'est pas convertible (L3-D4)."""
    valeur_brute = (
        await session.execute(select(Parametre.valeur).where(Parametre.cle == cle))
    ).scalar_one_or_none()
    if valeur_brute is None:
        return defaut
    try:
        return Decimal(valeur_brute)
    except InvalidOperation:
        return defaut


@dataclass(frozen=True)
class ResultatDefinitionFournisseur:
    """Issue de `definir_fournisseur`, pour le message de la CLI
    `fournisseur-definir`."""

    cree: bool
    nombre_alias: int
    nombre_agences: int


async def definir_fournisseur(
    session: AsyncSession,
    *,
    nom: str,
    siret: str | None,
    tva: str | None,
    alias: Sequence[str],
    agence: Sequence[str],
) -> ResultatDefinitionFournisseur:
    """CLI `fournisseur-definir` (L3-T5) : crée le fournisseur `nom` (comparé
    sans casse) s'il n'existe pas, sinon le met à jour — seul point
    d'écriture du référentiel fournisseur (Q7/L3-D8, jamais créé
    automatiquement par l'extraction).

    SIRET et TVA sont remplacés s'ils sont fournis (`siret`/`tva` non
    `None`), jamais effacés sinon. Alias et agences sont ajoutés sans
    doublon (comparaison `normalize.texte.normaliser_libelle`, alignée sur
    la comparaison par nom de `resoudre_fournisseur`/`resoudre_agence`) ;
    les alias existants sont conservés tels quels (jamais renormalisés).

    Journalise la mutation (« toute action qui modifie une donnée métier
    est journalisée », contraintes globales du lot) : `action
    ="fournisseur_defini"`, `utilisateur_id=None` (résolution/écriture
    automatique, comme `depot_telegram`, jamais par un admin authentifié
    ici — la CLI n'a pas de session utilisateur), `avant=None` à la
    création sinon l'état précédent (siret/tva/aliases), `apres` l'état
    final (nom/siret/tva/aliases) et les seules agences ajoutées par cet
    appel (pas la liste complète, déjà couverte par `avant`/`apres.aliases`
    pour les alias). Même organisation que `creer_utilisateur`
    (`app/core/auth.py`) : le journal est ajouté dans la même transaction,
    avant le commit — qui reste à la charge de l'appelant (la CLI).
    """
    fournisseur = (
        await session.execute(
            select(Fournisseur).where(func.lower(Fournisseur.nom) == nom.lower())
        )
    ).scalar_one_or_none()

    cree = fournisseur is None
    avant: dict[str, Any] | None = None
    if fournisseur is None:
        fournisseur = Fournisseur(nom=nom, siret=siret, tva=tva, aliases=[])
        session.add(fournisseur)
    else:
        avant = {
            "siret": fournisseur.siret,
            "tva": fournisseur.tva,
            "aliases": list(fournisseur.aliases) if fournisseur.aliases else [],
        }
        if siret is not None:
            fournisseur.siret = siret
        if tva is not None:
            fournisseur.tva = tva

    aliases_actuels = list(fournisseur.aliases or [])
    normalises_actuels = {normaliser_libelle(a) for a in aliases_actuels}
    for candidat in alias:
        normalise = normaliser_libelle(candidat)
        if normalise not in normalises_actuels:
            aliases_actuels.append(candidat)
            normalises_actuels.add(normalise)
    fournisseur.aliases = aliases_actuels or None

    await session.flush()  # peuple `fournisseur.id` s'il vient d'être créé.

    agences_actuelles = (
        (
            await session.execute(
                select(AgenceFournisseur.nom).where(
                    AgenceFournisseur.fournisseur_id == fournisseur.id
                )
            )
        )
        .scalars()
        .all()
    )
    normalises_agences = {normaliser_libelle(a) for a in agences_actuelles}
    agences_ajoutees: list[str] = []
    for nom_agence in agence:
        normalise = normaliser_libelle(nom_agence)
        if normalise not in normalises_agences:
            session.add(
                AgenceFournisseur(fournisseur_id=fournisseur.id, nom=nom_agence)
            )
            normalises_agences.add(normalise)
            agences_ajoutees.append(nom_agence)
    await session.flush()

    nombre_agences = (
        await session.execute(
            select(func.count())
            .select_from(AgenceFournisseur)
            .where(AgenceFournisseur.fournisseur_id == fournisseur.id)
        )
    ).scalar_one()

    session.add(
        Journal(
            utilisateur_id=None,
            action="fournisseur_defini",
            cible_table="fournisseur",
            cible_id=str(fournisseur.id),
            avant=avant,
            apres={
                "nom": fournisseur.nom,
                "siret": fournisseur.siret,
                "tva": fournisseur.tva,
                "aliases": aliases_actuels,
                "agences_ajoutees": agences_ajoutees,
            },
        )
    )

    return ResultatDefinitionFournisseur(
        cree=cree,
        nombre_alias=len(aliases_actuels),
        nombre_agences=nombre_agences,
    )


# ---------------------------------------------------------------------------
# Opérations admin de l'écran « À traiter » (L3-T8b)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChantierResume:
    """Une ligne de `GET /api/chantiers`."""

    id: uuid.UUID
    nom_canonique: str
    agence: str | None
    actif: bool


@dataclass(frozen=True)
class AgenceResume:
    """Une agence (point de vente) d'un fournisseur, dans `GET /api
    /fournisseurs` (Ruling L5-R9, tour de correction 1 de L5-T8) : le point
    de vente est ce qui distingue deux dépôts d'un même fournisseur, la
    table `agence_fournisseur` existe depuis le lot 1 mais n'était encore
    lue par aucune route de lecture. `adresse` est incluse car elle vient de
    la même ligne, sans coût supplémentaire (décision du contrôleur)."""

    id: uuid.UUID
    nom: str
    adresse: str | None


@dataclass(frozen=True)
class FournisseurResume:
    """Une ligne de `GET /api/fournisseurs`, agences comprises (Ruling
    L5-R9)."""

    id: uuid.UUID
    nom: str
    agences: list[AgenceResume]


class ChantierEnDouble(Exception):
    """Un chantier existe déjà avec ce nom (`normaliser_libelle` identique,
    décision du contrôleur : actif ou non)."""

    def __init__(self, original_id: uuid.UUID) -> None:
        super().__init__("chantier déjà existant")
        self.original_id = original_id


class AliasIntrouvable(Exception):
    """Aucun `chantier_alias` avec cet identifiant."""


class AliasDejaValide(Exception):
    """L'alias porte déjà un `chantier_id` (déjà rattaché)."""


class ChantierIntrouvable(Exception):
    """Aucun `chantier` avec cet identifiant."""


class ArticleIntrouvable(Exception):
    """Aucun `article` avec cet identifiant."""


async def lister_chantiers(session: AsyncSession) -> list[ChantierResume]:
    """Référentiel chantier complet, actifs d'abord puis par nom (décision du
    contrôleur) — pour le formulaire de validation d'un alias."""
    resultat = await session.execute(
        select(Chantier).order_by(Chantier.actif.desc(), Chantier.nom_canonique.asc())
    )
    return [
        ChantierResume(
            id=chantier.id,
            nom_canonique=chantier.nom_canonique,
            agence=chantier.agence,
            actif=chantier.actif,
        )
        for chantier in resultat.scalars().all()
    ]


async def creer_chantier(
    session: AsyncSession,
    *,
    nom_canonique: str,
    agence: str | None,
    auteur_id: uuid.UUID,
) -> ChantierResume:
    """Crée un chantier (décision du contrôleur) : `nom_canonique` débarrassé
    des espaces de bord, `agence` vide -> `None`, `actif = true`. Refuse un
    nom déjà porté par un chantier existant (actif ou non) une fois passé
    par `normaliser_libelle` (`ChantierEnDouble`, `original_id` du chantier
    déjà existant). Journalise `chantier_cree`.

    Le référentiel chantier reste de volume faible (CDC §9) : la comparaison
    de doublon charge tous les chantiers existants et compare en Python,
    même principe que `definir_fournisseur` pour ses alias/agences — une
    requête SQL ne saurait pas appliquer `normaliser_libelle` (accents,
    casse, ponctuation) sans un index dédié, hors périmètre de cette tâche.
    """
    nom = nom_canonique.strip()
    normalise_cible = normaliser_libelle(nom)

    chantiers_existants = (await session.execute(select(Chantier))).scalars().all()
    for existant in chantiers_existants:
        if normaliser_libelle(existant.nom_canonique) == normalise_cible:
            raise ChantierEnDouble(existant.id)

    agence_normalisee = agence.strip() if agence is not None else None
    agence_normalisee = agence_normalisee or None

    chantier = Chantier(nom_canonique=nom, agence=agence_normalisee, actif=True)
    session.add(chantier)
    await session.flush()

    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="chantier_cree",
            cible_table="chantier",
            cible_id=str(chantier.id),
            avant=None,
            apres={
                "nom_canonique": nom,
                "agence": agence_normalisee,
                "actif": True,
            },
        )
    )
    await session.commit()
    await session.refresh(chantier)

    return ChantierResume(
        id=chantier.id,
        nom_canonique=chantier.nom_canonique,
        agence=chantier.agence,
        actif=chantier.actif,
    )


async def lister_fournisseurs(session: AsyncSession) -> list[FournisseurResume]:
    """Référentiel fournisseur complet (nom et agences), trié par nom — pour
    le formulaire de validation d'un alias et l'écran « Chantiers &
    fournisseurs » (Ruling L5-R9, tour de correction 1 de L5-T8).

    Une requête pour les fournisseurs, une pour toutes leurs agences
    (jamais une requête par fournisseur, décision du contrôleur) : les
    agences sont regroupées en mémoire par `fournisseur_id`, triées par
    nom. Un fournisseur sans agence reçoit une liste vide, jamais `None`
    (`defaultdict` : accéder à une clé absente rend `[]`, jamais une
    exception)."""
    fournisseurs = (
        await session.execute(
            select(Fournisseur.id, Fournisseur.nom).order_by(Fournisseur.nom.asc())
        )
    ).all()

    agences_par_fournisseur: defaultdict[uuid.UUID, list[AgenceResume]] = defaultdict(
        list
    )
    resultat_agences = await session.execute(
        select(
            AgenceFournisseur.fournisseur_id,
            AgenceFournisseur.id,
            AgenceFournisseur.nom,
            AgenceFournisseur.adresse,
        ).order_by(AgenceFournisseur.nom.asc())
    )
    for fournisseur_id, agence_id, nom_agence, adresse in resultat_agences:
        agences_par_fournisseur[fournisseur_id].append(
            AgenceResume(id=agence_id, nom=nom_agence, adresse=adresse)
        )

    return [
        FournisseurResume(id=id_, nom=nom, agences=agences_par_fournisseur[id_])
        for id_, nom in fournisseurs
    ]


async def _documents_candidats_alias(
    session: AsyncSession, fournisseur_id: uuid.UUID
) -> Sequence[Document]:
    """Documents de `fournisseur_id` encore sans chantier résolu (candidats à
    la propagation d'un alias) : `chantier_id IS NULL`, statut différent de
    `archive` (un document archivé ne compte plus), `chantier_brut` renseigné
    (sinon `decomposer_chantier` ne produit aucun libellé à comparer)."""
    return (
        (
            await session.execute(
                select(Document).where(
                    Document.fournisseur_id == fournisseur_id,
                    Document.chantier_id.is_(None),
                    Document.statut != "archive",
                    Document.chantier_brut.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )


async def _blocs_candidats_alias(
    session: AsyncSession, fournisseur_id: uuid.UUID
) -> Sequence[BlocFacture]:
    """Blocs des factures de `fournisseur_id` encore sans chantier résolu —
    même principe que `_documents_candidats_alias`, via une jointure sur la
    facture (`bloc_facture` ne porte pas son propre `fournisseur_id`)."""
    return (
        (
            await session.execute(
                select(BlocFacture)
                .join(Document, Document.id == BlocFacture.facture_id)
                .where(
                    Document.fournisseur_id == fournisseur_id,
                    BlocFacture.chantier_id.is_(None),
                    BlocFacture.chantier_brut.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )


def _libelle_correspond(chantier_brut: str | None, libelle: str) -> bool:
    decompose = decomposer_chantier(chantier_brut)
    return decompose is not None and decompose.libelle == libelle


async def candidats_alias(
    session: AsyncSession, fournisseur_id: uuid.UUID, libelle: str
) -> tuple[list[Document], list[BlocFacture]]:
    """Documents et blocs de facture de `fournisseur_id`, sans chantier
    résolu, dont le libellé décomposé de `chantier_brut` égale `libelle`
    (décision du contrôleur) : sélection **partagée** par `ingest.a_traiter
    .lister_a_traiter` (comptage/exemple de l'alias en attente) et
    `valider_alias` ci-dessous (propagation) — jamais dupliquée entre les
    deux."""
    documents = await _documents_candidats_alias(session, fournisseur_id)
    blocs = await _blocs_candidats_alias(session, fournisseur_id)
    return (
        [d for d in documents if _libelle_correspond(d.chantier_brut, libelle)],
        [b for b in blocs if _libelle_correspond(b.chantier_brut, libelle)],
    )


async def valider_alias(
    session: AsyncSession,
    alias_id: uuid.UUID,
    *,
    chantier_id: uuid.UUID,
    auteur_id: uuid.UUID,
) -> int:
    """Rattache un alias en attente à un chantier existant (L3-D7) et propage
    `chantier_id` (`candidats_alias`, même sélection que le comptage de
    l'écran « À traiter ») aux documents et blocs de facture concernés.

    Lève `AliasIntrouvable`, `AliasDejaValide` (un alias déjà rattaché ne se
    revalide pas) ou `ChantierIntrouvable`. Journalise `alias_valide` avec
    `apres = {"libelle", "chantier_id", "methode": "validation_humaine",
    "nb_mis_a_jour"}` (décision du contrôleur)."""
    alias = await session.get(ChantierAlias, alias_id)
    if alias is None:
        raise AliasIntrouvable(str(alias_id))
    if alias.chantier_id is not None:
        raise AliasDejaValide(str(alias_id))
    if await session.get(Chantier, chantier_id) is None:
        raise ChantierIntrouvable(str(chantier_id))

    documents, blocs = await candidats_alias(
        session, alias.fournisseur_id, alias.libelle_brut
    )
    for document in documents:
        document.chantier_id = chantier_id
    for bloc in blocs:
        bloc.chantier_id = chantier_id
    nb_mis_a_jour = len(documents) + len(blocs)

    alias.chantier_id = chantier_id
    alias.valide_par = auteur_id
    alias.valide_le = datetime.now(UTC)

    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="alias_valide",
            cible_table="chantier_alias",
            cible_id=str(alias_id),
            avant=None,
            apres={
                "libelle": alias.libelle_brut,
                "chantier_id": str(chantier_id),
                "methode": "validation_humaine",
                "nb_mis_a_jour": nb_mis_a_jour,
            },
        )
    )
    await session.commit()
    return nb_mis_a_jour


def _unite_normalisee_saisie(valeur: str | None) -> str | None:
    """`normaliser_unite(valeur).code` si reconnue, sinon la chaîne saisie
    débarrassée des espaces de bord ; chaîne vide (ou `None`) -> `None`
    (décision du contrôleur)."""
    if valeur is None:
        return None
    texte = valeur.strip()
    if not texte:
        return None
    unite = normaliser_unite(texte)
    return unite.code if unite is not None else texte


async def valider_article(
    session: AsyncSession,
    article_id: uuid.UUID,
    *,
    unite_cdt: str | None,
    unite_fact: str | None,
    ratio: Decimal | None,
    auteur_id: uuid.UUID,
) -> None:
    """Valide un article (fige unités et ratio, `valide = true`). `ratio`
    doit être strictement positif s'il est fourni — déjà garanti côté route
    par `ValidationArticleRequete` (`Field(gt=0)`), revérifié ici (décision
    du contrôleur, défense en profondeur pour tout appelant direct).

    Une revalidation d'un article déjà validé est autorisée (l'admin corrige
    un ratio) : toujours journalisée (`article_valide`, avant/après)."""
    if ratio is not None and ratio <= 0:
        raise ValueError("ratio invalide : doit être strictement positif")

    article = await session.get(Article, article_id)
    if article is None:
        raise ArticleIntrouvable(str(article_id))

    avant = {
        "unite_cdt": article.unite_cdt,
        "unite_fact": article.unite_fact,
        "ratio": str(article.ratio) if article.ratio is not None else None,
        "valide": article.valide,
    }

    article.unite_cdt = _unite_normalisee_saisie(unite_cdt)
    article.unite_fact = _unite_normalisee_saisie(unite_fact)
    article.ratio = ratio
    article.valide = True

    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="article_valide",
            cible_table="article",
            cible_id=str(article_id),
            avant=avant,
            apres={
                "unite_cdt": article.unite_cdt,
                "unite_fact": article.unite_fact,
                "ratio": str(article.ratio) if article.ratio is not None else None,
                "valide": True,
            },
        )
    )
    await session.commit()
