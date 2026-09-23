"""Tests de `ingest/tableau_de_bord.py` (refonte front T2) : totaux du
mois, comptes de blocs/anomalies, état par chantier et priorités -- voir
`app/modules/ingest/tests/test_bilan.py` pour les scénarios métier détaillés
des quatre montants sous-jacents (L5-D3, déjà commité, non modifié ici).

Base de test réelle (`bl_test_t2` sur cet arbre de travail), données
entièrement inventées. `db_session` (fixture locale,
`app/modules/ingest/tests/conftest.py`) vide toutes les tables après chaque
test : aucun nettoyage manuel nécessaire ici.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Chantier,
    Document,
    Fournisseur,
    Ligne,
)
from app.modules.ingest.tableau_de_bord import tableau_de_bord

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_SEPT = date(2026, 9, 1)


# --------------------------------------------------------------------------
# Aides de construction (données inventées, copiées/réduites de
# `app/modules/ingest/tests/test_bilan.py` -- ce dossier ne partage pas ses
# aides entre fichiers de test, même convention que le reste du dépôt).
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur Tableau"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_chantier(
    db_session: AsyncSession, *, nom: str = "Chantier Tableau"
) -> Chantier:
    chantier = Chantier(nom_canonique=nom)
    db_session.add(chantier)
    await db_session.commit()
    await db_session.refresh(chantier)
    return chantier


async def _creer_facture(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    numero: str,
    date_doc: date | None,
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero=numero,
        fournisseur_id=fournisseur.id,
        date_doc=date_doc,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_bloc(
    db_session: AsyncSession,
    *,
    facture: Document,
    ordre: int = 0,
    numero_bl: str | None = "L0001",
    chantier_id: uuid.UUID | None = None,
    statut_rapprochement: str | None = "recu",
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=ordre,
        numero_bl=numero_bl,
        chantier_id=chantier_id,
        statut_rapprochement=statut_rapprochement,
    )
    db_session.add(bloc)
    await db_session.commit()
    await db_session.refresh(bloc)
    return bloc


async def _creer_ligne(
    db_session: AsyncSession,
    *,
    document: Document,
    bloc: BlocFacture,
    montant_ht: Decimal = Decimal("100.00"),
    ordre: int = 0,
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        bloc_id=bloc.id,
        montant_ht=montant_ht,
        type_ligne="article",
        ordre=ordre,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _creer_anomalie(
    db_session: AsyncSession,
    *,
    regle: str,
    gravite: str,
    bloc_id: uuid.UUID | None = None,
    ligne_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
    statut: str = "ouverte",
) -> Anomalie:
    anomalie = Anomalie(
        regle=regle,
        gravite=gravite,
        statut=statut,
        bloc_id=bloc_id,
        ligne_id=ligne_id,
        detail=detail if detail is not None else {"cle": "valeur"},
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)
    return anomalie


# --------------------------------------------------------------------------
# Scénarios
# --------------------------------------------------------------------------


async def test_tableau_de_bord_mois_vide(db_session: AsyncSession) -> None:
    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.totaux.facture_ht == Decimal("0")
    assert tdb.totaux.rapproche == Decimal("0")
    assert tdb.totaux.en_ecart == Decimal("0")
    assert tdb.totaux.non_justifie == Decimal("0")
    assert tdb.totaux.conforme == Decimal("0")
    assert tdb.chantiers == []
    assert tdb.priorites == []
    assert tdb.nb_bl_factures == 0
    assert tdb.nb_bl_recus == 0
    assert tdb.nb_problemes_ouverts == 0
    assert tdb.nb_problemes_urgents == 0


async def test_tableau_de_bord_totaux_et_conforme(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-T2-1", date_doc=date(2026, 9, 10)
    )

    bloc_sans_ecart = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=0,
        numero_bl="B1",
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_sans_ecart, montant_ht=Decimal("100.00")
    )

    bloc_en_ecart = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=1,
        numero_bl="B2",
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_en_ecart, montant_ht=Decimal("50.00")
    )
    await _creer_anomalie(
        db_session, regle="R08", gravite="haute", bloc_id=bloc_en_ecart.id
    )

    bloc_non_recu = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=2,
        numero_bl="B3",
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_non_recu, montant_ht=Decimal("30.00")
    )
    await _creer_anomalie(
        db_session, regle="R01", gravite="haute", bloc_id=bloc_non_recu.id
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.totaux.facture_ht == Decimal("180.00")
    assert tdb.totaux.en_ecart == Decimal("50.00")
    assert tdb.totaux.non_justifie == Decimal("30.00")
    assert tdb.totaux.conforme == Decimal("100.00")
    assert (tdb.nb_bl_factures, tdb.nb_bl_recus) == (3, 2)
    assert (tdb.nb_problemes_ouverts, tdb.nb_problemes_urgents) == (2, 2)


async def test_tableau_de_bord_etats(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier_a = await _creer_chantier(db_session, nom="A")
    chantier_b = await _creer_chantier(db_session, nom="B")
    chantier_c = await _creer_chantier(db_session, nom="C")
    chantier_d = await _creer_chantier(db_session, nom="D")
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-T2-ETATS",
        date_doc=date(2026, 9, 12),
    )

    bloc_a = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=0,
        numero_bl="A1",
        chantier_id=chantier_a.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_a, montant_ht=Decimal("10.00")
    )

    bloc_b = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=1,
        numero_bl="B1",
        chantier_id=chantier_b.id,
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_b, montant_ht=Decimal("10.00")
    )

    bloc_c = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=2,
        numero_bl="C1",
        chantier_id=chantier_c.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_c, montant_ht=Decimal("10.00")
    )
    await _creer_anomalie(db_session, regle="R08", gravite="haute", bloc_id=bloc_c.id)

    bloc_d = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=3,
        numero_bl="D1",
        chantier_id=chantier_d.id,
        statut_rapprochement="recu",
    )
    ligne_d = await _creer_ligne(
        db_session, document=facture, bloc=bloc_d, montant_ht=Decimal("10.00")
    )
    await _creer_anomalie(
        db_session,
        regle="R03",
        gravite="haute",
        bloc_id=bloc_d.id,
        ligne_id=ligne_d.id,
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    etats = {chantier.nom_canonique: chantier.etat for chantier in tdb.chantiers}
    assert etats == {"A": "conforme", "B": "bl_manquant", "C": "prix", "D": "quantites"}


async def test_tableau_de_bord_chantier_non_resolu(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-T2-NR", date_doc=date(2026, 9, 5)
    )
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="NR1")
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("20.00")
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    ligne = next(chantier for chantier in tdb.chantiers if chantier.chantier_id is None)
    assert ligne.etat == "a_rattacher"
    assert ligne.nom_canonique is None


async def test_tableau_de_bord_priorites_triees_et_limitees(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-T2-PRIO",
        date_doc=date(2026, 9, 8),
    )
    blocs = [
        await _creer_bloc(db_session, facture=facture, ordre=i, numero_bl=f"P{i}")
        for i in range(5)
    ]
    for bloc in blocs:
        await _creer_ligne(
            db_session, document=facture, bloc=bloc, montant_ht=Decimal("10.00")
        )

    await _creer_anomalie(
        db_session,
        regle="R07",
        gravite="moyenne",
        bloc_id=blocs[0].id,
        detail={"info": "R07 sans montant chiffrable"},
    )
    await _creer_anomalie(
        db_session,
        regle="R01",
        gravite="haute",
        bloc_id=blocs[1].id,
        detail={"montant_ht": "30.00"},
    )
    await _creer_anomalie(
        db_session,
        regle="R02",
        gravite="haute",
        bloc_id=blocs[2].id,
        detail={"montant_ht": "200.00"},
    )
    await _creer_anomalie(
        db_session,
        regle="R08",
        gravite="haute",
        bloc_id=blocs[3].id,
        detail={"info": "R08 sans montant"},
    )
    await _creer_anomalie(
        db_session,
        regle="R01",
        gravite="haute",
        bloc_id=blocs[4].id,
        detail={"montant_ht": "90.00"},
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    regles = [probleme.anomalie.regle for probleme in tdb.priorites]
    assert regles == ["R02", "R01", "R01", "R08"]


async def test_tableau_de_bord_ignore_les_autres_mois(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture_aout = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-T2-AOUT",
        date_doc=date(2026, 8, 20),
    )
    bloc = await _creer_bloc(db_session, facture=facture_aout, numero_bl="A1")
    await _creer_ligne(
        db_session, document=facture_aout, bloc=bloc, montant_ht=Decimal("15.00")
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.chantiers == []
