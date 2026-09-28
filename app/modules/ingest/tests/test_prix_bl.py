"""Tests de `ingest/prix_bl.py` (phase 3, tâche P7) : contrôle des prix
d'un bon face à la grille du fournisseur et à la dernière facture
retrouvée, ses branchements (extraction, correction, changement de grille)
et le masquage des alertes (spec `docs/superpowers/specs/2026-09-27-prix-
design.md` §6). Base de test réelle (`bl_test`), données entièrement
inventées.

Trois volets :
- `controler_prix_bl` seule : interrupteur éteint, document non
  applicable, chaque alerte déclenchée (R19, R20), conversion d'unité par
  l'article, alerte levée quand la grille baisse, jamais rouverte, cascade
  de suppression d'une ligne.
- branchements : extraction (`enregistrer_extraction_bl`), correction
  (`corriger_lignes`, chemin réel -- alerte créée puis levée par deux
  corrections successives -- et chemin en échec forcé pour l'extraction et
  la correction, qui ne doit jamais les faire échouer) et changement de
  grille (`enregistrer_prix`).
- masquage (`ingest.commun.regles_masquees`) : interrupteur général,
  alerte par alerte, `traiter_anomalie` sur une alerte masquée,
  `CompteProblemes.controle_prix_actif` (factures OU bons)."""

from __future__ import annotations

import copy
import io
import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest import a_traiter as a_traiter_module
from app.modules.ingest import prix_bl as prix_bl_module
from app.modules.ingest.a_traiter import compter_problemes_a_regler
from app.modules.ingest.anomalies import (
    AnomalieIntrouvable,
    lister_anomalies,
    traiter_anomalie,
)
from app.modules.ingest.commun import regles_masquees
from app.modules.ingest.corrections import LigneSaisie, corriger_lignes
from app.modules.ingest.extraction_bl import enregistrer_extraction_bl
from app.modules.ingest.grilles import SaisiePrix, enregistrer_prix, importer_grille
from app.modules.ingest.models import (
    Anomalie,
    Article,
    Document,
    Fournisseur,
    GrillePrix,
    Journal,
    Ligne,
    Utilisateur,
)
from app.modules.ingest.parametres import modifier_parametre
from app.modules.ingest.prix_bl import controler_prix_bl, controler_prix_bl_sans_echec
from app.modules.normalize.prix import cle_produit, prix_net
from app.modules.rules.engine import REGLES_PRIX_BL

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_DONNEES_SYNTHETIQUES = (
    Path(__file__).resolve().parent.parent.parent
    / "extract"
    / "tests"
    / "donnees"
    / "bl_synthetique.mistral-ocr.json"
)
with _DONNEES_SYNTHETIQUES.open(encoding="utf-8") as _fichier:
    _REPONSE_SYNTHETIQUE_BASE: dict[str, Any] = json.load(_fichier)


def _reponse_synthetique() -> dict[str, Any]:
    return copy.deepcopy(_REPONSE_SYNTHETIQUE_BASE)


