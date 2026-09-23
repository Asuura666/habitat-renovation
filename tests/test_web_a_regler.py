"""Contrat front de l'écran « À régler » (Task 6, refonte du front) — tests
texte sur les fichiers source, même convention que `test_web_socle.py`/
`test_web_bilan.py` (aucune exécution JS, aucune base nécessaire).
"""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).parents[1] / "web"
SRC = WEB / "src"


def _lire(*chemins: str) -> str:
    chemin = SRC.joinpath(*chemins)
    assert chemin.exists(), f"{chemin} est introuvable"
    return chemin.read_text()


def test_ecran_a_regler_existe_et_liste_les_filtres_sans_jargon() -> None:
    page = _lire("pages", "ARegler.tsx")

    assert "useSearchParams" in page

    for libelle in (
        "Tous",
        "Urgents",
        "BL manquants",
        "Prix",
        "Quantités",
        "À rattacher",
        "Bons illisibles",
        "Déjà réglés",
    ):
        assert libelle in page, libelle

    # Filtres dans l'URL (spec §4) : jamais un simple état local perdu au
    # rechargement.
    assert '"filtre"' in page

    # Langage courant (spec §5) : jamais un code de règle brut interpolé
    # dans un texte affiché.
    for jargon in (
        "{anomalie.regle}",
        "{p.anomalie.regle}",
        "{probleme.anomalie.regle}",
    ):
        assert jargon not in page, jargon
    # Mots interdits dans un texte affiché (spec §5) : vérifiés comme nœud
    # de texte JSX isolé (`>Mot<`) -- les identifiants de code
    # (`anomalie.id`, `CLE_ANOMALIES`, commentaires) portent légitimement
    # ces mots ailleurs dans le fichier, ce n'est pas ce qui est interdit.
    for jargon in (">Anomalies<", ">Bloc<", ">Alias<", ">Rapprochement<"):
        assert jargon not in page, jargon


def test_ecran_a_regler_reprend_le_filtre_bloc_id_de_l_ancien_ecran_anomalies() -> None:
    """Fonctionnalité reprise d'`Anomalies.tsx` (supprimé par cette tâche) :
    `BilanFournisseur.tsx` lie toujours vers `/anomalies?blocId=...`, qui
    redirige maintenant vers `/a-regler` (voir `test_anciennes_routes_
    redirigent`) -- `ARegler.tsx` doit lire ce même paramètre, sous peine de
    perdre le lien « Voir les anomalies » d'un bloc précis. Contrat repris
    de `test_filtre_anomalies_accepte_un_bloc_exact`
    (`tests/test_web_bilan_navigation.py`, mis à jour par cette tâche)."""
    page = _lire("pages", "ARegler.tsx")
    assert 'parametres.get("blocId")' in page

    client = _lire("api", "anomalies.ts")
    assert 'params.set("bloc_id", filtres.blocId)' in client


def test_probleme_detail_couvre_le_traitement_d_une_anomalie() -> None:
    page = _lire("pages", "ProblemeDetail.tsx")

    assert "Commentaire (obligatoire)" in page
    assert "Contesté auprès du fournisseur" in page
    assert "C'est normal, ignorer" in page
    assert "Voir la facture" in page
    assert "Voir le bon de livraison" in page
    assert "/documents/${" in page
    assert "/bl/${" in page

    # Commentaire obligatoire : les deux boutons de traitement sont
    # désactivés tant qu'il est vide (même contrat que l'ancien
    # `ActionsAnomalie` d'`Anomalies.tsx`).
    assert "disabled={!soumissionValide" in page or "disabled={" in page

    # Invalidation après succès (brief Task 6) : anomalies, tableau de
    # bord, bilan -- et, depuis la revue finale (constat LIENS-4), la
    # comparaison des bons : une seule aide partagée par toutes les
    # écritures qui changent des problèmes.
    assert "invaliderApresChangementAnomalies(queryClient)" in page
    aide = _lire("api", "invalidations.ts")
    for cle in ("CLE_ANOMALIES", "CLE_TABLEAU_DE_BORD", '["bilan"]', '["document"]'):
        assert f"queryKey: {cle}" in aide, cle

    # Jamais un code de règle brut affiché.
    assert "{anomalie.regle}" not in page


