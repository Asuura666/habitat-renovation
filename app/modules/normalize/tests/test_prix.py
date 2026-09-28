"""Tests de `normalize/prix.py` (phase 3, tâche P2, spec §4).

Toutes les données sont inventées, y compris le tableau de l'exemple §4.3 :
la spec le dit elle-même explicitement (« exemples inventés, même forme que
les vraies paires »)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.normalize.prix import (
    Conversion,
    Correspondance,
    ProduitGrille,
    cle_produit,
    mots_produit,
    normaliser_reference,
    prix_net,
    ressemblance_produit,
    trouver_produit,
    unites_comparables,
)

# --------------------------------------------------------------------------
# normaliser_reference / cle_produit (spec §4.1)
# --------------------------------------------------------------------------


def test_normaliser_reference_insensible_casse_espaces_et_tirets() -> None:
    assert normaliser_reference(" ABC-123 ") == "abc123"


def test_normaliser_reference_none_renvoie_chaine_vide() -> None:
    assert normaliser_reference(None) == ""


def test_cle_produit_par_reference_si_non_vide() -> None:
    assert cle_produit("ABC-123", "Plaque std") == "ref:abc123"


def test_cle_produit_par_designation_si_reference_absente() -> None:
    assert cle_produit(None, "Plaque std") == "nom:plaque std"


def test_cle_produit_par_designation_si_reference_blanche() -> None:
    """Une référence qui ne contient que des espaces ou de la ponctuation
    (donc vide une fois normalisée) retombe sur la désignation."""
    assert cle_produit("   ", "Plaque std") == "nom:plaque std"


def test_cle_produit_meme_reference_ecrite_differemment_meme_cle() -> None:
    assert cle_produit("abc 123", "Plaque std") == cle_produit(
        "ABC-123", "Autre libellé"
    )


# --------------------------------------------------------------------------
# prix_net (spec §4.2)
# --------------------------------------------------------------------------


def test_prix_net_sans_remise_renvoie_le_prix_ht() -> None:
    assert prix_net(Decimal("7.5"), None) == Decimal("7.5000")


def test_prix_net_avec_remise() -> None:
    assert prix_net(Decimal("10"), Decimal("12.5")) == Decimal("8.7500")


def test_prix_net_arrondi_a_quatre_decimales_round_half_up() -> None:
    assert prix_net(Decimal("10"), Decimal("33.333")) == Decimal("6.6667")


def test_prix_net_refuse_prix_ht_nul() -> None:
    with pytest.raises(ValueError):
        prix_net(Decimal("0"), None)


def test_prix_net_refuse_prix_ht_negatif() -> None:
    with pytest.raises(ValueError):
        prix_net(Decimal("-5"), None)


def test_prix_net_refuse_remise_negative() -> None:
    with pytest.raises(ValueError):
        prix_net(Decimal("10"), Decimal("-1"))


def test_prix_net_refuse_remise_de_100() -> None:
    with pytest.raises(ValueError):
        prix_net(Decimal("10"), Decimal("100"))


# --------------------------------------------------------------------------
# mots_produit (spec §4.3, point 1)
# --------------------------------------------------------------------------


def test_mots_produit_separe_chiffres_et_lettres_accolees() -> None:
    assert mots_produit("70mm") == frozenset({"70", "mm"})
    assert mots_produit("d14mm") == frozenset({"d", "14", "mm"})


def test_mots_produit_nom_vide_renvoie_ensemble_vide() -> None:
    assert mots_produit("") == frozenset()
    assert mots_produit(None) == frozenset()


def test_mots_produit_insensible_casse_et_accents() -> None:
    assert mots_produit("Isolant Laine ALPHA") == frozenset(
        {"isolant", "laine", "alpha"}
    )


# --------------------------------------------------------------------------
# ressemblance_produit (spec §4.3, tableau -- exemples inventés)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bon", "grille", "score"),
    [
        ("CLOISON STD KX 48 NF 3M", "Cloison 48", 100),
        ("CLOISON STD KX 70 NF 3M", "Cloison 48", 50),
        ("ENDUIT PRO E2 LENT 25KG", "E2 lent", 100),
        ("ENDUIT PRO E2 LENT 25KG", "E3 lent", 66),
        ("ISOLANT LAINE ALPHA 70MM", "Alpha 70", 100),
        ("ISOLANT LAINE ALPHA 70MM", "Alpha 45", 50),
    ],
)
def test_ressemblance_produit_tableau_de_la_spec(
    bon: str, grille: str, score: int
) -> None:
    assert ressemblance_produit(bon, grille) == score


def test_ressemblance_produit_symetrique() -> None:
    a, b = "CLOISON STD KX 48 NF 3M", "Cloison 48"
    assert ressemblance_produit(a, b) == ressemblance_produit(b, a)


def test_ressemblance_produit_nom_vide_renvoie_zero() -> None:
    assert ressemblance_produit("", "Cloison 48") == 0
    assert ressemblance_produit("Cloison 48", "") == 0


# --------------------------------------------------------------------------
# trouver_produit (spec §4.3, points 2-3)
# --------------------------------------------------------------------------


def _produit(
    designation: str, reference: str | None = None, cle: str | None = None
) -> ProduitGrille:
    return ProduitGrille(
        cle=cle or f"nom:{designation.lower()}",
        reference=reference,
        designation=designation,
        unite=None,
        prix_net=Decimal("10"),
        date_effet=date(2026, 1, 1),
    )


def test_trouver_produit_par_reference_prioritaire_sur_le_nom() -> None:
    """Même si la désignation ressemble peu, la référence l'emporte."""
    produit_ref = _produit("Plaque std 13", reference="ABC-123")
    produit_nom = _produit("PLAQUE STANDARD BA13 2500", reference=None)
    resultat = trouver_produit(
        "abc123", "AUTRE CHOSE SANS RAPPORT", [produit_ref, produit_nom], seuil=80
    )
    assert resultat == Correspondance(
        produit=produit_ref, methode="reference", ressemblance=100
    )


