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
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.ingest.tableau_de_bord as tableau_de_bord_module
from app.core.fuseau import FUSEAU_PARIS
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
    # « Conforme » strict (décision d'Ilane du 29/09/2026) : un bloc « reçu »
    # cite un bon validé. Bon daté de 2020 et sans montant : il n'entre dans
    # aucun compte de bons du mois testé.
    bl_document_id = None
    if statut_rapprochement == "recu":
        bon = await _creer_bon(db_session, total_ht=None, date_doc=date(2020, 1, 1))
        bl_document_id = bon.id
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=ordre,
        numero_bl=numero_bl,
        chantier_id=chantier_id,
        statut_rapprochement=statut_rapprochement,
        bl_document_id=bl_document_id,
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
    """Anomalie de la forme que produit réellement le rapprochement (revue
    finale de la refonte du front, constat SERVEUR-8) : une anomalie de bloc
    porte toujours `document_id` = la facture de ce bloc (Ruling R17 du lot
    4, `rapprochement.py` complète `document_id` à partir du bloc) -- avant
    ce correctif, les scénarios de ce fichier ne posaient jamais
    `document_id`, une forme qui n'existe pas en base réelle."""
    document_id: uuid.UUID | None = None
    if bloc_id is not None:
        bloc = await db_session.get(BlocFacture, bloc_id)
        assert bloc is not None
        document_id = bloc.facture_id
    anomalie = Anomalie(
        regle=regle,
        gravite=gravite,
        statut=statut,
        document_id=document_id,
        bloc_id=bloc_id,
        ligne_id=ligne_id,
        detail=detail if detail is not None else {"cle": "valeur"},
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)
    return anomalie


