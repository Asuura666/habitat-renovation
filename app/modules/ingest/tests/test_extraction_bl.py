"""Tests de `app/modules/ingest/extraction_bl.py` (L3-T6) : extraction et
enregistrement complets d'un BL, cœur de l'orchestration du lot 3.

Base de test réelle (`bl_test`). La donnée synthétique (fournisseur, BL,
chantier et articles entièrement inventés, décision du contrôleur) est lue
depuis `app/modules/extract/tests/donnees/bl_synthetique.mistral-ocr.json`
(chemin relatif à ce fichier) et modifiée en mémoire (`copy.deepcopy`) pour
chaque scénario qui en a besoin — jamais mutée en place, jamais relue depuis
le disque plusieurs fois. Aucune fixture réelle (`tests/fixtures/`) n'est
utilisée ici (R17)."""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest import extraction_bl as ingest_extraction_bl
from app.modules.ingest.extraction_bl import (
    enregistrer_echec_ocr,
    enregistrer_extraction_bl,
)
from app.modules.ingest.models import (
    Article,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    Utilisateur,
)

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

NUMERO_BL_SYNTHETIQUE = "L209900000123"


def _reponse_synthetique() -> dict[str, Any]:
    """Copie profonde de la donnée synthétique (jamais mutée en place, jamais
    relue depuis le disque)."""
    return copy.deepcopy(_REPONSE_SYNTHETIQUE_BASE)


def _annotation(reponse: dict[str, Any]) -> dict[str, Any]:
    """Annotation décodée d'une réponse synthétique, prête à être modifiée
    puis réencodée (`reponse["document_annotation"] = json.dumps(...)`)."""
    annotation: dict[str, Any] = json.loads(reponse["document_annotation"])
    return annotation


async def _creer_fournisseur_peintures_exemple(
    db_session: AsyncSession,
) -> Fournisseur:
    """Fournisseur du référentiel correspondant au BL synthétique (« PEINTURES
    EXEMPLE SAS » sur le document), défini avec un alias (Q7/L3-D8 : jamais
    créé automatiquement par l'extraction, seule la CLI `fournisseur-definir`
    alimente ce référentiel)."""
    fournisseur = Fournisseur(
        nom="Peintures Exemple", aliases=["Peintures Exemple SAS"]
    )
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_document(db_session: AsyncSession) -> Document:
    document = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path="chemin-invente.jpg",
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _journal_extraction(db_session: AsyncSession, document_id: Any) -> Journal:
    """La seule ligne `journal` `extraction_bl` ciblant `document_id` (erreur
    si aucune ou plusieurs)."""
    return (
        await db_session.execute(
            select(Journal).where(
                Journal.cible_id == str(document_id),
                Journal.action == "extraction_bl",
            )
        )
    ).scalar_one()


def _motifs(document: Document) -> list[dict[str, Any]]:
    """`document.motifs` non nul (colonne JSONB nullable côté modèle, mais
    toujours renseignée par `enregistrer_extraction_bl`/`enregistrer_echec_ocr`,
    au moins à `[]`) — évite de répéter l'assertion dans chaque test."""
    assert document.motifs is not None
    return document.motifs


async def _lignes_du_document(
    db_session: AsyncSession, document_id: Any
) -> Sequence[Ligne]:
    return (
        (
            await db_session.execute(
                select(Ligne)
                .where(Ligne.document_id == document_id)
                .order_by(Ligne.ordre)
            )
        )
        .scalars()
        .all()
    )


# --------------------------------------------------------------------------
# BL complet, fournisseur connu (avec alias) : statut `recu`, colonnes
# renseignées, lignes, articles créés, demande d'alias créée, journal.
# --------------------------------------------------------------------------


