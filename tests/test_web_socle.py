from pathlib import Path

WEB = Path(__file__).parents[1] / "web"
SRC = WEB / "src"


def test_polices_auto_hebergees() -> None:
    assert "fonts.googleapis" not in (WEB / "index.html").read_text()
    main = (SRC / "main.tsx").read_text()
    for paquet in (
        "@fontsource/fraunces",
        "@fontsource/ibm-plex-sans",
        "@fontsource/ibm-plex-mono",
    ):
        assert paquet in main


def test_jetons_de_la_charte() -> None:
    config = next(WEB.glob("tailwind.config.*")).read_text()
    for valeur in (
        "#f6f4ef",
        "#1f4d3a",
        "#2f7a55",
        "#c77700",
        "#b3261e",
        "Fraunces",
        "IBM Plex Mono",
    ):
        assert valeur in config


def test_libelles_couvre_toutes_les_regles() -> None:
    libelles = (SRC / "ui" / "libelles.ts").read_text()
    for n in range(1, 18):
        assert f"R{n:02d}:" in libelles
    assert "Bon de livraison jamais reçu" in libelles
    assert (
        "Prix plus cher que d'habitude" in libelles
        or "Prix plus cher que d’habitude" in libelles  # noqa: RUF001
    )
    assert "Problème à vérifier" in libelles  # repli pour une règle inconnue


def test_navigation_cinq_entrees_sans_jargon() -> None:
    gabarit = (SRC / "components" / "Gabarit.tsx").read_text()
    for libelle in (
        "Vue d'ensemble",
        "À régler",
        "Chantiers",
        "Fournisseurs",
        "Documents",
        "Réglages",
        "Journal",
    ):
        assert libelle in gabarit
    for jargon in ("Anomalies", "Bilan", "BL déposés", "À traiter"):
        assert f">{jargon}<" not in gabarit
    assert "md:hidden" in gabarit and "fixed bottom-0" in gabarit


def test_anciennes_routes_redirigent() -> None:
    """Redirections encore actives (spec §3) après le fix round 1 : R1
    (« aucune fonctionnalité existante n'est supprimée » l'emporte sur une
    redirection posée par erreur en Task 4 pour `/factures*`/`/anomalies`,
    voir `test_ecrans_sans_remplacement_restent_montes`) et R2 (`/bilan/:c/
    :f` redirige désormais vers `/chantiers/:c/:f`, pas `/documents/:id`)."""
    app = (SRC / "App.tsx").read_text()
    for ancien in ('"a-traiter"', '"bilan"', '"bl"'):
        assert f"path={ancien}" in app
    assert "RedirectionAncienneUrl" in app

    declaration = app.split('path="bilan/:chantierId/:fournisseurId"', 1)[1].split(
        "path=", 1
    )[0]
    assert "/chantiers/${p.chantierId" in declaration
    assert "p.fournisseurId" in declaration


def test_ecrans_sans_remplacement_restent_montes() -> None:
    """Fix round 1, R1 : Factures et Anomalies n'ont pas encore de
    remplacement construit — ils restent de vrais écrans, gardés admin, sur
    leur ancienne URL, plutôt qu'une redirection qui les rendrait
    inaccessibles."""
    app = (SRC / "App.tsx").read_text()
    for chemin, composant in (
        ('path="factures"', "FacturesListe"),
        ('path="factures/:id"', "FactureDetail"),
        ('path="anomalies"', "Anomalies"),
    ):
        assert chemin in app
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert f"<{composant}" in declaration, chemin
        assert "GardeAdmin" in declaration, chemin
        assert "RedirectionAncienneUrl" not in declaration, chemin


def test_chantiers_referentiel_reste_accessible() -> None:
    """Fix round 1, R1 : la création de chantier et la validation d'alias
    (`Chantiers.tsx`, ex-écran « Chantiers & fournisseurs ») restent
    accessibles à `/chantiers/referentiel`, avec un lien visible depuis la
    navigation."""
    app = (SRC / "App.tsx").read_text()
    assert 'path="chantiers/referentiel"' in app
    declaration = app.split('path="chantiers/referentiel"', 1)[1].split("path=", 1)[0]
    assert "<Chantiers" in declaration
    assert "GardeAdmin" in declaration

    gabarit = (SRC / "components" / "Gabarit.tsx").read_text()
    assert "Gérer les chantiers" in gabarit
    assert "/chantiers/referentiel" in gabarit


def test_redirection_preserve_recherche_et_ancre() -> None:
    """Fix round 1, finding 1 : une redirection d'ancienne URL ne doit
    jamais perdre les filtres (`search`) ni l'ancre (`hash`) de l'URL
    d'origine."""
    redirection = (SRC / "routes" / "RedirectionAncienneUrl.tsx").read_text()
    assert "location.search" in redirection
    assert "location.hash" in redirection


def test_libelles_sans_jargon_technique() -> None:
    """Fix round 1, finding 2 : mots techniques retirés des phrases
    affichées par `phraseProbleme` (reformulation seulement, aucun calcul
    ajouté)."""
    libelles = (SRC / "ui" / "libelles.ts").read_text()
    phrases = libelles.split("export function phraseProbleme", 1)[1]
    for mot in (
        "rapproché",
        "PU facturé",
        "médiane",
        "occurrence(s)",
        "non résolu",
        "ratio",
    ):
        assert mot not in phrases, mot


def test_routes_admin_sont_gardees() -> None:
    app = (SRC / "App.tsx").read_text()
    for chemin in (
        'path="/"',
        'path="a-regler"',
        'path="chantiers"',
        'path="fournisseurs"',
        'path="journal"',
        'path="reglages"',
    ):
        # la déclaration de route va jusqu'au prochain `path=` : elle doit
        # monter GardeAdmin
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert "GardeAdmin" in declaration, chemin