def test_trouver_produit_par_nom_au_dessus_du_seuil() -> None:
    produit = _produit("Alpha 70")
    resultat = trouver_produit(None, "ISOLANT LAINE ALPHA 70MM", [produit], seuil=80)
    assert resultat == Correspondance(produit=produit, methode="nom", ressemblance=100)


def test_trouver_produit_sous_le_seuil_renvoie_aucun_sans_candidats() -> None:
    produit = _produit("Alpha 45")
    resultat = trouver_produit(None, "ISOLANT LAINE ALPHA 70MM", [produit], seuil=80)
    assert resultat is None


def test_trouver_produit_sans_aucun_produit_renvoie_aucun() -> None:
    assert trouver_produit(None, "ISOLANT LAINE ALPHA 70MM", [], seuil=50) is None


def test_trouver_produit_egalite_departagee_par_l_ancienne_ressemblance() -> None:
    """Deux produits à égalité sur `ressemblance_produit` (50) mais
    départagés par `ressemblance` (l'ancienne, 57 contre 42)."""
    gagnant = _produit("ABC XYZ")
    perdant = _produit("DEF XYZ")
    resultat = trouver_produit(None, "ABC DEF", [perdant, gagnant], seuil=40)
    assert resultat == Correspondance(produit=gagnant, methode="nom", ressemblance=50)


def test_trouver_produit_egalite_parfaite_renvoie_aucun_et_candidats() -> None:
    """Égalité non départageable même par l'ancienne ressemblance (mêmes
    mots, ordre différent) : aucune correspondance, candidats rendus."""
    produit_a = _produit("ABC GHI")
    produit_b = _produit("GHI ABC")
    resultat = trouver_produit(None, "ABC DEF", [produit_a, produit_b], seuil=40)
    assert resultat == Correspondance(
        produit=None,
        methode="nom",
        ressemblance=50,
        candidats=("ABC GHI", "GHI ABC"),
    )


def test_trouver_produit_candidats_limites_a_trois() -> None:
    produits = [_produit(f"ABC GHI {i}") for i in range(5)]
    resultat = trouver_produit(None, "ABC DEF", produits, seuil=10)
    assert resultat is not None
    assert resultat.produit is None
    assert len(resultat.candidats) == 3


# --------------------------------------------------------------------------
# unites_comparables (spec §4.4)
# --------------------------------------------------------------------------


def test_unites_comparables_meme_unite() -> None:
    resultat = unites_comparables("kg", "kg", None, None, None, False)
    assert resultat == Conversion(possible=True, facteur=Decimal("1"))


def test_unites_comparables_memes_variantes_ecrites_differemment() -> None:
    resultat = unites_comparables("KGS", "Kilo", None, None, None, False)
    assert resultat == Conversion(possible=True, facteur=Decimal("1"))


def test_unites_comparables_bon_en_conditionnement_ref_en_facturation() -> None:
    """Grille au kg, bon au seau de 15 kg : le prix de référence est ramené
    à l'unité du bon (facteur 15, spec §4.4)."""
    resultat = unites_comparables("seau", "kg", "seau", "kg", Decimal("15"), True)
    assert resultat == Conversion(possible=True, facteur=Decimal("15"))


def test_unites_comparables_bon_en_facturation_ref_en_conditionnement() -> None:
    """Sens inverse : facteur `1 / ratio`."""
    resultat = unites_comparables("kg", "seau", "seau", "kg", Decimal("15"), True)
    assert resultat == Conversion(possible=True, facteur=Decimal(1) / Decimal("15"))


def test_unites_comparables_ratio_non_valide_impossible() -> None:
    resultat = unites_comparables("seau", "kg", "seau", "kg", Decimal("15"), False)
    assert resultat == Conversion(possible=False)


def test_unites_comparables_ratio_absent_impossible() -> None:
    resultat = unites_comparables("seau", "kg", "seau", "kg", None, True)
    assert resultat == Conversion(possible=False)


def test_unites_comparables_une_seule_unite_connue_facteur_un() -> None:
    """Cas Cedeo : la grille n'a pas d'unité, celle du bon (sac) est
    traitée comme comparable (facteur 1, l'humain juge)."""
    resultat = unites_comparables("sac", None, None, None, None, False)
    assert resultat == Conversion(possible=True, facteur=Decimal("1"))


def test_unites_comparables_deux_unites_inconnues_facteur_un() -> None:
    resultat = unites_comparables("XYZ", "ABC", None, None, None, False)
    assert resultat == Conversion(possible=True, facteur=Decimal("1"))


def test_unites_comparables_unites_differentes_sans_article_impossible() -> None:
    resultat = unites_comparables("l", "kg", None, None, None, False)
    assert resultat == Conversion(possible=False)