async def test_enregistrer_extraction_bl_complet_fournisseur_connu_statut_recu(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur_peintures_exemple(db_session)
    document = await _creer_document(db_session)
    reponse = _reponse_synthetique()

    resultat = await enregistrer_extraction_bl(db_session, document.id, reponse)

    assert resultat.statut == "recu"
    assert resultat.numero == NUMERO_BL_SYNTHETIQUE
    assert resultat.fournisseur_nom == "Peintures Exemple"
    assert resultat.chantier_brut == "MAISON TEST (9900000001)"
    assert resultat.nb_motifs == 0

    await db_session.refresh(document)
    assert document.statut == "recu"
    assert document.motifs == []
    assert document.type == "bl"
    assert document.numero == NUMERO_BL_SYNTHETIQUE
    assert document.fournisseur_id == fournisseur.id
    assert document.date_doc == date(2026, 9, 3)
    assert document.chantier_brut == "MAISON TEST (9900000001)"
    assert document.numero_commande == "CDE-TEST-42"
    assert document.enleve_par == "J. DUPONT"
    assert document.total_ht == Decimal("161.50")
    assert document.total_tva == Decimal("32.30")
    assert document.total_ttc == Decimal("193.80")
    assert document.confiance_min is not None
    assert document.ocr_brut == reponse
    assert document.extraction is not None
    assert document.extraction["motifs"] == []
    assert (
        document.extraction["champs"]["fournisseur"]["brut"] == "PEINTURES EXEMPLE SAS"
    )

    lignes = await _lignes_du_document(db_session, document.id)
    assert [ligne.code_brut for ligne in lignes] == ["AB1234", "CD5678", "EF9012"]
    assert all(ligne.confiance is not None for ligne in lignes)
    assert all(ligne.article_id is not None for ligne in lignes)
    assert all(ligne.type_ligne == "article" for ligne in lignes)
    assert lignes[0].montant_ht == Decimal("126.00")
    # L3-D24 : `bl_synthetique.mistral-ocr.json` (schéma L3-T1, avant
    # `quantite_conditionnements`) n'imprime qu'une seule quantité par ligne
    # -> `qte_livree` (conditionnements) reste `None`, `qte_totale`
    # (quantité facturée) reprend l'ancienne valeur `quantite`.
    assert lignes[0].qte_livree is None
    assert lignes[0].qte_totale == Decimal("4")

    articles = (await db_session.execute(select(Article))).scalars().all()
    assert len(articles) == 3
    assert all(article.valide is False for article in articles)

    # Avenant du 27/09/2026 (décision d'Ilane, spec §2.3) : aucun chantier
    # connu ne ressemble à « MAISON TEST » -> un chantier « à compléter » est
    # créé automatiquement (remplace l'ancien alias en attente, L3-D7).
    assert document.chantier_id is not None
    chantier = await db_session.get(Chantier, document.chantier_id)
    assert chantier is not None
    assert chantier.nom_canonique == "MAISON TEST"
    assert chantier.a_completer is True

    alias = (
        await db_session.execute(
            select(ChantierAlias).where(ChantierAlias.fournisseur_id == fournisseur.id)
        )
    ).scalar_one()
    assert alias.libelle_brut == "maison test"
    assert alias.chantier_id == chantier.id

    journal = await _journal_extraction(db_session, document.id)
    assert journal.utilisateur_id is None
    assert journal.apres is not None
    assert journal.apres["statut"] == "recu"
    assert journal.apres["nb_lignes"] == 3
    assert journal.apres["motifs"] == []
    assert journal.apres["fournisseur_id"] == str(fournisseur.id)
    assert journal.apres["methode_fournisseur"] == "nom"
    assert journal.apres["chantier_libelle"] == "maison test"
    assert journal.apres["chantier_id"] == str(chantier.id)
    assert journal.apres["methode_chantier"] == "création"


# --------------------------------------------------------------------------
# Fournisseur absent du référentiel : `a_verifier`, `fournisseur_inconnu`,
# aucun article ni alias créé.
# --------------------------------------------------------------------------


async def test_enregistrer_extraction_bl_fournisseur_inconnu_a_verifier(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_synthetique()
    )

    assert resultat.statut == "a_verifier"
    assert resultat.fournisseur_nom is None

    await db_session.refresh(document)
    assert document.statut == "a_verifier"
    assert document.fournisseur_id is None
    codes = [motif["code"] for motif in _motifs(document)]
    assert "fournisseur_inconnu" in codes
    motif = next(m for m in _motifs(document) if m["code"] == "fournisseur_inconnu")
    assert motif["champ"] == "fournisseur"
    assert motif["detail"] == {"brut_present": "oui"}

    assert (await db_session.execute(select(Article))).scalars().all() == []
    assert (await db_session.execute(select(ChantierAlias))).scalars().all() == []


# --------------------------------------------------------------------------
# Total modifié -> `somme_incoherente` ; confiance abaissée -> `confiance_
# faible` sur le bon champ ; date absente -> `champ_absent`.
# --------------------------------------------------------------------------


async def test_enregistrer_extraction_bl_total_modifie_somme_incoherente(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    document = await _creer_document(db_session)
    reponse = _reponse_synthetique()
    annotation = _annotation(reponse)
    annotation["total_ht"] = "999,99"
    reponse["document_annotation"] = json.dumps(annotation)

    resultat = await enregistrer_extraction_bl(db_session, document.id, reponse)

    assert resultat.statut == "a_verifier"
    await db_session.refresh(document)
    assert document.total_ht == Decimal("999.99")
    codes = [motif["code"] for motif in _motifs(document)]
    assert "somme_incoherente" in codes
    motif = next(m for m in _motifs(document) if m["code"] == "somme_incoherente")
    assert motif["detail"]["somme"] == "161.50"
    assert motif["detail"]["total"] == "999.99"


async def test_enregistrer_extraction_bl_confiance_faible_sur_le_bon_champ(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    document = await _creer_document(db_session)
    reponse = _reponse_synthetique()
    for mot in reponse["pages"][0]["confidence_scores"]["word_confidence_scores"]:
        if mot["text"] == " MAISON":
            mot["confidence"] = 0.10

    resultat = await enregistrer_extraction_bl(db_session, document.id, reponse)

    assert resultat.statut == "a_verifier"
    await db_session.refresh(document)
    motifs_confiance = [
        m
        for m in _motifs(document)
        if m["code"] == "confiance_faible" and m["champ"] == "chantier_brut"
    ]
    assert len(motifs_confiance) == 1
    assert motifs_confiance[0]["detail"]["seuil"] == "0.80"


async def test_enregistrer_extraction_bl_date_absente_champ_absent(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    document = await _creer_document(db_session)
    reponse = _reponse_synthetique()
    annotation = _annotation(reponse)
    annotation["date_doc"] = None
    reponse["document_annotation"] = json.dumps(annotation)

    resultat = await enregistrer_extraction_bl(db_session, document.id, reponse)

    assert resultat.statut == "a_verifier"
    await db_session.refresh(document)
    assert document.date_doc is None
    motif = next(m for m in _motifs(document) if m["code"] == "champ_absent")
    assert motif["champ"] == "date_doc"


# --------------------------------------------------------------------------
# Annotation absente -> `annotation_illisible`, numéro repris du motif
# déterministe existant.
# --------------------------------------------------------------------------


async def test_enregistrer_extraction_bl_annotation_illisible_numero_repris(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)
    reponse = _reponse_synthetique()
    del reponse["document_annotation"]

    resultat = await enregistrer_extraction_bl(db_session, document.id, reponse)

    assert resultat.statut == "a_verifier"
    assert resultat.numero == NUMERO_BL_SYNTHETIQUE
    assert resultat.fournisseur_nom is None
    assert resultat.chantier_brut is None

    await db_session.refresh(document)
    assert document.numero == NUMERO_BL_SYNTHETIQUE
    assert document.type == "bl"
    assert document.statut == "a_verifier"
    assert document.motifs == [
        {"code": "annotation_illisible", "champ": None, "detail": {}}
    ]
    assert document.extraction == {
        "version": 1,
        "champs": {},
        "lignes": [],
        "numero_detecte": NUMERO_BL_SYNTHETIQUE,
        "motifs": [{"code": "annotation_illisible", "champ": None, "detail": {}}],
    }
    assert await _lignes_du_document(db_session, document.id) == []


# --------------------------------------------------------------------------
# `enregistrer_echec_ocr` : l'appel OCR lui-même a échoué (ou une réponse
# structurellement inexploitable), le document part `a_verifier` avec le
# seul motif `ocr_echec`.
# --------------------------------------------------------------------------


async def test_enregistrer_echec_ocr_statut_a_verifier_motif_ocr_echec(
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)

    resultat = await enregistrer_echec_ocr(db_session, document.id)

    assert resultat.statut == "a_verifier"
    assert resultat.numero is None
    assert resultat.nb_motifs == 1

    await db_session.refresh(document)
    assert document.statut == "a_verifier"
    assert document.motifs == [{"code": "ocr_echec", "champ": None, "detail": {}}]

    journal = await _journal_extraction(db_session, document.id)
    assert journal.utilisateur_id is None
    assert journal.apres == {"motifs": ["ocr_echec"]}


# --------------------------------------------------------------------------
# Même BL déposé deux fois (même fournisseur, même numéro) : le second
# document part `a_verifier`, `numero_en_double`, numéro NULL ; le premier
# reste intact (L3-D11).
# --------------------------------------------------------------------------


async def test_enregistrer_extraction_bl_doublon_numero_meme_fournisseur(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    premier = await _creer_document(db_session)
    second = await _creer_document(db_session)

    resultat_premier = await enregistrer_extraction_bl(
        db_session, premier.id, _reponse_synthetique()
    )
    assert resultat_premier.statut == "recu"
    assert resultat_premier.numero == NUMERO_BL_SYNTHETIQUE

    resultat_second = await enregistrer_extraction_bl(
        db_session, second.id, _reponse_synthetique()
    )

    assert resultat_second.statut == "a_verifier"
    assert resultat_second.numero is None

    await db_session.refresh(premier)
    await db_session.refresh(second)
    assert premier.numero == NUMERO_BL_SYNTHETIQUE
    assert premier.statut == "recu"
    assert second.numero is None
    assert second.statut == "a_verifier"

    motif = next(m for m in _motifs(second) if m["code"] == "numero_en_double")
    assert motif["champ"] == "numero"
    assert motif["detail"] == {
        "numero": NUMERO_BL_SYNTHETIQUE,
        "numero_interne_existant": str(premier.numero_interne),
    }


# --------------------------------------------------------------------------
# Fix round 1, finding 3 : doublon détecté-puis-agi non sûr en concurrence.
# Deux dépôts du même numéro/fournisseur, traités en même temps, peuvent
# tous les deux passer `_numero_interne_doublon` avant qu'aucun n'ait
# committé. Simulé de façon déterministe en forçant `_numero_interne_doublon`
# à répondre « aucun doublon » au premier appel (alors que le document
# concurrent est déjà committé en base) : le commit lève `IntegrityError`,
# rattrapée puis rejouée une fois — cette seconde fois, le doublon (bien
# réel) est détecté normalement.
# --------------------------------------------------------------------------


async def test_enregistrer_extraction_bl_doublon_concurrent_rejoue_apres_erreur(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    concurrent = await _creer_document(db_session)
    resultat_concurrent = await enregistrer_extraction_bl(
        db_session, concurrent.id, _reponse_synthetique()
    )
    assert resultat_concurrent.statut == "recu"
    assert resultat_concurrent.numero == NUMERO_BL_SYNTHETIQUE

    document = await _creer_document(db_session)

    doublon_reel = ingest_extraction_bl._numero_interne_doublon
    appels = 0

    async def _doublon_ment_une_fois(
        session: AsyncSession,
        document_id: Any,
        fournisseur_id: Any,
        numero: str,
    ) -> int | None:
        nonlocal appels
        appels += 1
        if appels == 1:
            # Simule la course : le contrôle applicatif ne voit pas encore
            # le document concurrent (pourtant déjà committé ci-dessus,
            # dans un test réel ce serait une transaction concurrente non
            # encore validée au moment du contrôle).
            return None
        return await doublon_reel(session, document_id, fournisseur_id, numero)

    monkeypatch.setattr(
        ingest_extraction_bl, "_numero_interne_doublon", _doublon_ment_une_fois
    )

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_synthetique()
    )

    assert appels == 2
    assert resultat.statut == "a_verifier"
    assert resultat.numero is None

    await db_session.refresh(document)
    await db_session.refresh(concurrent)
    assert document.numero is None
    assert document.statut == "a_verifier"
    # Le document concurrent, déjà committé avant la course, reste intact.
    assert concurrent.numero == NUMERO_BL_SYNTHETIQUE
    assert concurrent.statut == "recu"

    motif = next(m for m in _motifs(document) if m["code"] == "numero_en_double")
    assert motif["champ"] == "numero"
    assert motif["detail"] == {
        "numero": NUMERO_BL_SYNTHETIQUE,
        "numero_interne_existant": str(concurrent.numero_interne),
    }


# --------------------------------------------------------------------------
# Alias déjà validé (par un admin) : `chantier_id` renseigné directement.
# --------------------------------------------------------------------------


async def test_enregistrer_extraction_bl_alias_deja_valide_chantier_id_renseigne(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur_peintures_exemple(db_session)
    chantier = Chantier(nom_canonique="Maison Test (canonique)")
    db_session.add(chantier)
    await db_session.flush()
    db_session.add(
        ChantierAlias(
            fournisseur_id=fournisseur.id,
            libelle_brut="maison test",
            code_brut=None,
            chantier_id=chantier.id,
        )
    )
    await db_session.commit()

    document = await _creer_document(db_session)

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_synthetique()
    )

    assert resultat.statut == "recu"
    await db_session.refresh(document)
    assert document.chantier_id == chantier.id


# --------------------------------------------------------------------------
# Avenant du 27/09/2026 (décision d'Ilane, spec §2.3) : rattachement
# automatique du chantier par ressemblance de nom (`ingest
# .rattachement_chantier.rattacher_chantier_document`, bout en bout).
# --------------------------------------------------------------------------


async def test_extraction_rattache_le_chantier_par_ressemblance(
    db_session: AsyncSession,
) -> None:
    """Bout en bout : le chantier « Maison Test » (casse différente du nom
    lu « MAISON TEST », donnée synthétique inchangée -- confiance OCR
    intacte, `statut` reste `recu`) est rattaché par ressemblance, jamais
    via un alias exact (aucun `ChantierAlias` pré-existant ici)."""
    fournisseur = await _creer_fournisseur_peintures_exemple(db_session)
    maison_test = Chantier(nom_canonique="Maison Test")
    db_session.add(maison_test)
    await db_session.commit()

    document = await _creer_document(db_session)

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_synthetique()
    )

    assert resultat.statut == "recu"
    await db_session.refresh(document)
    assert document.chantier_id == maison_test.id
    assert document.chantier_brut == "MAISON TEST (9900000001)"

    journal = await _journal_extraction(db_session, document.id)
    assert journal.apres is not None
    assert journal.apres["chantier_id"] == str(maison_test.id)
    assert journal.apres["methode_chantier"] == "ressemblance"

    alias = (
        await db_session.execute(
            select(ChantierAlias).where(ChantierAlias.fournisseur_id == fournisseur.id)
        )
    ).scalar_one()
    assert alias.libelle_brut == "maison test"
    assert alias.chantier_id == maison_test.id


# --------------------------------------------------------------------------
# `relance=True` (L3-D15) : le document reste `a_verifier` même sans motif —
# seul « Valider » le repasse `recu`.
# --------------------------------------------------------------------------


async def test_enregistrer_extraction_bl_relance_reste_a_verifier_sans_motif(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    document = await _creer_document(db_session)

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_synthetique(), relance=True
    )

    assert resultat.statut == "a_verifier"
    assert resultat.nb_motifs == 0
    await db_session.refresh(document)
    assert document.statut == "a_verifier"
    assert document.motifs == []


# --------------------------------------------------------------------------
# Ruling R11 (revue L3-T8a) : une relance (`relance=True`) garde le
# `fournisseur_id` déjà résolu du document — le contrôle de doublon d'une
# annotation illisible doit l'utiliser (au lieu d'un `fournisseur_id=None`
# figé), sous peine de violer l'unicité `(fournisseur_id, numero)` en
# écrivant un numéro déjà porté par un autre document du même fournisseur.
# --------------------------------------------------------------------------


async def test_annotation_illisible_doublon_utilise_le_fournisseur_du_document(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur_peintures_exemple(db_session)
    premier = await _creer_document(db_session)
    resultat_premier = await enregistrer_extraction_bl(
        db_session, premier.id, _reponse_synthetique()
    )
    assert resultat_premier.statut == "recu"
    assert resultat_premier.numero == NUMERO_BL_SYNTHETIQUE

    # Document déjà rattaché à ce fournisseur avant la relance (résolu ou
    # corrigé auparavant, cf. Ruling R11) — jamais fait par
    # `enregistrer_extraction_bl` lui-même dans la branche annotation
    # illisible, donc renseigné directement ici.
    document = Document(
        type="bl",
        source="telegram",
        statut="a_verifier",
        fichier_path="chemin-invente-relance.jpg",
        fournisseur_id=fournisseur.id,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)

    # Annotation illisible, mais le motif déterministe existant
    # (`detecter_numero_bl`, indépendant de l'annotation) retrouve le même
    # numéro que le premier document dans le texte OCR déjà présent sur la
    # donnée synthétique (« BON DE LIVRAISON N°L209900000123 »).
    reponse = _reponse_synthetique()
    reponse["document_annotation"] = None

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, reponse, relance=True
    )

    assert resultat.statut == "a_verifier"
    assert resultat.numero is None

    await db_session.refresh(document)
    assert document.numero is None
    assert document.fournisseur_id == fournisseur.id

    motif = next(m for m in _motifs(document) if m["code"] == "numero_en_double")
    assert motif["champ"] == "numero"
    assert motif["detail"] == {
        "numero": NUMERO_BL_SYNTHETIQUE,
        "numero_interne_existant": str(premier.numero_interne),
    }


# --------------------------------------------------------------------------
# L3-T6b (constat 11, L3-D24/L3-D26) : deux quantités par ligne persistées
# dans le bon sens, ratio proposé, ligne d'éco-participation sans article.
# --------------------------------------------------------------------------


async def test_enregistrer_extraction_bl_qte_livree_qte_totale_et_ratio(
    db_session: AsyncSession,
) -> None:
    """`qte_livree` reprend le nombre de conditionnements
    (`quantite_conditionnements`), `qte_totale` la quantité facturée
    (`quantite`) — même sens que la facture Unikalo (L3-D24) — et un ratio
    est proposé sur l'article correspondant quand les deux diffèrent."""
    fournisseur = await _creer_fournisseur_peintures_exemple(db_session)
    document = await _creer_document(db_session)
    reponse = _reponse_synthetique()
    annotation = _annotation(reponse)
    annotation["lignes"][0]["quantite_conditionnements"] = "4"
    annotation["lignes"][0]["quantite"] = "100"
    reponse["document_annotation"] = json.dumps(annotation)

    await enregistrer_extraction_bl(db_session, document.id, reponse)

    lignes = await _lignes_du_document(db_session, document.id)
    assert lignes[0].qte_livree == Decimal("4")
    assert lignes[0].qte_totale == Decimal("100")
    assert lignes[0].type_ligne == "article"

    article = (
        await db_session.execute(
            select(Article).where(
                Article.fournisseur_id == fournisseur.id,
                Article.code == "AB1234",
            )
        )
    ).scalar_one()
    assert article.ratio == Decimal("25")


async def test_enregistrer_extraction_bl_ligne_eco_type_ligne_sans_article(
    db_session: AsyncSession,
) -> None:
    """Une ligne d'éco-participation (L3-D26) est typée `eco`, jamais
    proposée comme article (`article_id` reste `None`, aucun `Article`
    créé pour son code)."""
    await _creer_fournisseur_peintures_exemple(db_session)
    document = await _creer_document(db_session)
    reponse = _reponse_synthetique()
    annotation = _annotation(reponse)
    annotation["lignes"][0]["designation"] = "ECO-PARTICIPATION"
    annotation["lignes"][0]["code"] = "ECO001"
    reponse["document_annotation"] = json.dumps(annotation)

    await enregistrer_extraction_bl(db_session, document.id, reponse)

    lignes = await _lignes_du_document(db_session, document.id)
    ligne_eco = next(ligne for ligne in lignes if ligne.code_brut == "ECO001")
    assert ligne_eco.type_ligne == "eco"
    assert ligne_eco.article_id is None

    articles_eco = (
        (await db_session.execute(select(Article).where(Article.code == "ECO001")))
        .scalars()
        .all()
    )
    assert articles_eco == []


# --------------------------------------------------------------------------
# Lot 2 du 31/10/2026, A2 : fournisseur reconnu par son SIREN ou sa TVA, la
# confiance de lecture du nom ne compte plus.
# --------------------------------------------------------------------------


def _reponse_nom_fournisseur_incertain() -> dict[str, Any]:
    reponse = _reponse_synthetique()
    for mot in reponse["pages"][0]["confidence_scores"]["word_confidence_scores"]:
        if mot["text"] == " PEINTURES":
            mot["confidence"] = 0.10
    return reponse


def _motifs_fournisseur_confiance(document: Document) -> list[dict[str, Any]]:
    return [
        m
        for m in _motifs(document)
        if m["code"] == "confiance_faible" and m["champ"] == "fournisseur"
    ]


@pytest.mark.parametrize(
    ("champs", "raison"),
    [
        ({"tva": "FR00000000000"}, "Fournisseur confirmé par son numéro de TVA"),
        ({"siret": "000 000 000 12345"}, "Fournisseur confirmé par son SIREN"),
    ],
    ids=["par TVA", "par SIREN"],
)
async def test_fournisseur_reconnu_par_siren_ou_tva_retire_la_confiance_faible(
    db_session: AsyncSession, champs: dict[str, str], raison: str
) -> None:
    db_session.add(Fournisseur(nom="Négoce Exemple", **champs))
    await db_session.commit()
    document = await _creer_document(db_session)

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_nom_fournisseur_incertain()
    )

    await db_session.refresh(document)
    assert _motifs_fournisseur_confiance(document) == []
    assert resultat.statut == "recu"
    assert document.statut == "recu"
    assert document.extraction is not None
    assert all(m["champ"] != "fournisseur" for m in document.extraction["motifs"])
    journal = await _journal_extraction(db_session, document.id)
    assert journal.apres is not None
    assert journal.apres["motifs_leves"] == [{"champ": "fournisseur", "raison": raison}]


async def test_fournisseur_reconnu_par_le_nom_garde_la_confiance_faible(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    document = await _creer_document(db_session)

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_nom_fournisseur_incertain()
    )

    await db_session.refresh(document)
    assert len(_motifs_fournisseur_confiance(document)) == 1
    assert resultat.statut == "a_verifier"
    journal = await _journal_extraction(db_session, document.id)
    assert journal.apres is not None
    assert journal.apres["motifs_leves"] == []


async def test_relance_fournisseur_par_tva_leve_le_motif_mais_reste_a_verifier(
    db_session: AsyncSession,
) -> None:
    db_session.add(Fournisseur(nom="Négoce Exemple", tva="FR00000000000"))
    await db_session.commit()
    document = await _creer_document(db_session)

    resultat = await enregistrer_extraction_bl(
        db_session,
        document.id,
        _reponse_nom_fournisseur_incertain(),
        relance=True,
    )

    await db_session.refresh(document)
    assert _motifs_fournisseur_confiance(document) == []
    assert resultat.nb_motifs == 0
    assert document.statut == "a_verifier"  # une relance reste à vérifier


# --------------------------------------------------------------------------
# Lot 2 du 31/10/2026, A3 : chantier reconnu dans le référentiel, la
# confiance de lecture du nom ne compte plus ; chantier donné par la légende,
# il ne manque plus.
# --------------------------------------------------------------------------


def _reponse_chantier_incertain() -> dict[str, Any]:
    reponse = _reponse_synthetique()
    for mot in reponse["pages"][0]["confidence_scores"]["word_confidence_scores"]:
        if mot["text"] == " MAISON":
            mot["confidence"] = 0.10
    return reponse


def _reponse_sans_chantier() -> dict[str, Any]:
    reponse = _reponse_synthetique()
    annotation = _annotation(reponse)
    annotation["chantier_brut"] = None
    reponse["document_annotation"] = json.dumps(annotation)
    return reponse


def _motifs_chantier(document: Document, code: str) -> list[dict[str, Any]]:
    return [
        m
        for m in _motifs(document)
        if m["code"] == code and m["champ"] == "chantier_brut"
    ]


async def test_chantier_reconnu_retire_la_confiance_faible_du_nom_lu(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    db_session.add(Chantier(nom_canonique="Maison Test", a_completer=False))
    await db_session.commit()
    document = await _creer_document(db_session)

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_chantier_incertain()
    )

    await db_session.refresh(document)
    assert _motifs_chantier(document, "confiance_faible") == []
    assert resultat.statut == "recu"
    assert document.statut == "recu"
    journal = await _journal_extraction(db_session, document.id)
    assert journal.apres is not None
    assert journal.apres["motifs_leves"] == [
        {
            "champ": "chantier_brut",
            "raison": "Lecture du chantier confirmée : Maison Test (100 %)",
        }
    ]


async def test_chantier_a_completer_ne_confirme_pas_la_lecture(
    db_session: AsyncSession,
) -> None:
    """Un chantier créé automatiquement (« à compléter ») ne confirme rien."""
    await _creer_fournisseur_peintures_exemple(db_session)
    db_session.add(Chantier(nom_canonique="Maison Test", a_completer=True))
    await db_session.commit()
    document = await _creer_document(db_session)

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_chantier_incertain()
    )

    await db_session.refresh(document)
    assert len(_motifs_chantier(document, "confiance_faible")) == 1
    assert resultat.statut == "a_verifier"


async def test_chantier_cree_par_la_lecture_ne_confirme_pas_la_lecture(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    document = await _creer_document(db_session)

    await enregistrer_extraction_bl(
        db_session, document.id, _reponse_chantier_incertain()
    )

    await db_session.refresh(document)
    assert len(_motifs_chantier(document, "confiance_faible")) == 1
    journal = await _journal_extraction(db_session, document.id)
    assert journal.apres is not None
    assert journal.apres["motifs_leves"] == []


async def test_chantier_donne_par_la_legende_retire_champ_absent(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    db_session.add(Chantier(nom_canonique="Villa Legende", a_completer=False))
    await db_session.commit()
    document = await _creer_document(db_session)
    document.legende = "Chantier Villa Legende"
    await db_session.commit()

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_sans_chantier()
    )

    await db_session.refresh(document)
    assert document.chantier_id is not None
    assert _motifs_chantier(document, "champ_absent") == []
    assert resultat.statut == "recu"
    journal = await _journal_extraction(db_session, document.id)
    assert journal.apres is not None
    assert journal.apres["motifs_leves"] == [
        {
            "champ": "chantier_brut",
            "raison": "Chantier donné par la légende : Villa Legende",
        }
    ]


async def test_legende_vers_chantier_a_completer_garde_champ_absent(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    db_session.add(Chantier(nom_canonique="Villa Legende", a_completer=True))
    await db_session.commit()
    document = await _creer_document(db_session)
    document.legende = "Chantier Villa Legende"
    await db_session.commit()

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_sans_chantier()
    )

    await db_session.refresh(document)
    assert len(_motifs_chantier(document, "champ_absent")) == 1
    assert resultat.statut == "a_verifier"


async def test_legende_inconnue_cree_un_chantier_et_garde_champ_absent(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    document = await _creer_document(db_session)
    document.legende = "Chantier Nouveau Lieu"
    await db_session.commit()

    await enregistrer_extraction_bl(db_session, document.id, _reponse_sans_chantier())

    await db_session.refresh(document)
    assert len(_motifs_chantier(document, "champ_absent")) == 1


# --------------------------------------------------------------------------
# Lot 2 du 31/10/2026, A4 : chantier vide, lire la « Référence commande
# client » (`document.numero_commande`).
# --------------------------------------------------------------------------


def _reponse_reference(
    reference: str, *, chantier: str | None = None
) -> dict[str, Any]:
    reponse = _reponse_synthetique()
    annotation = _annotation(reponse)
    annotation["chantier_brut"] = chantier
    annotation["numero_commande"] = reference
    reponse["document_annotation"] = json.dumps(annotation)
    return reponse


async def _nombre_chantiers(db_session: AsyncSession) -> int:
    return len((await db_session.execute(select(Chantier.id))).all())


async def test_reference_de_commande_reconnue_rattache_le_chantier(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur_peintures_exemple(db_session)
    kayre = Chantier(nom_canonique="Kayre", a_completer=False)
    db_session.add(kayre)
    await db_session.commit()
    document = await _creer_document(db_session)

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_reference("KAYRE")
    )

    await db_session.refresh(document)
    assert document.chantier_id == kayre.id
    assert _motifs_chantier(document, "champ_absent") == []
    assert resultat.statut == "recu"
    journal = await _journal_extraction(db_session, document.id)
    assert journal.apres is not None
    assert journal.apres["methode_chantier"] == "référence de commande"
    assert journal.apres["score_chantier"] == 100
    assert journal.apres["motifs_leves"] == [
        {
            "champ": "chantier_brut",
            "raison": "Chantier retrouvé par la référence de commande : Kayre",
        }
    ]
    # Aucun apprentissage d'alias depuis une référence.
    alias = (
        await db_session.execute(
            select(ChantierAlias).where(ChantierAlias.fournisseur_id == fournisseur.id)
        )
    ).all()
    assert alias == []


async def test_reference_inconnue_ne_cree_pas_de_chantier(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    db_session.add(Chantier(nom_canonique="Kayre", a_completer=False))
    await db_session.commit()
    avant = await _nombre_chantiers(db_session)
    document = await _creer_document(db_session)

    resultat = await enregistrer_extraction_bl(
        db_session, document.id, _reponse_reference("CAMBUS")
    )

    await db_session.refresh(document)
    assert document.chantier_id is None
    assert await _nombre_chantiers(db_session) == avant
    assert _motifs_chantier(document, "champ_absent") == []
    inconnus = _motifs_chantier(document, "reference_chantier_inconnue")
    assert len(inconnus) == 1
    assert inconnus[0]["detail"] == {"reference": "CAMBUS"}
    assert resultat.statut == "a_verifier"


async def test_reference_ambigue_liste_les_chantiers_candidats(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    db_session.add_all(
        [
            Chantier(nom_canonique="Lot 12", a_completer=False),
            Chantier(nom_canonique="Lot 13", a_completer=False),
        ]
    )
    await db_session.commit()
    document = await _creer_document(db_session)

    await enregistrer_extraction_bl(
        db_session, document.id, _reponse_reference("Lot 14")
    )

    await db_session.refresh(document)
    assert document.chantier_id is None
    inconnus = _motifs_chantier(document, "reference_chantier_inconnue")
    assert len(inconnus) == 1
    assert inconnus[0]["detail"] == {
        "reference": "Lot 14",
        "candidats": "Lot 12, Lot 13",
    }


@pytest.mark.parametrize("reference", ["LORIS", "1089390591", "AB"])
async def test_reference_inutilisable_ne_change_rien(
    db_session: AsyncSession, reference: str
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    db_session.add(Chantier(nom_canonique="Loris", a_completer=False))
    db_session.add(
        Utilisateur(
            email="loris@example.invalid",
            role="agent",
            is_active=True,
            nom="Loris Legras",
        )
    )
    await db_session.commit()
    document = await _creer_document(db_session)

    await enregistrer_extraction_bl(
        db_session, document.id, _reponse_reference(reference)
    )

    await db_session.refresh(document)
    assert document.chantier_id is None
    assert len(_motifs_chantier(document, "champ_absent")) == 1
    assert _motifs_chantier(document, "reference_chantier_inconnue") == []


async def test_reference_ignoree_quand_le_nom_du_chantier_est_lu(
    db_session: AsyncSession,
) -> None:
    await _creer_fournisseur_peintures_exemple(db_session)
    kayre = Chantier(nom_canonique="Kayre", a_completer=False)
    db_session.add(kayre)
    await db_session.commit()
    document = await _creer_document(db_session)

    await enregistrer_extraction_bl(
        db_session,
        document.id,
        _reponse_reference("KAYRE", chantier="MAISON TEST (9900000001)"),
    )

    await db_session.refresh(document)
    assert document.chantier_id != kayre.id
