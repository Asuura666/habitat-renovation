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
    « À régler » dit en toutes lettres qu'elle compte tous les problèmes à
    régler, tous mois confondus (constats LIENS-2/ECRAN-6)."""
    gabarit = (SRC / "components" / "Gabarit.tsx").read_text()
    assert "window.scrollTo(0, 0)" in gabarit
    assert "}, [pathname]);" in gabarit
    assert 'useMatch("/bl/*")' in gabarit
    assert "activeAussiSurPageBon(vers, classesLienBarreLaterale)" in gabarit
    assert "activeAussiSurPageBon(vers, classesLienBarreBasse)" in gabarit
    assert "className={classesLienDiscret}" in gabarit
    assert "className={classesLienEnTete}" in gabarit
    assert "min-w-0 flex-1 flex-col" in gabarit
    # Branche vivante pour un compte admin chargé (`urgents` connu) --
    # l'ancienne assertion (« … en tout ») ne couvrait que la branche
    # `undefined` (non-admin ou requête pas encore résolue), jamais celle
    # réellement affichée à l'admin.
    assert 'à régler, dont ${urgents} urgent${urgents > 1 ? "s" : ""}' in gabarit


def test_gabarit_remonte_en_haut_seulement_au_changement_d_ecran() -> None:
    """Contrôle (régression du premier correctif, revue démo constat
    défilement) : à chaque changement de chemin, la page remonte en haut --
    sauf sur grand écran (`GRAND_ECRAN`, même seuil `lg`/1024 px que le
    panneau collant d'« À régler ») quand l'ancien ET le nouveau chemin
    commencent tous les deux par `/a-regler` (liste <-> détail <-> détail
    suivant dans le même écran maître/détail). Au téléphone (< 1024 px),
    cette exception ne s'applique jamais : on remonte toujours, y compris
    `/a-regler/:id` -> `/a-regler/:idSuivant` et le retour à la liste.
    Aucune autre heuristique (nombre de segments, premier segment commun)
    n'entre en jeu."""
    gabarit = (SRC / "components" / "Gabarit.tsx").read_text()
    assert 'const GRAND_ECRAN = "(min-width: 1024px)";' in gabarit

    effet = gabarit.split("const cheminPrecedent = useRef<string | null>(null);", 1)[
        1
    ].split("}, [pathname]);", 1)[0]
    # Espaces normalisés (suites d'espaces/retours à la ligne réduites à un
    # seul espace) : la mise en forme peut changer sans casser le test, mais
    # les expressions exactes ci-dessous, elles, doivent rester intactes.
    effet_normalise = " ".join(effet.split())

    # L'exception ne joue que si l'ancien ET le nouveau chemin sont dans
    # « À régler » -- jamais un simple partage de premier segment
    # quelconque (ex. `/chantiers` -> `/chantiers/:id`), et seulement avec
    # un ET (jamais un OU, qui déclencherait dès qu'un seul des deux
    # chemins est dans « À régler »).
    assert (
        'precedent !== null && precedent.startsWith("/a-regler") '
        '&& pathname.startsWith("/a-regler")'
    ) in effet_normalise
    # L'exception (ne pas remonter) exige le ET avec le grand écran -- pas
    # un OU (qui s'appliquerait même au téléphone) -- et sa condition n'est
    # pas inversée (un `!` devant `window.matchMedia` déclencherait
    # l'exception sur petit écran au lieu du grand). Le corps du `if` doit
    # être un vrai `return;`, pas une instruction vide (no-op) qui laisserait
    # passer le `window.scrollTo(0, 0)` qui suit.
    assert (
        "if (memeEcranMaitreDetailARegler && window.matchMedia(GRAND_ECRAN).matches) "
        "{ return; }"
    ) in effet_normalise
    # Aucune trace de l'ancienne heuristique par segments.
    assert "segmentsDuChemin" not in effet
    assert "segments" not in effet.lower()
    # En dehors de l'exception, on remonte toujours en haut.
    assert "window.scrollTo(0, 0)" in effet


def test_pastille_a_regler_couleur_neutre_et_libelle_avec_urgents() -> None:
    """Revue démo, constat couleur : la pastille de navigation compte
    désormais tous les problèmes à régler (pas seulement les urgents,
    revue finale) -- couleur neutre de la charte (`bg-encre`, texte blanc),
    le rouge `bg-alerte` restant réservé à un compte d'urgents affiché comme
    tel, que cette pastille n'affiche pas. Le libellé accessible donne aussi
    le nombre d'urgents quand il est connu -- `nb_urgents` de la même
    réponse que le compte total, jamais un second appel réseau."""
    gabarit = (SRC / "components" / "Gabarit.tsx").read_text()

    # Couleur neutre sur les deux pastilles (barre latérale, barre basse) ;
    # plus aucune n'est rouge.
    assert 'bg-encre px-1.5 py-0.5 text-xs font-semibold text-white"' in gabarit
    assert 'bg-encre px-1 text-[10px] font-semibold text-white"' in gabarit
    assert 'bg-alerte px-1.5 py-0.5 text-xs font-semibold text-white"' not in gabarit
    assert 'bg-alerte px-1 text-[10px] font-semibold text-white"' not in gabarit

    # Nombre d'urgents lu sur la même requête que le compte total, jamais un
    # second appel.
    assert (
        "const urgentsARegler = estAdmin ? compte.data?.nb_urgents : undefined;"
        in gabarit
    )
    assert "urgents: number | undefined" in gabarit

    fonction = gabarit.split("function libellePastilleARegler(", 1)[1].split(
        "\n}\n", 1
    )[0]
    assert "compte: number, urgents: number | undefined" in fonction
    assert "à régler en tout" in fonction
    assert "à régler, dont ${urgents} urgent${urgents > 1" in fonction


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


def test_routes_de_detail_admin_sont_gardees() -> None:
    """Revue finale (constat COUVERTURE-23, Review Focus 4) : les routes de
    détail réservées à l'admin sont gardées elles aussi, et la garde de
    « / » est vérifiée sur la vraie déclaration de route (l'accueil index),
    jamais sur un texte de commentaire."""
    app = (SRC / "App.tsx").read_text()
    for chemin in (
        'path="a-regler/:id"',
        'path="chantiers/:chantierId"',
        'path="fournisseurs/:fournisseurId"',
    ):
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert "GardeAdmin" in declaration, chemin
    accueil = app.split("<Route\n            index", 1)[1].split("/>\n", 1)[0]
    assert "<GardeAdmin>" in accueil


def test_cache_vide_quand_le_compte_change() -> None:
    """Revue finale (constat DROITS-2) : à la connexion, à la déconnexion et
    sur une session expirée (401), tout le cache TanStack Query est vidé --
    sur un navigateur partagé, un agent ne voit jamais, même un instant, les
    chiffres de l'admin restés en mémoire."""
    connexion = (SRC / "pages" / "Connexion.tsx").read_text()
    assert "queryClient.clear();" in connexion
    gabarit = (SRC / "components" / "Gabarit.tsx").read_text()
    deconnexion = gabarit.split("const deconnexion = useMutation", 1)[1].split(
        "\n  });", 1
    )[0]
    assert "queryClient.clear();" in deconnexion
    ecoute = (SRC / "components" / "EcouteAuthentification.tsx").read_text()
    assert "queryClient.clear();" in ecoute


def test_telephone_champs_16px_et_tuiles_lisibles() -> None:
    """Revue finale : sous `md`, tous les champs passent à 16 px (Safari
    zoome sinon la page au toucher, constat TELEPHONE-6) ; le grand chiffre
    d'une tuile réduit sa taille là où six tuiles partagent la ligne
    (constat COUVERTURE-25) ; l'espace des milliers est visible (constat
    ECRAN-7)."""
    css = (SRC / "index.css").read_text()
    regle = css.split("@media (max-width: 767px)", 1)[1]
    assert "font-size: 16px !important;" in regle
    for element in ("input", "select", "textarea"):
        assert element in regle
    chiffre = (SRC / "ui" / "Chiffre.tsx").read_text()
    assert "xl:text-xl 2xl:text-2xl" in chiffre
    formats = (SRC / "lib" / "formats.ts").read_text()
    assert "const ESPACE_FINE_INSECABLE = /\\u202f/g;" in formats
    assert "espacesVisibles(FORMATEUR_MONTANT.format(" in formats


def test_motif_de_lecture_sans_pourcentage_technique() -> None:
    """Revue finale (constats ECRAN-13, TELEPHONE-13) : plus de
    « confiance 45 %, seuil 80 % » affiché au dirigeant."""
    motifs = (SRC / "lib" / "motifs.ts").read_text()
    assert "seuil ${" not in motifs
    assert "Lecture incertaine de « " in motifs


def test_fil_ariane_cible_44px() -> None:
    """Revue finale (constat TELEPHONE-7) : les liens du fil d'Ariane, seul
    chemin de retour de plusieurs pages de détail au téléphone, ont une
    cible d'au moins 44 px (spec §7)."""
    fil = (SRC / "ui" / "FilAriane.tsx").read_text()
    lien = fil.split("<Link", 1)[1].split(">", 1)[0]
    assert "min-h-[44px]" in lien


# ---------------------------------------------------------------------------
# Contrôles de prix désactivés (décision d'Ilane du 24/09/2026,
# `docs/dette.md`) : aucun calcul métier côté front, seulement des libellés
# et un filtre adaptés à `CompteProblemesReponse.controle_prix_actif`
# (`GET /api/a-regler/compte`, seule source du drapeau).
# ---------------------------------------------------------------------------


def test_libelle_ecart_bascule_sur_controle_prix_actif() -> None:
    """`libelleEcart` (une seule fonction, reprise par les trois tuiles
    ci-dessous) : « Écart prix ou quantité » quand le drapeau est vrai,
    « Écart de quantité » sinon — jamais un calcul, une correspondance
    texte."""
    libelles = (SRC / "ui" / "libelles.ts").read_text()
    fonction = libelles.split("export function libelleEcart(", 1)[1].split("\n}\n", 1)[
        0
    ]
    assert '"Écart prix ou quantité"' in fonction
    assert '"Écart de quantité"' in fonction


def test_tuiles_ecart_utilisent_libelle_ecart_partage() -> None:
    """Vue d'ensemble, fiche chantier et fiche fournisseur : les trois
    tuiles « Écart … » appellent `libelleEcart` et `sousTexteEcart`, jamais
    le texte figé « Écart prix ou quantité » recopié à la main (constat de
    la tâche : un seul point de traduction, `ui/libelles.ts`) -- et jamais
    non plus un sous-texte muet sur la nature de l'écart (constat « Tuile »
    de la revue des contrôles de prix)."""
    for chemin in ("VueEnsemble.tsx", "FicheChantier.tsx", "FicheFournisseur.tsx"):
        page = (SRC / "pages" / chemin).read_text()
        assert "libelleEcart(controlePrixActif)" in page, chemin
        assert "sousTexteEcart(controlePrixActif)" in page, chemin
        assert '"Écart prix ou quantité"' not in page, chemin


def test_controle_prix_actif_repli_est_toujours_faux() -> None:
    """Constat mineur 2 de la revue des contrôles de prix : le repli de
    `controle_prix_actif` (le temps qu'une requête réponde) est toujours
    `false` -- même valeur que le défaut serveur (`CONTROLE_PRIX_ACTIF`
    absente -> désactivé), jamais `true`, qui ferait flasher le libellé
    « Écart prix ou quantité », la puce « Prix » ou le filtre « Prix » avant
    la réponse de `GET /api/a-regler/compte`."""
    for chemin in (
        "ARegler.tsx",
        "VueEnsemble.tsx",
        "FicheChantier.tsx",
        "FicheFournisseur.tsx",
    ):
        page = (SRC / "pages" / chemin).read_text()
        assert "controle_prix_actif ?? false" in page, chemin
        assert "controle_prix_actif ?? true" not in page, chemin


def test_a_regler_masque_le_filtre_prix_quand_controle_prix_inactif() -> None:
    """Le filtre « Prix » de l'écran « À régler » n'est construit que si
    `controlePrixActif` est vrai — sinon aucune anomalie R07/R08/R09 ne
    peut plus être ouverte (masquées côté serveur), un filtre vide n'aurait
    aucun sens."""
    a_regler = (SRC / "pages" / "ARegler.tsx").read_text()
    assert (
        "const controlePrixActif = compteARegler.data?.controle_prix_actif ?? false;"
        in a_regler
    )
    options = a_regler.split("const options: OptionFiltre[] = [", 1)[1].split("];", 1)[
        0
    ]
    assert "...(controlePrixActif" in options
    assert '{ valeur: "prix", libelle: "Prix"' in options


def test_a_regler_ancien_lien_filtre_prix_revient_a_tous() -> None:
    """Constat mineur 6 de la revue des contrôles de prix : un ancien lien
    `/a-regler?filtre=prix` (partagé avant la désactivation) revient au
    filtre « tous » tant que le contrôle de prix reste désactivé -- calculé
    une seule fois (`filtreEffectif`), réutilisé à la fois par la liste
    affichée et par la pastille active des filtres (`Filtres`), jamais deux
    lectures divergentes de la même règle."""
    a_regler = (SRC / "pages" / "ARegler.tsx").read_text()
    assert (
        'const filtreEffectif = filtreActif === "prix" && !controlePrixActif '
        '? "tous" : filtreActif;' in a_regler
    )
    assert "valeur={filtreEffectif}" in a_regler
    bloc_liste = a_regler.split("const listeAffichee = useMemo(() => {", 1)[1].split(
        "}, [filtreEffectif", 1
    )[0]
    assert "filtreEffectif ===" in bloc_liste


def test_reglages_ne_filtre_plus_les_seuils_lui_meme() -> None:
    """Un réglage propre à un contrôle désactivé (les trois seuils de prix
    lus par R07/R08/R09, ou le seuil de R06) n'est plus signalé par une
    mention sur l'écran Réglages : le serveur ne le renvoie plus du tout
    tant que le contrôle reste désactivé (`ingest/parametres.py
    ::_cle_masquee`, GET /api/parametres), un seul point de décision.
    L'ancienne mention (« Contrôle des prix désactivé pour le moment »,
    « Contrôle désactivé pour le moment ») a disparu, sans qu'un filtre
    équivalent ne soit reconstruit côté front : l'écran affiche simplement
    la liste que l'API lui renvoie."""
    reglages = (SRC / "pages" / "Reglages.tsx").read_text()
    assert "Contrôle des prix désactivé pour le moment." not in reglages
    assert "Contrôle désactivé pour le moment." not in reglages
    assert "controlePrixActif" not in reglages
    assert "controleLivreNonFactureActif" not in reglages
    assert "CLES_SEUILS_PRIX" not in reglages
    assert "obtenirCompteARegler" not in reglages
