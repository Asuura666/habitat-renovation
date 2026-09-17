"""Tests de `normaliser_unite` et `convertir_en_unite_fact` (`unites.py`)."""

from __future__ import annotations

from decimal import Decimal

from app.modules.normalize.unites import (
    NatureUnite,
    Unite,
    convertir_en_unite_fact,
    normaliser_unite,
)


def test_normaliser_unite_mesure_connue_insensible_casse_et_espaces() -> None:
    assert normaliser_unite(" Kgs ") == Unite(code="kg", nature=NatureUnite.MESURE)


def test_normaliser_unite_conditionnement_connu() -> None:
    assert normaliser_unite("SEAUX") == Unite(
        code="seau", nature=NatureUnite.CONDITIONNEMENT
    )


def test_normaliser_unite_bag_reconnu_comme_sac() -> None:
    """L3-D26, constat 11 : Point.P imprime « BAG » (sac)."""
    assert normaliser_unite("BAG") == Unite(
        code="sac", nature=NatureUnite.CONDITIONNEMENT
    )
    assert normaliser_unite("bags") == Unite(
        code="sac", nature=NatureUnite.CONDITIONNEMENT
    )


def test_normaliser_unite_metre_carre_symbole_exposant() -> None:
    assert normaliser_unite("M²") == Unite(code="m2", nature=NatureUnite.MESURE)


def test_normaliser_unite_inconnue_renvoie_none() -> None:
    assert normaliser_unite("XYZ") is None


def test_normaliser_unite_none_renvoie_none() -> None:
    assert normaliser_unite(None) is None


# --------------------------------------------------------------------------
# convertir_en_unite_fact (L4-D7, L4-T6)
#
# CDC §10 : « 0 anomalie R03/R04 due à une unité ». Une conversion qui ne
# peut pas être établie avec certitude renvoie `None` plutôt que de deviner :
# aucun des quatre cas du Ruling R6 ne tolère d'approximation.
# --------------------------------------------------------------------------


def test_convertir_unite_lue_egale_unite_fact_renvoie_qte_inchangee() -> None:
    assert convertir_en_unite_fact(
        qte=Decimal("10"),
        unite_lue="KG",
        unite_cdt=None,
        unite_fact="kg",
        ratio=None,
        ratio_valide=False,
    ) == Decimal("10")


def test_convertir_unite_lue_egale_unite_cdt_avec_ratio_valide_multiplie() -> None:
    assert convertir_en_unite_fact(
        qte=Decimal("4"),
        unite_lue="SEAU",
        unite_cdt="seau",
        unite_fact="kg",
        ratio=Decimal("25"),
        ratio_valide=True,
    ) == Decimal("100")


def test_convertir_unite_lue_absente_et_unite_fact_connue_renvoie_qte_inchangee() -> (
    None
):
    """Cas Unikalo (constat 4) : la ligne n'imprime pas d'unité."""
    assert convertir_en_unite_fact(
        qte=Decimal("15"),
        unite_lue=None,
        unite_cdt=None,
        unite_fact="kg",
        ratio=None,
        ratio_valide=False,
    ) == Decimal("15")


def test_convertir_unite_lue_absente_et_unite_fact_inconnue_renvoie_none() -> None:
    assert (
        convertir_en_unite_fact(
            qte=Decimal("15"),
            unite_lue=None,
            unite_cdt=None,
            unite_fact="XYZ",
            ratio=None,
            ratio_valide=False,
        )
        is None
    )


def test_convertir_unite_lue_egale_unite_cdt_mais_ratio_non_valide_renvoie_none() -> (
    None
):
    assert (
        convertir_en_unite_fact(
            qte=Decimal("4"),
            unite_lue="SEAU",
            unite_cdt="seau",
            unite_fact="kg",
            ratio=Decimal("25"),
            ratio_valide=False,
        )
        is None
    )


def test_convertir_unite_lue_egale_unite_cdt_mais_ratio_absent_renvoie_none() -> None:
    assert (
        convertir_en_unite_fact(
            qte=Decimal("4"),
            unite_lue="SEAU",
            unite_cdt="seau",
            unite_fact="kg",
            ratio=None,
            ratio_valide=True,
        )
        is None
    )


def test_convertir_unite_lue_egale_unite_cdt_mais_ratio_nul_renvoie_none() -> None:
    assert (
        convertir_en_unite_fact(
            qte=Decimal("4"),
            unite_lue="SEAU",
            unite_cdt="seau",
            unite_fact="kg",
            ratio=Decimal("0"),
            ratio_valide=True,
        )
        is None
    )


def test_convertir_unite_lue_egale_unite_cdt_mais_ratio_negatif_renvoie_none() -> None:
    assert (
        convertir_en_unite_fact(
            qte=Decimal("4"),
            unite_lue="SEAU",
            unite_cdt="seau",
            unite_fact="kg",
            ratio=Decimal("-25"),
            ratio_valide=True,
        )
        is None
    )


def test_convertir_unite_lue_ne_correspond_a_rien_renvoie_none() -> None:
    """Unité lue reconnue (« L ») mais qui n'est ni `unite_fact` ni
    `unite_cdt` de l'article : pas de conversion devinée."""
    assert (
        convertir_en_unite_fact(
            qte=Decimal("4"),
            unite_lue="L",
            unite_cdt="seau",
            unite_fact="kg",
            ratio=Decimal("25"),
            ratio_valide=True,
        )
        is None
    )


def test_convertir_unite_lue_inconnue_renvoie_none() -> None:
    assert (
        convertir_en_unite_fact(
            qte=Decimal("4"),
            unite_lue="XYZ",
            unite_cdt="seau",
            unite_fact="kg",
            ratio=Decimal("25"),
            ratio_valide=True,
        )
        is None
    )


def test_convertir_qte_none_renvoie_none() -> None:
    assert (
        convertir_en_unite_fact(
            qte=None,
            unite_lue="KG",
            unite_cdt=None,
            unite_fact="kg",
            ratio=None,
            ratio_valide=False,
        )
        is None
    )
