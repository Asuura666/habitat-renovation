"""Tests de la lecture d'un fichier Excel de grille de prix
(`grille_excel.py`), spec `docs/superpowers/specs/2026-09-27-prix-design.md`
§7.1 et §12.

Aucun fichier réel : chaque classeur est construit en mémoire par le test
(`_classeur`) avec des valeurs entièrement inventées. Le test sur les
documents réels du client (`tests/test_grilles_reelles.py`) est séparé.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from decimal import Decimal

import openpyxl
import pytest

from app.modules.extract.grille_excel import (
    LIGNES_MAX,
    FichierGrilleInvalide,
    lire_grille_excel,
)

# --------------------------------------------------------------------------
# Constructeurs de classeurs inventés
# --------------------------------------------------------------------------


def _classeur(feuilles: Mapping[str, Sequence[Sequence[object]]]) -> bytes:
    """Un classeur `.xlsx` en mémoire : une feuille par entrée, une ligne par
    sous-liste (aucun fichier écrit sur disque)."""
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


def _avec_cache_formule(contenu: bytes, cellule: str, valeur: str) -> bytes:
    """Injecte un `<v>` (valeur en cache) sur la cellule-formule `cellule`
    de la première feuille : `openpyxl` n'écrit jamais de cache pour une
    formule qu'il n'a pas calculée lui-même, contrairement à Excel -- on
    reproduit donc ici la forme d'un vrai fichier (formule + valeur en
    cache), à la main, sur le XML du classeur déjà écrit."""
    with zipfile.ZipFile(io.BytesIO(contenu)) as zin:
        donnees = {nom: zin.read(nom) for nom in zin.namelist()}
    chemin = "xl/worksheets/sheet1.xml"
    xml = donnees[chemin].decode("utf-8")
    # `openpyxl` écrit déjà un `<v />` vide à côté de la formule (jamais
    # calculée) : on le remplace par la valeur en cache, plutôt que d'en
    # ajouter un second.
    motif = re.compile(rf'(<c r="{cellule}"[^>]*><f>[^<]*</f>)(?:<v\s*/>)?(</c>)')
    xml_modifie, nb = motif.subn(rf"\1<v>{valeur}</v>\2", xml)
    assert nb == 1, "cellule-formule introuvable dans le XML du test"
    donnees[chemin] = xml_modifie.encode("utf-8")

    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as zout:
        for nom, contenu_fichier in donnees.items():
            zout.writestr(nom, contenu_fichier)
    return tampon.getvalue()


_ENTETE_MODELE = ["Référence", "Désignation", "Unité", "Prix unitaire HT", "Remise %"]
_ENTETE_CEDEO = ["Marque", "Référence", "Article", "Prix unitaire HT (€)", None]


# --------------------------------------------------------------------------
# En-têtes
# --------------------------------------------------------------------------


def test_entete_du_modele_est_reconnue() -> None:
    contenu = _classeur(
        {
            "Grille": [
                _ENTETE_MODELE,
                ["REF1", "Produit inventé un", "u", 12.5, 10],
                [None, "Produit inventé deux (sans référence)", "sac", 7],
            ]
        }
    )
    grille = lire_grille_excel(contenu)

    assert grille.erreurs == ()
    assert grille.feuilles_ignorees == ()
    assert len(grille.lignes) == 2
    premiere = grille.lignes[0]
    assert premiere.reference == "REF1"
    assert premiere.designation == "Produit inventé un"
    assert premiere.unite_brut == "u"
    assert premiere.prix_ht == Decimal("12.5")
    assert premiere.remise_pct == Decimal("10")
    seconde = grille.lignes[1]
    assert seconde.reference is None
    assert seconde.remise_pct is None


def test_entete_a_la_cedeo_famille_egale_nom_de_feuille() -> None:
    contenu = _classeur(
        {
            "Plomberie": [
                _ENTETE_CEDEO,
                ["Marque Inventée", "4000493", "Produit plomberie inventé", "6,30 €"],
            ],
            "Sanitaire": [
                _ENTETE_CEDEO,
                ["Marque Inventée", "4000494", "Produit sanitaire inventé", 9.9],
            ],
        }
    )
    grille = lire_grille_excel(contenu)

    assert grille.erreurs == ()
    assert grille.feuilles_ignorees == ()
    assert len(grille.lignes) == 2
    plomberie, sanitaire = grille.lignes
    assert plomberie.famille == "Plomberie"
    assert plomberie.marque == "Marque Inventée"
    assert plomberie.prix_ht == Decimal("6.30")
    assert sanitaire.famille == "Sanitaire"
    assert sanitaire.prix_ht == Decimal("9.9")


def test_entete_en_ligne_trois() -> None:
    contenu = _classeur(
        {
            "Grille": [
                ["Fiche produit inventée"],
                [None],
                _ENTETE_MODELE,
                ["REF9", "Produit décalé", "u", "5"],
            ]
        }
    )
    grille = lire_grille_excel(contenu)

    assert grille.erreurs == ()
    assert len(grille.lignes) == 1
    ligne = grille.lignes[0]
    assert ligne.designation == "Produit décalé"
    # Numéro Excel exact : ligne 4 (en-tête en ligne 3, deux lignes avant).
    assert ligne.numero_ligne == 4


def test_feuille_sans_entete_reconnu_est_ignoree() -> None:
    contenu = _classeur(
        {
            "Mode d'emploi": [
                ["Merci de remplir une ligne par produit."],
                ["La colonne Prix doit être en euros."],
            ],
            "Grille": [
                _ENTETE_MODELE,
                ["REF1", "Produit inventé", "u", "5"],
            ],
        }
    )
    grille = lire_grille_excel(contenu)

    assert grille.feuilles_ignorees == ("Mode d'emploi",)
    assert len(grille.lignes) == 1


# --------------------------------------------------------------------------
# Formats de prix et de référence
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valeur_prix", "attendu"),
    [
        ("6,30 €", Decimal("6.30")),
        ("6.30", Decimal("6.30")),
        (6.3, Decimal("6.3")),
        (7, Decimal("7")),
    ],
)
def test_formats_de_prix_acceptes(valeur_prix: object, attendu: Decimal) -> None:
    contenu = _classeur(
        {"Grille": [_ENTETE_MODELE, ["REF1", "Produit inventé", "u", valeur_prix]]}
    )
    grille = lire_grille_excel(contenu)

    assert grille.erreurs == ()
    assert grille.lignes[0].prix_ht == attendu


def test_reference_numerique_est_ramenee_a_lentier() -> None:
    contenu = _classeur(
        {"Grille": [_ENTETE_MODELE, [4000493.0, "Produit inventé", "u", "5"]]}
    )
    grille = lire_grille_excel(contenu)

    assert grille.erreurs == ()
    assert grille.lignes[0].reference == "4000493"


# --------------------------------------------------------------------------
# Lignes en erreur
# --------------------------------------------------------------------------


def test_designation_manquante() -> None:
    contenu = _classeur({"Grille": [_ENTETE_MODELE, ["REF1", "", "u", "5"]]})
    grille = lire_grille_excel(contenu)

    assert grille.lignes == ()
    assert len(grille.erreurs) == 1
    erreur = grille.erreurs[0]
    assert erreur.numero_ligne == 2
    assert erreur.message == "désignation manquante"


def test_prix_manquant() -> None:
    contenu = _classeur({"Grille": [_ENTETE_MODELE, ["REF1", "Produit inventé"]]})
    grille = lire_grille_excel(contenu)

    assert grille.lignes == ()
    assert grille.erreurs[0].message == "prix manquant"


def test_prix_illisible() -> None:
    contenu = _classeur(
        {"Grille": [_ENTETE_MODELE, ["REF1", "Produit inventé", "u", "pas un prix"]]}
    )
    grille = lire_grille_excel(contenu)

    assert grille.lignes == ()
    assert grille.erreurs[0].message == "prix illisible : « pas un prix »"


def test_prix_nul_ou_negatif() -> None:
    contenu = _classeur(
        {
            "Grille": [
                _ENTETE_MODELE,
                ["REF1", "Produit inventé un", "u", "0"],
                ["REF2", "Produit inventé deux", "u", "-3"],
            ]
        }
    )
    grille = lire_grille_excel(contenu)

    assert grille.lignes == ()
    assert len(grille.erreurs) == 2
    assert all(e.message == "le prix doit être supérieur à 0" for e in grille.erreurs)


def test_remise_hors_bornes() -> None:
    contenu = _classeur(
        {"Grille": [_ENTETE_MODELE, ["REF1", "Produit inventé", "u", "5", "100"]]}
    )
    grille = lire_grille_excel(contenu)

    assert grille.lignes == ()
    assert (
        grille.erreurs[0].message
        == "la remise doit être comprise entre 0 et 100 (exclu)"
    )


def test_remise_illisible() -> None:
    contenu = _classeur(
        {
            "Grille": [
                _ENTETE_MODELE,
                ["REF1", "Produit inventé", "u", "5", "beaucoup"],
            ]
        }
    )
    grille = lire_grille_excel(contenu)

    assert grille.lignes == ()
    assert grille.erreurs[0].message == "remise illisible : « beaucoup »"


def test_doublon_meme_reference() -> None:
    contenu = _classeur(
        {
            "Grille": [
                _ENTETE_MODELE,
                ["REF1", "Produit inventé un", "u", "5"],
                ["ref1", "Produit inventé un (autre libellé)", "u", "6"],
            ]
        }
    )
    grille = lire_grille_excel(contenu)

    assert len(grille.lignes) == 1
    assert len(grille.erreurs) == 1
    erreur = grille.erreurs[0]
    assert erreur.numero_ligne == 3
    assert erreur.message == "même produit déjà présent ligne 2 (Grille)"


def test_doublon_meme_designation_sans_reference() -> None:
    contenu = _classeur(
        {
            "Grille": [
                _ENTETE_MODELE,
                [None, "Produit Sans Référence", "u", "5"],
                [None, "produit   sans   référence", "sac", "6"],
            ]
        }
    )
    grille = lire_grille_excel(contenu)

    assert len(grille.lignes) == 1
    assert grille.erreurs[0].message == "même produit déjà présent ligne 2 (Grille)"


def test_ligne_entierement_vide_est_ignoree() -> None:
    contenu = _classeur(
        {
            "Grille": [
                _ENTETE_MODELE,
                ["REF1", "Produit inventé un", "u", "5"],
                [None, None, None, None, None],
                ["REF2", "Produit inventé deux", "u", "6"],
            ]
        }
    )
    grille = lire_grille_excel(contenu)

    assert grille.erreurs == ()
    assert len(grille.lignes) == 2
    # La ligne vide (Excel n°3) n'a laissé aucune trace ; la ligne suivante
    # garde son vrai numéro Excel (4), pas un numéro recalculé après le trou.
    assert [ligne.numero_ligne for ligne in grille.lignes] == [2, 4]


def test_formule_avec_valeur_en_cache_est_lue() -> None:
    contenu = _classeur(
        {"Grille": [_ENTETE_MODELE, ["REF1", "Produit inventé", "u", "=1+2"]]}
    )
    contenu = _avec_cache_formule(contenu, "D2", "3")
    grille = lire_grille_excel(contenu)

    assert grille.erreurs == ()
    assert grille.lignes[0].prix_ht == Decimal("3")


def test_formule_sans_valeur_en_cache_est_une_erreur() -> None:
    contenu = _classeur(
        {"Grille": [_ENTETE_MODELE, ["REF1", "Produit inventé", "u", "=1+2"]]}
    )
    grille = lire_grille_excel(contenu)

    assert grille.lignes == ()
    assert grille.erreurs[0].message == "prix manquant"


# --------------------------------------------------------------------------
# Refus immédiat du fichier
# --------------------------------------------------------------------------


def test_octets_non_excel_sont_refuses() -> None:
    with pytest.raises(FichierGrilleInvalide):
        lire_grille_excel(b"ceci n'est pas un classeur Excel")


def test_fichier_protege_est_refuse() -> None:
    signature_ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32
    with pytest.raises(FichierGrilleInvalide, match="protégé"):
        lire_grille_excel(signature_ole)


def test_zip_qui_nest_pas_un_classeur_est_refuse() -> None:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as zout:
        zout.writestr("rien.txt", "pas un classeur Excel")
    with pytest.raises(FichierGrilleInvalide):
        lire_grille_excel(tampon.getvalue())


def test_plus_de_20000_lignes_est_refuse() -> None:
    entete: list[object] = list(_ENTETE_MODELE)
    lignes: list[list[object]] = [entete]
    lignes += [
        [f"REF{i}", f"Produit inventé {i}", "u", "5"] for i in range(LIGNES_MAX + 1)
    ]
    contenu = _classeur({"Grille": lignes})

    with pytest.raises(FichierGrilleInvalide, match=str(LIGNES_MAX)):
        lire_grille_excel(contenu)
