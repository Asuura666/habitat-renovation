"""B-06 avec base : même code sur plusieurs lignes d'un BL (BL 10 + 10,
facture 20) -- rapprochement réel, liens en base, bilan détaillé et écran de
comparaison du BL. Données inventées."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.bilan import bilan_detail
from app.modules.ingest.comparaison_bl import comparer_bl
from app.modules.ingest.models import Document, Ligne, RapprochementLigne
from app.modules.ingest.rapprochement import rapprocher_facture
from app.modules.ingest.tests.test_rapprochement import (
    _anomalies_de,
    _creer_article,
    _creer_bl,
    _creer_bloc,
    _creer_facture,
    _creer_fournisseur,
    _creer_ligne,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _scenario(
    db_session: AsyncSession, qte_facture: str
) -> tuple[Document, Document, Ligne, list[Ligne]]:
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(
        db_session,
        fournisseur=fournisseur,
        code="X1",
        unite_cdt="kg",
        unite_fact="kg",
        ratio=Decimal("1"),
    )
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0001")
    ligne_facture = await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        code_brut="X1",
        article=article,
        qte_totale=Decimal(qte_facture),
        unite_brut="kg",
        pu_ht=Decimal("2.00"),
        montant_ht=Decimal(qte_facture) * 2,
    )
    bl = await _creer_bl(db_session, fournisseur=fournisseur, numero="L0001")
    lignes_bl = [
        await _creer_ligne(
            db_session,
            document=bl,
            code_brut="X1",
            article=article,
            ordre=ordre,
            qte_totale=Decimal("10"),
            unite_brut="kg",
        )
        for ordre in (0, 1)
    ]
    await rapprocher_facture(db_session, facture.id)
    return facture, bl, ligne_facture, lignes_bl


async def test_bl_10_plus_10_facture_20_aucune_anomalie_liens_et_vues(
    db_session: AsyncSession,
) -> None:
    facture, bl, ligne_facture, lignes_bl = await _scenario(db_session, "20")

    assert [a.regle for a in await _anomalies_de(db_session, facture)] == []

    liens = (
        (
            await db_session.execute(
                select(RapprochementLigne).where(
                    RapprochementLigne.ligne_facture_id == ligne_facture.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert {lien.ligne_bl_id for lien in liens} == {ligne.id for ligne in lignes_bl}
    assert all(lien.ligne_facture_id == ligne_facture.id for lien in liens)

    # Bilan détaillé : une seule ligne pour la ligne facturée, montant unique,
    # quantité BL = somme des deux lignes.
    detail = [
        ligne
        for ligne in await bilan_detail(db_session, mois=None, agence=None)
        if ligne.facture_id == facture.id
    ]
    assert len(detail) == 1
    assert detail[0].montant_ht == Decimal("40")
    assert detail[0].qte_bl_appariee == Decimal("20")

    # Comparaison du BL : aucune ligne « non facturée », montant montré une fois.
    comparaison = await comparer_bl(db_session, bl.id)
    assert [ligne.controle for ligne in comparaison.lignes] == ["conforme", "conforme"]
    assert sum(
        (ligne.montant_facture or Decimal("0")) for ligne in comparaison.lignes
    ) == Decimal("40")
    assert comparaison.nb_problemes == 0

    # Rejeu idempotent : pas de liens en double.
    await rapprocher_facture(db_session, facture.id)
    nb = (
        await db_session.execute(
            select(RapprochementLigne).where(
                RapprochementLigne.ligne_facture_id.in_(
                    select(Ligne.id).where(Ligne.document_id == facture.id)
                )
            )
        )
    ).all()
    assert len(nb) == 2


async def test_bl_10_plus_10_facture_25_une_r03_avec_detail(
    db_session: AsyncSession,
) -> None:
    facture, _bl, ligne_facture, _lignes_bl = await _scenario(db_session, "25")

    anomalies = await _anomalies_de(db_session, facture)
    assert [a.regle for a in anomalies] == ["R03"]
    detail = anomalies[0].detail
    assert detail["qte_facture"] == "25"
    assert detail["qte_bl"] == "20"
    assert detail["ecart"] == "5"
    assert detail["lignes_facture"] == "25"
    assert detail["lignes_bl"] == "10 + 10"
    assert anomalies[0].ligne_id == ligne_facture.id