# --------------------------------------------------------------------------
# Aides de construction (données inventées)
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur Prix"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=f"{nom} {uuid.uuid4()}")
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_utilisateur(db_session: AsyncSession) -> Utilisateur:
    utilisateur = Utilisateur(
        email=f"admin.{uuid.uuid4()}@example.invalid", role="admin", is_active=True
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _creer_bl(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur | None,
    date_doc: date | None = date(2026, 6, 1),
    statut: str = "recu",
    type_: str = "bl",
) -> Document:
    document = Document(
        type=type_,
        source="telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        numero=f"L-{uuid.uuid4()}",
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
        date_doc=date_doc,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_ligne(
    db_session: AsyncSession,
    *,
    document: Document,
    code_brut: str | None = "REF1",
    article_brut: str | None = "Produit inventé",
    pu_ht: Decimal | None = Decimal("10.00"),
    unite_brut: str | None = None,
    remise_pct: Decimal | None = None,
    article: Article | None = None,
    ordre: int = 0,
    type_ligne: str = "article",
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        type_ligne=type_ligne,
        code_brut=code_brut,
        article_brut=article_brut,
        article_id=article.id if article is not None else None,
        pu_ht=pu_ht,
        unite_brut=unite_brut,
        remise_pct=remise_pct,
        ordre=ordre,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _creer_prix_grille(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    reference: str | None = "REF1",
    designation: str = "Produit inventé",
    prix_ht: str = "10.00",
    unite: str | None = None,
    date_effet: date = date(2026, 1, 1),
) -> GrillePrix:
    ligne = GrillePrix(
        fournisseur_id=fournisseur.id,
        cle_produit=cle_produit(reference, designation),
        reference=reference,
        designation=designation,
        unite_brut=unite,
        unite=unite,
        prix_ht=Decimal(prix_ht),
        prix_net=prix_net(Decimal(prix_ht), None),
        date_effet=date_effet,
        source="saisie",
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _activer_controle(db_session: AsyncSession) -> None:
    await modifier_parametre(db_session, "prix_controle_bl_actif", "1", auteur_id=None)


async def _anomalies_du_document(
    db_session: AsyncSession, document_id: uuid.UUID
) -> list[Anomalie]:
    resultat = await db_session.execute(
        select(Anomalie).where(Anomalie.document_id == document_id)
    )
    return list(resultat.scalars().all())


async def _dernier_journal(db_session: AsyncSession, action: str) -> Journal | None:
    resultat = await db_session.execute(
        select(Journal)
        .where(Journal.action == action)
        .order_by(Journal.horodatage.desc())
    )
    return resultat.scalars().first()


# --------------------------------------------------------------------------
# controler_prix_bl : interrupteur, document non applicable.
# --------------------------------------------------------------------------


async def test_interrupteur_general_eteint_ne_recalcule_rien(
    db_session: AsyncSession,
) -> None:
    """Défaut (`prix_controle_bl_actif` = 0) : aucune anomalie créée, même
    avec une ligne qui déclencherait R22 (absent de la grille)."""
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))

    nb = await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    assert nb == 0
    assert await _anomalies_du_document(db_session, document.id) == []


@pytest.mark.parametrize(
    "type_,statut,sans_fournisseur",
    [
        ("facture", "recu", False),
        ("bl", "archive", False),
        ("bl", "recu", True),
    ],
)
async def test_document_non_applicable_ne_fait_rien(
    db_session: AsyncSession, type_: str, statut: str, sans_fournisseur: bool
) -> None:
    await _activer_controle(db_session)
    fournisseur = None if sans_fournisseur else await _creer_fournisseur(db_session)
    document = await _creer_bl(
        db_session, fournisseur=fournisseur, type_=type_, statut=statut
    )
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))

    nb = await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    assert nb == 0
    assert await _anomalies_du_document(db_session, document.id) == []


# --------------------------------------------------------------------------
# Chaque alerte, conversion d'unité, levée, jamais rouverte, cascade.
# --------------------------------------------------------------------------


async def test_r19_plus_cher_que_la_grille(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))

    nb = await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    assert nb == 1
    anomalies = await _anomalies_du_document(db_session, document.id)
    assert [a.regle for a in anomalies] == ["R19"]
    assert anomalies[0].gravite == "haute"
    assert anomalies[0].detail["prix_bon"] == "20.00"
    assert anomalies[0].detail["prix_grille"] == "10.0000"


