"""Tests de R02 — BL facturé « pas de bon » (CDC §5, L4-T2) et de
`mention_pas_de_bon`. Données inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import BlocControle, DocumentControle, Gravite
from app.modules.rules.rules.R02 import R02, mention_pas_de_bon


def _document(**overrides: Any) -> DocumentControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_interne": 1,
        "numero": "L209900000123",
        "date_doc": date(2026, 8, 12),
        "statut": "recu",
        "somme_lignes": Decimal("245.30"),
        "total_ht": Decimal("245.30"),
        "ecart_somme": None,
        "depose_le": None,
        "deposant": None,
        "confirme_le": None,
    }
    base.update(overrides)
    return DocumentControle(**base)


def _bloc(**overrides: Any) -> BlocControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_bl": "L209900000123",
        "date_bl": date(2026, 8, 12),
        "chantier_brut": "MAISON TEST",
        "chantier": "maison test",
        "commentaire": None,
        "montant_ht": Decimal("245.30"),
        "bl": None,
        "lignes": (),
        "lignes_bl_non_facturees": (),
        "autre_facture_numero": None,
        "autre_facture_id": None,
    }
    base.update(overrides)
    return BlocControle(**base)


# --- mention_pas_de_bon ------------------------------------------------


def test_mention_pas_de_bon_commentaire_none_renvoie_none() -> None:
    assert mention_pas_de_bon(None) is None


def test_mention_pas_de_bon_sans_mention_renvoie_none() -> None:
    assert mention_pas_de_bon("Retrait effectué normalement, RAS") is None


def test_mention_pas_de_bon_commentaire_vide_renvoie_none() -> None:
    assert mention_pas_de_bon("") is None


def test_mention_pas_de_bon_variante_simple() -> None:
    extrait = mention_pas_de_bon("RETRAIT FRED PAS DE BON")
    assert extrait == "RETRAIT FRED PAS DE BON"


def test_mention_pas_de_bon_variante_minuscules_et_accents() -> None:
    """La casse et les accents du reste du commentaire ne gênent pas la
    détection (normalisation : majuscules, sans accents)."""
    extrait = mention_pas_de_bon("Enlèvement client, pas de bon fourni")
    assert extrait == "Enlèvement client, pas de bon fourni"


def test_mention_pas_de_bon_variante_espaces_multiples() -> None:
    extrait = mention_pas_de_bon("RETRAIT   PAS    DE   BON")
    assert extrait is not None


def test_mention_pas_de_bon_variante_ponctuation_entre_les_mots() -> None:
    extrait = mention_pas_de_bon("RETRAIT, PAS - DE / BON")
    assert extrait is not None


def test_mention_pas_de_bon_variante_sans_bon() -> None:
    extrait = mention_pas_de_bon("CLIENT REPART SANS BON DE LIVRAISON")
    assert extrait is not None


def test_mention_pas_de_bon_extrait_tronque_a_200_caracteres() -> None:
    commentaire = ("X" * 150) + " PAS DE BON " + ("Y" * 150)

    extrait = mention_pas_de_bon(commentaire)

    assert extrait is not None
    assert len(extrait) <= 200
    assert "PAS DE BON" in extrait  # la mention reste dans l'extrait


def test_mention_pas_de_bon_extrait_court_renvoie_le_commentaire_entier() -> None:
    commentaire = "RETRAIT FRED, PAS DE BON, à confirmer demain"
    assert mention_pas_de_bon(commentaire) == commentaire


# --- R02 -----------------------------------------------------------------


def test_R02_bloc_sans_bl_avec_mention_produit_une_anomalie_haute() -> None:
    bloc = _bloc(commentaire="RETRAIT FRED PAS DE BON")

    anomalie = R02(bloc)

    assert anomalie is not None
    assert anomalie.regle == "R02"
    assert anomalie.gravite is Gravite.HAUTE
    assert anomalie.bloc_id == bloc.id
    assert anomalie.document_id is None
    assert anomalie.ligne_id is None
    assert anomalie.detail == {
        "numero_bl": "L209900000123",
        "chantier": "maison test",
        "date_bl": "2026-08-12",
        "montant_ht": "245.30",
        "mention": "RETRAIT FRED PAS DE BON",
    }
    assert anomalie.detail  # jamais vide


def test_R02_bloc_sans_mention_ne_produit_rien() -> None:
    bloc = _bloc(commentaire="Retrait normal, RAS")
    assert R02(bloc) is None


def test_R02_bloc_sans_commentaire_ne_produit_rien() -> None:
    bloc = _bloc(commentaire=None)
    assert R02(bloc) is None


def test_R02_bloc_avec_bl_rapproche_et_mention_ne_produit_rien() -> None:
    """Le bon a bien été remis malgré la mention : R02 ne se déclenche pas
    (décision du contrôleur — « même si la mention est présente »)."""
    bloc = _bloc(commentaire="RETRAIT FRED PAS DE BON", bl=_document())
    assert R02(bloc) is None


def test_R02_valeurs_manquantes_utilisent_un_tiret() -> None:
    bloc = _bloc(
        commentaire="PAS DE BON",
        numero_bl=None,
        date_bl=None,
        chantier=None,
        chantier_brut=None,
    )

    anomalie = R02(bloc)

    assert anomalie is not None
    assert anomalie.detail["numero_bl"] == "—"
    assert anomalie.detail["date_bl"] == "—"
    assert anomalie.detail["chantier"] == "—"
