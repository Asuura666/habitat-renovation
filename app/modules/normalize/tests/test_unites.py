"""Tests de `normaliser_unite` et `convertir_en_unite_fact` (`unites.py`)."""

from __future__ import annotations

from decimal import Decimal

from app.modules.normalize.unites import (
    NatureUnite,
    Unite,
    convertir_en_unite_fact,
    normaliser_unite,
    unite_implicite,
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
# convertir_en_unite_fact (L4-D7, L4-T6, fix round 1 Ruling R10, fix round 1
# de L4-T7 Ruling R14)
#
# CDC §10 : « 0 anomalie R03/R04 due à une unité ». Une conversion qui ne
# peut pas être établie avec certitude renvoie `None` plutôt que de deviner :
# aucun des cas du Ruling R6 ne tolère d'approximation.
#
# Ruling R10 : `unite_absente_acceptee` distingue une facture Unikalo (pas
# de colonne unité, l'appelant passe `True`) d'une ligne de BL photographié
# (une unité y est toujours imprimée quand l'article est résolu : son
# absence signale alors un échec d'OCR, jamais une acceptation, l'appelant
# passe `False`, la valeur par défaut).
#
# Ruling R14 (fix round 1 de la tâche L4-T7, constat réel sur la facture
# Unikalo d'août) : quand ni l'unité lue ni l'unité de facturation de
# l'article ne sont connues, la quantité est renvoyée inchangée, quel que
# soit `unite_absente_acceptee` -- `unite_absente_acceptee` ne garde son
# sens que pour le cas où `unite_fact` est connue mais pas imprimée sur ce
# document précis.
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


def test_convertir_unite_lue_egale_unite_cdt_multiplication_decimale_exacte() -> None:
    """Fix round 1 : `Decimal * Decimal` doit rester exact pour une quantité
    non entière (`Decimal` jamais `float`, `CLAUDE.md`)."""
    assert convertir_en_unite_fact(
        qte=Decimal("4.5"),
        unite_lue="SEAU",
        unite_cdt="seau",
        unite_fact="kg",
        ratio=Decimal("25"),
        ratio_valide=True,
    ) == Decimal("112.5")


def test_convertir_unite_absente_acceptee_et_fact_connue_renvoie_qte() -> None:
    """Cas Unikalo (constat 4) : la facture n'imprime pas d'unité, l'appelant
    (L4-T7) passe donc `unite_absente_acceptee=True`."""
    assert convertir_en_unite_fact(
        qte=Decimal("15"),
        unite_lue=None,
        unite_cdt=None,
        unite_fact="kg",
        ratio=None,
        ratio_valide=False,
        unite_absente_acceptee=True,
    ) == Decimal("15")


def test_convertir_unite_absente_et_fact_inconnue_renvoie_qte_ruling_r14() -> None:
    """Ruling R14 (fix round 1, L4-T7) : ni l'unité lue ni l'unité de
    facturation de l'article ne sont connues (`unite_fact="XYZ"` n'est pas
    reconnue par `normaliser_unite`) -> la quantité est renvoyée inchangée,
    même avec `unite_absente_acceptee=True` (avant ce ruling, ce cas
    renvoyait `None` -- constat réel : c'est exactement la situation
    Unikalo, aucune unité nulle part)."""
    assert convertir_en_unite_fact(
        qte=Decimal("15"),
        unite_lue=None,
        unite_cdt=None,
        unite_fact="XYZ",
        ratio=None,
        ratio_valide=False,
        unite_absente_acceptee=True,
    ) == Decimal("15")


def test_convertir_unite_et_fact_toutes_deux_absentes_renvoie_qte_ruling_r14() -> None:
    """Ruling R14 : même résultat quand `unite_fact` est carrément `None`
    (article pas encore résolu), pas seulement une chaîne non reconnue."""
    assert convertir_en_unite_fact(
        qte=Decimal("15"),
        unite_lue=None,
        unite_cdt=None,
        unite_fact=None,
        ratio=None,
        ratio_valide=False,
        unite_absente_acceptee=True,
    ) == Decimal("15")


def test_convertir_unite_absente_non_acceptee_et_fact_connue_none() -> None:
    """Fix round 1, Ruling R10 : une ligne de BL photographié imprime
    toujours une unité (CDC §4.3) -- son absence signale un échec d'OCR, pas
    l'absence de colonne. `unite_absente_acceptee` par défaut (`False`)
    refuse la conversion même si `unite_fact` est connue, pour ne jamais
    comparer silencieusement une quantité potentiellement fausse (R03/R04)."""
    assert (
        convertir_en_unite_fact(
            qte=Decimal("15"),
            unite_lue=None,
            unite_cdt=None,
            unite_fact="kg",
            ratio=None,
            ratio_valide=False,
        )
        is None
    )


def test_convertir_unite_absente_non_acceptee_fact_inconnue_ruling_r14() -> None:
    """Ruling R14 : le nouveau cas s'applique « quel que soit le drapeau »
    -- ici `unite_absente_acceptee=False` (valeur par défaut, ligne de BL),
    même résultat que la variante `True` ci-dessus."""
    assert convertir_en_unite_fact(
        qte=Decimal("15"),
        unite_lue=None,
        unite_cdt=None,
        unite_fact="XYZ",
        ratio=None,
        ratio_valide=False,
        unite_absente_acceptee=False,
    ) == Decimal("15")


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


def test_convertir_unite_lue_connue_mais_fact_et_cdt_absentes_renvoie_none() -> None:
    """Ruling R14 ne s'applique jamais quand une unité a effectivement été
    lue (« reconnue mais pas convertible »), même si l'article n'a ni
    `unite_fact` ni `unite_cdt` connue -- seule l'absence structurelle des
    deux côtés (`unite_lue` absente) déclenche la comparaison implicite."""
    assert (
        convertir_en_unite_fact(
            qte=Decimal("4"),
            unite_lue="KG",
            unite_cdt=None,
            unite_fact=None,
            ratio=None,
            ratio_valide=False,
        )
        is None
    )


def test_convertir_unite_lue_inconnue_et_fact_absente_renvoie_none() -> None:
    """Une unité lue non reconnue par `normaliser_unite` n'est pas traitée
    comme une absence : Ruling R14 ne s'applique pas, résultat `None`."""
    assert (
        convertir_en_unite_fact(
            qte=Decimal("4"),
            unite_lue="XYZ",
            unite_cdt=None,
            unite_fact=None,
            ratio=None,
            ratio_valide=False,
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


# --------------------------------------------------------------------------
# unite_implicite (Ruling R16, fix round 2 de L4-T7)
#
# Vrai exactement dans le cas 2 de `convertir_en_unite_fact` -- deux lignes
# appariées ne sont comparables (R03/R04) que si elles portent la même
# valeur (voir `rules.rules.R03.ecart_qte_fact`).
# --------------------------------------------------------------------------


def test_unite_implicite_vrai_quand_rien_n_est_connu() -> None:
    assert unite_implicite(None, None) is True


def test_unite_implicite_vrai_quand_fact_non_reconnue() -> None:
    """Une chaîne non reconnue par `normaliser_unite` compte comme
    inconnue, pas seulement `None`."""
    assert unite_implicite(None, "XYZ") is True


def test_unite_implicite_faux_si_unite_lue_presente() -> None:
    assert unite_implicite("KG", None) is False


def test_unite_implicite_faux_si_unite_fact_connue() -> None:
    assert unite_implicite(None, "kg") is False
