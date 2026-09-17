"""Tests de `evaluer_facture` (L4-T1, L4-T2) : ordre du CDC §5, Ruling R2.

R10 (document), R11 (BL rapproché par bloc) et, depuis L4-T2, R01/R02/R12
(niveau bloc, toujours évaluées) sont enchaînées ; les règles de ligne
(R03-R09/R13/R17) n'existent pas encore (L4-T3 à L4-T5). Données
inventées."""

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


def test_evaluer_facture_bloc_sans_bl_produit_r01_et_pas_r11() -> None:
    """Un bloc sans BL déposé (`bl=None`) ne fait pas planter R11 (elle
    n'est simplement pas évaluée, ce n'est pas son rôle) et produit R01
    (BL facturé non reçu, L4-T2) puisqu'aucune mention « pas de bon »
    n'est présente sur son commentaire."""
    document = _document(coherent=True)
    bloc = _bloc(bl=None)

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert len(anomalies) == 1
    assert anomalies[0].regle == "R01"
    assert anomalies[0].bloc_id == bloc.id


def test_evaluer_facture_bloc_recu_ne_produit_ni_r01_ni_r02() -> None:
    """Un bloc dont le BL a été rapproché (`bl` non `None`) ne produit ni
    R01 ni R02, même si son commentaire porte une mention « pas de bon » —
    le bon a bien été remis (décision du contrôleur)."""
    document = _document(coherent=True)
    bl = _document(coherent=True)
    bloc = _bloc(bl=bl, commentaire="RETRAIT FRED PAS DE BON")

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert anomalies == ()


def test_evaluer_facture_bloc_sans_bl_avec_mention_produit_r02_pas_r01() -> None:
    document = _document(coherent=True)
    bloc = _bloc(bl=None, commentaire="RETRAIT FRED PAS DE BON")

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert len(anomalies) == 1
    assert anomalies[0].regle == "R02"


def test_evaluer_facture_r12_evaluee_meme_si_r11_se_declenche() -> None:
    """Ruling R2 (restructuration L4-T2) : quand R11 se déclenche pour un
    bloc, ses règles de *ligne* (pas encore écrites) seraient sautées,
    mais pas ses règles de *bloc* — ici R12, indépendante de R11."""
    document = _document(coherent=True)
    bl_incoherent = _document(coherent=False)
    bloc = _bloc(
        bl=bl_incoherent,
        autre_facture_numero="FAC-AUTRE-INVENTEE",
        autre_facture_id=uuid.uuid4(),
    )

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert [a.regle for a in anomalies] == ["R11", "R12"]
    assert anomalies[0].document_id == bl_incoherent.id
    assert anomalies[1].bloc_id == bloc.id


def test_evaluer_facture_r01_et_r12_ordre_dans_le_meme_bloc() -> None:
    document = _document(coherent=True)
    bloc = _bloc(
        bl=None,
        autre_facture_numero="FAC-AUTRE-INVENTEE",
        autre_facture_id=uuid.uuid4(),
    )

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert [a.regle for a in anomalies] == ["R01", "R12"]


def test_evaluer_facture_r02_et_r12_ordre_dans_le_meme_bloc() -> None:
    document = _document(coherent=True)
    bloc = _bloc(
        bl=None,
        commentaire="RETRAIT FRED PAS DE BON",
        autre_facture_numero="FAC-AUTRE-INVENTEE",
        autre_facture_id=uuid.uuid4(),
    )

    anomalies = evaluer_facture(_facture(document, (bloc,)), Parametres())

    assert [a.regle for a in anomalies] == ["R02", "R12"]


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
