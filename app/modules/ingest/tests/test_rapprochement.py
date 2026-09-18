"""Tests de `ingest/rapprochement.py` (L4-T7) : rapprochement facture <-> BL,
cœur du lot 4 — pour une facture, rapproche chaque bloc « Concerne le B.L. »
avec le BL déposé, apparie les lignes, convertit les quantités, alimente le
moteur de règles pur (`app.modules.rules`) et persiste le résultat (statut
de bloc, lignes de rapprochement, `qte_fact`, anomalies, journal) —
idempotent (L4-D3).

Base de test réelle (`bl_test`), données entièrement inventées (R17), sauf
le test de fixture réelle (`pytest.skip` si absente, assertions par
booléens calculés, Ruling R7 du lot 3).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.anomalies import lister_anomalies
from app.modules.ingest.corrections import valider_document
from app.modules.ingest.extraction_bl import enregistrer_extraction_bl
from app.modules.ingest.factures import deposer_facture
from app.modules.ingest.lecture import facture_detail
from app.modules.ingest.models import (
    Anomalie,
    Article,
    BlocFacture,
    Chantier,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    RapprochementLigne,
)
from app.modules.ingest.rapprochement import (
    FactureIntrouvable,
    rapprocher_facture,
    rapprocher_factures_du_bl,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

# --------------------------------------------------------------------------
# Aides de construction (données inventées)
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur Testeur"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_article(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    code: str = "ART1",
    unite_cdt: str | None = None,
    unite_fact: str | None = None,
    ratio: Decimal | None = None,
    valide: bool = True,
) -> Article:
    article = Article(
        fournisseur_id=fournisseur.id,
        code=code,
        unite_cdt=unite_cdt,
        unite_fact=unite_fact,
        ratio=ratio,
        valide=valide,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)
    return article


async def _creer_chantier(
    db_session: AsyncSession, *, nom: str = "Chantier Testeur"
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
    numero: str = "F0001",
    statut: str = "recu",
    date_doc: date | None = date(2026, 8, 15),
    total_ht: Decimal | None = None,
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero=numero,
        fournisseur_id=fournisseur.id,
        date_doc=date_doc,
        total_ht=total_ht,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_bl(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    numero: str = "L0001",
    statut: str = "recu",
    type_: str = "bl",
    date_doc: date | None = date(2026, 8, 1),
    chantier_brut: str | None = None,
    total_ht: Decimal | None = None,
) -> Document:
    document = Document(
        type=type_,
        source="telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        numero=numero,
        fournisseur_id=fournisseur.id,
        date_doc=date_doc,
        chantier_brut=chantier_brut,
        total_ht=total_ht,
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
    commentaire: str | None = None,
    chantier_id: uuid.UUID | None = None,
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=ordre,
        numero_bl=numero_bl,
        commentaire=commentaire,
        chantier_id=chantier_id,
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
    ordre: int = 0,
    type_ligne: str = "article",
    code_brut: str | None = "ART1",
    article_brut: str | None = "Article inventé",
    article: Article | None = None,
    qte_livree: Decimal | None = None,
    qte_totale: Decimal | None = None,
    unite_brut: str | None = None,
    pu_ht: Decimal | None = None,
    remise_pct: Decimal | None = None,
    montant_ht: Decimal | None = None,
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        bloc_id=bloc.id if bloc is not None else None,
        type_ligne=type_ligne,
        code_brut=code_brut,
        article_brut=article_brut,
        article_id=article.id if article is not None else None,
        qte_livree=qte_livree,
        qte_totale=qte_totale,
        unite_brut=unite_brut,
        pu_ht=pu_ht,
        remise_pct=remise_pct,
        montant_ht=montant_ht,
        ordre=ordre,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _rafraichir(db_session: AsyncSession, instance: Any) -> None:
    await db_session.refresh(instance)


async def _anomalies_de(
    db_session: AsyncSession, facture: Document
) -> Sequence[Anomalie]:
    """Toutes les anomalies rattachées à `facture` : par `document_id`
    (R10), par `bloc_id` (R01/R02/R12) ou par `ligne_id` (R03-R09, R13,
    R17 — ces règles ne portent ni `document_id` ni `bloc_id`, `rules
    .modeles.Anomalie`)."""
    return (
        (
            await db_session.execute(
                select(Anomalie).where(
                    (Anomalie.document_id == facture.id)
                    | (
                        Anomalie.bloc_id.in_(
                            select(BlocFacture.id).where(
                                BlocFacture.facture_id == facture.id
                            )
                        )
                    )
                    | (
                        Anomalie.ligne_id.in_(
                            select(Ligne.id).where(Ligne.document_id == facture.id)
                        )
                    )
                )
            )
        )
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------
# BL déposé avant : bloc reçu, lignes appariées, qte_fact convertie
# --------------------------------------------------------------------------


async def test_rapprocher_facture_bl_depose_avant_bloc_recu_lignes_appariees(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(
        db_session,
        fournisseur=fournisseur,
        unite_cdt="seau",
        unite_fact="kg",
        ratio=Decimal("25"),
    )
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0001")
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        article=article,
        qte_livree=Decimal("4"),
        qte_totale=Decimal("100"),
        unite_brut=None,  # une ligne de facture Unikalo n'imprime pas d'unité
        pu_ht=Decimal("10.00"),
        montant_ht=Decimal("1000.00"),
    )
    bl = await _creer_bl(db_session, fournisseur=fournisseur, numero="L0001")
    ligne_bl = await _creer_ligne(
        db_session,
        document=bl,
        bloc=None,
        article=article,
        qte_livree=Decimal("4"),
        qte_totale=Decimal("4"),
        unite_brut="seau",
        pu_ht=Decimal("10.00"),
        montant_ht=Decimal("1000.00"),
    )

    resultat = await rapprocher_facture(db_session, facture.id)

    ok = (
        resultat.nb_blocs == 1
        and resultat.nb_blocs_recus == 1
        and resultat.nb_blocs_pas_de_bon == 0
        and resultat.nb_lignes_appariees == 1
    )
    assert ok, "le bloc doit être reçu avec sa ligne appariée"

    await _rafraichir(db_session, bloc)
    assert bloc.statut_rapprochement == "recu"
    assert bloc.bl_document_id == bl.id

    ligne_facture = (
        await db_session.execute(select(Ligne).where(Ligne.bloc_id == bloc.id))
    ).scalar_one()
    await _rafraichir(db_session, ligne_facture)
    await _rafraichir(db_session, ligne_bl)
    ok = ligne_facture.qte_fact == Decimal("100") and ligne_bl.qte_fact == Decimal(
        "100"
    )
    assert ok, "les deux lignes doivent porter la même quantité convertie"

    rapprochements = (
        (
            await db_session.execute(
                select(RapprochementLigne).where(
                    RapprochementLigne.ligne_facture_id == ligne_facture.id
                )
            )
        )
        .scalars()
        .all()
    )
    ok = (
        len(rapprochements) == 1
        and rapprochements[0].ligne_bl_id == ligne_bl.id
        and rapprochements[0].methode == "code"
        and rapprochements[0].ecart_qte == Decimal("0")
    )
    assert ok, "la ligne facture doit être appariée par code sans écart"


async def test_rapprocher_facture_appariement_par_designation_si_code_absent(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0002")
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        code_brut=None,
        article_brut="Désignation Commune",
        qte_totale=Decimal("10"),
        montant_ht=Decimal("50.00"),
    )
    bl = await _creer_bl(db_session, fournisseur=fournisseur, numero="L0002")
    await _creer_ligne(
        db_session,
        document=bl,
        code_brut=None,
        article_brut="Désignation Commune",
        qte_totale=Decimal("10"),
        unite_brut=None,
        montant_ht=Decimal("50.00"),
    )

    resultat = await rapprocher_facture(db_session, facture.id)

    assert resultat.nb_lignes_appariees == 1
    ligne_facture = (
        await db_session.execute(select(Ligne).where(Ligne.bloc_id == bloc.id))
    ).scalar_one()
    rapprochement = (
        await db_session.execute(
            select(RapprochementLigne).where(
                RapprochementLigne.ligne_facture_id == ligne_facture.id
            )
        )
    ).scalar_one()
    assert rapprochement.methode == "libelle"


async def test_rapprocher_facture_ruling_r3_bl_a_verifier_pas_de_comparaison_qte(
    db_session: AsyncSession,
) -> None:
    """Ruling R3 du contrôleur : un bloc est `recu` dès qu'un BL non
    archivé du même fournisseur porte son numéro, quel que soit le statut de
    ce BL — mais le moteur ne compare les quantités (R03/R04) que si ce BL
    est lui-même `recu`. Ici le BL est encore `a_verifier` : le bloc doit
    devenir `recu`, sans anomalie de quantité malgré un écart marqué."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0003B")
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        qte_totale=Decimal("100"),
        unite_brut=None,
        montant_ht=Decimal("10.00"),
    )
    bl = await _creer_bl(
        db_session, fournisseur=fournisseur, numero="L0003B", statut="a_verifier"
    )
    await _creer_ligne(
        db_session,
        document=bl,
        qte_totale=Decimal("1"),
        unite_brut=None,
        montant_ht=Decimal("10.00"),
    )

    await rapprocher_facture(db_session, facture.id)

    await _rafraichir(db_session, bloc)
    ok = bloc.statut_rapprochement == "recu" and bloc.bl_document_id == bl.id
    assert ok, "Ruling R3 : le bloc doit être reçu même si le BL est à vérifier"

    anomalies = await _anomalies_de(db_session, facture)
    assert not any(a.regle in ("R03", "R04") for a in anomalies), (
        "Ruling R3 : aucune comparaison de quantité tant que le BL n'est pas reçu"
    )