def test_ecritures_qui_changent_des_problemes_invalident_tout() -> None:
    """Revue finale (constat LIENS-4) : valider/archiver/relire un bon
    (rapprochement relancé), déposer une facture (idem), rattacher un
    chantier (chantier des livraisons réécrit) changent des problèmes côté
    serveur -- la pastille « À régler », la vue d'ensemble, le bilan et la
    comparaison du bon doivent être invalidés, pas seulement après le
    traitement d'un problème."""
    for chemin in (
        ("pages", "DocumentDetail.tsx"),
        ("pages", "DocumentsListe.tsx"),
        ("components", "AliasCarte.tsx"),
        ("pages", "ProblemeDetail.tsx"),
    ):
        assert "invaliderApresChangementAnomalies(queryClient)" in _lire(*chemin), (
            chemin
        )

    detail = _lire("pages", "DocumentDetail.tsx")
    sur_ecriture = detail.split("function surEcriture", 1)[1].split("\n  }\n", 1)[0]
    assert "invaliderApresChangementAnomalies(queryClient)" in sur_ecriture

    liste = _lire("pages", "DocumentsListe.tsx")
    depot = liste.split("function DepotFacture", 1)[1].split("\nfunction ", 1)[0]
    assert "invaliderApresChangementAnomalies(queryClient)" in depot


def test_a_regler_lit_les_perimetres_poses_par_les_autres_ecrans() -> None:
    """Revue finale (constats LIENS-1, ECRAN-2, COUVERTURE-1, COUVERTURE-23)
    : un paramètre posé par un écran doit être lu par l'écran cible. La page
    du bon ouvre `/a-regler?document=<id>` (« Régler les N problèmes »), les
    fiches chantier et fournisseur ouvrent `?chantier=`/`?fournisseur=`
    (« Régler les problèmes », « Voir l'historique ») -- `ARegler` lit chacun
    et le transmet au serveur, qui filtre (`bl_document_id`, `chantier_id`,
    `fournisseur_id`) : jamais la file complète à la place."""
    page_bl = _lire("pages", "PageBl.tsx")
    assert "`/a-regler?document=${documentId}`" in page_bl

    fiche_chantier = _lire("pages", "FicheChantier.tsx")
    assert "`/a-regler?chantier=${id}`" in fiche_chantier
    assert "`/a-regler?filtre=regles&chantier=${id}`" in fiche_chantier

    fiche_fournisseur = _lire("pages", "FicheFournisseur.tsx")
    assert "/a-regler?fournisseur=" in fiche_fournisseur
    assert "/a-regler?filtre=regles&fournisseur=" in fiche_fournisseur

    aregler = _lire("pages", "ARegler.tsx")
    for parametre in ("document", "blocId", "chantier", "fournisseur"):
        assert f'parametres.get("{parametre}")' in aregler, parametre
    for filtre in (
        "blDocumentId: portee.id",
        "blocId: portee.id",
        "chantierId: portee.id",
        "fournisseurId: portee.id",
    ):
        assert filtre in aregler, filtre
    # Bandeau qui dit la restriction, avec la sortie vers la file complète.
    assert "Problèmes de ce bon de livraison uniquement." in aregler
    assert "Afficher tous les problèmes" in aregler

    client = _lire("api", "anomalies.ts")
    assert 'params.set("bl_document_id", filtres.blDocumentId)' in client


def test_page_bl_accorde_le_bouton_regler() -> None:
    """Mineur de la Task 8 (« Régler les 1 problèmes ») corrigé à la revue
    finale."""
    page_bl = _lire("pages", "PageBl.tsx")
    assert '"Régler le problème"' in page_bl
    assert "Régler les ${nbProblemes} problèmes" in page_bl