async def test_conversion_unite_conditionnement_vers_facturation(
    db_session: AsyncSession,
) -> None:
    """Grille au kg, bon au seau de 15 kg (article validé) : le prix de
    grille est ramené à l'unité du bon avant comparaison (spec §4.4)."""
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    article = Article(
        fournisseur_id=fournisseur.id,
        code="REF1",
        unite_cdt="seau",
        unite_fact="kg",
        ratio=Decimal("15"),
        valide=True,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    await _creer_prix_grille(
        db_session, fournisseur=fournisseur, prix_ht="1.00", unite="kg"
    )
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(
        db_session,
        document=document,
        article=article,
        unite_brut="seau",
        pu_ht=Decimal("20.00"),
    )

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    regles = {a.regle for a in anomalies}
    assert "R19" in regles
    r19 = next(a for a in anomalies if a.regle == "R19")
    assert r19.detail["prix_grille"] == "15.0000"


async def test_r20_plus_cher_que_la_derniere_facture(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    facture = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"facture-invente-{uuid.uuid4()}.pdf",
        numero="F1",
        fournisseur_id=fournisseur.id,
        date_doc=date(2026, 5, 1),
    )
    db_session.add(facture)
    await db_session.commit()
    await db_session.refresh(facture)
    ligne_facture = Ligne(
        document_id=facture.id,
        type_ligne="article",
        code_brut="REF1",
        article_brut="Produit inventé",
        pu_ht=Decimal("10.00"),
        ordre=0,
    )
    db_session.add(ligne_facture)
    await db_session.commit()

    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    regles = {a.regle for a in anomalies}
    assert "R20" in regles
    r20 = next(a for a in anomalies if a.regle == "R20")
    assert r20.detail["numero_facture"] == "F1"


async def test_r20_dernier_prix_facture_retrouve_par_nom(
    db_session: AsyncSession,
) -> None:
    """Constat de la relecture (tour 1) : le dernier prix facturé doit
    aussi pouvoir être retrouvé sans correspondance de référence -- ici la
    ligne de facture ne porte aucun code, seule la ressemblance des noms
    permet le rapprochement (spec §6.3, `_reference_facture` méthode
    « nom »)."""
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    facture = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"facture-invente-{uuid.uuid4()}.pdf",
        numero="F2",
        fournisseur_id=fournisseur.id,
        date_doc=date(2026, 5, 1),
    )
    db_session.add(facture)
    await db_session.commit()
    await db_session.refresh(facture)
    ligne_facture = Ligne(
        document_id=facture.id,
        type_ligne="article",
        code_brut=None,
        article_brut="Produit Exemple Alpha",
        pu_ht=Decimal("10.00"),
        ordre=0,
    )
    db_session.add(ligne_facture)
    await db_session.commit()

    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(
        db_session,
        document=document,
        code_brut=None,
        article_brut="Produit Exemple Alpha",
        pu_ht=Decimal("20.00"),
    )

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    r20 = next(a for a in anomalies if a.regle == "R20")
    assert r20.detail["methode"] == "nom"
    assert r20.detail["ressemblance"] == "100"
    assert r20.detail["dernier_prix"] == "10.0000"


async def test_r20_utilise_le_prix_net_facture_apres_remise(
    db_session: AsyncSession,
) -> None:
    """Constat de la relecture (tour 1) : R20 doit comparer au prix **net**
    de la dernière facture, pas à son prix brut -- une remise qui n'était
    pas déduite masquerait une vraie hausse (spec §6.3)."""
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    facture = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"facture-invente-{uuid.uuid4()}.pdf",
        numero="F3",
        fournisseur_id=fournisseur.id,
        date_doc=date(2026, 5, 1),
    )
    db_session.add(facture)
    await db_session.commit()
    await db_session.refresh(facture)
    ligne_facture = Ligne(
        document_id=facture.id,
        type_ligne="article",
        code_brut="REF1",
        article_brut="Produit inventé",
        pu_ht=Decimal("100.00"),
        remise_pct=Decimal("10"),
        ordre=0,
    )
    db_session.add(ligne_facture)
    await db_session.commit()

    document = await _creer_bl(db_session, fournisseur=fournisseur)
    # 95 € dépasse le prix net (90 €) mais pas le prix brut (100 €) : ne
    # déclenche R20 que si la remise est bien déduite.
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("95.00"))

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    regles = {a.regle for a in anomalies}
    assert "R20" in regles
    r20 = next(a for a in anomalies if a.regle == "R20")
    assert r20.detail["dernier_prix"] == "90.0000"