# --------------------------------------------------------------------------
# Ruling R16 (fix round 2, L4-T7) : paire mixte unite_implicite
# --------------------------------------------------------------------------


async def test_rapprocher_facture_ruling_r16_paire_mixte_aucune_anomalie(
    db_session: AsyncSession,
) -> None:
    """Ruling R16 : la ligne de facture a un article résolu (ratio validé,
    unité de conditionnement imprimée) -> cas 5 de `convertir_en_unite_fact`,
    quantité multipliée par le ratio (2 -> 30). La ligne de BL appariée n'a
    ni article résolu ni unité imprimée -> cas 2, quantité rendue inchangée
    (2). Avant ce correctif, R03 comparait 30 à 2 et signalait une
    sur-facturation qui n'existe pas ; le Ruling R16 l'interdit (paire
    mixte : une seule ligne en unité implicite)."""
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(
        db_session,
        fournisseur=fournisseur,
        unite_cdt="seau",
        unite_fact="kg",
        ratio=Decimal("15"),
    )
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0016")
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        article=article,
        qte_livree=Decimal("2"),
        qte_totale=Decimal("2"),
        unite_brut="seau",  # unité de conditionnement imprimée -> cas 5
        montant_ht=Decimal("30.00"),
    )
    bl = await _creer_bl(db_session, fournisseur=fournisseur, numero="L0016")
    await _creer_ligne(
        db_session,
        document=bl,
        article=None,  # article non résolu côté BL
        qte_totale=Decimal("2"),
        unite_brut=None,  # aucune unité imprimée -> cas 2
        montant_ht=Decimal("30.00"),
    )

    resultat = await rapprocher_facture(db_session, facture.id)

    assert resultat.nb_lignes_appariees == 1
    anomalies = await _anomalies_de(db_session, facture)
    assert not any(a.regle in ("R03", "R04") for a in anomalies), (
        "Ruling R16 : une paire mixte (unité implicite d'un seul côté) ne "
        "doit produire ni R03 ni R04"
    )


# --------------------------------------------------------------------------
# BL déposé après : rejeu via rapprocher_factures_du_bl
# --------------------------------------------------------------------------


async def test_rapprocher_factures_du_bl_met_a_jour_le_bloc_apres_coup(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0003")
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("20.00")
    )

    premier = await rapprocher_facture(db_session, facture.id)
    assert premier.nb_blocs_recus == 0
    await _rafraichir(db_session, bloc)
    assert bloc.statut_rapprochement == "non_recu"

    bl = await _creer_bl(db_session, fournisseur=fournisseur, numero="L0003")

    resultats = await rapprocher_factures_du_bl(db_session, bl.id)

    assert len(resultats) == 1
    assert resultats[0].facture_id == facture.id
    assert resultats[0].nb_blocs_recus == 1

    await _rafraichir(db_session, bloc)
    ok = bloc.statut_rapprochement == "recu" and bloc.bl_document_id == bl.id
    assert ok, "le rejeu déclenché par le BL doit mettre le bloc à jour"