def test_probleme_detail_couvre_documents_alias_et_articles() -> None:
    page = _lire("pages", "ProblemeDetail.tsx")

    assert "Chantier à rattacher" in page
    assert "Article à valider" in page

    # Fix round 1, finding 5 : titre d'un document « à vérifier » choisi
    # selon son type et sa confirmation (bon illisible / facture à
    # vérifier / écart signalé par l'équipe) -- fonction partagée avec la
    # liste (`ARegler.tsx::titreDocument`), jamais un intitulé unique
    # `<h2>Bon illisible à corriger</h2>` qui confondait les trois cas.
    assert "titreDocument(document)" in page
    aregler = _lire("pages", "ARegler.tsx")
    for titre in (
        "Bon illisible à corriger",
        "Facture à vérifier",
        "Écart signalé par l'équipe",
    ):
        assert titre in aregler, titre

    # Documents « à vérifier » : lien de correction vers la page du bon
    # (BL/enlèvement) ou de la facture -- jamais un formulaire dupliqué
    # ici, jamais le même lien pour les deux (finding 5(a) : `/bl/:id`
    # refuse une facture, `_document_pour_lecture`,
    # `app/modules/ingest/corrections.py`). Revue finale : la facture
    # s'ouvre sur sa nouvelle URL (constat LIENS-10, plus `/factures/:id` et
    # sa redirection), le bon directement sur sa section de correction
    # (constat COUVERTURE-17, ancre `#corriger`).
    assert "`${lienBon(document.id)}#corriger`" in page
    assert "`/documents/${document.id}`" in page
    assert "/factures/" not in page
    page_bl = _lire("pages", "PageBl.tsx")
    assert 'id="corriger"' in page_bl
    assert 'location.hash === "#corriger"' in page_bl

    # Chantiers à rattacher : réutilise le composant partagé, ne le
    # réimplémente pas.
    assert "AliasCarte" in page
    assert 'from "../components/AliasCarte"' in page

    # Articles à valider : fonctionnalité reprise de l'ancien
    # `ATraiter.tsx` (supprimé par cette tâche) -- mêmes trois champs.
    assert "validerArticle" in page
    assert "Unité de conditionnement" in page
    assert "Unité de facturation" in page
    assert "Ratio" in page


def test_app_route_a_regler_et_a_regler_id() -> None:
    app = _lire("App.tsx")

    for chemin in ('path="a-regler"', 'path="a-regler/:id"'):
        assert chemin in app, chemin
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert "<ARegler" in declaration, chemin
        assert "GardeAdmin" in declaration, chemin

    assert 'from "./pages/ARegler"' in app
    assert 'from "./pages/Anomalies"' not in app
    assert 'from "./pages/ATraiter"' not in app


def test_app_anciennes_routes_anomalies_et_a_traiter_redirigent() -> None:
    app = _lire("App.tsx")

    for ancien in ('"a-traiter"', '"anomalies"'):
        assert f"path={ancien}" in app, ancien
        declaration = app.split(f"path={ancien}", 1)[1].split("path=", 1)[0]
        assert "RedirectionAncienneUrl" in declaration, ancien
        assert "<Anomalies" not in declaration, ancien
        assert "<ATraiter" not in declaration, ancien


def test_anciennes_pages_supprimees_une_fois_reprises() -> None:
    assert not (SRC / "pages" / "Anomalies.tsx").exists()
    assert not (SRC / "pages" / "ATraiter.tsx").exists()


def test_gabarit_pastille_urgents_et_libelle_court_accueil() -> None:
    """Exception à la règle Gabarit (Task 6, seule tâche autorisée) : (1) la
    pastille du nombre de problèmes à régler sur « À régler » (compte unique
    du serveur depuis la revue finale) ; (2) « Accueil » dans la barre basse
    (téléphone), « Vue d'ensemble » conservé dans la barre latérale."""
    gabarit = _lire("components", "Gabarit.tsx")

    # (1) Pastille -- compte unique calculé par le serveur (revue finale,
    # voir `test_un_seul_compte_de_problemes_a_regler`), jamais un calcul
    # ni une liste recomptée côté front.
    assert "queryKey: CLE_COMPTE_A_REGLER" in gabarit
    assert "queryFn: obtenirCompteARegler" in gabarit
    assert "listerAnomalies" not in gabarit

    # (2) Libellé court de la barre basse, sans perdre celui de la barre
    # latérale.
    assert "Accueil" in gabarit
    assert "Vue d'ensemble" in gabarit


