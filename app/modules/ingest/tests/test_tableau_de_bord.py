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

import app.modules.ingest.tableau_de_bord as tableau_de_bord_module
from app.modules.ingest.anomalies import lister_anomalies as lister_anomalies_module
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
_JUILLET = date(2026, 7, 1)


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


# --------------------------------------------------------------------------
# Corrections de revue (fix round 1) : fuite inter-mois, plafond
# silencieux, valeur non convertible, tri des chantiers.
# --------------------------------------------------------------------------


async def test_tableau_de_bord_anomalie_dun_autre_mois_naffecte_pas_le_chantier(
    db_session: AsyncSession,
) -> None:
    """Un chantier avec une anomalie ouverte de juillet (R08, sur une
    facture datée de juillet) et une facture de septembre sans anomalie :
    le tableau de bord de septembre ne doit voir ni l'anomalie ni son
    influence sur l'état du chantier (constat de revue -- l'ancien filtre
    par `chantier_id` présent dans le bilan du mois laissait fuir cette
    anomalie dès que le chantier facturait aussi ce mois-ci). Le tableau de
    bord de juillet, lui, doit toujours la voir."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Multi-Mois")

    facture_juillet = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-T2-JUIL",
        date_doc=date(2026, 7, 10),
    )
    bloc_juillet = await _creer_bloc(
        db_session,
        facture=facture_juillet,
        numero_bl="J1",
        chantier_id=chantier.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session,
        document=facture_juillet,
        bloc=bloc_juillet,
        montant_ht=Decimal("40.00"),
    )
    await _creer_anomalie(
        db_session, regle="R08", gravite="haute", bloc_id=bloc_juillet.id
    )

    facture_septembre = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-T2-SEPT",
        date_doc=date(2026, 9, 18),
    )
    bloc_septembre = await _creer_bloc(
        db_session,
        facture=facture_septembre,
        numero_bl="S1",
        chantier_id=chantier.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session,
        document=facture_septembre,
        bloc=bloc_septembre,
        montant_ht=Decimal("60.00"),
    )

    tdb_septembre = await tableau_de_bord(db_session, mois=_SEPT)
    ligne_septembre = next(
        chantier_tableau
        for chantier_tableau in tdb_septembre.chantiers
        if chantier_tableau.chantier_id == chantier.id
    )
    assert ligne_septembre.etat == "conforme"
    assert ligne_septembre.montants.nb_anomalies_ouvertes == 0
    assert tdb_septembre.nb_problemes_ouverts == 0
    assert tdb_septembre.nb_problemes_urgents == 0
    assert tdb_septembre.priorites == []

    tdb_juillet = await tableau_de_bord(db_session, mois=_JUILLET)
    ligne_juillet = next(
        chantier_tableau
        for chantier_tableau in tdb_juillet.chantiers
        if chantier_tableau.chantier_id == chantier.id
    )
    assert ligne_juillet.etat == "prix"
    assert tdb_juillet.nb_problemes_ouverts == 1


async def test_tableau_de_bord_etat_anomalie_implique_nb_anomalies_ouvertes(
    db_session: AsyncSession,
) -> None:
    """Invariant de cohérence (constat de revue) : pour toute ligne, un
    `etat` parmi `prix`/`quantites`/`a_voir` implique
    `montants.nb_anomalies_ouvertes > 0` -- jamais l'inverse. Scénario
    mêlant un chantier réellement `prix` ce mois-ci et un chantier dont la
    seule anomalie ouverte est d'un autre mois (doit rester `conforme`)."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier_prix = await _creer_chantier(db_session, nom="Chantier Prix")
    chantier_fuite = await _creer_chantier(db_session, nom="Chantier Fuite")

    facture_septembre = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-T2-INV-SEPT",
        date_doc=date(2026, 9, 9),
    )
    bloc_prix = await _creer_bloc(
        db_session,
        facture=facture_septembre,
        ordre=0,
        numero_bl="PRIX1",
        chantier_id=chantier_prix.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session,
        document=facture_septembre,
        bloc=bloc_prix,
        montant_ht=Decimal("10.00"),
    )
    await _creer_anomalie(
        db_session, regle="R08", gravite="haute", bloc_id=bloc_prix.id
    )

    bloc_fuite_sept = await _creer_bloc(
        db_session,
        facture=facture_septembre,
        ordre=1,
        numero_bl="FUITE-SEPT",
        chantier_id=chantier_fuite.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session,
        document=facture_septembre,
        bloc=bloc_fuite_sept,
        montant_ht=Decimal("10.00"),
    )

    facture_juillet = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-T2-INV-JUIL",
        date_doc=date(2026, 7, 5),
    )
    bloc_fuite_juillet = await _creer_bloc(
        db_session,
        facture=facture_juillet,
        numero_bl="FUITE-JUIL",
        chantier_id=chantier_fuite.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session,
        document=facture_juillet,
        bloc=bloc_fuite_juillet,
        montant_ht=Decimal("10.00"),
    )
    await _creer_anomalie(
        db_session, regle="R09", gravite="haute", bloc_id=bloc_fuite_juillet.id
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert any(
        chantier.etat in ("prix", "quantites", "a_voir") for chantier in tdb.chantiers
    )
    for chantier in tdb.chantiers:
        if chantier.etat in ("prix", "quantites", "a_voir"):
            assert chantier.montants.nb_anomalies_ouvertes > 0

    ligne_fuite = next(
        chantier
        for chantier in tdb.chantiers
        if chantier.chantier_id == chantier_fuite.id
    )
    assert ligne_fuite.etat == "conforme"
    assert ligne_fuite.montants.nb_anomalies_ouvertes == 0


async def test_tableau_de_bord_ne_plafonne_jamais_la_limite_des_anomalies(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Correction de revue : plus de plafond fixe (`limite=500` retiré).
    `lister_anomalies` est appelée avec `limite >= nombre d'identifiants du
    mois` -- vérifié en espionnant l'appel plutôt qu'en construisant une
    fixture de centaines de lignes (inutilement coûteux)."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-T2-NOLIMIT",
        date_doc=date(2026, 9, 9),
    )
    blocs = [
        await _creer_bloc(db_session, facture=facture, ordre=i, numero_bl=f"NL{i}")
        for i in range(3)
    ]
    for i, bloc in enumerate(blocs):
        await _creer_ligne(
            db_session, document=facture, bloc=bloc, montant_ht=Decimal("10.00")
        )
        await _creer_anomalie(
            db_session,
            regle="R07",
            gravite="moyenne",
            bloc_id=bloc.id,
            detail={"info": f"anomalie-{i}"},
        )

    appels: list[dict[str, Any]] = []

    async def _lister_anomalies_espionne(
        session: AsyncSession, **kwargs: Any
    ) -> list[Any]:
        appels.append(kwargs)
        return await lister_anomalies_module(session, **kwargs)

    monkeypatch.setattr(
        tableau_de_bord_module, "lister_anomalies", _lister_anomalies_espionne
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.nb_problemes_ouverts == 3
    assert len(appels) == 1
    assert appels[0]["ids"] is not None
    assert len(appels[0]["ids"]) == 3
    assert appels[0]["limite"] >= 3


async def test_tableau_de_bord_montant_en_jeu_valeur_non_convertible(
    db_session: AsyncSession,
) -> None:
    """`detail["montant_ht"]` au tiret cadratin (valeur manquante, `TIRET`
    des règles pures) -- `montant_en_jeu` doit valoir `None`, jamais lever."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-T2-TIRET",
        date_doc=date(2026, 9, 11),
    )
    bloc = await _creer_bloc(
        db_session, facture=facture, numero_bl="TIRET1", statut_rapprochement="non_recu"
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("10.00")
    )
    await _creer_anomalie(
        db_session,
        regle="R01",
        gravite="haute",
        bloc_id=bloc.id,
        detail={"montant_ht": "—"},
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert len(tdb.priorites) == 1
    assert tdb.priorites[0].anomalie.regle == "R01"
    assert tdb.priorites[0].montant_en_jeu is None


async def test_tableau_de_bord_tri_chantiers(db_session: AsyncSession) -> None:
    """`a_verifier` décroissant puis `nom_canonique` croissant, le chantier
    non résolu se départageant en dernier à montant égal."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-T2-TRI",
        date_doc=date(2026, 9, 14),
    )

    chantier_top = await _creer_chantier(db_session, nom="Top")
    chantier_a = await _creer_chantier(db_session, nom="A")
    chantier_z = await _creer_chantier(db_session, nom="Z")

    bloc_top = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=0,
        numero_bl="T1",
        chantier_id=chantier_top.id,
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_top, montant_ht=Decimal("100.00")
    )

    bloc_a = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=1,
        numero_bl="A1",
        chantier_id=chantier_a.id,
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_a, montant_ht=Decimal("50.00")
    )

    bloc_z = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=2,
        numero_bl="Z1",
        chantier_id=chantier_z.id,
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_z, montant_ht=Decimal("50.00")
    )

    bloc_non_resolu = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=3,
        numero_bl="NR1",
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_non_resolu, montant_ht=Decimal("50.00")
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    noms = [chantier.nom_canonique for chantier in tdb.chantiers]
    assert noms == ["Top", "A", "Z", None]
