"""Dataclasses partagées de l'extraction de facture (module PUR).

Ces types sont la sortie de `ocr.analyser_facture_unikalo` : aucune
dépendance d'infrastructure (FastAPI, SQLAlchemy, httpx), aucun log. Les
montants et quantités sont toujours des `Decimal`, jamais des `float`
(R3 du brief T5, toujours valable).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class TypeLigne(StrEnum):
    """Nature d'une ligne de facture, au sens du CDC."""

    ARTICLE = "article"
    ECO = "eco"
    COMMENTAIRE = "commentaire"


@dataclass(frozen=True)
class LigneFacture:
    """Une ligne d'un bloc B.L., dans son ordre d'apparition sur la facture.

    `montant_ht` est négatif pour une ligne d'avoir, `None` pour un
    commentaire (R5) ou une ligne à remise 100 % sans montant imprimé (R7).
    `remise_pct` n'est renseigné que si un pourcentage est effectivement lu
    ou déduit (R7) ; `None` sinon, jamais deviné.
    """

    ordre: int
    type_ligne: TypeLigne
    code_article: str | None
    designation: str
    qte_livree: Decimal | None
    qte_totale: Decimal | None
    unite: str | None
    pu_ht: Decimal | None
    pu_cdt: Decimal | None
    remise_pct: Decimal | None
    montant_ht: Decimal | None
    tva: Decimal | None


@dataclass(frozen=True)
class BlocBL:
    """Un bloc « Concerne le B.L. » avec ses lignes (articles, éco, commentaires)."""

    numero_bl: str
    date_bl: date | None
    numero_commande: str | None
    chantier_brut: str | None
    lignes: tuple[LigneFacture, ...]

    @property
    def montant_ht(self) -> Decimal:
        """Somme des `montant_ht` non nuls des lignes du bloc."""
        return sum(
            (ligne.montant_ht for ligne in self.lignes if ligne.montant_ht is not None),
            Decimal("0"),
        )

    @property
    def commentaires(self) -> tuple[str, ...]:
        """Désignations des lignes `COMMENTAIRE` du bloc, dans l'ordre."""
        return tuple(
            ligne.designation
            for ligne in self.lignes
            if ligne.type_ligne is TypeLigne.COMMENTAIRE
        )


@dataclass(frozen=True)
class Facture:
    """Une facture fournisseur entièrement analysée : en-tête et blocs B.L."""

    fournisseur_brut: str
    numero: str
    date_facture: date
    client: str | None
    echeance: date | None
    total_ht: Decimal
    blocs: tuple[BlocBL, ...]


class FactureIllisible(Exception):
    """La réponse OCR n'a pas la structure attendue d'une facture Unikalo."""
