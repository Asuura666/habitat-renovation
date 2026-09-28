"""Tests des données de la migration 0013 (grilles de prix, phase 3, tâche
P1) : `grille_import`, `grille_prix` -- historique inaltérable et ses
contraintes -- et la cascade de `anomalie.ligne_id` (§3.3 de
`docs/superpowers/specs/2026-09-27-prix-design.md`). Base de test réelle
(`bl_test`), données entièrement inventées.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import (
    Anomalie,
    Document,
    Fournisseur,
    GrilleImport,
    GrillePrix,
    Ligne,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _creer_fournisseur(db_session: AsyncSession) -> Fournisseur:
    fournisseur = Fournisseur(nom="Fournisseur Invente Prix")
    db_session.add(fournisseur)
    await db_session.flush()
    return fournisseur


async def _creer_ligne_grille(
    db_session: AsyncSession,
    fournisseur: Fournisseur,
    *,
    cle_produit: str = "nom:produit invente",
    prix_ht: str = "10.00",
    prix_net: str = "10.00",
    source: str = "saisie",
    **kwargs: object,
) -> GrillePrix:
    ligne = GrillePrix(
        fournisseur_id=fournisseur.id,
        cle_produit=cle_produit,
        designation="Produit inventé",
        prix_ht=Decimal(prix_ht),
        prix_net=Decimal(prix_net),
        date_effet=kwargs.pop("date_effet", None) or date(2026, 1, 1),
        source=source,
        **kwargs,
    )
    db_session.add(ligne)
    await db_session.flush()
    return ligne


# ---------------------------------------------------------------------------
# Historique inaltérable : UPDATE, DELETE et TRUNCATE refusés par les
# déclencheurs posés en migration 0013 ; INSERT accepté.
# ---------------------------------------------------------------------------


async def test_insert_accepte(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    ligne = await _creer_ligne_grille(db_session, fournisseur)
    assert ligne.id is not None


async def test_update_refuse_historique_inalterable(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    ligne = await _creer_ligne_grille(db_session, fournisseur)
    await db_session.commit()

    with pytest.raises(DBAPIError, match="historique des prix inalt"):
        await db_session.execute(
            update(GrillePrix)
            .where(GrillePrix.id == ligne.id)
            .values(prix_ht=Decimal("12.00"))
        )
        await db_session.commit()
    await db_session.rollback()


async def test_delete_refuse_historique_inalterable(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    ligne = await _creer_ligne_grille(db_session, fournisseur)
    await db_session.commit()

    with pytest.raises(DBAPIError, match="historique des prix inalt"):
        await db_session.delete(ligne)
        await db_session.commit()
    await db_session.rollback()


async def test_truncate_refuse_historique_inalterable(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_ligne_grille(db_session, fournisseur)
    await db_session.commit()

    with pytest.raises(DBAPIError, match="historique des prix inalt"):
        await db_session.execute(text("TRUNCATE grille_prix"))
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# Contraintes CHECK
# ---------------------------------------------------------------------------


async def test_prix_ht_nul_ou_negatif_refuse(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    with pytest.raises(IntegrityError):
        await _creer_ligne_grille(db_session, fournisseur, prix_ht="0", prix_net="0")


async def test_remise_hors_bornes_refusee(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    with pytest.raises(IntegrityError):
        await _creer_ligne_grille(db_session, fournisseur, remise_pct=Decimal("100"))


async def test_source_inconnue_refusee(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    with pytest.raises(IntegrityError):
        await _creer_ligne_grille(db_session, fournisseur, source="inconnue")


async def test_import_sans_import_id_refuse(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    with pytest.raises(IntegrityError):
        await _creer_ligne_grille(db_session, fournisseur, source="import")


async def test_validation_sans_document_id_refusee(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    with pytest.raises(IntegrityError):
        await _creer_ligne_grille(db_session, fournisseur, source="validation")


async def test_import_avec_import_id_accepte(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    imp = GrilleImport(
        fournisseur_id=fournisseur.id,
        nom_fichier="grille-inventee.xlsx",
        empreinte="0" * 64,
        chemin=f"grilles/{fournisseur.id}/import-invente.xlsx",
        date_effet=date(2026, 1, 1),
        nb_nouveaux=1,
        nb_modifies=0,
        nb_inchanges=0,
        nb_erreurs=0,
    )
    db_session.add(imp)
    await db_session.flush()

    ligne = await _creer_ligne_grille(
        db_session, fournisseur, source="import", import_id=imp.id
    )
    assert ligne.import_id == imp.id


async def test_validation_avec_document_id_acceptee(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = Document(
        type="bl",
        source="telegram",
        statut="a_verifier",
        fichier_path=f"bl-invente-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id,
    )
    db_session.add(document)
    await db_session.flush()

    ligne = await _creer_ligne_grille(
        db_session, fournisseur, source="validation", document_id=document.id
    )
    assert ligne.document_id == document.id


# ---------------------------------------------------------------------------
# `anomalie.ligne_id` en `ON DELETE CASCADE` (§3.3)
# ---------------------------------------------------------------------------


async def test_suppression_ligne_supprime_lanomalie_portee(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = Document(
        type="bl",
        source="telegram",
        statut="a_verifier",
        fichier_path=f"bl-invente-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id,
    )
    db_session.add(document)
    await db_session.flush()

    ligne = Ligne(
        document_id=document.id,
        type_ligne="article",
        code_brut="ART-INVENTE",
        article_brut="Article inventé",
        ordre=0,
    )
    db_session.add(ligne)
    await db_session.flush()

    anomalie = Anomalie(
        regle="R19",
        gravite="haute",
        document_id=document.id,
        ligne_id=ligne.id,
        detail={"produit": "Article inventé"},
        statut="ouverte",
    )
    db_session.add(anomalie)
    await db_session.commit()
    anomalie_id = anomalie.id

    await db_session.delete(ligne)
    await db_session.commit()

    resultat = await db_session.execute(
        select(Anomalie).where(Anomalie.id == anomalie_id)
    )
    assert resultat.scalar_one_or_none() is None
