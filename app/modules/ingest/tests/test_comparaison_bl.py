"""Tests de `ingest/comparaison_bl.py` (Task 3, refonte front) : comparaison
d'un BL avec la facture qui le cite.

Base de test réelle (`bl_test_t3` en local, voir la consigne de la tâche),
données entièrement inventées (R17 — jamais `tests/fixtures/`). Le lien BL ->
bloc de facture réutilise `BlocFacture.bl_document_id`, déjà utilisé par
`ingest.bilan.bilan_par_bl` — jamais recalculé par correspondance de numéro
(`documents_bl_par_numeros`), contrairement à `facture_detail`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.comparaison_bl import ComparaisonBl, LigneComparee, comparer_bl
from app.modules.ingest.lecture import DocumentIntrouvable
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Document,
    Fournisseur,
    Ligne,
    RapprochementLigne,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur Testeur"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_document_bl(
    db_session: AsyncSession, *, numero: str = "L1000", type_: str = "bl"
) -> Document:
    document = Document(
        type=type_,
        source="telegram",
        statut="recu",
        fichier_path=f"/var/docs/{uuid.uuid4()}.jpg",
        numero=numero,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_facture(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    numero: str = "FAC0001",
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path="/var/docs/facture-invente.pdf",
        fournisseur_id=fournisseur.id,
        numero=numero,
        total_ht=Decimal("100.00"),
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
    numero_bl: str | None = "L1000",
    bl_document_id: uuid.UUID | None = None,
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=ordre,
        numero_bl=numero_bl,
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
    bloc: BlocFacture | None = None,
    ordre: int,
    code_brut: str | None = "ART1",
    article_brut: str | None = "Article inventé",
    qte_livree: Decimal | None = None,
    qte_totale: Decimal | None = None,
    pu_ht: Decimal | None = None,
    montant_ht: Decimal | None = None,
    type_ligne: str = "article",
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        bloc_id=bloc.id if bloc is not None else None,
        code_brut=code_brut,
        article_brut=article_brut,
        qte_livree=qte_livree,
        qte_totale=qte_totale,
        pu_ht=pu_ht,
        montant_ht=montant_ht,
        type_ligne=type_ligne,
        ordre=ordre,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _creer_rapprochement(
    db_session: AsyncSession,
    *,
    ligne_facture: Ligne,
    ligne_bl: Ligne,
    methode: str = "code",
) -> RapprochementLigne:
    rapprochement = RapprochementLigne(
        ligne_facture_id=ligne_facture.id,
        ligne_bl_id=ligne_bl.id,
        methode=methode,
    )
    db_session.add(rapprochement)
    await db_session.commit()
    return rapprochement


async def _creer_anomalie(
    db_session: AsyncSession,
    *,
    ligne_id: uuid.UUID | None = None,
    bloc_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    regle: str = "R08",
    statut: str = "ouverte",
    gravite: str = "haute",
) -> Anomalie:
    anomalie = Anomalie(
        regle=regle,
        gravite=gravite,
        statut=statut,
        ligne_id=ligne_id,
        bloc_id=bloc_id,
        document_id=document_id,
        detail={"cle": "valeur"},
        traitee_le=datetime.now(UTC) if statut != "ouverte" else None,
        commentaire="Traitée (test)." if statut != "ouverte" else None,
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)
    return anomalie


# --------------------------------------------------------------------------
# comparer_bl
# --------------------------------------------------------------------------


async def test_comparer_bl_id_inconnu_leve_document_introuvable(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(DocumentIntrouvable):
        await comparer_bl(db_session, uuid.uuid4())


async def test_comparer_bl_document_facture_leve_document_introuvable(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)

    with pytest.raises(DocumentIntrouvable):
        await comparer_bl(db_session, facture.id)


async def test_comparer_bl_scenario_complet(db_session: AsyncSession) -> None:
    """Un BL à 3 lignes, une facture dont le bloc cite ce BL, 2 lignes
    appariées via `rapprochement_ligne`, une R08 ouverte sur une ligne
    facture — voir le docstring du module pour le détail de chaque champ.

    Les lignes du BL posent volontairement un `qte_livree` (conditionnement,
    L3-D24) différent de leur `qte_totale` — la ligne 2 n'a même aucun
    conditionnement (`qte_livree=None`, cas réel le plus courant) — pour
    que les assertions `qte_livree == …` ci-dessous portent bien sur
    `Ligne.qte_totale`, jamais sur `Ligne.qte_livree` (tour de correction
    2, Task 8 — constat de revue)."""
    bl = await _creer_document_bl(db_session, numero="L2000")
    bl_ligne_0 = await _creer_ligne(
        db_session,
        document=bl,
        ordre=0,
        code_brut="ART-A",
        article_brut="Article A",
        qte_livree=Decimal("1"),
        qte_totale=Decimal("5"),
    )
    bl_ligne_1 = await _creer_ligne(
        db_session,
        document=bl,
        ordre=1,
        code_brut="ART-B",
        article_brut="Article B",
        qte_livree=Decimal("1"),
        qte_totale=Decimal("3"),
    )
    await _creer_ligne(
        db_session,
        document=bl,
        ordre=2,
        code_brut="ART-C",
        article_brut="Article C",
        qte_livree=None,
        qte_totale=Decimal("7"),
    )

    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="FAC-CMP"
    )
    bloc = await _creer_bloc(
        db_session, facture=facture, numero_bl="L2000", bl_document_id=bl.id
    )
    f_ligne_a = await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        ordre=0,
        code_brut="ART-A",
        qte_totale=Decimal("5"),
        pu_ht=Decimal("10.00"),
        montant_ht=Decimal("50.00"),
    )
    f_ligne_b = await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        ordre=1,
        code_brut="ART-B",
        qte_totale=Decimal("3"),
        pu_ht=Decimal("20.00"),
        montant_ht=Decimal("60.00"),
    )
    await _creer_rapprochement(db_session, ligne_facture=f_ligne_a, ligne_bl=bl_ligne_0)
    await _creer_rapprochement(db_session, ligne_facture=f_ligne_b, ligne_bl=bl_ligne_1)
    await _creer_anomalie(db_session, ligne_id=f_ligne_b.id, regle="R08")
    # Anomalie traitée (fermée) sur la même ligne : ne doit jamais apparaître
    # dans `regles_ouvertes` (seules les anomalies `statut == "ouverte"`
    # comptent).
    await _creer_anomalie(
        db_session, ligne_id=f_ligne_b.id, regle="R07", statut="traitee"
    )

    comparaison = await comparer_bl(db_session, bl.id)

    assert isinstance(comparaison, ComparaisonBl)
    assert comparaison.document_id == bl.id
    assert comparaison.facture_id == facture.id
    assert comparaison.numero_facture == "FAC-CMP"
    assert comparaison.montant_facture_ht == Decimal("110.00")
    # Une seule anomalie ouverte dans tout ce scénario (R08 sur f_ligne_b) —
    # la R07 traitée ne compte jamais.
    assert comparaison.nb_problemes == 1

    assert [ligne.ordre for ligne in comparaison.lignes] == [0, 1, 2]

    ligne_0, ligne_1, ligne_2 = comparaison.lignes
    assert isinstance(ligne_0, LigneComparee)
    assert ligne_0.code == "ART-A"
    assert ligne_0.article == "Article A"
    assert ligne_0.qte_livree == Decimal("5")
    assert ligne_0.qte_facturee == Decimal("5")
    assert ligne_0.pu_facture == Decimal("10.00")
    assert ligne_0.regles_ouvertes == []

    assert ligne_1.qte_livree == Decimal("3")
    assert ligne_1.qte_facturee == Decimal("3")
    assert ligne_1.pu_facture == Decimal("20.00")
    assert ligne_1.regles_ouvertes == ["R08"]

    # Ligne 2 : aucun appariement (`rapprochement_ligne`) -> jamais facturée
    # au sens de cette comparaison.
    assert ligne_2.qte_livree == Decimal("7")
    assert ligne_2.qte_facturee is None
    assert ligne_2.pu_facture is None
    assert ligne_2.regles_ouvertes == []


async def test_comparer_bl_sans_facture_qui_le_cite(db_session: AsyncSession) -> None:
    """Aucun bloc de facture ne porte `bl_document_id == bl.id` (photo
    reçue mais rapprochement jamais tourné, ou aucune facture ne la cite
    encore) : `facture_id`/`numero_facture`/`montant_facture_ht` valent
    `None`, chaque ligne reste sans appariement."""
    bl = await _creer_document_bl(db_session, numero="L2001")
    await _creer_ligne(db_session, document=bl, ordre=0, qte_livree=Decimal("1"))

    comparaison = await comparer_bl(db_session, bl.id)

    assert comparaison.facture_id is None
    assert comparaison.numero_facture is None
    assert comparaison.montant_facture_ht is None
    assert len(comparaison.lignes) == 1
    assert comparaison.lignes[0].qte_facturee is None


async def test_comparer_bl_anomalie_sur_ligne_bl_directement(
    db_session: AsyncSession,
) -> None:
    """Une anomalie ouverte peut porter directement sur `ligne_id` d'une
    ligne du BL (pas seulement sur sa ligne facture appariée)."""
    bl = await _creer_document_bl(db_session, numero="L2002")
    bl_ligne = await _creer_ligne(
        db_session, document=bl, ordre=0, qte_livree=Decimal("2")
    )
    await _creer_anomalie(db_session, ligne_id=bl_ligne.id, regle="R06")

    comparaison = await comparer_bl(db_session, bl.id)

    assert comparaison.lignes[0].regles_ouvertes == ["R06"]
    assert comparaison.nb_problemes == 1


async def test_comparer_bl_qte_livree_vient_de_qte_totale_jamais_du_conditionnement(
    db_session: AsyncSession,
) -> None:
    """Constat de revue (tour 2, Task 8) : `LigneComparee.qte_livree`
    affichait `Ligne.qte_livree` (nombre de conditionnements, souvent nul,
    L3-D24) au lieu de `Ligne.qte_totale` (quantité comparable à
    `qte_facturee`, celle qu'utilisent R03 et le bilan) — un BL sans
    conditionnement renseigné affichait « — » au lieu de la quantité
    livrée. Ici, `qte_livree` est nul (cas réel le plus fréquent,
    ex. BLD0005) alors que `qte_totale` porte la vraie quantité."""
    bl = await _creer_document_bl(db_session, numero="L2008")
    await _creer_ligne(
        db_session,
        document=bl,
        ordre=0,
        qte_livree=None,
        qte_totale=Decimal("10"),
    )

    comparaison = await comparer_bl(db_session, bl.id)

    assert comparaison.lignes[0].qte_livree == Decimal("10")


# --------------------------------------------------------------------------
# nb_problemes (tour de correction 1, Task 8) — constat de revue : le
# front affichait « Conforme » et sous-comptait les problèmes en ne
# sommant que `regles_ouvertes`, qui ne rassemble que les anomalies
# rattachées à une ligne du BL ou à sa ligne facture appariée. Ces tests
# couvrent les trois catégories d'anomalies qu'une telle somme manque.
# --------------------------------------------------------------------------


async def test_comparer_bl_nb_problemes_compte_une_ligne_facture_non_appariee(
    db_session: AsyncSession,
) -> None:
    """R05 (« facturée mais absente du bon ») porte sur une ligne de
    facture jamais appariée à une ligne de BL : elle n'apparaît dans
    aucune `LigneComparee.regles_ouvertes` (aucune ligne du BL ne la
    représente), mais doit compter dans `nb_problemes`."""
    bl = await _creer_document_bl(db_session, numero="L2003")
    await _creer_ligne(db_session, document=bl, ordre=0, qte_livree=Decimal("2"))

    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="FAC-R05"
    )
    bloc = await _creer_bloc(
        db_session, facture=facture, numero_bl="L2003", bl_document_id=bl.id
    )
    ligne_non_appariee = await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        ordre=0,
        code_brut="ART-X",
        qte_totale=Decimal("4"),
        pu_ht=Decimal("15.00"),
        montant_ht=Decimal("60.00"),
    )
    await _creer_anomalie(db_session, ligne_id=ligne_non_appariee.id, regle="R05")

    comparaison = await comparer_bl(db_session, bl.id)

    assert comparaison.lignes[0].regles_ouvertes == []
    assert comparaison.nb_problemes == 1


async def test_comparer_bl_nb_problemes_compte_une_anomalie_de_bloc(
    db_session: AsyncSession,
) -> None:
    """R12 (doublon de facturation) ne porte que sur le bloc
    (`bloc_id`, `ligne_id` absent) — jamais rattachée à une ligne, donc
    jamais comptée par une somme de `regles_ouvertes`."""
    bl = await _creer_document_bl(db_session, numero="L2004")
    await _creer_ligne(db_session, document=bl, ordre=0, qte_livree=Decimal("1"))

    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="FAC-R12"
    )
    bloc = await _creer_bloc(
        db_session, facture=facture, numero_bl="L2004", bl_document_id=bl.id
    )
    await _creer_anomalie(db_session, bloc_id=bloc.id, regle="R12")

    comparaison = await comparer_bl(db_session, bl.id)

    assert comparaison.lignes[0].regles_ouvertes == []
    assert comparaison.nb_problemes == 1


async def test_comparer_bl_nb_problemes_compte_une_anomalie_du_document(
    db_session: AsyncSession,
) -> None:
    """R11 (incohérence arithmétique du BL) porte sur le document
    lui-même (`document_id`), pas sur une ligne ni sur un bloc — comptée
    même quand aucune facture ne cite encore ce BL."""
    bl = await _creer_document_bl(db_session, numero="L2005")
    await _creer_ligne(db_session, document=bl, ordre=0, qte_livree=Decimal("1"))
    await _creer_anomalie(db_session, document_id=bl.id, regle="R11")

    comparaison = await comparer_bl(db_session, bl.id)

    assert comparaison.facture_id is None
    assert comparaison.lignes[0].regles_ouvertes == []
    assert comparaison.nb_problemes == 1


async def test_comparer_bl_nb_problemes_zero_sans_anomalie(
    db_session: AsyncSession,
) -> None:
    bl = await _creer_document_bl(db_session, numero="L2006")
    await _creer_ligne(db_session, document=bl, ordre=0, qte_livree=Decimal("1"))

    comparaison = await comparer_bl(db_session, bl.id)

    assert comparaison.nb_problemes == 0


async def test_comparer_bl_nb_problemes_ignore_les_anomalies_traitees(
    db_session: AsyncSession,
) -> None:
    bl = await _creer_document_bl(db_session, numero="L2007")
    bl_ligne = await _creer_ligne(
        db_session, document=bl, ordre=0, qte_livree=Decimal("1")
    )
    await _creer_anomalie(
        db_session, ligne_id=bl_ligne.id, regle="R06", statut="traitee"
    )
    await _creer_anomalie(db_session, document_id=bl.id, regle="R11", statut="ignoree")

    comparaison = await comparer_bl(db_session, bl.id)

    assert comparaison.nb_problemes == 0
