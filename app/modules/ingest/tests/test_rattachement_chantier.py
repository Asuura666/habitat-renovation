"""Tests de `ingest/rattachement_chantier.py` (avenant du 27/09/2026,
décision d'Ilane, spec §2.2-2.4) : rattachement automatique du chantier d'un
bon ou d'un bloc de facture par ressemblance de nom, création à compléter,
apprentissage d'alias et alerte R18.

Base de test réelle (`bl_test`), données entièrement inventées (« Villa
Test », « Résidence des Tilleuls »…), jamais `tests/fixtures/` (R17)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.db import creer_sessionmaker
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Parametre,
)
from app.modules.ingest.parametres import CLE_SEUIL_RESSEMBLANCE_CHANTIER
from app.modules.ingest.rattachement_chantier import (
    rattacher_chantier_bloc,
    rattacher_chantier_document,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _fournisseur(
    db_session: AsyncSession, nom: str = "Fournisseur Test"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.flush()
    return fournisseur


async def _chantier(db_session: AsyncSession, nom: str) -> Chantier:
    chantier = Chantier(nom_canonique=nom)
    db_session.add(chantier)
    await db_session.flush()
    return chantier


async def _bon(
    db_session: AsyncSession,
    *,
    fournisseur_id: uuid.UUID | None,
    chantier_brut: str | None,
    legende: str | None,
) -> Document:
    document = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur_id,
        chantier_brut=chantier_brut,
        legende=legende,
    )
    db_session.add(document)
    await db_session.flush()
    return document


# --------------------------------------------------------------------------
# rattacher_chantier_document
# --------------------------------------------------------------------------


async def test_nom_lu_ressemblant_rattache_et_apprend(db_session: AsyncSession) -> None:
    f = await _fournisseur(db_session)
    villa = await _chantier(db_session, "Villa Test")
    bon = await _bon(
        db_session, fournisseur_id=f.id, chantier_brut="VILLA TEST (123)", legende=None
    )
    r = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()
    assert r.chantier_id == villa.id and r.methode == "ressemblance"
    alias = (
        await db_session.execute(
            select(ChantierAlias).where(ChantierAlias.libelle_brut == "villa test")
        )
    ).scalar_one()
    assert alias.chantier_id == villa.id


async def test_nom_inconnu_cree_un_chantier_a_completer(
    db_session: AsyncSession,
) -> None:
    """Aucun chantier en base : le nom lu « RESIDENCE DES TILLEULS (9) » ne
    ressemble à rien -> un chantier « à compléter » est créé automatiquement,
    journal `chantier_cree_auto`."""
    f = await _fournisseur(db_session)
    bon = await _bon(
        db_session,
        fournisseur_id=f.id,
        chantier_brut="RESIDENCE DES TILLEULS (9)",
        legende=None,
    )

    r = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()
    await db_session.refresh(bon)

    assert r.cree is True
    assert r.methode == "création"
    assert r.chantier_id is not None
    assert bon.chantier_id == r.chantier_id

    chantier = await db_session.get(Chantier, r.chantier_id)
    assert chantier is not None
    assert chantier.nom_canonique == "RESIDENCE DES TILLEULS"
    assert chantier.a_completer is True
    assert chantier.actif is True

    journal = (
        await db_session.execute(
            select(Journal).where(
                Journal.cible_id == str(chantier.id),
                Journal.action == "chantier_cree_auto",
            )
        )
    ).scalar_one()
    assert journal.utilisateur_id is None
    assert journal.apres is not None
    assert journal.apres["nom_canonique"] == "RESIDENCE DES TILLEULS"
    assert journal.apres["source"] == "nom lu"
    assert journal.apres["document_id"] == str(bon.id)

    # Apprentissage : le nom lu devient un alias directement rattaché.
    alias = (
        await db_session.execute(
            select(ChantierAlias).where(
                ChantierAlias.libelle_brut == "residence des tilleuls"
            )
        )
    ).scalar_one()
    assert alias.chantier_id == chantier.id


async def test_nom_lu_inconnu_legende_reconnue(db_session: AsyncSession) -> None:
    f = await _fournisseur(db_session)
    villa = await _chantier(db_session, "Villa Test")
    bon = await _bon(
        db_session, fournisseur_id=f.id, chantier_brut="VT-NORD", legende="villa test"
    )

    r = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()
    await db_session.refresh(bon)

    assert r.chantier_id == villa.id
    assert r.methode == "légende"
    assert bon.chantier_id == villa.id

    alias = (
        await db_session.execute(
            select(ChantierAlias).where(ChantierAlias.libelle_brut == "vt nord")
        )
    ).scalar_one()
    assert alias.chantier_id == villa.id


async def test_desaccord_leve_R18_et_laisse_sans_chantier(
    db_session: AsyncSession,
) -> None:
    f = await _fournisseur(db_session)
    await _chantier(db_session, "Villa Test")
    await _chantier(db_session, "Résidence des Tilleuls")
    bon = await _bon(
        db_session,
        fournisseur_id=f.id,
        chantier_brut="VILLA TEST",
        legende="tilleuls residence",
    )

    r = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()
    await db_session.refresh(bon)

    assert r.alerte is True
    assert r.chantier_id is None
    assert bon.chantier_id is None

    anomalie = (
        await db_session.execute(
            select(Anomalie).where(
                Anomalie.document_id == bon.id, Anomalie.regle == "R18"
            )
        )
    ).scalar_one()
    assert anomalie.statut == "ouverte"
    assert anomalie.detail["candidats"] == "Villa Test / Résidence des Tilleuls"


async def test_correction_du_nom_leve_R18(db_session: AsyncSession) -> None:
    f = await _fournisseur(db_session)
    villa = await _chantier(db_session, "Villa Test")
    await _chantier(db_session, "Résidence des Tilleuls")
    bon = await _bon(
        db_session,
        fournisseur_id=f.id,
        chantier_brut="VILLA TEST",
        legende="tilleuls residence",
    )
    await rattacher_chantier_document(db_session, bon)
    await db_session.commit()

    bon.legende = None
    r = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()
    await db_session.refresh(bon)

    assert r.alerte is False
    assert r.chantier_id == villa.id
    assert bon.chantier_id == villa.id

    anomalies_ouvertes = (
        (
            await db_session.execute(
                select(Anomalie).where(
                    Anomalie.document_id == bon.id,
                    Anomalie.regle == "R18",
                    Anomalie.statut == "ouverte",
                )
            )
        )
        .scalars()
        .all()
    )
    assert anomalies_ouvertes == []


async def test_creation_concurrente_un_seul_chantier(db_engine: AsyncEngine) -> None:
    """Deux dépôts concurrents du même nom inconnu ne créent qu'un seul
    chantier (verrou `pg_advisory_xact_lock`)."""
    sessionmaker = creer_sessionmaker(db_engine)

    async def _deposer_et_committer(nom_fichier: str) -> None:
        async with sessionmaker() as session:
            bon = Document(
                type="bl",
                source="telegram",
                statut="recu",
                fichier_path=nom_fichier,
                chantier_brut="NOUVEAU CHANTIER",
            )
            session.add(bon)
            await session.flush()
            await rattacher_chantier_document(session, bon)
            await session.commit()

    await asyncio.gather(
        _deposer_et_committer("bon-concurrent-a.jpg"),
        _deposer_et_committer("bon-concurrent-b.jpg"),
    )

    async with sessionmaker() as verification:
        chantiers = (
            (
                await verification.execute(
                    select(Chantier).where(Chantier.nom_canonique == "NOUVEAU CHANTIER")
                )
            )
            .scalars()
            .all()
        )
    assert len(chantiers) == 1


async def test_seuil_lu_dans_les_reglages(db_session: AsyncSession) -> None:
    """Seuil réglé à 100 % : « Villa tes » (ressemblance 94 avec « Villa
    test ») ne reconnaît plus le chantier existant -> création."""
    f = await _fournisseur(db_session)
    villa = await _chantier(db_session, "Villa test")
    db_session.add(Parametre(cle=CLE_SEUIL_RESSEMBLANCE_CHANTIER, valeur="100"))
    await db_session.flush()

    bon = await _bon(
        db_session, fournisseur_id=f.id, chantier_brut="Villa tes", legende=None
    )
    r = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()

    assert r.methode == "création"
    assert r.cree is True
    assert r.chantier_id != villa.id


# --------------------------------------------------------------------------
# rattacher_chantier_bloc
# --------------------------------------------------------------------------


async def test_bloc_facture_ambigu_garde_l_alias_en_attente(
    db_session: AsyncSession,
) -> None:
    f = await _fournisseur(db_session)
    await _chantier(db_session, "Residence les Pins 1")
    await _chantier(db_session, "Residence les Pins 2")

    resultat = await rattacher_chantier_bloc(db_session, f.id, "RESIDENCE LES PINS")
    await db_session.commit()

    assert resultat is None

    alias = (
        await db_session.execute(
            select(ChantierAlias).where(
                ChantierAlias.fournisseur_id == f.id,
                ChantierAlias.libelle_brut == "residence les pins",
            )
        )
    ).scalar_one()
    assert alias.chantier_id is None


async def test_alias_en_attente_rattache_et_propage(db_session: AsyncSession) -> None:
    f = await _fournisseur(db_session)
    villa = await _chantier(db_session, "Villa Test")

    # Alias en attente (ancien flux) : un bloc de facture avait déjà tenté
    # de résoudre ce nom avant que le chantier existe.
    db_session.add(
        ChantierAlias(
            fournisseur_id=f.id,
            libelle_brut="villa test",
            code_brut=None,
            chantier_id=None,
        )
    )

    facture = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path="facture-invente.pdf",
        fournisseur_id=f.id,
    )
    db_session.add(facture)
    await db_session.flush()

    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=0,
        chantier_brut="VILLA TEST",
        chantier_id=None,
    )
    db_session.add(bloc)
    await db_session.flush()

    bon = await _bon(
        db_session, fournisseur_id=f.id, chantier_brut="VILLA TEST", legende=None
    )

    r = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()
    await db_session.refresh(bloc)

    assert r.chantier_id == villa.id
    assert r.methode == "ressemblance"

    alias = (
        await db_session.execute(
            select(ChantierAlias).where(
                ChantierAlias.fournisseur_id == f.id,
                ChantierAlias.libelle_brut == "villa test",
            )
        )
    ).scalar_one()
    assert alias.chantier_id == villa.id

    journal = (
        await db_session.execute(
            select(Journal).where(
                Journal.cible_id == str(alias.id),
                Journal.action == "alias_rattache_auto",
            )
        )
    ).scalar_one()
    assert journal.apres is not None
    assert journal.apres["chantier_id"] == str(villa.id)
    assert journal.apres["nb_mis_a_jour"] == 1

    assert bloc.chantier_id == villa.id
