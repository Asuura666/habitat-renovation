"""Tests de `evaluer_facture` (L4-T1) : ordre du CDC §5, Ruling R2.

À ce stade, seules R10 (document) et R11 (BL rapproché par bloc) sont
enchaînées ; les autres niveaux (R01/R02/R12 au bloc, R03-R09/R13/R17 à la
ligne) n'existent pas encore (L4-T2 à L4-T5). Données inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.engine import evaluer_facture
from app.modules.rules.modeles import (
    BlocControle,
    DocumentControle,
    FactureControlee,
    Parametres,
)


def _document(*, coherent: bool = True, **overrides: Any) -> DocumentControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_interne": 1,
        "numero": "DOC0001",
        "date_doc": date(2026, 8, 1),
        "statut": "extraite",
        "somme_lignes": Decimal("100.00"),
        "total_ht": Decimal("100.00"),
        "ecart_somme": None,
        "depose_le": None,
        "deposant": None,
        "confirme_le": None,
    }
    if not coherent:
        base.update(
            somme_lignes=Decimal("110.00"),
            total_ht=Decimal("100.00"),
            ecart_somme=Decimal("10.00"),
        )
    base.update(overrides)
    return DocumentControle(**base)


def _bloc(**overrides: Any) -> BlocControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_bl": "BL0001",
        "date_bl": date(2026, 8, 1),
        "chantier_brut": "CHANTIER INVENTE",
        "chantier": "chantier invente",
        "commentaire": None,
        "montant_ht": Decimal("100.00"),
        "bl": None,
        "lignes": (),
        "lignes_bl_non_facturees": (),
        "autre_facture_numero": None,
        "autre_facture_id": None,
    }
    base.update(overrides)
    return BlocControle(**base)


def _facture(
    document: DocumentControle, blocs: tuple[BlocControle, ...] = ()
) -> FactureControlee:
    return FactureControlee(
        document=document,
        fournisseur="FOURNISSEUR INVENTE",
        blocs=blocs,
        articles={},
        historiques={},
        lignes_negatives_sans_origine=(),
    )


def test_evaluer_facture_sans_aucune_incoherence_ne_produit_rien() -> None:
    document = _document(coherent=True)
    bloc = _bloc(bl=_document(coherent=True))

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert anomalies == ()


def test_evaluer_facture_bloc_sans_bl_rapproche_est_ignore_par_r11() -> None:
    """Un bloc sans BL déposé (`bl=None`, matière de R01) ne fait pas
    planter R11 : ce n'est simplement pas son rôle à ce stade."""
    document = _document(coherent=True)
    bloc = _bloc(bl=None)

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert anomalies == ()


def test_evaluer_facture_r10_est_la_seule_anomalie_renvoyee() -> None:
    """Ruling R2 : si R10 produit une anomalie, elle est la **seule**
    renvoyée — même si un bloc porte un BL par ailleurs incohérent."""
    document = _document(coherent=False)
    bloc = _bloc(bl=_document(coherent=False))

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert len(anomalies) == 1
    assert anomalies[0].regle == "R10"
    assert anomalies[0].document_id == document.id


def test_evaluer_facture_r11_par_bloc_dans_lordre_des_blocs() -> None:
    """Facture cohérente, trois blocs dont le premier et le troisième
    portent un BL incohérent : les anomalies R11 sont renvoyées dans
    l'ordre des blocs, le second bloc (cohérent) n'en produit aucune."""
    document = _document(coherent=True)
    bl_incoherent_1 = _document(coherent=False)
    bl_coherent = _document(coherent=True)
    bl_incoherent_3 = _document(coherent=False)
    blocs = (
        _bloc(bl=bl_incoherent_1),
        _bloc(bl=bl_coherent),
        _bloc(bl=bl_incoherent_3),
    )

    anomalies = evaluer_facture(_facture(document, blocs), Parametres())

    assert len(anomalies) == 2
    assert [a.regle for a in anomalies] == ["R11", "R11"]
    assert anomalies[0].document_id == bl_incoherent_1.id
    assert anomalies[1].document_id == bl_incoherent_3.id
    assert all(a.detail for a in anomalies)  # detail jamais vide