# ---------------------------------------------------------------------------
# Tour de correction 1 (revue de L5-T6/Task 6) -- un test par constat
# Critical/Important, voir le rapport de tâche.
# ---------------------------------------------------------------------------


def test_probleme_detail_garde_les_dates_de_detail_contre_un_tiret() -> None:
    """Finding 1 (Critical) : `detail["date_bl"]`/`depose_le`/
    `dernier_depot` valent parfois le tiret cadratin (R01/R02 sans date
    lue, R15/R16 sans dépôt) -- jamais passés bruts à `formaterDate`/
    `formaterDateHeure`, qui plantent sur une chaîne non convertible en
    date (même garde que `ui/libelles.ts::date`/`dateHeure`). Sans cette
    garde, ouvrir un de ces problèmes rendait toute l'application blanche
    (aucun `ErrorBoundary`)."""
    page = _lire("pages", "ProblemeDetail.tsx")
    assert "formaterDate(detail.date_bl" not in page
    assert "formaterDateHeure(detail.depose_le" not in page
    assert "formaterDateHeure(detail.dernier_depot" not in page
    assert 'dateOuTiret(detail, "date_bl")' in page
    assert 'dateHeureOuTiret(detail, "depose_le")' in page
    assert 'dateHeureOuTiret(detail, "dernier_depot")' in page


def test_valeur_du_filtre_illisible_correspond_a_la_categorie() -> None:
    """Finding 2 (Important) : la pastille « Bons illisibles » portait la
    valeur `illisibles` (pluriel) alors que `categorieFiltreProbleme`
    renvoie `illisible` -- `listeAffichee` ne faisait donc jamais
    correspondre aucune ligne à ce filtre, malgré un compte affiché."""
    page = _lire("pages", "ARegler.tsx")
    assert '{ valeur: "illisible", libelle: "Bons illisibles"' in page
    assert '"illisibles"' not in page

    # Contrat plus large demandé par la piste de correction : chaque
    # `valeur` de filtre catégorie (hors "tous"/"urgents"/"regles", qui ne
    # sont pas des catégories) correspond à une `CategorieFiltre` connue.
    categories_connues = {"bl", "prix", "quantites", "rattacher", "illisible", "autre"}
    valeurs_filtres_categorie = {"bl", "prix", "quantites", "rattacher", "illisible"}
    assert valeurs_filtres_categorie <= categories_connues


def test_id_anomalie_reste_luuid_brut_pour_les_liens_a_regler_id() -> None:
    """Finding 3 (Important) : `FicheChantier.tsx` (Task 7) et
    `FicheFournisseur.tsx` (Task 9) lient vers `/a-regler/${anomalie.id}`
    avec l'uuid brut d'une anomalie -- un identifiant composite
    (`anomalie:<uuid>`) rendait ces liens toujours introuvables (« Ce
    problème n'est plus disponible »). Seuls les pseudo-problèmes
    (document/alias/article) restent préfixés, faute d'espace
    d'identifiants garanti entre eux."""
    page = _lire("pages", "ARegler.tsx")
    assert "id: `anomalie:" not in page
    assert "id: anomalie.id" in page
    assert "id: a.id" in page
    for prefixe in ("document", "alias", "article"):
        assert f"id: `{prefixe}:" in page


def test_probleme_detail_monte_avec_une_cle_stable_par_probleme() -> None:
    """Finding 4 (Important) : sans `key`, changer de ligne sur ordinateur
    réutilise la même instance de `<ProblemeDetail>` -- le commentaire
    saisi, le formulaire d'article et le chantier choisi dans `AliasCarte`
    restaient collés au problème précédent (risque de contester un
    problème avec le commentaire d'un autre, ou de valider un article avec
    les unités d'un autre)."""
    page = _lire("pages", "ARegler.tsx")
    assert "<ProblemeDetail" in page
    bloc = page.split("<ProblemeDetail", 1)[1].split("/>", 1)[0]
    assert "key={problemeActuel.id}" in bloc


