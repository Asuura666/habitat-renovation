"""Invariants garantis en base (section 6 du CDC, décisions D4, D6, D7).

Toutes les valeurs utilisées ici sont inventées (aucune fixture réelle).
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import (
    Anomalie,
    Article,
    ChantierAlias,
    Document,
    Fournisseur,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _creer_fournisseur(db_session: AsyncSession) -> Fournisseur:
    fournisseur = Fournisseur(nom="Fournisseur Invente")
    db_session.add(fournisseur)
    await db_session.flush()
    return fournisseur


async def test_document_fournisseur_numero_unique_ensemble(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    db_session.add(
        Document(
            type="facture",
            source="upload",
            statut="recu",
            fichier_path="facture-invente-1.pdf",
            fournisseur_id=fournisseur.id,
            numero="F-INVENTE-0001",
        )
    )
    await db_session.commit()

    db_session.add(
        Document(
            type="facture",
            source="upload",
            statut="recu",
            fichier_path="facture-invente-2.pdf",
            fournisseur_id=fournisseur.id,
            numero="F-INVENTE-0001",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_document_numero_null_accepte(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    db_session.add(
        Document(
            type="bl",
            source="telegram",
            statut="recu",
            fichier_path="bl-invente-1.jpg",
            fournisseur_id=fournisseur.id,
            numero=None,
        )
    )
    db_session.add(
        Document(
            type="bl",
            source="telegram",
            statut="recu",
            fichier_path="bl-invente-2.jpg",
            fournisseur_id=fournisseur.id,
            numero=None,
        )
    )

    await db_session.commit()  # ne doit pas lever


async def test_chantier_alias_identiques_code_brut_null_unique(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    db_session.add(
        ChantierAlias(
            fournisseur_id=fournisseur.id,
            libelle_brut="chantier invente",
            code_brut=None,
        )
    )
    await db_session.commit()

    db_session.add(
        ChantierAlias(
            fournisseur_id=fournisseur.id,
            libelle_brut="chantier invente",
            code_brut=None,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_article_fournisseur_code_unique_ensemble(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    db_session.add(Article(fournisseur_id=fournisseur.id, code="ART-INVENTE-1"))
    await db_session.commit()

    db_session.add(Article(fournisseur_id=fournisseur.id, code="ART-INVENTE-1"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_document_type_invalide_viole_le_check(db_session: AsyncSession) -> None:
    db_session.add(
        Document(
            type="xyz", source="upload", statut="recu", fichier_path="doc-invente.pdf"
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_anomalie_detail_vide_viole_le_check(db_session: AsyncSession) -> None:
    db_session.add(Anomalie(regle="R01", gravite="haute", statut="ouverte", detail={}))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
