"""Rattachement du chantier d'un bon : les prénoms des employés ne font jamais
le nom d'un chantier (lot 4 du 02/11/2026, D2). Base de test réelle, noms
inventés (comptes « Odilon Verdier » et « Basile Tarral »)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import (
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Utilisateur,
)
from app.modules.ingest.rattachement_chantier import (
    rattacher_chantier_bloc,
    rattacher_chantier_document,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _decor(db_session: AsyncSession) -> Fournisseur:
    for nom in ("Odilon Verdier", "Basile Tarral"):
        db_session.add(
            Utilisateur(
                email=f"{uuid.uuid4()}@example.invalid",
                nom=nom,
                role="agent",
                is_active=True,
            )
        )
    f = Fournisseur(nom="Fournisseur Test")
    db_session.add(f)
    await db_session.flush()
    return f


async def _bon(
    db_session: AsyncSession,
    f: Fournisseur,
    chantier_brut: str | None,
    *,
    legende: str | None = None,
    numero_commande: str | None = None,
) -> Document:
    d = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        fournisseur_id=f.id,
        chantier_brut=chantier_brut,
        legende=legende,
        numero_commande=numero_commande,
    )
    db_session.add(d)
    await db_session.flush()
    return d


async def _noms_chantiers(db_session: AsyncSession) -> list[str]:
    return sorted(
        (await db_session.execute(select(Chantier.nom_canonique))).scalars().all()
    )


@pytest.mark.parametrize(
    "brut", ["POUR ODILON", "PRS PAR BASILE", "BASILE ODILON", "Odilon / Basile"]
)
async def test_nom_lu_d_employe_ne_cree_aucun_chantier(
    db_session: AsyncSession, brut: str
) -> None:
    f = await _decor(db_session)
    bon = await _bon(db_session, f, brut)

    r = await rattacher_chantier_document(db_session, bon)

    assert r.chantier_id is None and r.cree is False
    assert await _noms_chantiers(db_session) == []
    assert bon.chantier_brut == brut  # la lecture reste telle quelle


@pytest.mark.parametrize(
    "brut",
    [
        "LES SOURCES / ODILON",
        "LES SOURCES (ODILON)",
        "ODILON (LES SOURCES)",
        "POUR ODILON LES SOURCES",
    ],
)
async def test_chantier_cree_sans_le_prenom(
    db_session: AsyncSession, brut: str
) -> None:
    f = await _decor(db_session)
    bon = await _bon(db_session, f, brut)

    r = await rattacher_chantier_document(db_session, bon)

    assert r.cree is True
    assert await _noms_chantiers(db_session) == ["LES SOURCES"]
    alias = (await db_session.execute(select(ChantierAlias))).scalar_one()
    assert alias.libelle_brut == "les sources"
    assert bon.chantier_brut == brut


async def test_chantier_connu_reconnu_malgre_le_prenom(
    db_session: AsyncSession,
) -> None:
    f = await _decor(db_session)
    villa = Chantier(nom_canonique="Les Sources")
    db_session.add(villa)
    await db_session.flush()
    bon = await _bon(db_session, f, "LES SOURCES (ODILON)")

    r = await rattacher_chantier_document(db_session, bon)

    assert r.chantier_id == villa.id and r.cree is False
    assert await _noms_chantiers(db_session) == ["Les Sources"]


async def test_nom_vide_apres_nettoyage_passe_a_la_legende(
    db_session: AsyncSession,
) -> None:
    f = await _decor(db_session)
    villa = Chantier(nom_canonique="Les Sources")
    db_session.add(villa)
    await db_session.flush()
    bon = await _bon(db_session, f, "POUR ODILON", legende="Les Sources")

    r = await rattacher_chantier_document(db_session, bon)

    assert r.chantier_id == villa.id and r.methode == "légende"


async def test_nom_vide_apres_nettoyage_passe_a_la_reference_de_commande(
    db_session: AsyncSession,
) -> None:
    f = await _decor(db_session)
    villa = Chantier(nom_canonique="Les Sources")
    db_session.add(villa)
    await db_session.flush()
    bon = await _bon(db_session, f, "PRS PAR BASILE", numero_commande="LES SOURCES")

    r = await rattacher_chantier_document(db_session, bon)

    assert r.chantier_id == villa.id and r.methode == "référence de commande"


async def test_chantier_sans_prenom_inchange(db_session: AsyncSession) -> None:
    f = await _decor(db_session)
    bon = await _bon(db_session, f, "RESIDENCE DES TILLEULS (9)")

    r = await rattacher_chantier_document(db_session, bon)

    assert r.cree is True
    assert await _noms_chantiers(db_session) == ["RESIDENCE DES TILLEULS"]


async def test_bloc_de_facture_sans_le_prenom(db_session: AsyncSession) -> None:
    f = await _decor(db_session)

    vide = await rattacher_chantier_bloc(db_session, f.id, "POUR ODILON")
    assert vide is None
    assert await _noms_chantiers(db_session) == []

    cree = await rattacher_chantier_bloc(db_session, f.id, "LES SOURCES (BASILE)")
    assert cree is not None
    assert await _noms_chantiers(db_session) == ["LES SOURCES"]
