"""Propositions d'article et de ratio conditionnement/facturation (module
pur, L3-D9).

Un article est identifié par `(fournisseur_id, code)`, créé automatiquement
(non validé) à la première ligne qui porte un code -- la création et la
persistance sont hors de ce module (orchestrateur `ingest`) : il ne fait que
proposer les valeurs (libellé, unités, ratio) à partir d'une ligne de
facture ou de BL, et compléter un article existant sans jamais écraser une
valeur déjà renseignée.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .unites import NatureUnite, normaliser_unite

_QUANTUM_RATIO = Decimal("0.0001")


@dataclass(frozen=True)
class PropositionArticle:
    code: str
    libelle: str | None
    unite_cdt: str | None
    unite_fact: str | None
    ratio: Decimal | None


def _sans_notation_exponentielle(valeur: Decimal) -> Decimal:
    """`Decimal.normalize()` retombe en notation exponentielle pour un
    multiple de dix (ex. `Decimal("10")` -> `Decimal("1E+1")`) : on force
    l'écriture positionnelle usuelle dans ce cas."""
    exposant = valeur.as_tuple().exponent
    if isinstance(exposant, int) and exposant > 0:
        return valeur.quantize(Decimal(1))
    return valeur


def proposer_ratio(
    qte_conditionnement: Decimal | None, qte_facturation: Decimal | None
) -> Decimal | None:
    """`None` si l'une des deux quantités manque ou n'est pas strictement
    positive ; sinon `qte_facturation / qte_conditionnement`, quantifié à 4
    décimales (`ROUND_HALF_UP`) puis normalisé sans notation exponentielle."""
    if (
        qte_conditionnement is None
        or qte_facturation is None
        or qte_conditionnement <= 0
        or qte_facturation <= 0
    ):
        return None
    quantifie = (qte_facturation / qte_conditionnement).quantize(
        _QUANTUM_RATIO, rounding=ROUND_HALF_UP
    )
    return _sans_notation_exponentielle(quantifie.normalize())


def proposer_article_facture(
    code: str | None,
    designation: str | None,
    qte_livree: Decimal | None,
    qte_totale: Decimal | None,
) -> PropositionArticle | None:
    """`None` si `code` est absent ou blanc. Le ratio n'est proposé que si
    les deux quantités diffèrent (une facture sans conditionnement distinct
    de la facturation n'a rien à proposer)."""
    if code is None or not code.strip():
        return None
    ratio = proposer_ratio(qte_livree, qte_totale) if qte_livree != qte_totale else None
    return PropositionArticle(
        code=code, libelle=designation, unite_cdt=None, unite_fact=None, ratio=ratio
    )


def proposer_article_bl(
    code: str | None, designation: str | None, unite_brut: str | None
) -> PropositionArticle | None:
    """`None` si `code` est absent. L'unité lue, une fois normalisée, classe
    la ligne en conditionnement (`unite_cdt`) ou en mesure (`unite_fact`)."""
    if code is None or not code.strip():
        return None
    unite = normaliser_unite(unite_brut)
    unite_cdt = (
        unite.code
        if unite is not None and unite.nature is NatureUnite.CONDITIONNEMENT
        else None
    )
    unite_fact = (
        unite.code if unite is not None and unite.nature is NatureUnite.MESURE else None
    )
    return PropositionArticle(
        code=code,
        libelle=designation,
        unite_cdt=unite_cdt,
        unite_fact=unite_fact,
        ratio=None,
    )


def completer_article(
    existant: PropositionArticle, nouvelle: PropositionArticle
) -> PropositionArticle:
    """Garde chaque champ de `existant` ; ne prend de `nouvelle` que les
    champs `None` de `existant` (jamais d'écrasement). `code` reste celui de
    `existant`."""
    return PropositionArticle(
        code=existant.code,
        libelle=existant.libelle if existant.libelle is not None else nouvelle.libelle,
        unite_cdt=(
            existant.unite_cdt if existant.unite_cdt is not None else nouvelle.unite_cdt
        ),
        unite_fact=(
            existant.unite_fact
            if existant.unite_fact is not None
            else nouvelle.unite_fact
        ),
        ratio=existant.ratio if existant.ratio is not None else nouvelle.ratio,
    )
