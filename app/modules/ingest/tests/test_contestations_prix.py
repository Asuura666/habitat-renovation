"""Tests de `ingest.contestations_prix` (spec 2026-10-01 §4) : lecture des
alertes de prix contestées depuis la page Prix. Base de test réelle, données
entièrement inventées ; aides de construction reprises de `test_prix_page`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.contestations_prix import (
    charger_contestations,
    contestations_du_fournisseur,
)
from app.modules.ingest.grilles import FournisseurIntrouvable, retirer_produit
from app.modules.ingest.models import Anomalie, Document, Ligne
from app.modules.ingest.prix_bl import contester_prix
from app.modules.ingest.tests.test_prix_page import (
    _activer_controle,
    _anomalies_ouvertes_du_bon,
    _controler,
    _creer_bl,
    _creer_fournisseur,
    _creer_ligne,
    _creer_prix_grille,
    _creer_utilisateur,
)
from app.modules.normalize.prix import cle_produit

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _creer_anomalie_fermee(
    db_session: AsyncSession,
    *,
    document: Document,
    ligne: Ligne,
    regle: str = "R19",
    statut: str = "traitee",
    commentaire: str = "Contesté : prix négocié inventé",
    traitee_par: uuid.UUID | None = None,
    traitee_le: datetime = datetime(2026, 9, 30, 10, 0, tzinfo=UTC),
    detail: dict[str, str] | None = None,
) -> Anomalie:
    anomalie = Anomalie(
        regle=regle,
        gravite="haute",
        document_id=document.id,
        ligne_id=ligne.id,
        detail=detail
        if detail is not None
        else {
            "produit": "Produit inventé",
            "code": "REF1",
            "prix_bon": "12.00",
            "unite_bon": "u",
            "prix_grille": "10.00",
            "designation_grille": "Produit inventé",
            "methode": "reference",
        },
        statut=statut,
        commentaire=commentaire,
        traitee_par=traitee_par,
        traitee_le=traitee_le,
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)
    return anomalie


async def test_contestation_reelle_visible_dans_la_grille(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("12.00"))
    await _activer_controle(db_session)
    await _controler(db_session, document.id)
    ouvertes = await _anomalies_ouvertes_du_bon(db_session, document.id)
    assert ouvertes
    await contester_prix(
        db_session,
        anomalie_ids=[a.id for a in ouvertes],
        commentaire="Remise oubliée inventée",
        auteur_id=utilisateur.id,
    )

    resultat = await contestations_du_fournisseur(db_session, fournisseur.id)

    assert len(resultat) == 1
    c = resultat[0]
    assert c.commentaire == "Remise oubliée inventée"
    assert c.dans_la_grille is True
    assert c.cle_produit == cle_produit("REF1", "Produit inventé")
    assert c.prix_bon == Decimal("12.00")
    assert c.prix_grille == Decimal("10.00")
    assert c.auteur == utilisateur.email
    assert c.numero_bon == document.numero
    assert c.document_id == document.id
    assert "R19" in c.regles


async def test_ignoree_et_validee_exclues(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=document)
    await _creer_anomalie_fermee(
        db_session,
        document=document,
        ligne=ligne,
        statut="ignoree",
        commentaire="Ignoré depuis la page Prix",
    )
    await _creer_anomalie_fermee(
        db_session,
        document=document,
        ligne=ligne,
        regle="R20",
        commentaire="Prix validé inventé",
    )

    assert await contestations_du_fournisseur(db_session, fournisseur.id) == []


async def test_regle_hors_prix_exclue(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=document)
    await _creer_anomalie_fermee(
        db_session, document=document, ligne=ligne, regle="R01"
    )

    assert await contestations_du_fournisseur(db_session, fournisseur.id) == []


async def test_deux_regles_meme_ligne_une_seule_contestation(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=document)
    await _creer_anomalie_fermee(
        db_session, document=document, ligne=ligne, regle="R19"
    )
    await _creer_anomalie_fermee(
        db_session, document=document, ligne=ligne, regle="R20"
    )

    resultat = await contestations_du_fournisseur(db_session, fournisseur.id)

    assert len(resultat) == 1
    assert resultat[0].regles == ("R19", "R20")


async def test_bon_archive_exclu(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=document)
    await _creer_anomalie_fermee(db_session, document=document, ligne=ligne)
    document.statut = "archive"
    await db_session.commit()

    assert await contestations_du_fournisseur(db_session, fournisseur.id) == []


async def test_autre_fournisseur_exclu(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    autre = await _creer_fournisseur(db_session)
    document = await _creer_bl(db_session, fournisseur=autre)
    ligne = await _creer_ligne(db_session, document=document)
    await _creer_anomalie_fermee(db_session, document=document, ligne=ligne)

    assert await contestations_du_fournisseur(db_session, fournisseur.id) == []
    assert len(await contestations_du_fournisseur(db_session, autre.id)) == 1


async def test_produit_retire_absent_de_la_grille(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=document)
    await _creer_anomalie_fermee(db_session, document=document, ligne=ligne)

    avant = await contestations_du_fournisseur(db_session, fournisseur.id)
    assert [c.dans_la_grille for c in avant] == [True]

    await retirer_produit(
        db_session,
        fournisseur.id,
        cle_produit("REF1", "Produit inventé"),
        datetime.now(UTC).date(),
        auteur_id=None,
    )

    apres = await contestations_du_fournisseur(db_session, fournisseur.id)
    assert len(apres) == 1
    assert apres[0].dans_la_grille is False


async def test_r25_seule_sans_prix_du_bon(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=document)
    await _creer_anomalie_fermee(
        db_session,
        document=document,
        ligne=ligne,
        regle="R25",
        detail={
            "produit": "Produit inventé",
            "code": "REF1",
            "prix_grille": "10.00",
            "date_grille": "2025-01-01",
            "age_mois": "20",
        },
    )

    resultat = await contestations_du_fournisseur(db_session, fournisseur.id)

    assert len(resultat) == 1
    assert resultat[0].prix_bon is None
    assert resultat[0].unite_bon is None
    assert resultat[0].prix_grille == Decimal("10.00")


async def test_ordre_et_limite(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    for heure, commentaire in (
        (8, "Contesté : un"),
        (12, "Contesté : trois"),
        (10, "Contesté : deux"),
    ):
        ligne = await _creer_ligne(db_session, document=document, code_brut=f"R{heure}")
        await _creer_anomalie_fermee(
            db_session,
            document=document,
            ligne=ligne,
            commentaire=commentaire,
            traitee_le=datetime(2026, 9, 30, heure, 0, tzinfo=UTC),
        )

    tout = await charger_contestations(db_session, fournisseur_id=fournisseur.id)
    limitees = await charger_contestations(
        db_session, fournisseur_id=fournisseur.id, limite=2
    )

    assert [c.commentaire for c in tout] == ["trois", "deux", "un"]
    assert [c.commentaire for c in limitees] == ["trois", "deux"]


async def test_bornes_depuis_avant(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    debut = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)
    fin = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    for code, quand, commentaire in (
        ("A", debut, "Contesté : au début"),
        ("B", fin, "Contesté : à la fin"),
        ("C", datetime(2026, 10, 1, tzinfo=UTC), "Contesté : au milieu"),
    ):
        ligne = await _creer_ligne(db_session, document=document, code_brut=code)
        await _creer_anomalie_fermee(
            db_session,
            document=document,
            ligne=ligne,
            commentaire=commentaire,
            traitee_le=quand,
        )

    resultat = await charger_contestations(
        db_session, fournisseur_id=fournisseur.id, depuis=debut, avant=fin
    )

    assert sorted(c.commentaire for c in resultat) == ["au début", "au milieu"]


async def test_fournisseur_inconnu(db_session: AsyncSession) -> None:
    with pytest.raises(FournisseurIntrouvable):
        await contestations_du_fournisseur(db_session, uuid.uuid4())


async def test_auteur_nom_prefere_a_email(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    utilisateur = await _creer_utilisateur(db_session)
    utilisateur.nom = "Admin inventé"
    await db_session.commit()
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=document)
    await _creer_anomalie_fermee(
        db_session, document=document, ligne=ligne, traitee_par=utilisateur.id
    )

    resultat = await contestations_du_fournisseur(db_session, fournisseur.id)

    assert resultat[0].auteur == "Admin inventé"