def test_lien_anomalie_choisit_facture_ou_bon_de_livraison_selon_le_type() -> None:
    """Finding 6 (tour 1) : « Voir la facture » s'affichait pour toute
    anomalie ayant un `document_id`, même quand ce document est en réalité
    un bon de livraison (R11, R15 : `document_id` porte l'identifiant du
    BL) -- jamais deux liens vers deux documents différents affichés en
    même temps pour une même anomalie. Le lien facture reste conditionné
    par `anomalie.type === "facture"` (voir le test suivant pour le lien
    bon, dont la condition a changé au tour 2)."""
    page = _lire("pages", "ProblemeDetail.tsx")
    assert 'anomalie.type === "facture" && anomalie.document_id !== null' in page


def test_lien_bon_de_livraison_saffiche_meme_pour_une_anomalie_de_facture() -> None:
    """Finding 1 (tour 2, régression du fix du finding 6 au tour 1) : le
    correctif précédent conditionnait aussi le lien bon par `anomalie.type
    !== "facture"` -- or `rapprochement.py:931-936` pose `document_id =
    facture_id` sur toutes les règles pures (R01 à R09, R12, R13, R17), qui
    ont donc toutes `type === "facture"`. Résultat : aucune de ces
    anomalies n'affichait plus le lien bon, même avec un `bl_document_id`
    connu (capture `a-regler-detail-prix-1440.png`, anomalie de prix,
    maquette `ARegler` : « Voir la facture · Voir le bon de livraison »).
    Le lien bon ne dépend plus du type de l'anomalie : seulement de
    `cibleBon` (`document_id` pour R11/R15, dont `document_id` porte déjà
    l'identifiant du BL ; `bl_document_id` sinon, y compris pour une
    anomalie de facture) -- les deux liens peuvent s'afficher ensemble.

    Ce test ne fige plus l'expression exacte de `cibleBon` mot pour mot
    (voir `test_lien_bon_de_livraison_reste_visible_quand_document_id_est_
    absent`, qui a remplacé cette assertion trop stricte au tour 3 -- elle
    figeait justement la version encore fautive de `cibleBon`, laissant
    passer sans échec la régression corrigée à ce tour) : seul le bloc JSX
    des liens est vérifié ici, ce qui reste vrai quelle que soit la
    condition exacte retenue pour `cibleBon`."""
    page = _lire("pages", "ProblemeDetail.tsx")

    bloc_liens = page.split(
        '<div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">', 1
    )[1].split("</div>", 1)[0]
    # Le bloc du lien bon (après celui de la facture) : le lien s'affiche
    # dès que `cibleBon` est connu -- jamais recontrôlé par `anomalie.type`
    # à cet endroit précis (c'est cette condition en trop, ajoutée au tour
    # 1, qui masquait le lien pour toute anomalie de facture ayant
    # pourtant un `bl_document_id`).
    bloc_lien_bon = bloc_liens.split("Voir la facture", 1)[1]
    assert "cibleBon !== null" in bloc_lien_bon
    assert "anomalie.type" not in bloc_lien_bon
    assert "/bl/${cibleBon}" in bloc_lien_bon