async def test_r21_moins_cher_que_la_grille(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("5.00"))

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    assert [a.regle for a in anomalies] == ["R21"]
    assert anomalies[0].gravite == "basse"
    assert anomalies[0].detail["prix_bon"] == "5.00"
    assert anomalies[0].detail["prix_grille"] == "10.0000"


async def test_r22_produit_absent_de_la_grille(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    assert [a.regle for a in anomalies] == ["R22"]
    assert anomalies[0].gravite == "basse"
    assert anomalies[0].detail["prix_bon"] == "20.00"


async def test_r23_produit_reconnu_par_nom(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    await _creer_prix_grille(
        db_session,
        fournisseur=fournisseur,
        reference="REFX",
        designation="Produit Exemple Alpha",
        prix_ht="20.00",
    )
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    # Même prix que la grille (ni R19 ni R21) et aucun code (pas de
    # correspondance par référence) : seule R23 doit se déclencher.
    await _creer_ligne(
        db_session,
        document=document,
        code_brut=None,
        article_brut="Produit Exemple Alpha",
        pu_ht=Decimal("20.00"),
    )

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    assert [a.regle for a in anomalies] == ["R23"]
    assert anomalies[0].gravite == "basse"
    assert anomalies[0].detail["designation_grille"] == "Produit Exemple Alpha"
    assert anomalies[0].detail["ressemblance"] == "100"


async def test_r24_unites_differentes(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    await _creer_prix_grille(
        db_session, fournisseur=fournisseur, prix_ht="10.00", unite="kg"
    )
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    # Même référence (correspondance certaine), mais une unité de bon (« m »)
    # qui ne se ramène pas à celle de la grille (« kg »), sans article ni
    # ratio de conditionnement validé.
    await _creer_ligne(
        db_session, document=document, unite_brut="m", pu_ht=Decimal("20.00")
    )

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    assert [a.regle for a in anomalies] == ["R24"]
    assert anomalies[0].gravite == "moyenne"
    assert anomalies[0].detail["unite_bon"] == "m"
    assert anomalies[0].detail["unite_grille"] == "kg"


async def test_r25_grille_ancienne(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    # Bien plus de 12 mois avant aujourd'hui (défaut `prix_age_grille_mois`)
    # quelle que soit la date réelle d'exécution du test.
    await _creer_prix_grille(
        db_session,
        fournisseur=fournisseur,
        prix_ht="20.00",
        date_effet=date(2000, 1, 1),
    )
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    # Même prix que la grille : ni R19 ni R21 ne doivent parasiter le test.
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    assert [a.regle for a in anomalies] == ["R25"]
    assert anomalies[0].gravite == "basse"
    assert anomalies[0].detail["date_grille"] == "2000-01-01"


async def test_baisse_du_prix_de_grille_leve_lalerte(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    await _creer_prix_grille(
        db_session,
        fournisseur=fournisseur,
        prix_ht="10.00",
        date_effet=date(2026, 1, 1),
    )
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()
    assert any(
        a.regle == "R19" for a in await _anomalies_du_document(db_session, document.id)
    )

    # Nouveau prix de grille, en vigueur avant la date du bon : 25 € --
    # le bon à 20 € n'est plus « plus cher que la grille ».
    await _creer_prix_grille(
        db_session,
        fournisseur=fournisseur,
        prix_ht="25.00",
        date_effet=date(2026, 2, 1),
    )

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    assert not any(a.regle == "R19" for a in anomalies)
    journal_leve = await _dernier_journal(db_session, "anomalie_levee")
    assert journal_leve is not None
    assert journal_leve.avant is not None
    assert journal_leve.avant["regle"] == "R19"


async def test_alerte_reglee_jamais_rouverte(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))
    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    utilisateur = await _creer_utilisateur(db_session)
    anomalie = (await _anomalies_du_document(db_session, document.id))[0]
    await traiter_anomalie(
        db_session,
        anomalie.id,
        statut="traitee",
        commentaire="Prix accepté",
        auteur_id=utilisateur.id,
    )

    # Même bon, même écart : le contrôle est rejoué (ex. relance).
    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    assert len(anomalies) == 1
    assert anomalies[0].statut == "traitee"


async def test_suppression_ligne_cascade_puis_recreation_de_lalerte(
    db_session: AsyncSession,
) -> None:
    """La cascade de la migration 0013 (`anomalie.ligne_id` en `ON DELETE
    CASCADE`) fonctionne, et le contrôle recrée l'alerte sur la nouvelle
    ligne (même principe que le rejeu des autres règles à une relance)."""
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))
    await controler_prix_bl(db_session, document.id)
    await db_session.commit()
    assert len(await _anomalies_du_document(db_session, document.id)) == 1

    await db_session.delete(ligne)
    await db_session.commit()
    assert await _anomalies_du_document(db_session, document.id) == []

    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))
    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalies = await _anomalies_du_document(db_session, document.id)
    assert [a.regle for a in anomalies] == ["R19"]


