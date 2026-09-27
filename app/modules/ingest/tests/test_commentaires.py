"""Tests de la table `commentaire` (migration 0012, tâche C1 de la phase 3).

Seule la contrainte en base est testée ici (contraintes de longueur du
texte, comportement des clés étrangères) : le service (`ingest/commentaires
.py`) et l'API arrivent à la tâche C2. Base de test réelle (`bl_test`),
données entièrement inventées.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import Commentaire, Document, Fournisseur, Ligne

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _creer_document(db_session: AsyncSession) -> Document:
    fournisseur = Fournisseur(nom="Fournisseur Invente Commentaires")
    db_session.add(fournisseur)
    await db_session.flush()
    document = Document(
        type="bl",
        source="telegram",
        statut="a_verifier",
        fichier_path=f"bl-invente-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id,
    )
    db_session.add(document)
    await db_session.flush()
    return document


async def _creer_ligne(db_session: AsyncSession, document: Document) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        type_ligne="article",
        code_brut="ART-INVENTE",
        article_brut="Article inventé",
        ordre=0,
    )
    db_session.add(ligne)
    await db_session.flush()
    return ligne


async def test_texte_vide_refuse_par_le_controle_de_longueur(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    db_session.add(
        Commentaire(
            document_id=document.id,
            ligne_id=ligne.id,
            ligne_libelle="ART-INVENTE — Article inventé",
            texte="",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_texte_trop_long_refuse_par_le_controle_de_longueur(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    db_session.add(
        Commentaire(
            document_id=document.id,
            ligne_id=ligne.id,
            ligne_libelle="ART-INVENTE — Article inventé",
            texte="a" * 1001,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_suppression_de_la_ligne_commentee_laisse_le_commentaire_sans_ligne(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    commentaire = Commentaire(
        document_id=document.id,
        ligne_id=ligne.id,
        ligne_libelle="ART-INVENTE — Article inventé",
        texte="Commentaire inventé.",
    )
    db_session.add(commentaire)
    await db_session.commit()

    await db_session.delete(ligne)
    await db_session.commit()

    # `expire_on_commit=False` (`creer_sessionmaker`) : le commentaire déjà
    # chargé n'est pas automatiquement rafraîchi par le commit --
    # `refresh()` va relire la ligne mise à `NULL` par la base (`ON DELETE
    # SET NULL`), pas par l'ORM (aucune relation SQLAlchemy entre les deux
    # tables).
    await db_session.refresh(commentaire)
    assert commentaire.ligne_id is None
    assert commentaire.ligne_libelle == "ART-INVENTE — Article inventé"


async def test_suppression_du_document_supprime_le_commentaire(
    db_session: AsyncSession,
) -> None:
    """`document_id` en `ON DELETE CASCADE` : un commentaire ne survit pas à
    la suppression physique de son bon (qui n'arrive jamais en usage normal,
    aucune route ne le fait -- seule cette contrainte de base est testée).
    Pas de ligne créée ici : une ligne encore présente empêcherait la
    suppression du document (`ligne.document_id` sans `ondelete`, comme
    toutes les autres clés étrangères vers `document`)."""
    document = await _creer_document(db_session)
    commentaire = Commentaire(
        document_id=document.id,
        ligne_id=None,
        ligne_libelle="ART-INVENTE — Article inventé",
        texte="Commentaire inventé.",
    )
    db_session.add(commentaire)
    await db_session.commit()

    await db_session.delete(document)
    await db_session.commit()

    resultat = await db_session.execute(
        select(Commentaire).where(Commentaire.id == commentaire.id)
    )
    assert resultat.scalar_one_or_none() is None
