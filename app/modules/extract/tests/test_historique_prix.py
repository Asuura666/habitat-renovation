"""Tests de la lecture d'une feuille d'historique de prix observés
(`historique_prix.py`, lot 2 du 31/10/2026, B4).

Aucun fichier réel : chaque classeur est construit en mémoire avec des
valeurs entièrement inventées."""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

import openpyxl
import pytest

from app.modules.extract.grille_excel import FichierGrilleInvalide
from app.modules.extract.historique_prix import (
    FeuilleIntrouvable,
    lire_historique_prix,
)

_ENTETE = [
    "Date",
    "Facture",
    "Référence",
    "Désignation",
    "Quantité",
    "Unité",
    "Prix HT observé",
]


def _classeur(feuilles: Mapping[str, Sequence[Sequence[object]]]) -> bytes:
    classeur = openpyxl.Workbook()
    premiere = True
    for nom, lignes in feuilles.items():
        feuille = classeur.active if premiere else classeur.create_sheet()
        assert feuille is not None
        feuille.title = nom
        premiere = False
        for ligne in lignes:
            feuille.append(ligne)
    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


def test_lit_les_lignes_valides_d_une_feuille() -> None:
    contenu = _classeur(
        {
            "HISTORIQUE X": [
                _ENTETE,
                [datetime(2026, 8, 3), "F-100", 4000493.0, "Plaque BA13", 12, "u", 4.5],
                ["04/08/2026", "F-101", "AB 12", "Enduit", "2,5", "sac", "13,90 €"],
            ]
        }
    )

    resultat = lire_historique_prix(contenu, "HISTORIQUE X")

    assert resultat.erreurs == ()
    premiere, seconde = resultat.lignes
    assert premiere.numero_ligne == 2
    assert premiere.date_observation == date(2026, 8, 3)
    assert premiere.piece == "F-100"
    assert premiere.reference == "4000493"
    assert premiere.designation == "Plaque BA13"
    assert premiere.quantite == Decimal("12")
    assert premiere.unite_brut == "u"
    assert premiere.prix_ht == Decimal("4.5")
    assert seconde.date_observation == date(2026, 8, 4)
    assert seconde.quantite == Decimal("2.5")
    assert seconde.prix_ht == Decimal("13.90")


def test_les_champs_facultatifs_peuvent_manquer() -> None:
    contenu = _classeur(
        {"H": [_ENTETE, [datetime(2026, 8, 3), None, None, "Enduit", None, None, 9]]}
    )

    (ligne,) = lire_historique_prix(contenu, "H").lignes

    assert ligne.piece is None
    assert ligne.reference is None
    assert ligne.quantite is None
    assert ligne.unite_brut is None


def test_lignes_illisibles_comptees_en_erreurs_jamais_inventees() -> None:
    contenu = _classeur(
        {
            "H": [
                _ENTETE,
                ["pas une date", "F1", "R1", "A", 1, "u", 5],
                [None, "F1", "R1", "A", 1, "u", 5],
                [datetime(2026, 8, 3), "F1", "R1", "", 1, "u", 5],
                [datetime(2026, 8, 3), "F1", "R1", "A", 1, "u", "abc"],
                [datetime(2026, 8, 3), "F1", "R1", "A", 1, "u", None],
                [datetime(2026, 8, 3), "F1", "R1", "A", 1, "u", 0],
                [datetime(2026, 8, 3), "F1", "R1", "A", "x", "u", 5],
                [],
                [datetime(2026, 8, 3), "F1", "R1", "A", 1, "u", 5],
            ]
        }
    )

    resultat = lire_historique_prix(contenu, "H")

    assert len(resultat.lignes) == 1
    assert [erreur.numero_ligne for erreur in resultat.erreurs] == [2, 3, 4, 5, 6, 7, 8]
    messages = [erreur.message for erreur in resultat.erreurs]
    assert messages[0].startswith("date illisible")
    assert messages[1] == "date manquante"
    assert messages[2] == "désignation manquante"
    assert messages[3].startswith("prix illisible")
    assert messages[4] == "prix manquant"
    assert messages[5] == "le prix doit être supérieur à 0"
    assert messages[6].startswith("quantité illisible")


def test_en_tete_cherche_dans_les_premieres_lignes() -> None:
    contenu = _classeur(
        {
            "H": [
                ["Fichier de contrôle"],
                [],
                _ENTETE,
                [datetime(2026, 8, 3), "F1", "R1", "A", 1, "u", 5],
            ]
        }
    )

    resultat = lire_historique_prix(contenu, "H")

    assert len(resultat.lignes) == 1
    assert resultat.lignes[0].numero_ligne == 4


def test_feuille_absente_ou_sans_colonnes_attendues() -> None:
    contenu = _classeur({"H": [_ENTETE], "AUTRE": [["a", "b"], [1, 2]]})

    with pytest.raises(FeuilleIntrouvable):
        lire_historique_prix(contenu, "ABSENTE")
    with pytest.raises(FeuilleIntrouvable):
        lire_historique_prix(contenu, "AUTRE")


def test_fichier_pas_un_classeur() -> None:
    with pytest.raises(FichierGrilleInvalide):
        lire_historique_prix(b"pas un classeur", "H")