# --------------------------------------------------------------------------
# controler_prix_bl_sans_echec : exception forcée absorbée.
# --------------------------------------------------------------------------


async def test_sans_echec_absorbe_une_exception_forcee(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    document_id = document.id

    async def _leve(session: AsyncSession, document_id: uuid.UUID) -> int:
        # Touche la session avant d'échouer (même repro que
        # `test_valider_document_rafraichit_document_apres_rapprochement_en_echec`,
        # `test_corrections.py`) : garantit qu'une transaction est active au
        # moment du `rollback()` de `controler_prix_bl_sans_echec`.
        await session.execute(select(Document.id).where(Document.id == document_id))
        raise RuntimeError("panne simulée du contrôle des prix")

    monkeypatch.setattr(prix_bl_module, "controler_prix_bl", _leve)

    resultat = await controler_prix_bl_sans_echec(db_session, document_id)

    assert resultat is None
    # La session reste utilisable après le rollback interne -- `document_id`
    # capturé avant l'appel, jamais un attribut de `document` (expiré par ce
    # `rollback()`, même piège que Ruling R23).
    assert await _anomalies_du_document(db_session, document_id) == []


async def test_extraction_bl_reussit_malgre_exception_forcee_dans_controle_prix(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _activer_controle(db_session)
    fournisseur = Fournisseur(
        nom="Peintures Exemple", aliases=["Peintures Exemple SAS"]
    )
    db_session.add(fournisseur)
    await db_session.commit()

    document = Document(
        type="bl", source="telegram", statut="recu", fichier_path="chemin-invente.jpg"
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    document_id = document.id

    async def _leve(session: AsyncSession, document_id: uuid.UUID) -> int:
        await session.execute(select(Document.id).where(Document.id == document_id))
        raise RuntimeError("panne simulée du contrôle des prix")

    monkeypatch.setattr(prix_bl_module, "controler_prix_bl", _leve)

    resultat = await enregistrer_extraction_bl(
        db_session, document_id, _reponse_synthetique()
    )

    assert resultat.numero is not None
    assert resultat.statut in ("recu", "a_verifier")
    assert await _anomalies_du_document(db_session, document_id) == []


async def test_corriger_lignes_declenche_reellement_le_controle_des_prix(
    db_session: AsyncSession,
) -> None:
    """Constat de la relecture (tour 2) : contrairement au test suivant (qui
    force une exception dans `controler_prix_bl` pour vérifier que la
    correction n'échoue jamais), celui-ci exerce le chemin normal -- aucun
    monkeypatch -- où une correction de `pu_ht` fait bien recalculer et
    persister l'alerte de prix après le commit de `corriger_lignes`."""
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=document, pu_ht=Decimal("10.00"))
    utilisateur = await _creer_utilisateur(db_session)

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()
    assert await _anomalies_du_document(db_session, document.id) == []

    # Correction du prix unitaire vers un prix plus cher que la grille (10 €) :
    # doit déclencher R19 sans qu'on ait besoin de rappeler `controler_prix_bl`
    # nous-mêmes -- `corriger_lignes` le fait après son propre commit.
    await corriger_lignes(
        db_session,
        document.id,
        [
            LigneSaisie(
                id=ligne.id,
                code_brut="REF1",
                article_brut="Produit inventé",
                qte_livree=None,
                qte_totale=None,
                unite_brut=None,
                pu_ht=Decimal("20.00"),
                montant_ht=None,
            )
        ],
        auteur_id=utilisateur.id,
    )

    anomalies = await _anomalies_du_document(db_session, document.id)
    assert [a.regle for a in anomalies] == ["R19"]
    assert anomalies[0].detail["prix_bon"] == "20.00"

    # Nouvelle correction qui ramène le prix au niveau de la grille : l'alerte
    # doit être levée -- même alerte mise à jour, pas seulement créée une
    # première fois.
    await corriger_lignes(
        db_session,
        document.id,
        [
            LigneSaisie(
                id=ligne.id,
                code_brut="REF1",
                article_brut="Produit inventé",
                qte_livree=None,
                qte_totale=None,
                unite_brut=None,
                pu_ht=Decimal("10.00"),
                montant_ht=None,
            )
        ],
        auteur_id=utilisateur.id,
    )

    assert await _anomalies_du_document(db_session, document.id) == []


async def test_corriger_lignes_reussit_malgre_exception_forcee_dans_controle_prix(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    ligne = await _creer_ligne(db_session, document=document, pu_ht=Decimal("10.00"))
    utilisateur = await _creer_utilisateur(db_session)

    async def _leve(session: AsyncSession, document_id: uuid.UUID) -> int:
        await session.execute(select(Document.id).where(Document.id == document_id))
        raise RuntimeError("panne simulée du contrôle des prix")

    monkeypatch.setattr(prix_bl_module, "controler_prix_bl", _leve)

    detail = await corriger_lignes(
        db_session,
        document.id,
        [
            LigneSaisie(
                id=ligne.id,
                code_brut="REF1",
                article_brut="Produit inventé",
                qte_livree=None,
                qte_totale=None,
                unite_brut=None,
                pu_ht=Decimal("20.00"),
                montant_ht=None,
            )
        ],
        auteur_id=utilisateur.id,
    )

    assert detail.lignes[0].pu_ht == Decimal("20.00")
    assert await _anomalies_du_document(db_session, document.id) == []


# --------------------------------------------------------------------------
# Changement de grille : recontrôle des bons concernés (spec §6.4).
# --------------------------------------------------------------------------


async def test_enregistrer_prix_recontrole_les_bons_du_fournisseur(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    document = await _creer_bl(
        db_session, fournisseur=fournisseur, date_doc=date(2026, 6, 10)
    )
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))

    await enregistrer_prix(
        db_session,
        fournisseur.id,
        SaisiePrix(
            designation="Produit inventé",
            reference="REF1",
            prix_ht=Decimal("15.00"),
            date_effet=date(2026, 1, 1),
        ),
        auteur_id=None,
    )

    anomalies = await _anomalies_du_document(db_session, document.id)
    assert any(a.regle == "R19" for a in anomalies)


def _classeur_grille(lignes: list[tuple[object, ...]]) -> bytes:
    """Classeur `.xlsx` minimal en mémoire (une ligne d'en-tête, une feuille
    « Grille »), pour l'import -- jamais un fichier réel du client (spec
    §12, données inventées)."""
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    assert feuille is not None
    feuille.title = "Grille"
    feuille.append(("Référence", "Désignation", "Unité", "Prix unitaire HT (€)"))
    for ligne in lignes:
        feuille.append(ligne)
    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


async def test_importer_grille_recontrole_les_bons_concernes(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """Constat de la relecture (tour 1) : le recontrôle après changement de
    grille est câblé aussi bien depuis la saisie (`enregistrer_prix`, ci-
    dessus) que depuis l'import Excel (`importer_grille`, spec §6.4) -- un
    produit déjà en alerte sur un bon existant doit être recontrôlé une fois
    la grille importée à un nouveau prix."""
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    await _creer_prix_grille(
        db_session,
        fournisseur=fournisseur,
        prix_ht="5.00",
        date_effet=date(2026, 1, 1),
    )
    document = await _creer_bl(
        db_session, fournisseur=fournisseur, date_doc=date(2026, 6, 10)
    )
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()
    anomalies_avant = await _anomalies_du_document(db_session, document.id)
    assert [a.regle for a in anomalies_avant] == ["R19"]

    utilisateur = await _creer_utilisateur(db_session)
    contenu = _classeur_grille([("REF1", "Produit inventé", None, 25.0)])

    await importer_grille(
        db_session,
        fournisseur.id,
        contenu,
        "grille-invente.xlsx",
        date(2026, 2, 1),
        auteur_id=utilisateur.id,
        docs_dir=tmp_path,
    )

    # 20 € n'est plus « plus cher que la grille » (25 €) : le bon a bien été
    # recontrôlé par l'import, pas seulement par la saisie -- l'alerte R19
    # est levée, remplacée par R21 (moins cher, nouveau prix de grille).
    anomalies_apres = await _anomalies_du_document(db_session, document.id)
    regles_apres = {a.regle for a in anomalies_apres}
    assert "R19" not in regles_apres
    assert "R21" in regles_apres
    r21 = next(a for a in anomalies_apres if a.regle == "R21")
    assert r21.detail["prix_grille"] == "25.0000"


# --------------------------------------------------------------------------
# Masquage (spec §6.5).
# --------------------------------------------------------------------------


async def test_regles_masquees_interrupteur_general_eteint_masque_tout(
    db_session: AsyncSession,
) -> None:
    masquees = await regles_masquees(db_session)
    assert masquees >= REGLES_PRIX_BL


async def test_regles_masquees_une_alerte_eteinte_seule(
    db_session: AsyncSession,
) -> None:
    await _activer_controle(db_session)
    await modifier_parametre(
        db_session, "prix_alerte_absent_grille", "0", auteur_id=None
    )

    masquees = await regles_masquees(db_session)

    assert "R22" in masquees
    assert "R19" not in masquees
    assert "R23" not in masquees


async def test_lister_anomalies_masque_prix_selon_linterrupteur(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))
    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    visibles = await lister_anomalies(db_session, statut="ouverte", regle="R19")
    assert len(visibles) == 1

    await modifier_parametre(db_session, "prix_controle_bl_actif", "0", auteur_id=None)
    visibles = await lister_anomalies(db_session, statut="ouverte", regle="R19")
    assert visibles == []


async def test_traiter_anomalie_masquee_est_introuvable(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _activer_controle(db_session)
    await _creer_prix_grille(db_session, fournisseur=fournisseur, prix_ht="10.00")
    document = await _creer_bl(db_session, fournisseur=fournisseur)
    await _creer_ligne(db_session, document=document, pu_ht=Decimal("20.00"))
    await controler_prix_bl(db_session, document.id)
    await db_session.commit()
    anomalie = (await _anomalies_du_document(db_session, document.id))[0]

    await modifier_parametre(db_session, "prix_controle_bl_actif", "0", auteur_id=None)
    utilisateur = await _creer_utilisateur(db_session)

    with pytest.raises(AnomalieIntrouvable):
        await traiter_anomalie(
            db_session,
            anomalie.id,
            statut="traitee",
            commentaire="ok",
            auteur_id=utilisateur.id,
        )


async def test_compte_problemes_controle_prix_actif_vrai_si_bons_actifs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a_traiter_module, "controle_prix_actif", lambda: False)
    await _activer_controle(db_session)

    compte = await compter_problemes_a_regler(db_session)

    assert compte.controle_prix_actif is True


async def test_compte_problemes_controle_prix_actif_faux_si_aucun_actif(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a_traiter_module, "controle_prix_actif", lambda: False)

    compte = await compter_problemes_a_regler(db_session)

    assert compte.controle_prix_actif is False