async def _creer_bon(
    db_session: AsyncSession,
    *,
    type_bon: str = "bl",
    statut: str = "recu",
    total_ht: Decimal | None = Decimal("100.00"),
    date_doc: date | None = date(2026, 9, 10),
    created_at: datetime | None = None,
) -> Document:
    """Un BL ou un bon d'enlèvement (`type_bon` dans `TYPES_BL`), jamais une
    facture -- construction réduite à ce que lit `_compter_bons_recus`
    (décision d'Ilane du 25/09/2026, tuile « Montant des bons reçus »,
    docstring de module). `numero`/`fournisseur_id` restent `None` :
    non contraints ici, la contrainte d'unicité de `Document` traite
    plusieurs `NULL` comme distincts."""
    document = Document(
        type=type_bon,
        source="telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        total_ht=total_ht,
        date_doc=date_doc,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


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
    assert tdb.nb_bons_recus == 0
    assert tdb.montant_bons_recus == Decimal("0")
    assert tdb.nb_bons_sans_montant == 0


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
    # Un bloc non reçu porte toujours son R01 (le rapprochement le pose) :
    # c'est ce problème ouvert, plus le seul statut du bloc, qui fait l'état
    # `bl_manquant` (revue finale, constat SERVEUR-1).
    await _creer_anomalie(db_session, regle="R01", gravite="haute", bloc_id=bloc_b.id)

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
        db_session, regle="R09", gravite="moyenne", bloc_id=bloc_fuite_juillet.id
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
    # Chaque bloc non reçu porte son R01 ouvert (forme réelle) : c'est lui
    # qui le fait entrer dans `a_verifier` (revue finale, constat SERVEUR-1).
    for bloc in (bloc_top, bloc_a, bloc_z, bloc_non_resolu):
        await _creer_anomalie(db_session, regle="R01", gravite="haute", bloc_id=bloc.id)

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    noms = [chantier.nom_canonique for chantier in tdb.chantiers]
    assert noms == ["Top", "A", "Z", None]


# --------------------------------------------------------------------------
# Revue finale de la refonte du front (constats SERVEUR-1, SERVEUR-2,
# SERVEUR-3, SERVEUR-7, SERVEUR-8, ECRAN-8, COUVERTURE-4, COUVERTURE-26) :
# état et montants fondés sur les problèmes encore ouverts, chaque bloc
# compté une fois, formes d'anomalies réelles.
# --------------------------------------------------------------------------


async def test_tableau_de_bord_bon_manquant_deja_regle_nest_plus_a_verifier(
    db_session: AsyncSession,
) -> None:
    """SERVEUR-1/ECRAN-5 : un bloc non reçu dont le R01 est déjà contesté
    (`traitee`), et un bloc « livré sans bon » dont le R02 est ignoré, ne
    laissent plus leur chantier en « BL manquant » ni leur montant « à
    vérifier ». Le montant « sans bon de livraison » (L5-D3) ne change pas
    de définition, lui."""
    fournisseur = await _creer_fournisseur(db_session)
    bellevue = await _creer_chantier(db_session, nom="Résidence Test")
    perrier = await _creer_chantier(db_session, nom="Maison Test")
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-FIN-REGLE",
        date_doc=date(2026, 9, 3),
    )

    bloc_non_recu = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=0,
        numero_bl="NR-REGLE",
        chantier_id=bellevue.id,
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_non_recu, montant_ht=Decimal("303.90")
    )
    await _creer_anomalie(
        db_session,
        regle="R01",
        gravite="haute",
        bloc_id=bloc_non_recu.id,
        statut="traitee",
    )

    bloc_sans_bon = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=1,
        numero_bl="PDB-IGNORE",
        chantier_id=perrier.id,
        statut_rapprochement="pas_de_bon",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_sans_bon, montant_ht=Decimal("191.50")
    )
    await _creer_anomalie(
        db_session,
        regle="R02",
        gravite="haute",
        bloc_id=bloc_sans_bon.id,
        statut="ignoree",
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    par_nom = {chantier.nom_canonique: chantier for chantier in tdb.chantiers}
    for nom in ("Résidence Test", "Maison Test"):
        # Ni « BL manquant » ni montant à vérifier ; mais le bloc reste sans
        # bon : l'état se décide sur les blocs (correction commune 2/3, I2),
        # le chantier n'est donc pas « conforme » mais « à voir ».
        assert par_nom[nom].etat == "a_voir", nom
        assert par_nom[nom].a_verifier == Decimal("0"), nom
        assert par_nom[nom].montants.a_verifier == Decimal("0"), nom
        assert par_nom[nom].montants.nb_anomalies_ouvertes == 0, nom
    assert tdb.totaux.non_justifie == Decimal("495.40")
    assert tdb.nb_bl_manquants == 0
    assert tdb.nb_problemes_ouverts == 0


async def test_tableau_de_bord_bon_manquant_ouvert_reste_bl_manquant(
    db_session: AsyncSession,
) -> None:
    """Pendant de la règle précédente : tant que le R01 est ouvert, le
    chantier reste « BL manquant », son montant reste à vérifier et le bon
    est compté parmi ceux à réclamer. Un bloc « livré sans bon » (R02
    ouvert) est à vérifier mais n'a aucun bon à réclamer (COUVERTURE-4)."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Ouvert")
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-FIN-OUVERT",
        date_doc=date(2026, 9, 4),
    )
    bloc_non_recu = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=0,
        numero_bl="NR-OUVERT",
        chantier_id=chantier.id,
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_non_recu, montant_ht=Decimal("40.00")
    )
    await _creer_anomalie(
        db_session, regle="R01", gravite="haute", bloc_id=bloc_non_recu.id
    )
    bloc_sans_bon = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=1,
        numero_bl="PDB-OUVERT",
        chantier_id=chantier.id,
        statut_rapprochement="pas_de_bon",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_sans_bon, montant_ht=Decimal("25.00")
    )
    await _creer_anomalie(
        db_session, regle="R02", gravite="haute", bloc_id=bloc_sans_bon.id
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    ligne = next(c for c in tdb.chantiers if c.chantier_id == chantier.id)
    assert ligne.etat == "bl_manquant"
    assert ligne.a_verifier == Decimal("65.00")
    assert (tdb.nb_bl_factures, tdb.nb_bl_recus, tdb.nb_bl_manquants) == (2, 0, 1)


async def test_tableau_de_bord_prix_sur_bloc_non_recu_compte_une_seule_fois(
    db_session: AsyncSession,
) -> None:
    """SERVEUR-2, scénario 1 : un seul bloc non reçu de 1 000 € portant une
    R08 ouverte (R07-R09 s'évaluent quel que soit l'état du BL) et son R01.
    L'ancienne formule `en_ecart + non_justifie` donnait 2 000 € à vérifier,
    plus que le facturé."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Double")
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-FIN-DOUBLE",
        date_doc=date(2026, 9, 5),
    )
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        numero_bl="NR-PRIX",
        chantier_id=chantier.id,
        statut_rapprochement="non_recu",
    )
    ligne = await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("1000.00")
    )
    await _creer_anomalie(db_session, regle="R01", gravite="haute", bloc_id=bloc.id)
    await _creer_anomalie(
        db_session, regle="R08", gravite="haute", bloc_id=bloc.id, ligne_id=ligne.id
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.totaux.facture_ht == Decimal("1000.00")
    assert tdb.totaux.en_ecart == Decimal("1000.00")
    assert tdb.totaux.non_justifie == Decimal("1000.00")
    assert tdb.totaux.conforme == Decimal("0")
    ligne_chantier = next(c for c in tdb.chantiers if c.chantier_id == chantier.id)
    assert ligne_chantier.a_verifier == Decimal("1000.00")
    assert ligne_chantier.etat == "bl_manquant"


async def test_tableau_de_bord_conforme_ne_retire_pas_un_bloc_non_recu(
    db_session: AsyncSession,
) -> None:
    """SERVEUR-2, scénario 2 : bloc A reçu de 1 000 € sans anomalie, bloc B
    non reçu de 800 € avec une R09 ouverte. L'ancienne formule « rapproché -
    en écart » donnait « Conforme 200 € » au lieu de 1 000 €."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Conforme")
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-FIN-CONF",
        date_doc=date(2026, 9, 6),
    )
    bloc_a = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=0,
        numero_bl="A-RECU",
        chantier_id=chantier.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc_a, montant_ht=Decimal("1000.00")
    )
    bloc_b = await _creer_bloc(
        db_session,
        facture=facture,
        ordre=1,
        numero_bl="B-NON-RECU",
        chantier_id=chantier.id,
        statut_rapprochement="non_recu",
    )
    ligne_b = await _creer_ligne(
        db_session, document=facture, bloc=bloc_b, montant_ht=Decimal("800.00")
    )
    await _creer_anomalie(db_session, regle="R01", gravite="haute", bloc_id=bloc_b.id)
    await _creer_anomalie(
        db_session,
        regle="R09",
        gravite="moyenne",
        bloc_id=bloc_b.id,
        ligne_id=ligne_b.id,
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.totaux.rapproche == Decimal("1000.00")
    assert tdb.totaux.en_ecart == Decimal("800.00")
    assert tdb.totaux.conforme == Decimal("1000.00")
    ligne_chantier = next(c for c in tdb.chantiers if c.chantier_id == chantier.id)
    assert ligne_chantier.montants.conforme == Decimal("1000.00")
    assert ligne_chantier.a_verifier == Decimal("800.00")


async def test_tableau_de_bord_exclut_une_facture_archivee(
    db_session: AsyncSession,
) -> None:
    """SERVEUR-8 : une facture archivée (et ses anomalies, même restées
    ouvertes) n'entre dans aucun total, aucun compte, aucun état."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Archive")
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-FIN-ARCH",
        date_doc=date(2026, 9, 7),
    )
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        numero_bl="ARCH1",
        chantier_id=chantier.id,
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("70.00")
    )
    await _creer_anomalie(db_session, regle="R01", gravite="haute", bloc_id=bloc.id)
    facture.statut = "archive"
    await db_session.commit()

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.chantiers == []
    assert tdb.totaux.facture_ht == Decimal("0")
    assert (tdb.nb_bl_factures, tdb.nb_bl_manquants) == (0, 0)
    assert tdb.nb_problemes_ouverts == 0
    assert tdb.dernier_mois_facture is None


