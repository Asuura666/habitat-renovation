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

import pytest

from app.modules.ingest.bilan import (
    LigneBilanBl,
    LigneBilanChantier,
    LigneBilanDetail,
    LigneBilanFournisseur,
    MontantsBilan,
)
from app.modules.ingest.export import (
    _cellule,
    csv_bilan_bl,
    csv_bilan_chantiers,
    csv_bilan_detail,
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


@pytest.mark.parametrize("prefixe", ["=", "+", "-", "@"])
def test_cellule_neutralise_les_formules_apres_espaces_et_controles(
    prefixe: str,
) -> None:
    valeur = f" \t{prefixe}commande()"

    assert _cellule(valeur) == f"' \t{prefixe}commande()"


def test_cellule_conserve_une_valeur_ordinaire() -> None:
    assert _cellule("Libellé ordinaire") == "Libellé ordinaire"


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
        client=None,
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
        client=None,
        montants=_montants(facture_ht=Decimal("12.345")),
    )
    lignes = _lignes_csv(csv_bilan_chantiers([ligne]))

    assert lignes[1][2] == "12,35"


def test_csv_bilan_chantiers_montant_arrondit_en_dessous_sous_cinq() -> None:
    ligne = LigneBilanChantier(
        chantier_id=uuid.uuid4(),
        nom_canonique="Chantier Precision Basse",
        agence=None,
        client=None,
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
        client=None,
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
        client=None,
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
        client=None,
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
            client=None,
            montants=_montants(facture_ht=Decimal("10.00"), nb_anomalies_ouvertes=3),
        ),
        LigneBilanChantier(
            chantier_id=uuid.uuid4(),
            nom_canonique="Chantier Deux",
            agence="Agence Une",
            client=None,
            montants=_montants(facture_ht=Decimal("20.00"), nb_anomalies_ouvertes=0),
        ),
    ]
    lignes = _lignes_csv(csv_bilan_chantiers(lignes_source))

    assert len(lignes) == 3  # en-tête + 2 lignes
    assert lignes[1][6] == "3"
    assert lignes[2][6] == "0"


# --------------------------------------------------------------------------
# Export détaillé (décision d'Ilane du 23/09/2026, réponse à Q3 du lot 5)
# --------------------------------------------------------------------------


def _ligne_detail(
    *,
    fournisseur_nom: str | None = "Fournisseur Invente",
    numero_facture: str | None = "F0001",
    date_facture: date | None = date(2026, 8, 15),
    nom_chantier: str | None = "Chantier Invente",
    agence: str | None = "Agence Invente",
    numero_bl: str | None = "L0001",
    statut_rapprochement: str | None = "recu",
    type_ligne: str = "article",
    code_article: str | None = "ART1",
    designation: str | None = "Désignation Inventée",
    qte_facturee: Decimal | None = Decimal("10"),
    unite: str | None = "U",
    pu_ht: Decimal | None = Decimal("12.50"),
    remise_pct: Decimal | None = Decimal("5.00"),
    montant_ht: Decimal | None = Decimal("118.75"),
    qte_bl_appariee: Decimal | None = Decimal("10"),
    nb_anomalies_ouvertes: int = 0,
    codes_regles: tuple[str, ...] = (),
) -> LigneBilanDetail:
    return LigneBilanDetail(
        ligne_id=uuid.uuid4(),
        bloc_id=uuid.uuid4(),
        facture_id=uuid.uuid4(),
        mois=date(2026, 8, 1),
        fournisseur_id=uuid.uuid4(),
        fournisseur_nom=fournisseur_nom,
        numero_facture=numero_facture,
        date_facture=date_facture,
        chantier_id=uuid.uuid4(),
        nom_chantier=nom_chantier,
        agence=agence,
        numero_bl=numero_bl,
        statut_rapprochement=statut_rapprochement,
        type_ligne=type_ligne,
        code_article=code_article,
        designation=designation,
        qte_facturee=qte_facturee,
        unite=unite,
        pu_ht=pu_ht,
        remise_pct=remise_pct,
        montant_ht=montant_ht,
        qte_bl_appariee=qte_bl_appariee,
        nb_anomalies_ouvertes=nb_anomalies_ouvertes,
        codes_regles=codes_regles,
    )