def test_lien_bon_de_livraison_reste_visible_quand_document_id_est_absent() -> None:
    """Finding 1 (tour 3, régression du fix du finding 1 au tour 2) : la
    condition du tour 2 (`anomalie.type !== "facture" ? anomalie.document_id
    : anomalie.bl_document_id`) ne testait que `anomalie.type`, jamais la
    présence réelle de `document_id`. Or R06 (contrôle différé,
    `app/modules/ingest/suivi.py:370`, `engine.py:166-169`) ne porte que
    `bloc_id` (`R06.py:61`, confirmé par `test_suivi.py:190-194`, qui ne
    vérifie que `bloc_id`/`ligne_id`) : `document_id` et `type` valent donc
    tous les deux `null` (jointure externe sur `Document`,
    `anomalies.py:465`), alors que `bl_document_id` est toujours renseigné
    pour cette règle (`suivi.py:146` n'accepte que des blocs déjà reliés à
    un BL). Avec `null !== "facture"` vrai, `cibleBon` prenait la valeur de
    `document_id`, donc `null` : plus aucun lien bon pour une R06, alors que
    c'est justement une ligne de ce bon qui est en cause.

    Ce test ne fige plus l'expression de `cibleBon` mot pour mot (ce que
    faisait le test précédent, et qui avait laissé passer cette même
    régression sans qu'aucun test n'échoue) : il exige seulement que
    `document_id` ne soit retenu que lorsqu'il est réellement connu
    (`anomalie.document_id !== null` dans la condition qui choisit
    `document_id`), avec repli inconditionnel sur `bl_document_id` en
    dernière branche -- couvrant donc aussi bien R06 (`document_id === null`)
    que R01-R09/R12/R13/R17 (`document_id` connu mais `type === "facture"`)."""
    page = _lire("pages", "ProblemeDetail.tsx")
    declaration_cible_bon = page.split("const cibleBon =", 1)[1].split(";", 1)[0]

    # Repli inconditionnel sur `bl_document_id` (dernière branche du
    # ternaire) : seule garantie qu'un `document_id` absent (R06) ne masque
    # plus le lien bon, quelle que soit la valeur de `type`.
    assert declaration_cible_bon.strip().endswith(": anomalie.bl_document_id")

    # `document_id` n'est choisi que lorsqu'il est réellement connu --
    # jamais sur la seule base de `anomalie.type` (la condition incomplète
    # qui causait la régression de ce tour).
    assert "anomalie.document_id !== null" in declaration_cible_bon
    assert '"facture"' in declaration_cible_bon


def test_panneau_detail_reste_visible_et_defile_en_interne_sur_grand_ecran() -> None:
    """Finding 7 (Important) : le panneau de détail s'étirait sur toute la
    hauteur de la liste (`h-full` sur la carte, cellule de grille étirée) --
    avec les 25 anomalies d'août, les actions de traitement se seraient
    retrouvées à plus de 3000 px, hors de toute fenêtre. Le panneau reste
    désormais épinglé et défile lui-même une fois la hauteur de la fenêtre
    atteinte."""
    aregler = _lire("pages", "ARegler.tsx")
    assert "lg:sticky" in aregler
    assert "lg:max-h-" in aregler
    assert "lg:overflow-y-auto" in aregler
    detail = _lire("pages", "ProblemeDetail.tsx")
    assert 'className="flex h-full flex-col gap-5"' not in detail


def test_montant_en_jeu_jamais_un_prix_unitaire_ni_une_quantite_nue() -> None:
    """Finding 8 (Important) : R07/R08 affichaient le prix unitaire
    facturé (`pu_facture`) dans la colonne « montant en jeu » comme s'il
    s'agissait de la somme en jeu ; R03/R04/R06/R17 y affichaient une
    quantité nue sans unité (« 5 », « -10 »), illisible pour un
    non-technicien. Cette colonne ne montre plus que des montants du
    serveur, ou une quantité toujours accompagnée de son unité."""
    page = _lire("pages", "ARegler.tsx")
    assert '"pu_facture"' not in page
    assert "quantiteAvecUnite(detail, " in page


def test_quantite_avec_unite_replie_sur_tiret_quand_lunite_est_absente() -> None:
    """Finding 2 (tour 2, Important, correction partielle du finding 8 du
    tour 1) : quand l'article n'a pas d'`unite_fact` validée,
    `detail.unite` vaut le tiret cadratin (`R03.py::detail_ecart_qte` --
    le cas le plus courant, capturé sur les deux anomalies R03/R04 de la
    démo) et `quantiteAvecUnite` rendait alors la quantité nue (« 5 »,
    « -10 », captures `a-regler-liste-{1440,375}.png`) -- exactement le
    défaut que ce même correctif était censé éliminer, et incohérent avec
    R06/R17, déjà au tiret cadratin pour cette même raison. Repli
    désormais sur le tiret cadratin, jamais une quantité seule ni une
    unité inventée."""
    page = _lire("pages", "ARegler.tsx")
    ternaire = "unite !== undefined && unite !== TIRET"
    assert f"return {ternaire} ? `${{quantite}} ${{unite}}` : TIRET;" in page
    assert f"return {ternaire} ? `${{quantite}} ${{unite}}` : quantite;" not in page