async def test_tableau_de_bord_etat_suit_la_categorie_unique(
    db_session: AsyncSession,
) -> None:
    """SERVEUR-3 : l'état d'un chantier suit la table unique des catégories
    (`ingest.anomalies.CATEGORIES_REGLE`), la même que les filtres de
    l'écran « À régler » -- une R05 seule donne « quantités », une R17
    seule (conditionnement, hors écart de quantité/prix) donne « à voir »."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier_r05 = await _creer_chantier(db_session, nom="Chantier R05")
    chantier_r17 = await _creer_chantier(db_session, nom="Chantier R17")
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-FIN-CAT",
        date_doc=date(2026, 9, 8),
    )
    for ordre, (chantier, regle, gravite) in enumerate(
        ((chantier_r05, "R05", "haute"), (chantier_r17, "R17", "moyenne"))
    ):
        bloc = await _creer_bloc(
            db_session,
            facture=facture,
            ordre=ordre,
            numero_bl=f"CAT{ordre}",
            chantier_id=chantier.id,
            statut_rapprochement="recu",
        )
        ligne = await _creer_ligne(
            db_session, document=facture, bloc=bloc, montant_ht=Decimal("12.00")
        )
        await _creer_anomalie(
            db_session, regle=regle, gravite=gravite, bloc_id=bloc.id, ligne_id=ligne.id
        )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    etats = {c.nom_canonique: c.etat for c in tdb.chantiers}
    assert etats == {"Chantier R05": "quantites", "Chantier R17": "a_voir"}
    a_verifier = {c.nom_canonique: c.a_verifier for c in tdb.chantiers}
    assert a_verifier == {
        "Chantier R05": Decimal("12.00"),
        # R17 ouverte : « à vérifier » (définition unique de « Conforme »,
        # décision d'Ilane du 29/09/2026), même si ce n'est pas un écart de
        # quantité ou de prix.
        "Chantier R17": Decimal("12.00"),
    }


async def test_tableau_de_bord_normalise_le_mois_et_signe_des_montants(
    db_session: AsyncSession,
) -> None:
    """SERVEUR-7 : `mois` est toujours ramené au 1er du mois. ECRAN-8 :
    `montant_en_jeu` d'une R05 négative (avoir) reste signé, comme dans
    `detail` -- seule la clé de tri prend sa valeur absolue."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-FIN-SIGNE",
        date_doc=date(2026, 9, 9),
    )
    blocs = [
        await _creer_bloc(db_session, facture=facture, ordre=i, numero_bl=f"S{i}")
        for i in range(2)
    ]
    for bloc in blocs:
        await _creer_ligne(
            db_session, document=facture, bloc=bloc, montant_ht=Decimal("10.00")
        )
    await _creer_anomalie(
        db_session,
        regle="R05",
        gravite="haute",
        bloc_id=blocs[0].id,
        detail={"montant": "-45.00"},
    )
    await _creer_anomalie(
        db_session,
        regle="R05",
        gravite="haute",
        bloc_id=blocs[1].id,
        detail={"montant": "30.00"},
    )

    tdb = await tableau_de_bord(db_session, mois=date(2026, 9, 17))

    assert tdb.mois == _SEPT
    assert [p.montant_en_jeu for p in tdb.priorites] == [
        Decimal("-45.00"),
        Decimal("30.00"),
    ]


