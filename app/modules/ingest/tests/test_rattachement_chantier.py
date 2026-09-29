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
from app.modules.ingest.anomalies import traiter_anomalie
from app.modules.ingest.lecture import DocumentIntrouvable
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Parametre,
    Utilisateur,
)
from app.modules.ingest.parametres import CLE_SEUIL_RESSEMBLANCE_CHANTIER
from app.modules.ingest.rattachement_chantier import (
    BilanReprise,
    choisir_chantier_document,
    rattacher_chantier_bloc,
    rattacher_chantier_document,
    reprendre_chantiers,
)
from app.modules.ingest.referentiels import ChantierIntrouvable

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


async def _admin(db_session: AsyncSession) -> Utilisateur:
    utilisateur = Utilisateur(
        email=f"admin.{uuid.uuid4()}@example.invalid",
        role="admin",
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.flush()
    return utilisateur


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


async def test_alerte_apres_decision_humaine_traitee_conserve_le_chantier(
    db_session: AsyncSession,
) -> None:
    """Ruling 15 (A1, revue finale du 27/09/2026) : un bon dont la R18 a
    déjà été réglée par un humain (`choisir_chantier_document`, statut
    `traitee`) ne doit pas reperdre son chantier si une correction ultérieure
    de l'en-tête (ici simulée en rappelant `rattacher_chantier_document` sans
    changer nom lu/légende, comme le ferait `corrections
    ._resoudre_chantier_document`) retombe sur le même désaccord."""
    f = await _fournisseur(db_session)
    villa = await _chantier(db_session, "Villa Test")
    await _chantier(db_session, "Résidence des Tilleuls")
    admin = await _admin(db_session)
    bon = await _bon(
        db_session,
        fournisseur_id=f.id,
        chantier_brut="VILLA TEST",
        legende="tilleuls residence",
    )
    await rattacher_chantier_document(db_session, bon)
    await db_session.commit()

    await choisir_chantier_document(
        db_session, bon.id, chantier_id=villa.id, auteur_id=admin.id
    )
    await db_session.refresh(bon)
    assert bon.chantier_id == villa.id

    # Correction d'en-tête qui relance le rattachement -- même désaccord
    # nom lu/légende qu'au premier passage.
    r = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()
    await db_session.refresh(bon)

    assert r.methode == "décision humaine conservée"
    assert r.chantier_id == villa.id
    assert r.alerte is False
    assert bon.chantier_id == villa.id

    anomalies_r18 = (
        (
            await db_session.execute(
                select(Anomalie).where(
                    Anomalie.document_id == bon.id, Anomalie.regle == "R18"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(anomalies_r18) == 1
    assert anomalies_r18[0].statut == "traitee"


async def test_alerte_apres_decision_humaine_ignoree_conserve_sans_chantier(
    db_session: AsyncSession,
) -> None:
    """Même garde-fou (Ruling 15, A1) pour une R18 volontairement ignorée
    (`anomalies.traiter_anomalie`, statut `ignoree`) plutôt que réglée par un
    choix de chantier : le bon reste sans chantier, sans qu'une nouvelle R18
    `ouverte` ne réapparaisse."""
    f = await _fournisseur(db_session)
    await _chantier(db_session, "Villa Test")
    await _chantier(db_session, "Résidence des Tilleuls")
    admin = await _admin(db_session)
    bon = await _bon(
        db_session,
        fournisseur_id=f.id,
        chantier_brut="VILLA TEST",
        legende="tilleuls residence",
    )
    await rattacher_chantier_document(db_session, bon)
    await db_session.commit()

    anomalie = (
        await db_session.execute(
            select(Anomalie).where(
                Anomalie.document_id == bon.id, Anomalie.regle == "R18"
            )
        )
    ).scalar_one()
    await traiter_anomalie(
        db_session,
        anomalie.id,
        statut="ignoree",
        commentaire="Sans rapport avec ce bon.",
        auteur_id=admin.id,
    )
    await db_session.refresh(bon)
    assert bon.chantier_id is None

    r = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()
    await db_session.refresh(bon)

    assert r.methode == "décision humaine conservée"
    assert r.chantier_id is None
    assert r.alerte is False
    assert bon.chantier_id is None

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


# --------------------------------------------------------------------------
# choisir_chantier_document (Task 6, avenant du 27/09/2026, spec §2.4/§2.6)
# --------------------------------------------------------------------------


async def test_choisir_chantier_ferme_R18_et_journalise(
    db_session: AsyncSession,
) -> None:
    f = await _fournisseur(db_session)
    villa = await _chantier(db_session, "Villa Test")
    await _chantier(db_session, "Résidence des Tilleuls")
    admin = await _admin(db_session)
    bon = await _bon(
        db_session,
        fournisseur_id=f.id,
        chantier_brut="VILLA TEST",
        legende="tilleuls residence",
    )
    # Désaccord : lève la R18, le bon reste sans chantier.
    await rattacher_chantier_document(db_session, bon)
    await db_session.commit()
    anomalie = (
        await db_session.execute(
            select(Anomalie).where(
                Anomalie.document_id == bon.id, Anomalie.regle == "R18"
            )
        )
    ).scalar_one()
    assert anomalie.statut == "ouverte"

    resultat = await choisir_chantier_document(
        db_session, bon.id, chantier_id=villa.id, auteur_id=admin.id
    )
    await db_session.refresh(bon)
    await db_session.refresh(anomalie)

    assert resultat == villa.id
    assert bon.chantier_id == villa.id
    assert anomalie.statut == "traitee"
    assert anomalie.commentaire == "Chantier choisi : Villa Test"
    assert anomalie.traitee_par == admin.id
    assert anomalie.traitee_le is not None

    journal_anomalie = (
        await db_session.execute(
            select(Journal).where(
                Journal.cible_id == str(anomalie.id),
                Journal.action == "anomalie_traitee",
            )
        )
    ).scalar_one()
    assert journal_anomalie.apres == {
        "statut": "traitee",
        "commentaire": "Chantier choisi : Villa Test",
    }

    journal_chantier = (
        await db_session.execute(
            select(Journal).where(
                Journal.cible_id == str(bon.id),
                Journal.action == "chantier_choisi",
            )
        )
    ).scalar_one()
    assert journal_chantier.avant == {"chantier_id": None}
    assert journal_chantier.apres == {"chantier_id": str(villa.id)}


async def test_choisir_chantier_sans_r18_ouverte_ne_touche_aucune_anomalie(
    db_session: AsyncSession,
) -> None:
    """Choix du chantier depuis la fiche du bon (admin, hors alerte R18) :
    aucune anomalie à fermer, seul le journal `chantier_choisi` est écrit."""
    villa = await _chantier(db_session, "Villa Test")
    admin = await _admin(db_session)
    bon = await _bon(db_session, fournisseur_id=None, chantier_brut=None, legende=None)

    resultat = await choisir_chantier_document(
        db_session, bon.id, chantier_id=villa.id, auteur_id=admin.id
    )
    await db_session.refresh(bon)

    assert resultat == villa.id
    assert bon.chantier_id == villa.id
    nb_anomalies_traitees = (
        (await db_session.execute(select(Anomalie).where(Anomalie.regle == "R18")))
        .scalars()
        .all()
    )
    assert nb_anomalies_traitees == []
    journal_chantier = (
        await db_session.execute(
            select(Journal).where(
                Journal.cible_id == str(bon.id), Journal.action == "chantier_choisi"
            )
        )
    ).scalar_one()
    assert journal_chantier.apres == {"chantier_id": str(villa.id)}


async def test_choisir_chantier_document_archive_refuse(
    db_session: AsyncSession,
) -> None:
    villa = await _chantier(db_session, "Villa Test")
    admin = await _admin(db_session)
    bon = await _bon(db_session, fournisseur_id=None, chantier_brut=None, legende=None)
    bon.statut = "archive"
    await db_session.commit()

    with pytest.raises(DocumentIntrouvable):
        await choisir_chantier_document(
            db_session, bon.id, chantier_id=villa.id, auteur_id=admin.id
        )


async def test_choisir_chantier_document_inconnu(db_session: AsyncSession) -> None:
    villa = await _chantier(db_session, "Villa Test")
    admin = await _admin(db_session)

    with pytest.raises(DocumentIntrouvable):
        await choisir_chantier_document(
            db_session, uuid.uuid4(), chantier_id=villa.id, auteur_id=admin.id
        )


async def test_choisir_chantier_inconnu(db_session: AsyncSession) -> None:
    admin = await _admin(db_session)
    bon = await _bon(db_session, fournisseur_id=None, chantier_brut=None, legende=None)

    with pytest.raises(ChantierIntrouvable):
        await choisir_chantier_document(
            db_session, bon.id, chantier_id=uuid.uuid4(), auteur_id=admin.id
        )


# --------------------------------------------------------------------------
# reprendre_chantiers (Task 8, spec §2.8, avenant du 27/09/2026) — reprise,
# au déploiement, des noms en attente de l'ancien flux et des bons non
# archivés encore sans chantier.
# --------------------------------------------------------------------------


async def test_reprise_rattache_les_alias_en_attente(db_session: AsyncSession) -> None:
    """Trois alias en attente (`chantier_id IS NULL`, ancien flux), un par
    issue possible :
    - « villa existante » ressemble à un chantier déjà connu -> rattaché,
      sans création ;
    - « villa test » ne ressemble à rien -> un chantier est créé. Ruling du
      contrôleur (27/09/2026) : son nom vient du libellé BRUT le plus récent
      qui attend cet alias (« VILLA TEST (123) » sur le bloc de facture),
      jamais du libellé normalisé de l'alias (« villa test ») ;
    - « residence les pins » est ambigu entre deux chantiers homonymes ->
      reste en attente."""
    f = await _fournisseur(db_session)
    villa_existante = await _chantier(db_session, "Villa Existante")
    await _chantier(db_session, "Residence les Pins 1")
    await _chantier(db_session, "Residence les Pins 2")

    db_session.add_all(
        [
            ChantierAlias(
                fournisseur_id=f.id,
                libelle_brut="villa existante",
                code_brut=None,
                chantier_id=None,
            ),
            ChantierAlias(
                fournisseur_id=f.id,
                libelle_brut="villa test",
                code_brut=None,
                chantier_id=None,
            ),
            ChantierAlias(
                fournisseur_id=f.id,
                libelle_brut="residence les pins",
                code_brut=None,
                chantier_id=None,
            ),
        ]
    )
    facture = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"facture-invente-{uuid.uuid4()}.pdf",
        fournisseur_id=f.id,
    )
    db_session.add(facture)
    await db_session.flush()
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=0,
        chantier_brut="VILLA TEST (123)",
        chantier_id=None,
    )
    db_session.add(bloc)
    await db_session.commit()

    bilan = await reprendre_chantiers(db_session)

    assert bilan.alias_rattaches == 2  # villa existante + villa test
    assert bilan.chantiers_crees == 1  # seule « villa test » en a créé un
    assert bilan.alias_ambigus == 1  # residence les pins
    assert bilan.bons_rattaches == 0
    assert bilan.bons_en_alerte == 0

    alias_existante = (
        await db_session.execute(
            select(ChantierAlias).where(ChantierAlias.libelle_brut == "villa existante")
        )
    ).scalar_one()
    assert alias_existante.chantier_id == villa_existante.id

    alias_cree = (
        await db_session.execute(
            select(ChantierAlias).where(ChantierAlias.libelle_brut == "villa test")
        )
    ).scalar_one()
    assert alias_cree.chantier_id is not None
    chantier_cree = await db_session.get(Chantier, alias_cree.chantier_id)
    assert chantier_cree is not None
    assert chantier_cree.nom_canonique == "VILLA TEST"  # brut, jamais « villa test »
    assert chantier_cree.a_completer is True

    await db_session.refresh(bloc)
    assert bloc.chantier_id == chantier_cree.id

    alias_ambigu = (
        await db_session.execute(
            select(ChantierAlias).where(
                ChantierAlias.libelle_brut == "residence les pins"
            )
        )
    ).scalar_one()
    assert alias_ambigu.chantier_id is None


async def test_reprise_rattache_les_bons_sans_chantier(
    db_session: AsyncSession,
) -> None:
    """Aucun alias en attente ici : seule la seconde passe (bons non
    archivés, `chantier_id IS NULL`) est exercée -- un bon reconnu par
    ressemblance, un bon en désaccord (R18) et un bon archivé, exclu."""
    f = await _fournisseur(db_session)
    await _chantier(db_session, "Résidence des Tilleuls")
    await _chantier(db_session, "Atelier Nord")
    await _chantier(db_session, "Atelier Sud")

    reconnu = await _bon(
        db_session,
        fournisseur_id=f.id,
        chantier_brut="RESIDENCE DES TILLEULS",
        legende=None,
    )
    reconnu.type = "enlevement"
    en_alerte = await _bon(
        db_session,
        fournisseur_id=f.id,
        chantier_brut="ATELIER NORD",
        legende="atelier sud",
    )
    archive = await _bon(
        db_session,
        fournisseur_id=f.id,
        chantier_brut="RESIDENCE DES TILLEULS",
        legende=None,
    )
    archive.statut = "archive"
    await db_session.commit()

    bilan = await reprendre_chantiers(db_session)

    assert bilan.alias_rattaches == 0
    assert bilan.chantiers_crees == 0
    assert bilan.alias_ambigus == 0
    assert bilan.bons_rattaches == 1
    assert bilan.bons_en_alerte == 1

    await db_session.refresh(reconnu)
    await db_session.refresh(en_alerte)
    await db_session.refresh(archive)
    assert reconnu.chantier_id is not None
    assert en_alerte.chantier_id is None
    assert archive.chantier_id is None  # exclu (archivé), jamais touché

    anomalie = (
        await db_session.execute(
            select(Anomalie).where(
                Anomalie.document_id == en_alerte.id, Anomalie.regle == "R18"
            )
        )
    ).scalar_one()
    assert anomalie.statut == "ouverte"


async def test_reprise_idempotente(db_session: AsyncSession) -> None:
    """Un second appel ne retrouve plus rien à traiter (alias déjà rattaché,
    bon déjà rattaché) -> bilan entièrement à zéro."""
    f = await _fournisseur(db_session)
    await _chantier(db_session, "Villa Test")
    await _chantier(db_session, "Résidence des Tilleuls")

    db_session.add(
        ChantierAlias(
            fournisseur_id=f.id,
            libelle_brut="villa test",
            code_brut=None,
            chantier_id=None,
        )
    )
    await _bon(
        db_session,
        fournisseur_id=f.id,
        chantier_brut="RESIDENCE DES TILLEULS",
        legende=None,
    )
    await db_session.commit()

    premier = await reprendre_chantiers(db_session)
    assert premier == BilanReprise(
        alias_rattaches=1,
        chantiers_crees=0,
        alias_ambigus=0,
        bons_rattaches=1,
        bons_en_alerte=0,
    )

    second = await reprendre_chantiers(db_session)
    assert second == BilanReprise(
        alias_rattaches=0,
        chantiers_crees=0,
        alias_ambigus=0,
        bons_rattaches=0,
        bons_en_alerte=0,
    )


# --------------------------------------------------------------------------
# B-05 : noms ne différant que par un nombre -> jamais rattachés d'office
# --------------------------------------------------------------------------


async def test_voisin_numerote_leve_R18_sans_rattacher_ni_apprendre(
    db_session: AsyncSession,
) -> None:
    f = await _fournisseur(db_session)
    tilleuls12 = await _chantier(db_session, "Résidence Les Tilleuls 12")
    bon = await _bon(
        db_session,
        fournisseur_id=f.id,
        chantier_brut="RESIDENCE LES TILLEULS 13",
        legende=None,
    )

    r = await rattacher_chantier_document(db_session, bon)
    await db_session.commit()
    await db_session.refresh(bon)

    assert r.alerte is True and r.chantier_id is None and bon.chantier_id is None
    anomalie = (
        await db_session.execute(
            select(Anomalie).where(
                Anomalie.document_id == bon.id, Anomalie.regle == "R18"
            )
        )
    ).scalar_one()
    assert anomalie.statut == "ouverte"
    assert anomalie.detail["candidats"] == "Résidence Les Tilleuls 12"
    aucun_alias = (
        (
            await db_session.execute(
                select(ChantierAlias).where(
                    ChantierAlias.chantier_id == tilleuls12.id,
                    ChantierAlias.libelle_brut == "residence les tilleuls 13",
                )
            )
        )
        .scalars()
        .all()
    )
    assert aucun_alias == []


async def test_bloc_facture_voisin_numerote_non_rattache(
    db_session: AsyncSession,
) -> None:
    f = await _fournisseur(db_session)
    await _chantier(db_session, "Résidence Les Tilleuls 12")

    resultat = await rattacher_chantier_bloc(
        db_session, f.id, "Residence Les Tilleuls 13"
    )
    await db_session.commit()
    assert resultat is None