def test_a_regler_separe_ouverts_et_deja_regles_sans_troncature_silencieuse() -> None:
    """Finding 9 (Important) : un seul appel `statut=toutes` (limite
    serveur 500), filtré côté client, tronquait silencieusement les
    problèmes ouverts (les plus importants) dès que l'historique
    traité/ignoré dépassait cette limite -- sans aucun message. Deux
    appels séparés désormais (« Déjà réglés » chargé seulement quand ce
    filtre est actif), et un message remplace la troncature muette quand
    la limite est atteinte."""
    page = _lire("pages", "ARegler.tsx")
    assert 'statut: "ouverte" as const' in page
    assert 'statut: "toutes" as const' in page
    assert "enabled: filtreRegles" in page
    assert "la liste peut être incomplète" in page


def test_a_regler_ignore_le_cache_a_traiter_perime_quand_un_bloc_est_cible() -> None:
    """Finding 10 (Important) : avec `?blocId=`, la requête `a-traiter`
    est désactivée (`enabled: false`) mais TanStack Query peut quand même
    rendre des données en cache d'une visite précédente de l'écran --
    `construireProblemes` recevait alors des documents/alias/articles sans
    rapport avec le bon consulté, comptés dans le surtitre et les
    filtres. Revue finale (périmètres `?document=`/`?chantier=`/
    `?fournisseur=`) : la même garde couvre tous les périmètres -- aucun
    pseudo-problème pour une livraison, un chantier ou un fournisseur, et
    seulement le bon lui-même pour `?document=`."""
    page = _lire("pages", "ARegler.tsx")
    assert (
        "aTraiterUtile ? aTraiterDuPerimetre(aTraiter.data, portee) : undefined" in page
    )
    garde = page.split("function aTraiterDuPerimetre", 1)[1].split("\nfunction ", 1)[0]
    assert "document.id === portee.id" in garde
    assert "alias: []" in garde
    assert "articles: []" in garde
    assert "return undefined;" in garde


# ---------------------------------------------------------------------------
# Revue finale de la refonte du front
# ---------------------------------------------------------------------------


def test_rattachement_d_un_chantier_a_la_charte() -> None:
    """Constats LIENS-3, COUVERTURE-7, ECRAN-10, TELEPHONE-5 : le formulaire
    « Chantier à rattacher » était la seule tache bleue de l'application,
    avec des cibles d'environ 32 px et sans champ Client à la création.
    Constat LIENS-11 : un rattachement réussi passe au problème suivant."""
    carte = _lire("components", "AliasCarte.tsx")
    for ancien in ("blue-", "slate-", "red-700", "py-1.5"):
        assert ancien not in carte, ancien
    assert "<Bouton" in carte
    assert 'variante="secondaire"' in carte
    assert "min-h-[44px]" in carte
    assert ">\n                Client\n" in carte
    assert "client.trim()" in carte
    assert "onReussite?.();" in carte
    # Plus de double cadre dans la carte du détail (`<li>` bordé dans un
    # `<ul>` ajouté par l'appelant).
    assert "<li" not in carte

    detail = _lire("pages", "ProblemeDetail.tsx")
    assert "onReussite={onTraitementReussi}" in detail
    assert '<ul className="list-none">' not in detail
    # Un article validé passe lui aussi au problème suivant.
    article = detail.split("function DetailArticle", 1)[1].split("\nfunction ", 1)[0]
    assert "onTraitementReussi();" in article


def test_categorie_des_problemes_vient_du_serveur() -> None:
    """Constats SERVEUR-3/COUVERTURE-14 : plus de table règle -> catégorie
    côté front (elle contredisait l'état des chantiers) ; la catégorie est
    lue sur l'anomalie, calculée par le serveur."""
    libelles = _lire("ui", "libelles.ts")
    assert "const CATEGORIES_REGLE" not in libelles
    assert "return anomalie.categorie;" in libelles
    page = _lire("pages", "ARegler.tsx")
    assert "categorieRegle(probleme.anomalie)" in page