async def test_tableau_de_bord_dernier_mois_facture(db_session: AsyncSession) -> None:
    """COUVERTURE-26 : le serveur indique le dernier mois qui a une facture
    (ici août), même quand le mois demandé (septembre) n'en a aucune."""
    fournisseur = await _creer_fournisseur(db_session)
    assert (await tableau_de_bord(db_session, mois=_SEPT)).dernier_mois_facture is None

    await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-FIN-JUIL",
        date_doc=date(2026, 7, 30),
    )
    await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-FIN-AOUT",
        date_doc=date(2026, 8, 20),
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.chantiers == []
    assert tdb.dernier_mois_facture == date(2026, 8, 1)


# --------------------------------------------------------------------------
# Bons reçus du mois (décision d'Ilane du 25/09/2026, tuile « Montant des
# bons reçus » -- voir docstring de module).
# --------------------------------------------------------------------------


async def test_tableau_de_bord_bons_recus_bl_et_enlevement_comptes_et_sommes(
    db_session: AsyncSession,
) -> None:
    """Un BL et un bon d'enlèvement, tous deux « recu » ce mois-ci et avec
    un montant, sont comptés et leurs montants sommés."""
    await _creer_bon(db_session, type_bon="bl", total_ht=Decimal("120.00"))
    await _creer_bon(db_session, type_bon="enlevement", total_ht=Decimal("80.00"))

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.nb_bons_recus == 2
    assert tdb.montant_bons_recus == Decimal("200.00")
    assert tdb.nb_bons_sans_montant == 0


