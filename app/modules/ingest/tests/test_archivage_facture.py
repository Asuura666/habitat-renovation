"""Archiver une facture (lot 2, B1) : elle ne compte plus nulle part (bilan,
tuiles, livraisons, problèmes ouverts), et ses bons ne sont plus facturés.

Base de test réelle, données inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.anomalies import compter_anomalies_ouvertes
from app.modules.ingest.bilan import bilan_par_chantier, lister_livraisons
from app.modules.ingest.corrections import archiver_document
from app.modules.ingest.models import Document, Utilisateur
from app.modules.ingest.rapprochement import rapprocher_facture
from app.modules.ingest.tableau_de_bord import tableau_de_bord
from app.modules.ingest.tests.test_bilan import (
    _creer_bloc,
    _creer_chantier,
    _creer_document_bl,
    _creer_facture,
    _creer_fournisseur,
    _creer_ligne,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_AOUT = date(2026, 8, 1)


async def _admin(db_session: AsyncSession) -> Utilisateur:
    admin = Utilisateur(
        email=f"admin.{uuid.uuid4()}@example.invalid", role="admin", is_active=True
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


async def test_une_facture_archivee_ne_compte_plus_nulle_part(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bon: Document = await _creer_document_bl(
        db_session,
        chantier_id=chantier.id,
        fournisseur_id=fournisseur.id,
        date_doc=date(2026, 8, 14),
    )
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        bl_document_id=bon.id,
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("80.00")
    )
    await rapprocher_facture(db_session, facture.id)

    avant = await tableau_de_bord(db_session, mois=_AOUT)
    assert avant.totaux.facture_ht == Decimal("80.00")
    assert avant.nb_bl_factures == 1
    assert len(await bilan_par_chantier(db_session, mois=_AOUT, agence=None)) == 1
    assert (await compter_anomalies_ouvertes(db_session))[0] >= 1

    admin = await _admin(db_session)
    detail = await archiver_document(
        db_session, facture.id, commentaire="doublon", auteur_id=admin.id
    )
    assert detail.statut == "archive"

    apres = await tableau_de_bord(db_session, mois=_AOUT)
    assert apres.totaux.facture_ht == Decimal("0")
    assert apres.nb_bl_factures == 0
    assert apres.nb_problemes_ouverts == 0
    assert await bilan_par_chantier(db_session, mois=_AOUT, agence=None) == []
    assert (await compter_anomalies_ouvertes(db_session))[0] == 0
    livraisons = await lister_livraisons(
        db_session, mois=None, agence=None, chantier_id=None, fournisseur_id=None
    )
    assert [ligne for ligne in livraisons if ligne.facture_id == facture.id] == []