async def test_rapprocher_factures_du_bl_document_inconnu_liste_vide(
    db_session: AsyncSession,
) -> None:
    assert await rapprocher_factures_du_bl(db_session, uuid.uuid4()) == []


async def test_rapprocher_factures_du_bl_ignore_les_autres_fournisseurs(
    db_session: AsyncSession,
) -> None:
    fournisseur_a = await _creer_fournisseur(db_session, nom="Fournisseur A")
    fournisseur_b = await _creer_fournisseur(db_session, nom="Fournisseur B")
    facture = await _creer_facture(db_session, fournisseur=fournisseur_a)
    await _creer_bloc(db_session, facture=facture, numero_bl="L0004")

    bl_autre_fournisseur = await _creer_bl(
        db_session, fournisseur=fournisseur_b, numero="L0004"
    )

    resultats = await rapprocher_factures_du_bl(db_session, bl_autre_fournisseur.id)

    assert resultats == []


# --------------------------------------------------------------------------
# Mention « pas de bon » sans BL déposé
# --------------------------------------------------------------------------


async def test_rapprocher_facture_mention_pas_de_bon_sans_bl(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        numero_bl="L0005",
        commentaire="Livraison directe chantier, pas de bon remis",
    )

    resultat = await rapprocher_facture(db_session, facture.id)

    assert resultat.nb_blocs_recus == 0
    await _rafraichir(db_session, bloc)
    ok = bloc.statut_rapprochement == "pas_de_bon" and bloc.bl_document_id is None
    assert ok, "la mention doit produire le statut pas_de_bon"