def test_csv_bilan_detail_entetes() -> None:
    lignes = _lignes_csv(csv_bilan_detail([]))
    assert lignes == [
        [
            "Mois",
            "Fournisseur",
            "N° Facture",
            "Date facture",
            "Chantier",
            "Agence",
            "N° BL",
            "Statut BL",
            "Type de ligne",
            "Référence article",
            "Désignation",
            "Quantité facturée",
            "Unité",
            "Prix unitaire HT",
            "Remise (%)",
            "Montant HT",
            "Quantité BL appariée",
            "Anomalies ouvertes",
            "Règles concernées",
        ]
    ]


def test_csv_bilan_detail_ligne_complete_valeurs_et_ordre_des_colonnes() -> None:
    ligne = _ligne_detail(nb_anomalies_ouvertes=2, codes_regles=("R01", "R13"))
    lignes = _lignes_csv(csv_bilan_detail([ligne]))

    assert lignes[1] == [
        "2026-08",
        "Fournisseur Invente",
        "F0001",
        "2026-08-15",
        "Chantier Invente",
        "Agence Invente",
        "L0001",
        "BL reçu",
        "article",
        "ART1",
        "Désignation Inventée",
        "10,00",
        "U",
        "12,50",
        "5,00",
        "118,75",
        "10,00",
        "2",
        "R01, R13",
    ]


@pytest.mark.parametrize(
    ("statut_brut", "libelle_attendu"),
    [
        ("recu", "BL reçu"),
        ("non_recu", "BL non reçu"),
        ("pas_de_bon", "Pas de bon"),
    ],
)
def test_csv_bilan_detail_statut_bloc_traduit_avec_les_libelles_du_front(
    statut_brut: str, libelle_attendu: str
) -> None:
    ligne = _ligne_detail(statut_rapprochement=statut_brut)
    lignes = _lignes_csv(csv_bilan_detail([ligne]))

    assert lignes[1][7] == libelle_attendu


def test_csv_bilan_detail_valeurs_absentes_cellules_vides_jamais_none() -> None:
    ligne = _ligne_detail(
        fournisseur_nom=None,
        numero_facture=None,
        date_facture=None,
        nom_chantier=None,
        agence=None,
        numero_bl=None,
        statut_rapprochement=None,
        code_article=None,
        designation=None,
        qte_facturee=None,
        unite=None,
        pu_ht=None,
        remise_pct=None,
        montant_ht=None,
        qte_bl_appariee=None,
        codes_regles=(),
    )
    contenu = csv_bilan_detail([ligne])
    lignes = _lignes_csv(contenu)

    # Colonnes potentiellement absentes (index) : Fournisseur(1), N°
    # Facture(2), Date facture(3), Chantier(4), Agence(5), N° BL(6), Statut
    # BL(7), Référence article(9), Désignation(10), Quantité facturée(11),
    # Unité(12), Prix unitaire HT(13), Remise(14), Montant HT(15), Quantité
    # BL appariée(16), Règles concernées(18) -- toutes vides, jamais "None".
    indices_optionnels = [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 18]
    for indice in indices_optionnels:
        assert lignes[1][indice] == ""
    assert "None" not in contenu


def test_csv_bilan_detail_mois_au_format_annee_mois() -> None:
    ligne = _ligne_detail()
    lignes = _lignes_csv(csv_bilan_detail([ligne]))

    assert lignes[1][0] == "2026-08"


def test_csv_bilan_detail_libelle_avec_point_virgule_echappe() -> None:
    ligne = _ligne_detail(designation="Désignation; avec point-virgule")
    contenu = csv_bilan_detail([ligne])
    lignes = _lignes_csv(contenu)

    assert '"Désignation; avec point-virgule"' in contenu
    assert lignes[1][10] == "Désignation; avec point-virgule"
    assert len(lignes[1]) == len(lignes[0])
