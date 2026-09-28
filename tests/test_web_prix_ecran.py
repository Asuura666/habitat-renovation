"""Vérifications statiques (grep, même principe que `test_web_socle.py` --
aucun outil de test front dans la stack, L2-D17) de l'écran « Grille de
prix » d'un fournisseur et des interrupteurs de Réglages -- phase 3, tâche
P5, spec `docs/superpowers/specs/2026-09-27-prix-design.md` §9, §3.4."""

from pathlib import Path

WEB = Path(__file__).parents[1] / "web"
SRC = WEB / "src"


def test_route_grille_fournisseur_admin_gardee() -> None:
    app = (SRC / "App.tsx").read_text()
    assert 'path="fournisseurs/:fournisseurId/prix"' in app
    declaration = app.split('path="fournisseurs/:fournisseurId/prix"', 1)[1].split(
        "path=", 1
    )[0]
    assert "GardeAdmin" in declaration
    assert "GrilleFournisseur" in declaration


def test_lien_grille_de_prix_sur_la_fiche_fournisseur() -> None:
    fiche = (SRC / "pages" / "FicheFournisseur.tsx").read_text()
    assert "/prix`" in fiche
    assert "Grille de prix" in fiche


def test_ecran_grille_fournisseur_sans_jargon() -> None:
    """Textes à l'écran en français courant, sans mot technique (CLAUDE.md,
    Contraintes communes)."""
    ecran = (SRC / "pages" / "GrilleFournisseur.tsx").read_text()
    for mot_interdit in ("OCR", "alias", "clé produit"):
        assert mot_interdit not in ecran
    for texte in (
        "Ajouter un produit",
        "Retirer de la grille",
        "Télécharger le modèle",
        "Voir l'aperçu",
        "Rechercher par référence ou désignation",
    ):
        assert texte in ecran


def test_ecran_grille_fournisseur_appelle_l_api_grilles() -> None:
    ecran = (SRC / "pages" / "GrilleFournisseur.tsx").read_text()
    for symbole in (
        "obtenirGrilleFournisseur",
        "enregistrerPrixGrille",
        "retirerProduitGrille",
        "apercevoirImportGrille",
        "importerGrille",
        "urlModeleGrille",
    ):
        assert symbole in ecran


def test_api_grilles_ts_couvre_les_routes_admin() -> None:
    module = (SRC / "api" / "grilles.ts").read_text()
    for route in (
        "/api/grilles/fournisseurs/",
        "/prix",
        "/retrait",
        "/import/apercu",
        "/import",
        "/api/grilles/modele",
    ):
        assert route in module


def test_reglages_regroupe_par_groupe_et_rend_les_interrupteurs() -> None:
    reglages = (SRC / "pages" / "Reglages.tsx").read_text()
    assert "grouperParametres" in reglages
    assert "parametre.groupe" in reglages
    assert "parametre.interrupteur" in reglages
    assert "LigneInterrupteur" in reglages
    # Enregistre 0 ou 1 (spec §3.4 : un interrupteur n'accepte que ces deux
    # valeurs côté serveur), jamais un texte libre.
    assert '"1" : "0"' in reglages


def test_journal_connait_les_actions_de_grille_de_prix() -> None:
    journal = (SRC / "lib" / "journal.ts").read_text()
    for action in ("grille_importee", "grille_prix_saisi", "grille_prix_retire"):
        assert f'{action}: "' in journal
    for cible in ("grille_import", "grille_prix"):
        assert f'"{cible}"' in journal
