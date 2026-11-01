"""Lot 2, B3 (31/10/2026) : les bons non encore facturés figurent dans la
liste des livraisons, avec le champ `facture`.

« même s'il y a un problème je dois quand même voir le BL dans le bon
endroit » ; « on peut le mettre sur la carte Livraison et rajouter une
colonne si c'est facturé ou pas ». Base de test réelle, données inventées."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.bilan import LigneLivraison, lister_livraisons
from app.modules.ingest.corrections import archiver_document
from app.modules.ingest.models import Utilisateur
from app.modules.ingest.tests.test_bilan import (
    _creer_anomalie,
    _creer_bloc,
    _creer_chantier,
    _creer_document_bl,
    _creer_facture,
    _creer_fournisseur,
    _creer_ligne,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_AOUT = date(2026, 8, 1)


async def _toutes(
    db_session: AsyncSession,
    *,
    mois: date | None = None,
    agence: str | None = None,
    chantier_id: uuid.UUID | None = None,
    fournisseur_id: uuid.UUID | None = None,
) -> list[LigneLivraison]:
    return await lister_livraisons(
        db_session,
        mois=mois,
        agence=agence,
        chantier_id=chantier_id,
        fournisseur_id=fournisseur_id,
    )


async def test_un_bon_non_facture_apparait_avec_facture_faux(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Saint Georges")
    fournisseur = await _creer_fournisseur(db_session)
    bon = await _creer_document_bl(
        db_session,
        chantier_id=chantier.id,
        fournisseur_id=fournisseur.id,
        date_doc=date(2026, 8, 12),
    )

    lignes = await _toutes(db_session)

    assert len(lignes) == 1
    ligne = lignes[0]
    assert ligne.facture is False
    assert ligne.bl_document_id == bon.id
    assert ligne.bloc_id is None
    assert ligne.facture_id is None
    assert ligne.date_bl == date(2026, 8, 12)
    assert ligne.chantier == "Saint Georges"
    assert ligne.fournisseur == fournisseur.nom
    assert ligne.categorie == "recu"
    assert ligne.montants.facture_ht == Decimal("0")
    assert ligne.montants.nb_anomalies_ouvertes == 0


async def test_etats_d_un_bon_non_facture(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    a_verifier = await _creer_document_bl(
        db_session, fournisseur_id=fournisseur.id, statut="a_verifier"
    )
    avec_probleme = await _creer_document_bl(db_session, fournisseur_id=fournisseur.id)
    await _creer_anomalie(db_session, regle="R10", document_id=avec_probleme.id)
    # Un problème déjà réglé ne compte pas.
    regle = await _creer_document_bl(db_session, fournisseur_id=fournisseur.id)
    await _creer_anomalie(
        db_session, regle="R10", document_id=regle.id, statut="traitee"
    )

    par_bon = {ligne.bl_document_id: ligne for ligne in await _toutes(db_session)}

    assert par_bon[a_verifier.id].categorie == "a_verifier"
    assert par_bon[avec_probleme.id].categorie == "probleme_ouvert"
    assert par_bon[avec_probleme.id].montants.nb_anomalies_ouvertes == 1
    assert par_bon[regle.id].categorie == "recu"


async def test_un_bon_retrouve_sur_une_facture_n_apparait_qu_une_fois(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bon = await _creer_document_bl(db_session, fournisseur_id=fournisseur.id)
    bloc = await _creer_bloc(db_session, facture=facture, bl_document_id=bon.id)
    await _creer_ligne(db_session, document=facture, bloc=bloc)

    lignes = await _toutes(db_session)

    assert len(lignes) == 1
    assert lignes[0].facture is True
    assert lignes[0].bloc_id == bloc.id
    assert lignes[0].bl_document_id == bon.id


async def test_un_bon_archive_n_apparait_pas(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_document_bl(
        db_session, fournisseur_id=fournisseur.id, statut="archive"
    )

    assert await _toutes(db_session) == []


async def test_facture_archivee_ses_bons_redeviennent_non_factures(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bon = await _creer_document_bl(db_session, fournisseur_id=fournisseur.id)
    bloc = await _creer_bloc(db_session, facture=facture, bl_document_id=bon.id)
    await _creer_ligne(db_session, document=facture, bloc=bloc)
    admin = Utilisateur(
        email=f"admin.{uuid.uuid4()}@example.invalid", role="admin", is_active=True
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)

    await archiver_document(
        db_session, facture.id, commentaire="doublon", auteur_id=admin.id
    )

    lignes = await _toutes(db_session)
    assert [(ligne.facture, ligne.bl_document_id) for ligne in lignes] == [
        (False, bon.id)
    ]


async def test_filtres_mois_chantier_fournisseur_agence_sur_les_bons(
    db_session: AsyncSession,
) -> None:
    nord = await _creer_chantier(db_session, nom="Nord", agence="Agence Nord")
    sud = await _creer_chantier(db_session, nom="Sud", agence="Agence Sud")
    f1 = await _creer_fournisseur(db_session, nom="F1")
    f2 = await _creer_fournisseur(db_session, nom="F2")
    aout_nord = await _creer_document_bl(
        db_session,
        chantier_id=nord.id,
        fournisseur_id=f1.id,
        date_doc=date(2026, 8, 3),
    )
    await _creer_document_bl(
        db_session,
        chantier_id=sud.id,
        fournisseur_id=f2.id,
        date_doc=date(2026, 9, 3),
    )

    def ids(lignes: list[LigneLivraison]) -> list[uuid.UUID | None]:
        return [ligne.bl_document_id for ligne in lignes]

    assert ids(await _toutes(db_session, mois=_AOUT)) == [aout_nord.id]
    assert ids(await _toutes(db_session, chantier_id=nord.id)) == [aout_nord.id]
    assert ids(await _toutes(db_session, fournisseur_id=f1.id)) == [aout_nord.id]
    assert ids(await _toutes(db_session, agence="Agence Nord")) == [aout_nord.id]
    assert await _toutes(db_session, mois=date(2026, 7, 1)) == []


async def test_bon_sans_date_range_selon_la_date_de_depot(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    bon = await _creer_document_bl(
        db_session, fournisseur_id=fournisseur.id, date_doc=None
    )
    # `created_at` est posé par la base : on le lit pour le comparer.
    attendu = bon.created_at.astimezone(UTC).date()

    lignes = await _toutes(db_session)

    assert len(lignes) == 1
    assert lignes[0].date_bl is not None
    assert abs((lignes[0].date_bl - attendu).days) <= 1
    assert isinstance(bon.created_at, datetime)


async def test_tri_par_date_decroissante_factures_et_bons_melanges(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    ancien = await _creer_bloc(
        db_session, facture=facture, numero_bl="ANCIEN", bl_document_id=None
    )
    await _creer_ligne(db_session, document=facture, bloc=ancien)
    recent = await _creer_document_bl(
        db_session, fournisseur_id=fournisseur.id, date_doc=date(2026, 9, 20)
    )

    lignes = await _toutes(db_session)

    assert lignes[0].bl_document_id == recent.id
    assert lignes[0].facture is False
    assert lignes[1].facture is True