async def test_tableau_de_bord_bons_a_verifier_et_archives_ne_comptent_pas(
    db_session: AsyncSession,
) -> None:
    """Négatif : ni un bon encore « a_verifier » (pas confirmé), ni un bon
    « archive » (sorti du suivi actif) ne comptent dans les bons reçus."""
    await _creer_bon(db_session, statut="a_verifier", total_ht=Decimal("50.00"))
    await _creer_bon(db_session, statut="archive", total_ht=Decimal("50.00"))

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.nb_bons_recus == 0
    assert tdb.montant_bons_recus == Decimal("0")
    assert tdb.nb_bons_sans_montant == 0


async def test_tableau_de_bord_bon_autre_mois_ne_compte_pas(
    db_session: AsyncSession,
) -> None:
    """Négatif : un bon reçu daté de juillet ne compte pas dans le tableau
    de bord de septembre."""
    await _creer_bon(db_session, date_doc=date(2026, 7, 15), total_ht=Decimal("50.00"))

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.nb_bons_recus == 0
    assert tdb.montant_bons_recus == Decimal("0")


async def test_tableau_de_bord_facture_ne_compte_pas_dans_bons_recus(
    db_session: AsyncSession,
) -> None:
    """Négatif : une facture (même « recu », même mois) n'est pas un bon --
    `TYPES_BL` ne la contient pas."""
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-BONS-1",
        date_doc=date(2026, 9, 5),
    )

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.nb_bons_recus == 0
    assert tdb.montant_bons_recus == Decimal("0")


async def test_tableau_de_bord_bon_sans_montant(db_session: AsyncSession) -> None:
    """Beaucoup de bons n'ont pas de prix imprimé (docstring de module) : un
    bon sans `total_ht` compte dans `nb_bons_recus` et
    `nb_bons_sans_montant`, jamais dans `montant_bons_recus`."""
    await _creer_bon(db_session, total_ht=None)
    await _creer_bon(db_session, total_ht=Decimal("40.00"))

    tdb = await tableau_de_bord(db_session, mois=_SEPT)

    assert tdb.nb_bons_recus == 2
    assert tdb.nb_bons_sans_montant == 1
    assert tdb.montant_bons_recus == Decimal("40.00")


async def test_tableau_de_bord_bon_sans_date_doc_range_selon_created_at(
    db_session: AsyncSession,
) -> None:
    """Même repli que le bilan (L5-D4, `ingest.bilan._condition_mois`) : un
    bon sans `date_doc` est rangé selon sa date de dépôt (`created_at`),
    convertie en Europe/Paris -- positif sur le mois de dépôt, négatif sur
    un autre mois demandé."""
    await _creer_bon(
        db_session,
        date_doc=None,
        created_at=datetime(2026, 9, 3, 10, tzinfo=FUSEAU_PARIS),
        total_ht=Decimal("60.00"),
    )

    tdb_septembre = await tableau_de_bord(db_session, mois=_SEPT)
    assert tdb_septembre.nb_bons_recus == 1
    assert tdb_septembre.montant_bons_recus == Decimal("60.00")

    tdb_juillet = await tableau_de_bord(db_session, mois=_JUILLET)
    assert tdb_juillet.nb_bons_recus == 0
