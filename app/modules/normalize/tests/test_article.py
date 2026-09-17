"""Tests des propositions d'article et de ratio (`article.py`, L3-D9)."""

from __future__ import annotations

from decimal import Decimal

from app.modules.normalize.article import (
    PropositionArticle,
    completer_article,
    proposer_article_bl,
    proposer_article_facture,
    proposer_ratio,
)

# --------------------------------------------------------------------------
# proposer_ratio
# --------------------------------------------------------------------------


def test_proposer_ratio_100_sur_4_egale_25() -> None:
    assert proposer_ratio(Decimal("4"), Decimal("100")) == Decimal("25")


def test_proposer_ratio_arrondi_a_quatre_decimales() -> None:
    assert proposer_ratio(Decimal("3"), Decimal("10")) == Decimal("3.3333")


def test_proposer_ratio_quantite_nulle_renvoie_none() -> None:
    assert proposer_ratio(Decimal("0"), Decimal("10")) is None


def test_proposer_ratio_valeur_manquante_renvoie_none() -> None:
    assert proposer_ratio(None, Decimal("10")) is None


def test_proposer_ratio_evite_la_notation_exponentielle() -> None:
    ratio = proposer_ratio(Decimal("2"), Decimal("20"))
    assert ratio == Decimal("10")
    assert str(ratio) == "10"


# --------------------------------------------------------------------------
# proposer_article_facture
# --------------------------------------------------------------------------


def test_proposer_article_facture_calcule_le_ratio_si_quantites_differentes() -> None:
    proposition = proposer_article_facture(
        code="AB1234",
        designation="Seau exemple",
        qte_livree=Decimal("4"),
        qte_totale=Decimal("100"),
    )
    assert proposition == PropositionArticle(
        code="AB1234",
        libelle="Seau exemple",
        unite_cdt=None,
        unite_fact=None,
        ratio=Decimal("25"),
    )


def test_proposer_article_facture_sans_ratio_si_quantites_egales() -> None:
    proposition = proposer_article_facture(
        code="AB1234",
        designation="Seau exemple",
        qte_livree=Decimal("10"),
        qte_totale=Decimal("10"),
    )
    assert proposition is not None
    assert proposition.ratio is None


def test_proposer_article_facture_code_absent_ou_blanc_renvoie_none() -> None:
    assert (
        proposer_article_facture(
            code=None, designation="x", qte_livree=None, qte_totale=None
        )
        is None
    )
    assert (
        proposer_article_facture(
            code="   ", designation="x", qte_livree=None, qte_totale=None
        )
        is None
    )


# --------------------------------------------------------------------------
# proposer_article_bl
# --------------------------------------------------------------------------


def test_proposer_article_bl_classe_unite_conditionnement() -> None:
    proposition = proposer_article_bl(
        code="AB1234", designation="Seau exemple", unite_brut="SEAU"
    )
    assert proposition == PropositionArticle(
        code="AB1234",
        libelle="Seau exemple",
        unite_cdt="seau",
        unite_fact=None,
        ratio=None,
    )


def test_proposer_article_bl_classe_unite_mesure() -> None:
    proposition = proposer_article_bl(
        code="CD5678", designation="Colle exemple", unite_brut="KG"
    )
    assert proposition == PropositionArticle(
        code="CD5678",
        libelle="Colle exemple",
        unite_cdt=None,
        unite_fact="kg",
        ratio=None,
    )


def test_proposer_article_bl_code_absent_renvoie_none() -> None:
    assert proposer_article_bl(code=None, designation="x", unite_brut="KG") is None


def test_proposer_article_bl_ratio_propose_si_deux_quantites_differentes() -> None:
    """L3-D24, constat 11 : un BL qui imprime les deux quantités (ex. 4
    seaux pour 100 kg) propose lui aussi un ratio, comme une facture."""
    proposition = proposer_article_bl(
        code="AB1234",
        designation="Seau exemple",
        unite_brut="SEAU",
        qte_conditionnements=Decimal("4"),
        qte_facturee=Decimal("100"),
    )
    assert proposition == PropositionArticle(
        code="AB1234",
        libelle="Seau exemple",
        unite_cdt="seau",
        unite_fact=None,
        ratio=Decimal("25"),
    )


def test_proposer_article_bl_sans_ratio_si_quantites_egales() -> None:
    proposition = proposer_article_bl(
        code="AB1234",
        designation="Seau exemple",
        unite_brut="SEAU",
        qte_conditionnements=Decimal("10"),
        qte_facturee=Decimal("10"),
    )
    assert proposition is not None
    assert proposition.ratio is None


def test_proposer_article_bl_sans_ratio_si_quantites_absentes() -> None:
    """Compatibilité : les appelants existants n'ont pas à passer les deux
    nouveaux paramètres (nommés, défaut `None`)."""
    proposition = proposer_article_bl(
        code="AB1234", designation="Seau exemple", unite_brut="SEAU"
    )
    assert proposition is not None
    assert proposition.ratio is None


# --------------------------------------------------------------------------
# completer_article
# --------------------------------------------------------------------------


def test_completer_article_ne_remplace_pas_une_valeur_existante() -> None:
    existant = PropositionArticle(
        code="AB1234",
        libelle="Ancien libellé",
        unite_cdt="seau",
        unite_fact=None,
        ratio=None,
    )
    nouvelle = PropositionArticle(
        code="AB1234",
        libelle="Nouveau libellé",
        unite_cdt="sac",
        unite_fact="kg",
        ratio=Decimal("25"),
    )
    resultat = completer_article(existant, nouvelle)
    assert resultat == PropositionArticle(
        code="AB1234",
        libelle="Ancien libellé",
        unite_cdt="seau",
        unite_fact="kg",
        ratio=Decimal("25"),
    )


def test_completer_article_garde_le_code_de_lexistant() -> None:
    existant = PropositionArticle(
        code="AB1234", libelle=None, unite_cdt=None, unite_fact=None, ratio=None
    )
    nouvelle = PropositionArticle(
        code="ZZ9999", libelle="Libellé", unite_cdt=None, unite_fact=None, ratio=None
    )
    assert completer_article(existant, nouvelle).code == "AB1234"