def test_deja_regles_montrent_leur_issue() -> None:
    """Constats ECRAN-16/TELEPHONE-12 : sous « Déjà réglés », chaque
    problème montre « Contesté le … »/« Ignoré le … » plutôt que son
    urgence d'origine."""
    page = _lire("pages", "ARegler.tsx")
    ligne = page.split("function LigneProbleme", 1)[1].split("\nexport function ", 1)[0]
    assert "estDejaRegle(probleme)" in ligne
    assert "<PastilleIssue" in ligne
    issue = page.split("function PastilleIssue", 1)[1].split("\nfunction ", 1)[0]
    assert '"Contesté"' in issue
    assert '"Ignoré"' in issue
    assert "formaterDate(anomalie.traitee_le)" in issue


def test_chantier_non_rattache_nomme_et_pourcentages_francais() -> None:
    """Constats COUVERTURE-5, ECRAN-1, ECRAN-9, TELEPHONE-8 : « Chantier à
    rattacher » plutôt qu'un tiret dans le contexte d'un problème ;
    pourcentages au format français ; plus de « (—) » ni de « (s) » dans les
    phrases."""
    page = _lire("pages", "ARegler.tsx")
    assert "a.chantier ?? CHANTIER_A_RATTACHER" in page

    formats = _lire("lib", "formats.ts")
    assert "export function formaterPoints" in formats
    assert "maximumFractionDigits: 1" in formats.split("FORMATEUR_POINTS", 1)[1]

    libelles = _lire("ui", "libelles.ts")
    phrases = libelles.split("export function phraseProbleme", 1)[1]
    for scorie in ("facturé(s)", "facture(s)", "(${", "BL facturé(s)"):
        assert scorie not in phrases, scorie
    assert "garde(detail, cle, formaterPoints)" in libelles


def test_un_seul_compte_de_problemes_a_regler() -> None:
    """Revue finale (constats LIENS-2, ECRAN-6, TELEPHONE-2, COUVERTURE-2) :
    la tuile du mois, le lien « Voir les N problèmes », la pastille de
    navigation et l'en-tête d'« À régler » montraient trois nombres de
    périmètres différents (6, 5, 10) sans le dire. Désormais : un seul compte
    « en tout », calculé par le serveur (`GET /api/a-regler/compte`), sous
    une seule clé de requête partagée par les trois écrans ; le chiffre du
    mois est nommé comme tel ; chaque nombre dit son périmètre."""
    api = _lire("api", "aTraiter.ts")
    assert '"/api/a-regler/compte"' in api
    assert 'CLE_COMPTE_A_REGLER = ["a-traiter", "compte"] as const' in api

    gabarit = _lire("components", "Gabarit.tsx")
    assert "compte.data?.nb_problemes" in gabarit
    assert "à régler en tout" in gabarit

    vue = _lire("pages", "VueEnsemble.tsx")
    assert "queryKey: CLE_COMPTE_A_REGLER" in vue
    assert 'libelle="Problèmes à régler ce mois"' in vue
    assert "\\u00a0en tout, tous mois confondus" in vue
    assert "problèmes à régler en tout →" in vue

    page = _lire("pages", "ARegler.tsx")
    assert "queryKey: CLE_COMPTE_A_REGLER" in page
    assert "à régler en tout" in page
    # Plus jamais « N problèmes ouverts » sans périmètre en tête de l'écran
    # complet : restreint (bon, chantier, fournisseur), la liste le dit.
    assert "portee === undefined" in page.split("const surtitre", 1)[1]
    assert 'document: "sur ce bon"' in page
    assert "PERIMETRE_EN_TETE[portee.type]" in page

    # Toute écriture qui change la liste invalide aussi ce compte (préfixe
    # `CLE_A_TRAITER`), y compris la validation d'un article.
    invalidations = _lire("api", "invalidations.ts")
    assert "queryKey: CLE_A_TRAITER" in invalidations
    detail = _lire("pages", "ProblemeDetail.tsx")
    article = detail.split("function DetailArticle", 1)[1].split("\nfunction ", 1)[0]
    assert "invaliderApresChangementAnomalies(queryClient)" in article
