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

    # Task 6 (exception à la règle Gabarit) : « Vue d'ensemble » déborde à
    # 375 px dans la barre de navigation basse — remplacé là par « Accueil »,
    # sans perdre le libellé complet de la barre latérale (ci-dessus).
    assert "Accueil" in gabarit


def test_anciennes_routes_redirigent() -> None:
    """Redirections encore actives (spec §3) après le fix round 1 : R1
    (« aucune fonctionnalité existante n'est supprimée » l'emporte sur une
    redirection posée par erreur en Task 4 pour `/factures*`/`/anomalies`,
    voir `test_ecrans_sans_remplacement_restent_montes`) et R2 (`/bilan/:c/
    :f` redirige désormais vers `/chantiers/:c/:f`, pas `/documents/:id`)."""
    app = (SRC / "App.tsx").read_text()
    for ancien in ('"a-traiter"', '"bilan"', '"bl"', '"anomalies"'):
        assert f"path={ancien}" in app
    assert "RedirectionAncienneUrl" in app

    declaration = app.split('path="bilan/:chantierId/:fournisseurId"', 1)[1].split(
        "path=", 1
    )[0]
    assert "/chantiers/${p.chantierId" in declaration
    assert "p.fournisseurId" in declaration


def test_ecrans_transitoires_tous_migres() -> None:
    """Fix round 1, R1 : les anciens écrans Factures et Anomalies sont restés
    montés sur leur ancienne URL tant qu'ils n'avaient pas de remplacement.
    Ils en ont désormais un (Task 8 : `DocumentsListe`/`PageBl`/
    `FactureDetail` ; Task 6 : `ARegler`), donc leurs anciennes URL
    redirigent pour de bon, en conservant recherche et ancre."""
    app = (SRC / "App.tsx").read_text()
    for chemin, cible in (
        ('path="anomalies"', '"/a-regler"'),
        ('path="factures"', '"/documents"'),
    ):
        assert chemin in app
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert "RedirectionAncienneUrl" in declaration, chemin
        assert cible in declaration, chemin
    assert "<Anomalies" not in app
    assert "<FacturesListe" not in app


def test_chantiers_referentiel_reste_accessible() -> None:
    """Fix round 1, R1, mis à jour par la Task 7 de la refonte du front :
    la création de chantier (désormais dans `ChantiersListe.tsx`) et la
    validation d'alias (désormais dans l'écran « À régler ») ont repris tout
    le contenu utile de l'ancien écran « Chantiers & fournisseurs »
    (`Chantiers.tsx`, supprimé) — `/chantiers/referentiel` devient une
    simple redirection vers `/chantiers`, gardée pour les anciens favoris
    (spec §3, aucune fonctionnalité supprimée). Revue finale (constats
    LIENS-7, ECRAN-17, COUVERTURE-21) : le sous-lien « Gérer les chantiers »
    de la barre latérale, qui ne menait plus qu'à « Chantiers » (doublon
    sans effet visible, jamais actif), est retiré."""
    app = (SRC / "App.tsx").read_text()
    assert 'path="chantiers/referentiel"' in app
    declaration = app.split('path="chantiers/referentiel"', 1)[1].split("path=", 1)[0]
    assert "RedirectionAncienneUrl" in declaration
    assert '"/chantiers"' in declaration
    assert not (SRC / "pages" / "Chantiers.tsx").exists()

    gabarit = (SRC / "components" / "Gabarit.tsx").read_text()
    assert 'to="/chantiers/referentiel"' not in gabarit


def test_gabarit_remonte_en_haut_et_signale_l_ecran_actif() -> None:
    """Revue finale : changer d'écran repart du haut de la page (constat
    TELEPHONE-1, sur le chemin seulement : un changement de filtre ne fait
    pas sauter la page, une ancre est laissée à l'écran qui la cible) ; la
    page d'un bon allume « Documents » (constat LIENS-8) ; Réglages et
    Journal ont un état actif (constat TELEPHONE-14) ; la colonne de
    contenu peut rétrécir (`min-w-0`, constat COUVERTURE-21) ; la pastille
    « À régler » dit en toutes lettres qu'elle compte les urgents de tous
    les mois (constats LIENS-2/ECRAN-6)."""
    gabarit = (SRC / "components" / "Gabarit.tsx").read_text()
    assert "window.scrollTo(0, 0)" in gabarit
    assert "}, [pathname]);" in gabarit
    assert 'useMatch("/bl/*")' in gabarit
    assert "activeAussiSurPageBon(vers, classesLienBarreLaterale)" in gabarit
    assert "activeAussiSurPageBon(vers, classesLienBarreBasse)" in gabarit
    assert "className={classesLienDiscret}" in gabarit
    assert "className={classesLienEnTete}" in gabarit
    assert "min-w-0 flex-1 flex-col" in gabarit
    assert "tous mois confondus" in gabarit


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
