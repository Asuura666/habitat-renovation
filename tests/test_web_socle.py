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
    app = (SRC / "App.tsx").read_text()
    for ancien in ('"a-traiter"', '"anomalies"', '"bilan"', '"factures"', '"bl"'):
        assert f"path={ancien}" in app
    assert "Navigate" in app


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
