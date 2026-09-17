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
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import (
    AgenceFournisseur,
    Article,
    ChantierAlias,
    Fournisseur,
    Journal,
    Parametre,
)
from app.modules.normalize.article import PropositionArticle, completer_article
from app.modules.normalize.chantier import decomposer_chantier
from app.modules.normalize.fournisseur import AgenceRef, FournisseurRef
from app.modules.normalize.texte import normaliser_libelle


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
