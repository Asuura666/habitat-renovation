"""Tests de `ingest/export.py` (L5-T4) : sérialisation CSV du bilan, sans
base ni réseau (module pur au sens de ce fichier -- aucune fixture `db`,
aucun marqueur `anyio`, données inventées construites à la main).

Convention de lecture : `csv.reader` (bibliothèque standard, même module que
le producteur) reconstitue les lignes à partir du texte produit, ce qui
vérifie à la fois le séparateur et l'échappement sans dupliquer la logique
de découpage à la main.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from decimal import Decimal

from app.modules.ingest.bilan import (
    LigneBilanBl,
    LigneBilanChantier,
    LigneBilanFournisseur,
    MontantsBilan,
)
from app.modules.ingest.export import (
    csv_bilan_bl,
    csv_bilan_chantiers,
    csv_bilan_fournisseurs,
)


def _montants(
    *,
    facture_ht: Decimal = Decimal("100.00"),
    rapproche: Decimal = Decimal("0.00"),
    en_ecart: Decimal = Decimal("0.00"),
    non_justifie: Decimal = Decimal("0.00"),
    nb_anomalies_ouvertes: int = 0,
) -> MontantsBilan:
    return MontantsBilan(
        facture_ht=facture_ht,
        rapproche=rapproche,
        en_ecart=en_ecart,
        non_justifie=non_justifie,
        nb_anomalies_ouvertes=nb_anomalies_ouvertes,
    )


def _lignes_csv(contenu: str) -> list[list[str]]:
    """Reconstitue les lignes du CSV produit (séparateur `;`) -- aide de
    lisibilité partagée par les tests ci-dessous."""
    return list(csv.reader(io.StringIO(contenu), delimiter=";"))


# --------------------------------------------------------------------------
# En-têtes et ordre des colonnes, par niveau
# --------------------------------------------------------------------------


def test_csv_bilan_chantiers_entetes() -> None:
    lignes = _lignes_csv(csv_bilan_chantiers([]))
    assert lignes == [
        [
            "Chantier",
            "Agence",
            "Facturé HT",
            "Rapproché",
            "En écart",
            "Non justifié",
            "Anomalies ouvertes",
        ]
    ]


def test_csv_bilan_fournisseurs_entetes() -> None:
    lignes = _lignes_csv(csv_bilan_fournisseurs([]))
    assert lignes == [
        [
            "Fournisseur",
            "Facturé HT",
            "Rapproché",
            "En écart",
            "Non justifié",
            "Anomalies ouvertes",
        ]
    ]


def test_csv_bilan_bl_entetes() -> None:
    lignes = _lignes_csv(csv_bilan_bl([]))
    assert lignes == [
        [
            "N° BL",
            "Date BL",
            "Statut rapprochement",
            "Facturé HT",
            "Rapproché",
            "En écart",
            "Non justifié",
            "Anomalies ouvertes",
        ]
    ]


# --------------------------------------------------------------------------
# Séparateur point-virgule, virgule décimale
# --------------------------------------------------------------------------


def test_csv_bilan_chantiers_separateur_point_virgule_et_virgule_decimale() -> None:
    ligne = LigneBilanChantier(
        chantier_id=uuid.uuid4(),
        nom_canonique="Chantier Invente",
        agence="Agence Invente",
        montants=_montants(facture_ht=Decimal("1234.50")),
    )
    contenu = csv_bilan_chantiers([ligne])

    # Le texte brut porte bien un `;` littéral entre les colonnes et une
    # virgule décimale dans le montant -- pas seulement une reconstruction
    # via `csv.reader`, qui accepterait un autre délimiteur mal choisi.
    corps = contenu.splitlines()[1]
    assert corps == "Chantier Invente;Agence Invente;1234,50;0,00;0,00;0,00;0"
    assert "," in corps
    assert "1234.50" not in contenu


def test_csv_bilan_chantiers_montant_plus_de_deux_decimales_arrondi() -> None:
    """Décision documentée dans `export.py` : arrondi `ROUND_HALF_UP` à deux
    décimales, jamais un `Decimal` brut recopié tel quel."""
    ligne = LigneBilanChantier(
        chantier_id=uuid.uuid4(),
        nom_canonique="Chantier Precision",
        agence=None,
        montants=_montants(facture_ht=Decimal("12.345")),
    )
    lignes = _lignes_csv(csv_bilan_chantiers([ligne]))

    assert lignes[1][2] == "12,35"


def test_csv_bilan_chantiers_montant_arrondit_en_dessous_sous_cinq() -> None:
    ligne = LigneBilanChantier(
        chantier_id=uuid.uuid4(),
        nom_canonique="Chantier Precision Basse",
        agence=None,
        montants=_montants(facture_ht=Decimal("12.344")),
    )
    lignes = _lignes_csv(csv_bilan_chantiers([ligne]))

    assert lignes[1][2] == "12,34"


# --------------------------------------------------------------------------
# Valeurs absentes -> cellule vide, jamais "None"
# --------------------------------------------------------------------------


def test_csv_bilan_chantiers_ligne_non_resolue_cellules_vides() -> None:
    ligne = LigneBilanChantier(
        chantier_id=None,
        nom_canonique=None,
        agence=None,
        montants=_montants(facture_ht=Decimal("42.00")),
    )
    lignes = _lignes_csv(csv_bilan_chantiers([ligne]))

    assert lignes[1][0] == ""
    assert lignes[1][1] == ""
    assert "None" not in csv_bilan_chantiers([ligne])


def test_csv_bilan_fournisseurs_ligne_non_resolue_cellule_vide() -> None:
    ligne = LigneBilanFournisseur(
        fournisseur_id=None, nom=None, montants=_montants(facture_ht=Decimal("77.00"))
    )
    lignes = _lignes_csv(csv_bilan_fournisseurs([ligne]))

    assert lignes[1][0] == ""
    assert "None" not in csv_bilan_fournisseurs([ligne])


def test_csv_bilan_bl_numero_date_statut_absents_cellules_vides() -> None:
    ligne = LigneBilanBl(
        bloc_id=uuid.uuid4(),
        numero_bl=None,
        date_bl=None,
        statut_rapprochement=None,
        bl_document_id=None,
        facture_id=uuid.uuid4(),
        montants=_montants(),
    )
    lignes = _lignes_csv(csv_bilan_bl([ligne]))

    assert lignes[1][0] == ""
    assert lignes[1][1] == ""
    assert lignes[1][2] == ""
    assert "None" not in csv_bilan_bl([ligne])


def test_csv_bilan_bl_date_au_format_iso() -> None:
    ligne = LigneBilanBl(
        bloc_id=uuid.uuid4(),
        numero_bl="L-INVENTE-1",
        date_bl=date(2026, 8, 3),
        statut_rapprochement="recu",
        bl_document_id=uuid.uuid4(),
        facture_id=uuid.uuid4(),
        montants=_montants(),
    )
    lignes = _lignes_csv(csv_bilan_bl([ligne]))

    assert lignes[1][1] == "2026-08-03"
    assert lignes[1][2] == "recu"


# --------------------------------------------------------------------------
# Échappement RFC4180 : point-virgule ou guillemet dans un libellé
# --------------------------------------------------------------------------


def test_csv_bilan_chantiers_libelle_avec_point_virgule_echappe() -> None:
    ligne = LigneBilanChantier(
        chantier_id=uuid.uuid4(),
        nom_canonique="Chantier; avec point-virgule",
        agence=None,
        montants=_montants(),
    )
    contenu = csv_bilan_chantiers([ligne])
    lignes = _lignes_csv(contenu)

    # Le champ est cité dans le texte brut (sinon le point-virgule serait
    # lu comme un séparateur de colonne supplémentaire par Excel).
    assert '"Chantier; avec point-virgule"' in contenu
    assert lignes[1][0] == "Chantier; avec point-virgule"
    # Une seule colonne "Chantier" malgré le point-virgule interne : la
    # ligne reconstituée a le même nombre de champs que l'en-tête.
    assert len(lignes[1]) == len(lignes[0])


def test_csv_bilan_fournisseurs_libelle_avec_guillemet_echappe() -> None:
    ligne = LigneBilanFournisseur(
        fournisseur_id=uuid.uuid4(),
        nom='Fournisseur "Le Guillemet" Invente',
        montants=_montants(),
    )
    contenu = csv_bilan_fournisseurs([ligne])
    lignes = _lignes_csv(contenu)

    # RFC4180 : un guillemet interne est doublé, le champ entier est cité.
    assert '"Fournisseur ""Le Guillemet"" Invente"' in contenu
    assert lignes[1][0] == 'Fournisseur "Le Guillemet" Invente'
    assert len(lignes[1]) == len(lignes[0])


def test_csv_bilan_chantiers_libelle_point_virgule_guillemet_et_saut_de_ligne() -> None:
    """Le cas le plus piégeux (celui qui casse les exports faits à la
    main) : point-virgule, guillemet et retour à la ligne dans le même
    champ. `_lignes_csv` relit avec `csv.reader` un `io.StringIO` construit
    sans argument `newline` particulier -- par défaut `io.StringIO` ne
    traduit aucune fin de ligne (contrairement à un fichier réel ouvert
    sans `newline=""`), donc le retour à la ligne interne au champ cité est
    reconstitué tel quel, pas confondu avec une fin d'enregistrement."""
    valeur = 'Chantier "Rue du Bois"; Lot 2\nBâtiment B'
    ligne = LigneBilanChantier(
        chantier_id=uuid.uuid4(),
        nom_canonique=valeur,
        agence=None,
        montants=_montants(),
    )
    lignes = _lignes_csv(csv_bilan_chantiers([ligne]))

    # Une seule ligne de donnée malgré le retour à la ligne interne : le
    # champ cité en porte deux (en-tête + 1), pas trois.
    assert len(lignes) == 2
    assert lignes[1][0] == valeur
    assert len(lignes[1]) == len(lignes[0])


# --------------------------------------------------------------------------
# Plusieurs lignes, compte d'anomalies en entier
# --------------------------------------------------------------------------


def test_csv_bilan_chantiers_plusieurs_lignes_et_compte_anomalies_entier() -> None:
    lignes_source = [
        LigneBilanChantier(
            chantier_id=uuid.uuid4(),
            nom_canonique="Chantier Un",
            agence="Agence Une",
            montants=_montants(facture_ht=Decimal("10.00"), nb_anomalies_ouvertes=3),
        ),
        LigneBilanChantier(
            chantier_id=uuid.uuid4(),
            nom_canonique="Chantier Deux",
            agence="Agence Une",
            montants=_montants(facture_ht=Decimal("20.00"), nb_anomalies_ouvertes=0),
        ),
    ]
    lignes = _lignes_csv(csv_bilan_chantiers(lignes_source))

    assert len(lignes) == 3  # en-tête + 2 lignes
    assert lignes[1][6] == "3"
    assert lignes[2][6] == "0"
