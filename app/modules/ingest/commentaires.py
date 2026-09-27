"""Commentaires sur les lignes d'un bon (tâche C2 de la phase 3, §4 de
`docs/superpowers/specs/2026-09-27-commentaires-lignes-design.md`, décisions
d'Ilane du 27/09/2026, §6.3-8) : tout compte connecté qui voit la page du
bon (BL ou enlèvement, jamais une facture) peut ajouter un commentaire sur
une de ses lignes. Un commentaire n'est ni modifiable ni supprimable — pour
se corriger, on en ajoute un autre.

Visibilité : exactement celle de `detail_document`
(`ingest.corrections.document_visible`, réutilisée telle quelle, jamais
recopiée) — un agent ne voit et ne commente que les bons qu'il a déposés,
sinon `DocumentIntrouvable`/`LigneIntrouvable` (404), jamais un 403.

`ligne_libelle` est figé au moment de l'ajout (`Commentaire.ligne_libelle`,
migration 0012) : les lignes d'un bon sont supprimées puis recréées à
chaque lecture ou relance de la lecture
(`extraction_bl.enregistrer_extraction_bl`), et une correction manuelle peut
en supprimer (`corrections.corriger_lignes`) — la clé étrangère
`ligne_id` passe alors à `NULL` (`ON DELETE SET NULL`), et seul ce libellé
figé permet encore d'afficher le commentaire (`CommentairesBon.sans_ligne`).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.corrections import document_visible
from app.modules.ingest.lecture import DocumentIntrouvable
from app.modules.ingest.models import Commentaire, Journal, Ligne, Utilisateur

LONGUEUR_COMMENTAIRE_MAX = 1000


class LigneIntrouvable(Exception):
    """Ligne absente, ou ligne d'un document invisible pour l'appelant (une
    facture, ou le bon d'un autre agent) — toujours 404, même principe que
    `DocumentIntrouvable` (décision du contrôleur)."""


class CommentaireInvalide(Exception):
    """Texte vide une fois nettoyé (`str.strip()`), ou dépassant
    `LONGUEUR_COMMENTAIRE_MAX` caractères — 422."""


# --------------------------------------------------------------------------
# Dataclasses exposées
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CommentaireLu:
    """Un commentaire tel qu'exposé par l'API : sous sa ligne
    (`LigneCommentee.commentaires`), sans ligne (`CommentairesBon
    .sans_ligne`), ou seul (retour d'`ajouter_commentaire`).
    `ligne_libelle` est le libellé figé au moment de l'ajout — utile
    seulement quand la ligne a disparu, ignoré par le front sous une ligne
    encore présente (décision du contrôleur, jamais deux dataclasses pour un
    même commentaire)."""

    id: uuid.UUID
    ligne_libelle: str
    auteur: str | None
    texte: str
    cree_le: datetime


@dataclass(frozen=True)
class LigneCommentee:
    """Une ligne du bon, avec ses commentaires du plus ancien au plus
    récent."""

    ligne_id: uuid.UUID
    code: str | None
    article: str | None
    quantite: Decimal | None
    unite: str | None
    commentaires: list[CommentaireLu]


@dataclass(frozen=True)
class CommentairesBon:
    """Réponse de `commentaires_du_bon` (`GET /api/commentaires/documents/
    {id}`)."""

    nb_commentaires: int
    lignes: list[LigneCommentee]
    sans_ligne: list[CommentaireLu]


# --------------------------------------------------------------------------
# Libellé figé d'une ligne (§3 de la spec)
# --------------------------------------------------------------------------


def _libelle_ligne(ligne: Ligne) -> str:
    """« code — désignation », ou la partie présente seule, ou « Ligne
    <ordre + 1> » si les deux manquent (décision du contrôleur, §4 de la
    spec) — `ordre` est 0-indexé en base, jamais affiché tel quel."""
    code = (ligne.code_brut or "").strip() or None
    article = (ligne.article_brut or "").strip() or None
    if code and article:
        return f"{code} — {article}"
    if code:
        return code
    if article:
        return article
    return f"Ligne {ligne.ordre + 1}"


async def _nom_auteur(session: AsyncSession, auteur_id: uuid.UUID | None) -> str | None:
    """`Utilisateur.nom`, sinon `email` (décision du contrôleur) — même
    principe que `ingest.corrections._nom_utilisateur`, non réutilisable
    telle quelle (fonction privée d'un autre sous-module)."""
    if auteur_id is None:
        return None
    return (
        await session.execute(
            select(func.coalesce(Utilisateur.nom, Utilisateur.email)).where(
                Utilisateur.id == auteur_id
            )
        )
    ).scalar_one_or_none()


# --------------------------------------------------------------------------
# commentaires_du_bon
# --------------------------------------------------------------------------


async def commentaires_du_bon(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    utilisateur_id: uuid.UUID,
    role: str,
) -> CommentairesBon:
    """Commentaires d'un BL/enlèvement, groupés par ligne (dans l'ordre du
    bon) puis les commentaires sans ligne (leur ligne a disparu) — deux
    requêtes au total (les lignes, puis tous les commentaires avec leur
    auteur), jamais une par ligne ni par commentaire."""
    await document_visible(
        session, document_id, utilisateur_id=utilisateur_id, role=role
    )

    lignes_db = (
        (
            await session.execute(
                select(Ligne)
                .where(Ligne.document_id == document_id)
                .order_by(Ligne.ordre)
            )
        )
        .scalars()
        .all()
    )

    commentaires_db = (
        await session.execute(
            select(Commentaire, func.coalesce(Utilisateur.nom, Utilisateur.email))
            .outerjoin(Utilisateur, Utilisateur.id == Commentaire.auteur_id)
            .where(Commentaire.document_id == document_id)
            .order_by(Commentaire.created_at.asc())
        )
    ).all()

    commentaires_par_ligne: dict[uuid.UUID, list[CommentaireLu]] = defaultdict(list)
    sans_ligne: list[CommentaireLu] = []
    for commentaire, nom_auteur in commentaires_db:
        commentaire_lu = CommentaireLu(
            id=commentaire.id,
            ligne_libelle=commentaire.ligne_libelle,
            auteur=nom_auteur,
            texte=commentaire.texte,
            cree_le=commentaire.created_at,
        )
        if commentaire.ligne_id is not None:
            commentaires_par_ligne[commentaire.ligne_id].append(commentaire_lu)
        else:
            sans_ligne.append(commentaire_lu)

    lignes = [
        LigneCommentee(
            ligne_id=ligne.id,
            code=ligne.code_brut,
            article=ligne.article_brut,
            quantite=ligne.qte_totale,
            unite=ligne.unite_brut,
            commentaires=commentaires_par_ligne.get(ligne.id, []),
        )
        for ligne in lignes_db
    ]

    return CommentairesBon(
        nb_commentaires=len(commentaires_db), lignes=lignes, sans_ligne=sans_ligne
    )


# --------------------------------------------------------------------------
# ajouter_commentaire
# --------------------------------------------------------------------------


async def ajouter_commentaire(
    session: AsyncSession,
    ligne_id: uuid.UUID,
    texte: str,
    *,
    utilisateur_id: uuid.UUID,
    role: str,
) -> CommentaireLu:
    """Ajoute un commentaire sur une ligne d'un BL/enlèvement, et une entrée
    de journal (`commentaire_ajoute`), dans la même transaction (commit à la
    fin)."""
    ligne = await session.get(Ligne, ligne_id)
    if ligne is None:
        raise LigneIntrouvable(str(ligne_id))
    try:
        document = await document_visible(
            session, ligne.document_id, utilisateur_id=utilisateur_id, role=role
        )
    except DocumentIntrouvable as exc:
        # Même 404 qu'une ligne absente (décision du contrôleur, §4 de la
        # spec) : jamais distinguer une facture ou le bon d'un autre agent
        # d'une ligne qui n'existe pas.
        raise LigneIntrouvable(str(ligne_id)) from exc

    texte_nettoye = texte.strip()
    if not texte_nettoye or len(texte_nettoye) > LONGUEUR_COMMENTAIRE_MAX:
        raise CommentaireInvalide(str(ligne_id))

    libelle = _libelle_ligne(ligne)
    commentaire = Commentaire(
        document_id=ligne.document_id,
        ligne_id=ligne.id,
        ligne_libelle=libelle,
        auteur_id=utilisateur_id,
        texte=texte_nettoye,
    )
    session.add(commentaire)
    await session.flush()

    session.add(
        Journal(
            utilisateur_id=utilisateur_id,
            action="commentaire_ajoute",
            cible_table="commentaire",
            cible_id=str(commentaire.id),
            avant=None,
            apres={
                "document_id": str(document.id),
                "numero": document.numero,
                "ligne": libelle,
                "texte": texte_nettoye,
            },
        )
    )
    await session.commit()
    await session.refresh(commentaire)

    nom_auteur = await _nom_auteur(session, utilisateur_id)
    return CommentaireLu(
        id=commentaire.id,
        ligne_libelle=commentaire.ligne_libelle,
        auteur=nom_auteur,
        texte=commentaire.texte,
        cree_le=commentaire.created_at,
    )