async def test_rapprocher_facture_sans_bl_ni_mention_non_recu_et_anomalie_r01(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0006")

    resultat = await rapprocher_facture(db_session, facture.id)

    await _rafraichir(db_session, bloc)
    ok = (
        bloc.statut_rapprochement == "non_recu"
        and bloc.bl_document_id is None
        and resultat.nb_anomalies >= 1
    )
    assert ok, "un bloc sans BL ni mention doit rester non_recu avec une anomalie"

    anomalies = await _anomalies_de(db_session, facture)
    assert any(a.regle == "R01" and a.bloc_id == bloc.id for a in anomalies)


# --------------------------------------------------------------------------
# Idempotence : rejeu complet sans doublon
# --------------------------------------------------------------------------


async def test_rapprocher_facture_rejeu_sans_doublon(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0007")
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("30.00")
    )
    bl = await _creer_bl(db_session, fournisseur=fournisseur, numero="L0007")
    await _creer_ligne(
        db_session,
        document=bl,
        montant_ht=Decimal("30.00"),
        qte_totale=Decimal("1"),
        unite_brut=None,
    )

    await rapprocher_facture(db_session, facture.id)
    rapprochements_1 = (
        (await db_session.execute(select(RapprochementLigne))).scalars().all()
    )
    anomalies_1 = (await db_session.execute(select(Anomalie))).scalars().all()

    await rapprocher_facture(db_session, facture.id)
    rapprochements_2 = (
        (await db_session.execute(select(RapprochementLigne))).scalars().all()
    )
    anomalies_2 = (await db_session.execute(select(Anomalie))).scalars().all()

    ok = len(rapprochements_1) == len(rapprochements_2) and len(anomalies_1) == len(
        anomalies_2
    )
    assert ok, "un rejeu identique ne doit ni dupliquer ni faire disparaître de ligne"

    ids_rapprochements_1 = {r.id for r in rapprochements_1}
    ids_rapprochements_2 = {r.id for r in rapprochements_2}
    # Les lignes de rapprochement sont remplacées à chaque rejeu (décision du
    # contrôleur) : mêmes comptes, mais pas nécessairement les mêmes lignes.
    assert len(ids_rapprochements_1) == len(ids_rapprochements_2)


async def test_rapprocher_facture_journal_facture_rapprochee(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_bloc(db_session, facture=facture, numero_bl="L0008")

    await rapprocher_facture(db_session, facture.id)

    journal = (
        await db_session.execute(
            select(Journal).where(
                Journal.cible_id == str(facture.id),
                Journal.action == "facture_rapprochee",
            )
        )
    ).scalar_one()
    assert journal.utilisateur_id is None


# --------------------------------------------------------------------------
# Facture à vérifier : aucun rapprochement
# --------------------------------------------------------------------------


async def test_rapprocher_facture_a_verifier_ne_fait_rien(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, statut="a_verifier"
    )
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0009")

    resultat = await rapprocher_facture(db_session, facture.id)

    ok = (
        resultat.nb_blocs == 0
        and resultat.nb_blocs_recus == 0
        and resultat.nb_blocs_pas_de_bon == 0
        and resultat.nb_lignes_appariees == 0
        and resultat.nb_anomalies == 0
    )
    assert ok, "une facture à vérifier ne doit produire aucun résultat"

    await _rafraichir(db_session, bloc)
    assert bloc.statut_rapprochement is None
    assert bloc.bl_document_id is None

    aucun_journal = (
        await db_session.execute(
            select(Journal).where(
                Journal.cible_id == str(facture.id),
                Journal.action == "facture_rapprochee",
            )
        )
    ).first()
    assert aucun_journal is None


async def test_rapprocher_facture_id_inconnu_leve_facture_introuvable(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(FactureIntrouvable):
        await rapprocher_facture(db_session, uuid.uuid4())


async def test_rapprocher_facture_document_non_facture_leve_facture_introuvable(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    bl = await _creer_bl(db_session, fournisseur=fournisseur)
    with pytest.raises(FactureIntrouvable):
        await rapprocher_facture(db_session, bl.id)


# --------------------------------------------------------------------------
# R12 — doublon de facturation
# --------------------------------------------------------------------------


async def test_rapprocher_facture_doublon_numero_bl_autre_facture_anomalie_r12(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    premiere = await _creer_facture(db_session, fournisseur=fournisseur, numero="F0010")
    await _creer_bloc(db_session, facture=premiere, numero_bl="L0010")
    await rapprocher_facture(db_session, premiere.id)

    seconde = await _creer_facture(db_session, fournisseur=fournisseur, numero="F0011")
    bloc_seconde = await _creer_bloc(db_session, facture=seconde, numero_bl="L0010")

    resultat = await rapprocher_facture(db_session, seconde.id)

    assert resultat.nb_anomalies >= 1
    anomalies = await _anomalies_de(db_session, seconde)
    assert any(a.regle == "R12" and a.bloc_id == bloc_seconde.id for a in anomalies)


async def test_rapprocher_facture_doublon_facture_archivee_aucune_anomalie_r12(
    db_session: AsyncSession,
) -> None:
    """Fix round 1, finding 1 de la revue : une facture archivée (action
    corrective normale de l'admin, ex. déposée deux fois par erreur) ne doit
    jamais faire signaler R12 sur une facture légitime qui réutilise le même
    numéro de BL ensuite. Une facture non archivée avec le même numéro
    continue, elle, de déclencher R12 (non-régression)."""
    fournisseur = await _creer_fournisseur(db_session)
    archivee = await _creer_facture(db_session, fournisseur=fournisseur, numero="F0012")
    await _creer_bloc(db_session, facture=archivee, numero_bl="L0012")
    await rapprocher_facture(db_session, archivee.id)
    archivee.statut = "archive"
    await db_session.commit()

    legitime = await _creer_facture(db_session, fournisseur=fournisseur, numero="F0013")
    await _creer_bloc(db_session, facture=legitime, numero_bl="L0012")

    await rapprocher_facture(db_session, legitime.id)

    anomalies = await _anomalies_de(db_session, legitime)
    assert not any(a.regle == "R12" for a in anomalies), (
        "une facture archivée ne doit jamais produire de doublon R12"
    )

    # Non-régression : une troisième facture, non archivée, avec le même
    # numéro déclenche toujours R12 (contre `legitime`, la plus ancienne des
    # deux non archivées).
    troisieme = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F0014"
    )
    bloc_troisieme = await _creer_bloc(db_session, facture=troisieme, numero_bl="L0012")

    await rapprocher_facture(db_session, troisieme.id)

    anomalies_troisieme = await _anomalies_de(db_session, troisieme)
    assert any(
        a.regle == "R12" and a.bloc_id == bloc_troisieme.id for a in anomalies_troisieme
    ), "une facture non archivée avec le même numéro déclenche toujours R12"


# --------------------------------------------------------------------------
# Ruling R17 (fix round 2, L4-T7) : document_id sur les anomalies de facture
# --------------------------------------------------------------------------


async def test_rapprocher_facture_ruling_r17_document_id_sur_toutes_les_anomalies(
    db_session: AsyncSession,
) -> None:
    """La fiche L4-T7 demande que toute anomalie produite par
    `rapprocher_facture` porte `document_id = facture_id`, même une
    anomalie de bloc (R01) ou de ligne (R17) qui ne le porte pas nativement
    (seules R10/R11/R15 le font) -- sans quoi l'écran Anomalies ne peut pas
    remonter à la pièce (CDC §4.6)."""
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(
        db_session, fournisseur=fournisseur, ratio=Decimal("10"), valide=True
    )
    facture = await _creer_facture(db_session, fournisseur=fournisseur)

    # Bloc 1 : sans BL ni mention -> R01 (anomalie de bloc, document_id
    # natif None).
    await _creer_bloc(db_session, facture=facture, numero_bl="L0020A")

    # Bloc 2 : BL reçu, ligne avec conditionnement non entier -> R17
    # (anomalie de ligne, document_id natif None).
    bloc_2 = await _creer_bloc(db_session, facture=facture, numero_bl="L0020B")
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc_2,
        article=article,
        qte_livree=Decimal("2.5"),
        qte_totale=Decimal("25"),
        unite_brut=None,
        montant_ht=Decimal("100.00"),
    )
    bl_2 = await _creer_bl(db_session, fournisseur=fournisseur, numero="L0020B")
    await _creer_ligne(
        db_session,
        document=bl_2,
        article=article,
        qte_totale=Decimal("25"),
        unite_brut=None,
        montant_ht=Decimal("100.00"),
    )

    resultat = await rapprocher_facture(db_session, facture.id)
    assert resultat.nb_anomalies >= 2

    toutes = (
        (
            await db_session.execute(
                select(Anomalie).where(Anomalie.document_id == facture.id)
            )
        )
        .scalars()
        .all()
    )
    regles = {a.regle for a in toutes}
    ok = "R01" in regles and "R17" in regles and len(toutes) == resultat.nb_anomalies
    assert ok, "toutes les anomalies (bloc R01, ligne R17) doivent porter document_id"


async def test_rapprocher_facture_ruling_r17_idempotent_sur_rejeu(
    db_session: AsyncSession,
) -> None:
    """Deux rapprochements successifs ne doivent ni dupliquer l'anomalie de
    bloc (R01), ni changer son identifiant, une fois `document_id` renseigné
    par le correctif."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_bloc(db_session, facture=facture, numero_bl="L0021")

    await rapprocher_facture(db_session, facture.id)
    premieres = (await db_session.execute(select(Anomalie))).scalars().all()

    await rapprocher_facture(db_session, facture.id)
    secondes = (await db_session.execute(select(Anomalie))).scalars().all()

    ok = (
        len(premieres) == 1
        and len(secondes) == 1
        and premieres[0].id == secondes[0].id
        and premieres[0].document_id == facture.id
        and secondes[0].document_id == facture.id
    )
    assert ok, "un rejeu identique doit retrouver la même anomalie R01, sans doublon"


async def test_rapprocher_facture_ruling_r17_visible_du_filtre_fournisseur(
    db_session: AsyncSession,
) -> None:
    """Avant ce correctif, une anomalie de bloc (R01, `document_id` natif
    `None`) était invisible du filtre `fournisseur_id` de `lister_anomalies`
    (`_requete_anomalies` résout le fournisseur via `Document.fournisseur_id`,
    joint sur `Anomalie.document_id`)."""
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur R17")
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_bloc(db_session, facture=facture, numero_bl="L0022")

    await rapprocher_facture(db_session, facture.id)

    resultat = await lister_anomalies(db_session, fournisseur_id=fournisseur.id)
    ok = len(resultat) == 1 and resultat[0].regle == "R01"
    assert ok, "l'anomalie de bloc doit être visible du filtre fournisseur"


# --------------------------------------------------------------------------
# R13 — avoir sans origine
# --------------------------------------------------------------------------


async def test_rapprocher_facture_ligne_negative_sans_origine_anomalie_r13(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session)
    article = await _creer_article(
        db_session, fournisseur=fournisseur, code="ART-AVOIR"
    )
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(
        db_session, facture=facture, numero_bl="L0011", chantier_id=chantier.id
    )
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        article=article,
        code_brut="ART-AVOIR",
        montant_ht=Decimal("-50.00"),
    )

    resultat = await rapprocher_facture(db_session, facture.id)

    assert resultat.nb_anomalies >= 1
    anomalies = await _anomalies_de(db_session, facture)
    assert any(a.regle == "R13" for a in anomalies)


async def test_rapprocher_facture_ligne_negative_avec_origine_aucune_anomalie_r13(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session)
    article = await _creer_article(
        db_session, fournisseur=fournisseur, code="ART-AVOIR-OK"
    )

    origine = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F0020",
        date_doc=date(2026, 7, 1),
    )
    bloc_origine = await _creer_bloc(
        db_session, facture=origine, numero_bl="L0020", chantier_id=chantier.id
    )
    await _creer_ligne(
        db_session,
        document=origine,
        bloc=bloc_origine,
        article=article,
        code_brut="ART-AVOIR-OK",
        montant_ht=Decimal("50.00"),
    )
    await rapprocher_facture(db_session, origine.id)

    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F0021",
        date_doc=date(2026, 8, 1),
    )
    bloc = await _creer_bloc(
        db_session, facture=facture, numero_bl="L0021", chantier_id=chantier.id
    )
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        article=article,
        code_brut="ART-AVOIR-OK",
        montant_ht=Decimal("-50.00"),
    )

    await rapprocher_facture(db_session, facture.id)

    anomalies = await _anomalies_de(db_session, facture)
    assert not any(a.regle == "R13" for a in anomalies)


# --------------------------------------------------------------------------
# Historique de prix — R07/R08/R09
# --------------------------------------------------------------------------


async def test_rapprocher_facture_prix_hors_historique_anomalie_r07(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(db_session, fournisseur=fournisseur, code="ART-PRIX")

    for mois, numero in ((5, "H0001"), (6, "H0002"), (7, "H0003")):
        historique = await _creer_facture(
            db_session,
            fournisseur=fournisseur,
            numero=numero,
            date_doc=date(2026, mois, 1),
        )
        await _creer_ligne(
            db_session,
            document=historique,
            bloc=None,
            article=article,
            code_brut="ART-PRIX",
            pu_ht=Decimal("10.00"),
            montant_ht=Decimal("10.00"),
        )

    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F0030", date_doc=date(2026, 8, 15)
    )
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0030")
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        article=article,
        code_brut="ART-PRIX",
        pu_ht=Decimal("12.00"),
        montant_ht=Decimal("12.00"),
    )

    await rapprocher_facture(db_session, facture.id)

    anomalies = await _anomalies_de(db_session, facture)
    assert any(a.regle in ("R07", "R08") for a in anomalies)


async def test_rapprocher_facture_prix_conforme_sans_historique_suffisant(
    db_session: AsyncSession,
) -> None:
    """Moins de 3 occurrences (L4-D9) : aucune anomalie de prix, même avec un
    écart important."""
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(
        db_session, fournisseur=fournisseur, code="ART-PRIX-RARE"
    )

    historique = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="H0100", date_doc=date(2026, 7, 1)
    )
    await _creer_ligne(
        db_session,
        document=historique,
        bloc=None,
        article=article,
        code_brut="ART-PRIX-RARE",
        pu_ht=Decimal("10.00"),
        montant_ht=Decimal("10.00"),
    )

    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F0101", date_doc=date(2026, 8, 15)
    )
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0101")
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        article=article,
        code_brut="ART-PRIX-RARE",
        pu_ht=Decimal("50.00"),
        montant_ht=Decimal("50.00"),
    )

    await rapprocher_facture(db_session, facture.id)

    anomalies = await _anomalies_de(db_session, facture)
    assert not any(a.regle in ("R07", "R08") for a in anomalies)


# --------------------------------------------------------------------------
# Ruling L5-R3 (tour de correction 1, L5-T1) : bloc_id sur les anomalies de
# ligne (R07-R09, R13, R17)
# --------------------------------------------------------------------------


async def test_rapprocher_facture_ruling_l5r3_bloc_id_sur_anomalie_prix_et_r17(
    db_session: AsyncSession,
) -> None:
    """R07/R08/R09 (prix) et R17 (conditionnement non entier) ne posent
    nativement que `ligne_id` sur l'anomalie qu'elles produisent -- la règle
    pure ne reçoit que la ligne, jamais le bloc. `rapprocher_facture` doit
    compléter `bloc_id` depuis la ligne, comme il complète déjà
    `document_id` (Ruling R17 du lot 4) : sans ce complément,
    `CHANTIER_ID_RESOLU` (`ingest/anomalies.py`) ne peut résoudre le
    chantier d'aucune de ces anomalies."""
    fournisseur = await _creer_fournisseur(db_session)
    article_prix = await _creer_article(
        db_session, fournisseur=fournisseur, code="ART-L5R3-PRIX"
    )
    article_r17 = await _creer_article(
        db_session, fournisseur=fournisseur, ratio=Decimal("10"), valide=True
    )

    for mois, numero in ((5, "H-L5R3-1"), (6, "H-L5R3-2"), (7, "H-L5R3-3")):
        historique = await _creer_facture(
            db_session,
            fournisseur=fournisseur,
            numero=numero,
            date_doc=date(2026, mois, 1),
        )
        await _creer_ligne(
            db_session,
            document=historique,
            bloc=None,
            article=article_prix,
            code_brut="ART-L5R3-PRIX",
            pu_ht=Decimal("10.00"),
            montant_ht=Decimal("10.00"),
        )

    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-L5R3", date_doc=date(2026, 8, 15)
    )

    bloc_prix = await _creer_bloc(db_session, facture=facture, numero_bl="L-L5R3-PRIX")
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc_prix,
        article=article_prix,
        code_brut="ART-L5R3-PRIX",
        pu_ht=Decimal("12.00"),
        montant_ht=Decimal("12.00"),
    )

    bloc_r17 = await _creer_bloc(db_session, facture=facture, numero_bl="L-L5R3-R17")
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc_r17,
        article=article_r17,
        qte_livree=Decimal("2.5"),
        qte_totale=Decimal("25"),
        unite_brut=None,
        montant_ht=Decimal("100.00"),
    )
    bl_r17 = await _creer_bl(db_session, fournisseur=fournisseur, numero="L-L5R3-R17")
    await _creer_ligne(
        db_session,
        document=bl_r17,
        article=article_r17,
        qte_totale=Decimal("25"),
        unite_brut=None,
        montant_ht=Decimal("100.00"),
    )

    await rapprocher_facture(db_session, facture.id)

    anomalies = await _anomalies_de(db_session, facture)
    anomalie_prix = next(
        (a for a in anomalies if a.regle in ("R07", "R08", "R09")), None
    )
    anomalie_r17 = next((a for a in anomalies if a.regle == "R17"), None)

    ok = (
        anomalie_prix is not None
        and anomalie_prix.bloc_id == bloc_prix.id
        and anomalie_r17 is not None
        and anomalie_r17.bloc_id == bloc_r17.id
    )
    assert ok, (
        "les anomalies de prix et R17 doivent porter le bloc_id de leur "
        "propre ligne, jamais bloc_id=None"
    )


