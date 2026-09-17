"""Tests de R10 — incohérence arithmétique facture (CDC §5, L4-T1).

Toutes les données sont inventées (`DocumentControle` construit à la main),
aucune fixture, aucune base."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import DocumentControle, Gravite, Parametres
from app.modules.rules.rules.R10 import R10


def _document(**overrides: Any) -> DocumentControle:
    """`DocumentControle` de facture cohérente par défaut (`ecart_somme`
    `None`) ; chaque test override ce qui l'intéresse."""
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_interne": 1,
        "numero": "FAC0001",
        "date_doc": date(2026, 8, 1),
        "statut": "extraite",
        "somme_lignes": Decimal("100.00"),
        "total_ht": Decimal("100.00"),
        "ecart_somme": None,
        "depose_le": None,
        "deposant": None,
        "confirme_le": None,
    }
    base.update(overrides)
    return DocumentControle(**base)


# --------------------------------------------------------------------------
# Négatifs
# --------------------------------------------------------------------------


def test_R10_sans_ecart_calcule_ne_produit_rien() -> None:
    """`ecart_somme` `None` (somme cohérente ou non calculable, L4-D8) :
    R10 ne recalcule jamais la somme lui-même."""
    document = _document(ecart_somme=None)
    assert R10(document, Parametres()) is None


def test_R10_ecart_exactement_a_la_tolerance_ne_produit_rien() -> None:
    """Égalité à la tolérance acceptée (`>` strict, pas `>=`)."""
    parametres = Parametres(tolerance_total_ht=Decimal("0.05"))
    document = _document(
        somme_lignes=Decimal("100.05"),
        total_ht=Decimal("100.00"),
        ecart_somme=Decimal("0.05"),
    )
    assert R10(document, parametres) is None


def test_R10_donnees_incoherentes_sans_total_ne_leve_pas() -> None:
    """`ecart_somme` renseigné mais `total_ht` absent (état incohérent qui
    ne devrait jamais arriver depuis `ingest`) : une règle ne lève jamais,
    une donnée manquante donne `None`."""
    document = _document(total_ht=None, ecart_somme=Decimal("1.00"))
    assert R10(document, Parametres()) is None


# --------------------------------------------------------------------------
# Positifs
# --------------------------------------------------------------------------


def test_R10_ecart_au_dessus_de_la_tolerance_produit_une_anomalie_haute() -> None:
    parametres = Parametres(tolerance_total_ht=Decimal("0.05"))
    document = _document(
        somme_lignes=Decimal("100.06"),
        total_ht=Decimal("100.00"),
        ecart_somme=Decimal("0.06"),
    )

    anomalie = R10(document, parametres)

    assert anomalie is not None
    assert anomalie.regle == "R10"
    assert anomalie.gravite is Gravite.HAUTE
    assert anomalie.document_id == document.id
    assert anomalie.bloc_id is None
    assert anomalie.ligne_id is None
    assert anomalie.article_id is None
    assert anomalie.detail == {
        "somme": "100.06",
        "total": "100.00",
        "ecart": "0.06",
        "tolerance": "0.05",
    }


def test_R10_ecart_negatif_au_dela_de_la_tolerance_produit_une_anomalie() -> None:
    parametres = Parametres(tolerance_total_ht=Decimal("0.05"))
    document = _document(
        somme_lignes=Decimal("99.90"),
        total_ht=Decimal("100.00"),
        ecart_somme=Decimal("-0.10"),
    )

    anomalie = R10(document, parametres)

    assert anomalie is not None
    assert anomalie.detail["ecart"] == "-0.10"
    assert anomalie.detail  # jamais vide
