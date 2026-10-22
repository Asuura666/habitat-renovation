"""Tests de `ingest/referentiels_vue.py::chantiers_du_mois` : un chantier est
« du mois » s'il a un bon (BL ou enlèvement non archivé) daté de ce mois, ou
s'il est facturé ce mois-ci (même notion de mois que le bilan).

Base de test réelle, données entièrement inventées. `db_session` vide les
tables après chaque test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.models import BlocFacture, Chantier, Document, Fournisseur
from app.modules.ingest.referentiels_vue import ChantierDuMois, chantiers_du_mois

pytestmark = [pytest.mark.anyio, pytest.mark.db]

SEPTEMBRE = date(2026, 9, 1)


async def _chantier(
    db: AsyncSession,
    nom: str = "Chantier Testeur",
    agence: str | None = None,
    fusionne_dans_id: uuid.UUID | None = None,
) -> Chantier:
    chantier = Chantier(
        nom_canonique=nom, agence=agence, fusionne_dans_id=fusionne_dans_id
    )
    db.add(chantier)
    await db.commit()
    await db.refresh(chantier)
    return chantier


async def _bon(
    db: AsyncSession,
    chantier: Chantier | None,
    *,
    type_: str = "bl",
    statut: str = "recu",
    date_doc: date | None = None,
    created_at: datetime | None = None,
) -> Document:
    document = Document(
        type=type_,
        source="telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        chantier_id=chantier.id if chantier is not None else None,
        date_doc=date_doc,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def _facture_avec_bloc(
    db: AsyncSession,
    chantier: Chantier,
    *,
    date_doc: date | None = date(2026, 9, 15),
    statut: str = "recu",
    created_at: datetime | None = None,
) -> None:
    fournisseur = Fournisseur(nom=f"Fournisseur {uuid.uuid4()}")
    db.add(fournisseur)
    await db.commit()
    facture = Document(
        type="facture",
        source="upload",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero="F1",
        fournisseur_id=fournisseur.id,
        date_doc=date_doc,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db.add(facture)
    await db.commit()
    db.add(
        BlocFacture(
            facture_id=facture.id,
            ordre=0,
            numero_bl="L1",
            chantier_id=chantier.id,
            statut_rapprochement="non_recu",
        )
    )
    await db.commit()


def _par_id(lignes: list[ChantierDuMois]) -> dict[uuid.UUID, ChantierDuMois]:
    return {ligne.chantier_id: ligne for ligne in lignes}


async def test_bon_date_du_mois(db_session: AsyncSession) -> None:
    c = await _chantier(db_session)
    await _bon(db_session, c, date_doc=date(2026, 9, 3))
    await _bon(db_session, c, type_="enlevement", date_doc=date(2026, 9, 20))

    lignes = await chantiers_du_mois(db_session, SEPTEMBRE, None)

    assert lignes == [
        ChantierDuMois(
            chantier_id=c.id,
            nb_bons=2,
            dernier_bon_le=date(2026, 9, 20),
            facture_ce_mois=False,
        )
    ]


async def test_bon_sans_date_depose_dans_le_mois(db_session: AsyncSession) -> None:
    c = await _chantier(db_session)
    await _bon(
        db_session,
        c,
        date_doc=None,
        created_at=datetime(2026, 9, 10, 8, 0, tzinfo=FUSEAU_PARIS),
    )

    ligne = _par_id(await chantiers_du_mois(db_session, SEPTEMBRE, None))[c.id]

    assert ligne.nb_bons == 1
    assert ligne.dernier_bon_le == date(2026, 9, 10)


async def test_bon_date_du_mois_precedent_depose_ce_mois_exclu(
    db_session: AsyncSession,
) -> None:
    c = await _chantier(db_session)
    await _bon(
        db_session,
        c,
        date_doc=date(2026, 8, 28),
        created_at=datetime(2026, 9, 5, 9, 0, tzinfo=FUSEAU_PARIS),
    )

    assert await chantiers_du_mois(db_session, SEPTEMBRE, None) == []


async def test_bon_archive_exclu(db_session: AsyncSession) -> None:
    c = await _chantier(db_session)
    await _bon(db_session, c, statut="archive", date_doc=date(2026, 9, 3))

    assert await chantiers_du_mois(db_session, SEPTEMBRE, None) == []


async def test_facture_du_mois_sans_bon(db_session: AsyncSession) -> None:
    c = await _chantier(db_session)
    await _facture_avec_bloc(db_session, c)

    assert await chantiers_du_mois(db_session, SEPTEMBRE, None) == [
        ChantierDuMois(
            chantier_id=c.id, nb_bons=0, dernier_bon_le=None, facture_ce_mois=True
        )
    ]


async def test_bons_et_facture_du_mois(db_session: AsyncSession) -> None:
    c = await _chantier(db_session)
    await _bon(db_session, c, date_doc=date(2026, 9, 3))
    await _facture_avec_bloc(db_session, c)

    ligne = _par_id(await chantiers_du_mois(db_session, SEPTEMBRE, None))[c.id]

    assert (ligne.nb_bons, ligne.facture_ce_mois) == (1, True)


async def test_facture_archivee_ou_d_un_autre_mois_exclue(
    db_session: AsyncSession,
) -> None:
    c1 = await _chantier(db_session, nom="Archivée")
    c2 = await _chantier(db_session, nom="Autre mois")
    await _facture_avec_bloc(db_session, c1, statut="archive")
    await _facture_avec_bloc(db_session, c2, date_doc=date(2026, 8, 31))

    assert await chantiers_du_mois(db_session, SEPTEMBRE, None) == []


async def test_bornes_heure_de_paris(db_session: AsyncSession) -> None:
    dedans = await _chantier(db_session, nom="Dernier jour")
    dehors = await _chantier(db_session, nom="Mois suivant")
    # 30/09 23 h 30 à Paris = 21 h 30 UTC (heure d'été) : encore septembre.
    await _bon(
        db_session,
        dedans,
        created_at=datetime(2026, 9, 30, 23, 30, tzinfo=FUSEAU_PARIS),
    )
    # 1/10 00 h 30 à Paris = 30/09 22 h 30 UTC : déjà octobre.
    await _bon(
        db_session,
        dehors,
        created_at=datetime(2026, 10, 1, 0, 30, tzinfo=FUSEAU_PARIS),
    )

    lignes = _par_id(await chantiers_du_mois(db_session, SEPTEMBRE, None))

    assert set(lignes) == {dedans.id}
    assert lignes[dedans.id].dernier_bon_le == date(2026, 9, 30)


async def test_bon_depose_le_1er_a_paris_avant_minuit_utc(
    db_session: AsyncSession,
) -> None:
    c = await _chantier(db_session)
    await _bon(
        db_session,
        c,
        created_at=datetime(2026, 8, 31, 22, 30, tzinfo=UTC),  # 1/09 00 h 30 Paris
    )

    ligne = _par_id(await chantiers_du_mois(db_session, SEPTEMBRE, None))[c.id]

    assert ligne.dernier_bon_le == date(2026, 9, 1)


async def test_filtre_agence(db_session: AsyncSession) -> None:
    nord = await _chantier(db_session, nom="Nord", agence="Nord")
    sud = await _chantier(db_session, nom="Sud", agence="Sud")
    await _bon(db_session, nord, date_doc=date(2026, 9, 3))
    await _bon(db_session, sud, date_doc=date(2026, 9, 3))

    lignes = await chantiers_du_mois(db_session, SEPTEMBRE, "Nord")

    assert [ligne.chantier_id for ligne in lignes] == [nord.id]


async def test_bon_sans_chantier_et_chantier_fusionne_exclus(
    db_session: AsyncSession,
) -> None:
    cible = await _chantier(db_session, nom="Cible")
    fusionne = await _chantier(db_session, nom="Fusionné", fusionne_dans_id=cible.id)
    await _bon(db_session, None, date_doc=date(2026, 9, 3))
    await _bon(db_session, fusionne, date_doc=date(2026, 9, 3))

    assert await chantiers_du_mois(db_session, SEPTEMBRE, None) == []