async def test_rapprocher_facture_ruling_l5r3_anomalie_prix_visible_du_filtre_chantier(
    db_session: AsyncSession,
) -> None:
    """Avant ce correctif, une anomalie de prix (`bloc_id` natif `None`)
    était invisible du filtre `chantier_id` de `lister_anomalies` :
    `CHANTIER_ID_RESOLU` ne passe jamais par la ligne, retombait donc sur
    `Document.chantier_id`, presque toujours vide pour une facture."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier L5R3")
    article = await _creer_article(
        db_session, fournisseur=fournisseur, code="ART-L5R3-CHANTIER"
    )

    for mois, numero in ((5, "H-L5R3B-1"), (6, "H-L5R3B-2"), (7, "H-L5R3B-3")):
        historique = await _creer_facture(
            db_session,
            fournisseur=fournisseur,
            numero=numero,
            date_doc=date(2026, mois, 1),
        )
        await _creer_ligne(
            db_session,
            document=historique,
            bloc=None,
            article=article,
            code_brut="ART-L5R3-CHANTIER",
            pu_ht=Decimal("10.00"),
            montant_ht=Decimal("10.00"),
        )

    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-L5R3B",
        date_doc=date(2026, 8, 20),
    )
    bloc = await _creer_bloc(
        db_session, facture=facture, numero_bl="L-L5R3B", chantier_id=chantier.id
    )
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        article=article,
        code_brut="ART-L5R3-CHANTIER",
        pu_ht=Decimal("12.00"),
        montant_ht=Decimal("12.00"),
    )

    await rapprocher_facture(db_session, facture.id)

    resultat = await lister_anomalies(db_session, chantier_id=chantier.id)
    ok = any(a.regle in ("R07", "R08", "R09") for a in resultat)
    assert ok, "l'anomalie de prix doit être visible du filtre chantier"


async def test_rapprocher_facture_ruling_l5r3_idempotent_sur_rejeu(
    db_session: AsyncSession,
) -> None:
    """Deux rapprochements successifs ne doivent ni dupliquer l'anomalie de
    prix, ni changer son identifiant, ni changer son `bloc_id` (désormais
    renseigné par le correctif) -- même garantie que le Ruling R17 du lot 4
    pour `document_id`."""
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(
        db_session, fournisseur=fournisseur, code="ART-L5R3-IDEMP"
    )

    for mois, numero in ((5, "H-L5R3C-1"), (6, "H-L5R3C-2"), (7, "H-L5R3C-3")):
        historique = await _creer_facture(
            db_session,
            fournisseur=fournisseur,
            numero=numero,
            date_doc=date(2026, mois, 1),
        )
        await _creer_ligne(
            db_session,
            document=historique,
            bloc=None,
            article=article,
            code_brut="ART-L5R3-IDEMP",
            pu_ht=Decimal("10.00"),
            montant_ht=Decimal("10.00"),
        )

    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-L5R3C",
        date_doc=date(2026, 8, 20),
    )
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L-L5R3C")
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        article=article,
        code_brut="ART-L5R3-IDEMP",
        pu_ht=Decimal("12.00"),
        montant_ht=Decimal("12.00"),
    )

    await rapprocher_facture(db_session, facture.id)
    premieres = [
        a
        for a in await _anomalies_de(db_session, facture)
        if a.regle in ("R07", "R08", "R09")
    ]

    await rapprocher_facture(db_session, facture.id)
    secondes = [
        a
        for a in await _anomalies_de(db_session, facture)
        if a.regle in ("R07", "R08", "R09")
    ]

    ok = (
        len(premieres) == 1
        and len(secondes) == 1
        and premieres[0].id == secondes[0].id
        and premieres[0].bloc_id == bloc.id
        and secondes[0].bloc_id == bloc.id
    )
    assert ok, (
        "un rejeu identique doit retrouver la même anomalie de prix, "
        "avec le même bloc_id"
    )


async def test_rapprocher_facture_ruling_l5r6_anomalie_prix_traitee_survit_au_rejeu(
    db_session: AsyncSession,
) -> None:
    """Ruling L5-R6 (tour de correction 2, migration 0008) : une anomalie de
    prix `traitee` par un humain, dont `bloc_id` a déjà été réparé (même
    valeur que celle qu'un rapprochement recalculerait aujourd'hui pour
    cette ligne -- exactement l'état laissé par la migration 0008 sur une
    ligne qui existait avant le Ruling L5-R3), doit être retrouvée par sa
    clé au rejeu : aucune anomalie ouverte ne doit être créée en double pour
    la même cause, sans quoi la décision de l'humain serait contournée en
    silence (L4-D12)."""
    fournisseur = await _creer_fournisseur(db_session)
    article = await _creer_article(db_session, fournisseur=fournisseur, code="ART-L5R6")

    for mois, numero in ((5, "H-L5R6-1"), (6, "H-L5R6-2"), (7, "H-L5R6-3")):
        historique = await _creer_facture(
            db_session,
            fournisseur=fournisseur,
            numero=numero,
            date_doc=date(2026, mois, 1),
        )
        await _creer_ligne(
            db_session,
            document=historique,
            bloc=None,
            article=article,
            code_brut="ART-L5R6",
            pu_ht=Decimal("10.00"),
            montant_ht=Decimal("10.00"),
        )

    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-L5R6",
        date_doc=date(2026, 8, 20),
    )
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L-L5R6")
    ligne = await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        article=article,
        code_brut="ART-L5R6",
        pu_ht=Decimal("12.00"),
        montant_ht=Decimal("12.00"),
    )

    # Anomalie déjà traitée par un humain, `document_id`/`bloc_id` déjà
    # complétés -- exactement l'état laissé par un rapprochement antérieur
    # au Ruling L5-R3 (le complément de `document_id`, lui, existe depuis le
    # Ruling R17 du lot 4 : seul `bloc_id` manquait) et réparé depuis par la
    # migration 0008. `regle="R08"` : écart de 20 % (12,00 vs médiane
    # 10,00), au-dessus de `seuil_prix_fort_pct` (15 % par défaut) -- la
    # même règle que celle que `rapprocher_facture` recalcule plus bas pour
    # cette ligne (identité complète, donc, pas seulement `bloc_id`).
    anomalie_existante = Anomalie(
        regle="R08",
        gravite="haute",
        statut="traitee",
        document_id=facture.id,
        ligne_id=ligne.id,
        bloc_id=bloc.id,
        detail={"cle": "valeur"},
        traitee_le=datetime.now(UTC),
        commentaire="Écart de prix accepté (test).",
    )
    db_session.add(anomalie_existante)
    await db_session.commit()
    await db_session.refresh(anomalie_existante)

    await rapprocher_facture(db_session, facture.id)

    anomalies_prix = [
        a
        for a in await _anomalies_de(db_session, facture)
        if a.regle in ("R07", "R08", "R09")
    ]
    ok = (
        len(anomalies_prix) == 1
        and anomalies_prix[0].id == anomalie_existante.id
        and anomalies_prix[0].statut == "traitee"
    )
    assert ok, (
        "une anomalie de prix déjà traitee, bloc_id réparé, doit survivre au "
        "rejeu sans être dupliquée par une anomalie ouverte"
    )


# --------------------------------------------------------------------------
# Déclenchements : dépôt de facture, validation d'un BL, extraction d'un BL
# --------------------------------------------------------------------------


async def test_deposer_facture_declenche_le_rapprochement(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, tmp_path: Path
) -> None:
    from app.modules.extract.facture import (
        BlocBL,
        Facture,
        LigneFacture,
        TypeLigne,
    )
    from app.modules.ingest import factures as ingest_factures
    from app.modules.ingest.commun import Deposant
    from app.modules.ingest.models import Utilisateur

    fournisseur = await _creer_fournisseur(db_session, nom="Unikalo")

    bl = await _creer_bl(db_session, fournisseur=fournisseur, numero="L0200")

    admin = Utilisateur(
        email=f"admin.{uuid.uuid4()}@example.invalid", role="admin", is_active=True
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    deposant = Deposant(id=admin.id, nom_affichage="Admin Testeur")

    facture_inventee = Facture(
        fournisseur_brut="Unikalo",
        numero="F0200",
        date_facture=date(2026, 8, 20),
        client=None,
        echeance=None,
        total_ht=Decimal("40.00"),
        blocs=(
            BlocBL(
                numero_bl="L0200",
                date_bl=date(2026, 8, 18),
                numero_commande=None,
                chantier_brut=None,
                lignes=(
                    LigneFacture(
                        ordre=0,
                        type_ligne=TypeLigne.ARTICLE,
                        code_article="ART-DEPOT",
                        designation="Article inventé dépôt",
                        qte_livree=Decimal("1"),
                        qte_totale=Decimal("1"),
                        unite=None,
                        pu_ht=Decimal("40.00"),
                        pu_cdt=None,
                        remise_pct=None,
                        montant_ht=Decimal("40.00"),
                        tva=None,
                    ),
                ),
            ),
        ),
    )

    monkeypatch.setattr(
        ingest_factures,
        "analyser_facture_unikalo",
        lambda reponse: facture_inventee,
    )

    async def _ocr(contenu: bytes, mime: str) -> dict[str, Any]:
        return {"pages": []}

    resultat = await deposer_facture(
        db_session,
        b"%PDF-invente",
        deposant,
        tmp_path,
        _ocr,
    )

    bloc = (
        await db_session.execute(
            select(BlocFacture).where(BlocFacture.facture_id == resultat.id)
        )
    ).scalar_one()
    ok = bloc.statut_rapprochement == "recu" and bloc.bl_document_id == bl.id
    assert ok, "le dépôt de la facture doit déclencher le rapprochement"


async def test_valider_document_declenche_rapprocher_factures_du_bl(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0300")
    await rapprocher_facture(db_session, facture.id)
    await _rafraichir(db_session, bloc)
    assert bloc.statut_rapprochement == "non_recu"

    bl = await _creer_bl(
        db_session,
        fournisseur=fournisseur,
        numero="L0300",
        statut="a_verifier",
        chantier_brut="Chantier Testeur BL",
        total_ht=Decimal("1.00"),
    )
    await _creer_ligne(db_session, document=bl, montant_ht=Decimal("1.00"))

    from app.modules.ingest.models import Utilisateur

    admin = Utilisateur(
        email=f"admin.{uuid.uuid4()}@example.invalid", role="admin", is_active=True
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)

    await valider_document(db_session, bl.id, auteur_id=admin.id)

    await _rafraichir(db_session, bloc)
    ok = bloc.statut_rapprochement == "recu" and bloc.bl_document_id == bl.id
    assert ok, "la validation du BL doit déclencher le rejeu de la facture"


async def test_extraction_bl_declenche_rapprocher_factures_du_bl(
    db_session: AsyncSession,
) -> None:
    """`enregistrer_extraction_bl` doit déclencher `rapprocher_factures_du_bl`
    dès qu'un numéro est résolu — vérifié via l'annotation illisible (chemin
    le plus simple à préparer sans dépendre du schéma OCR complet), qui peut
    tout de même renseigner `document.numero` via le motif déterministe
    `detecter_numero_bl` (L3-D3)."""
    fournisseur = await _creer_fournisseur(db_session, nom="Peintures Exemple")
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L209900000123")

    document = Document(
        type="bl",
        source="telegram",
        statut="a_verifier",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)

    texte_annotation_illisible = "N/A"
    reponse = {
        "pages": [
            {
                "index": 0,
                "markdown": "LIVRAISON N°L209900000123",
                "images": [],
                "dimensions": {"dpi": 200, "height": 100, "width": 100},
            }
        ],
        "model": "test",
        "document_annotation": texte_annotation_illisible,
        "usage_info": {"pages_processed": 1, "doc_size_bytes": 1},
    }

    await enregistrer_extraction_bl(db_session, document.id, reponse)

    await _rafraichir(db_session, bloc)
    ok = bloc.statut_rapprochement == "recu" and bloc.bl_document_id == document.id
    assert ok, "une extraction qui résout un numéro doit déclencher le rapprochement"


# --------------------------------------------------------------------------
# Fixture réelle (skip si absente) : facture Unikalo d'août + 3 photos de BL
# --------------------------------------------------------------------------

_RACINE_FIXTURES = Path(__file__).resolve().parents[4] / "tests" / "fixtures"
_FIXTURE_FACTURE = _RACINE_FIXTURES / "unikalo" / "facture_2026-08.mistral-ocr.json"
_FIXTURES_BL = tuple(
    _RACINE_FIXTURES / "bl" / f"unikalo_0{i}.mistral-ocr.json" for i in (1, 2, 3)
)

NB_BLOCS_ATTENDU = 28  # constat 7 du brief L4-T7 (`docs/plan-lot-4/L4-T7-brief.md`)
NB_BLOCS_RECUS_ATTENDU = 3


@pytest.fixture
def fixtures_reelles() -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    fichiers_absents = not _FIXTURE_FACTURE.is_file() or any(
        not f.is_file() for f in _FIXTURES_BL
    )
    if fichiers_absents:
        pytest.skip(
            "fixtures réelles absentes de tests/fixtures/ (clone neuf ou "
            "fixtures non déposées)"
        )
    facture = json.loads(_FIXTURE_FACTURE.read_text(encoding="utf-8"))
    bls = tuple(json.loads(f.read_text(encoding="utf-8")) for f in _FIXTURES_BL)
    return facture, bls


async def test_fixture_reelle_rapprochement_28_blocs_3_recus(
    db_session: AsyncSession,
    tmp_path: Path,
    fixtures_reelles: tuple[dict[str, Any], tuple[dict[str, Any], ...]],
) -> None:
    reponse_facture, reponses_bl = fixtures_reelles

    from app.modules.ingest.commun import Deposant
    from app.modules.ingest.models import Utilisateur

    admin = Utilisateur(
        email=f"admin.{uuid.uuid4()}@example.invalid", role="admin", is_active=True
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    deposant = Deposant(id=admin.id, nom_affichage="Admin Testeur")

    async def _ocr_facture(contenu: bytes, mime: str) -> dict[str, Any]:
        return reponse_facture

    resultat_facture = await deposer_facture(
        db_session,
        b"%PDF-1.4 invente",
        deposant,
        tmp_path,
        _ocr_facture,
    )

    for reponse_bl in reponses_bl:
        document = Document(
            type="bl",
            source="telegram",
            statut="a_verifier",
            fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        )
        db_session.add(document)
        await db_session.commit()
        await db_session.refresh(document)
        await enregistrer_extraction_bl(db_session, document.id, reponse_bl)

    resultat = await rapprocher_facture(db_session, resultat_facture.id)

    ok_nb_blocs = resultat.nb_blocs == NB_BLOCS_ATTENDU
    assert ok_nb_blocs, "la facture réelle doit compter le nombre de blocs attendu"

    ok_nb_recus = resultat.nb_blocs_recus == NB_BLOCS_RECUS_ATTENDU
    assert ok_nb_recus, (
        "seuls les blocs dont le numéro correspond à une photo sont reçus"
    )

    blocs = (
        (
            await db_session.execute(
                select(BlocFacture).where(BlocFacture.facture_id == resultat_facture.id)
            )
        )
        .scalars()
        .all()
    )
    aucun_recu_sans_bl = all(
        bloc.bl_document_id is not None
        for bloc in blocs
        if bloc.statut_rapprochement == "recu"
    )
    assert aucun_recu_sans_bl, "un bloc reçu doit toujours porter un bl_document_id"

    # Fix round 1, finding 2 (controller-confirmed sur la facture réelle) :
    # Ruling R14 (`normalize.unites.convertir_en_unite_fact`) doit permettre
    # une comparaison même sans unité imprimée nulle part chez Unikalo —
    # `qte_fact` ne doit donc plus être `NULL` pour les lignes qui portent
    # une quantité, au moins sur les blocs rapprochés (booléen calculé,
    # message fixe, aucune valeur réelle affichée).
    blocs_recus_ids = [bloc.id for bloc in blocs if bloc.statut_rapprochement == "recu"]
    lignes_blocs_recus = (
        (
            await db_session.execute(
                select(Ligne).where(Ligne.bloc_id.in_(blocs_recus_ids))
            )
        )
        .scalars()
        .all()
    )
    qte_fact_remplie = all(
        ligne.qte_fact is not None
        for ligne in lignes_blocs_recus
        if ligne.qte_totale is not None
    )
    assert qte_fact_remplie, (
        "Ruling R14 : qte_fact doit être renseignée pour toute ligne "
        "portant une quantité dans un bloc rapproché"
    )

    bl_document_ids = [
        bloc.bl_document_id
        for bloc in blocs
        if bloc.statut_rapprochement == "recu" and bloc.bl_document_id is not None
    ]
    lignes_bl_recus = (
        (
            await db_session.execute(
                select(Ligne).where(Ligne.document_id.in_(bl_document_ids))
            )
        )
        .scalars()
        .all()
    )
    qte_fact_bl_remplie = all(
        ligne.qte_fact is not None
        for ligne in lignes_bl_recus
        if ligne.qte_totale is not None
    )
    assert qte_fact_bl_remplie, (
        "Ruling R14 : qte_fact doit aussi être renseignée côté BL rapproché"
    )

    detail = await facture_detail(db_session, resultat_facture.id)
    coherent = sum(1 for b in detail.blocs if b.bl_recu) == NB_BLOCS_RECUS_ATTENDU
    assert coherent, "la lecture doit refléter le statut persisté"

    anomalies_r01 = (
        (await db_session.execute(select(Anomalie).where(Anomalie.regle == "R01")))
        .scalars()
        .all()
    )
    assert len(anomalies_r01) >= 1, "au moins un bloc facturé doit être non reçu"
