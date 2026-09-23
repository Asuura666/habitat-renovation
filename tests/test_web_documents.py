"""Contrats front de la Task 8 (refonte front) : page BL (`PageBl.tsx`),
liste unifiée « Documents » (`DocumentsListe.tsx`), routage (`App.tsx`) et
habillage de `DocumentDetail.tsx`/`FactureDetail.tsx`. Chaînes exactes
listées dans `.superpowers/sdd/2026-09-23-refonte-front/task-8-brief.md`."""

from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).parents[1]
WEB = RACINE / "web" / "src"


def test_client_documents_expose_comparaison_et_telechargement() -> None:
    client = (WEB / "api" / "documents.ts").read_text()

    assert "export function obtenirComparaisonBl" in client
    assert "/comparaison" in client
    assert "export function urlTelechargement" in client
    assert "telechargement=true" in client
    assert 'components["schemas"]["ComparaisonBlReponse"]' in client
    assert 'components["schemas"]["LigneCompareeReponse"]' in client


def test_page_bl_contrat() -> None:
    page = (WEB / "pages" / "PageBl.tsx").read_text()

    for chaine in (
        "Télécharger la photo",
        "download",
        "urlTelechargement",
        "Ouvrir en grand",
        "Livré et facturé",
        "Corriger la lecture du bon",
        "Quantités vérifiées par l'équipe",
        "obtenirComparaisonBl",
        "Prix unit.",
        "Contrôle",
        "md:hidden",
        "FilAriane",
    ):
        assert chaine in page, chaine

    assert "alt={`Photo du bon de livraison" in page

    # Sans jargon visible (spec §5) : aucun code de règle brut, aucun des
    # mots interdits dans les chaînes affichées. Mots entiers seulement
    # (`\b`) : « bloc » ne doit pas confondre `md:block` (classe Tailwind).
    for jargon in ("bloc", "alias", "rapprochement", "OCR", "anomalie"):
        assert re.search(rf"\b{jargon}\b", page) is None, jargon
    for n in range(1, 18):
        assert f"R{n:02d}" not in page, f"R{n:02d}"


def test_page_bl_reserve_la_comparaison_et_la_correction_a_ladmin() -> None:
    """Agent : image, téléchargement, statut de confirmation, pas de
    comparaison (brief) — la carte « Livré et facturé » n'est montée que
    lorsque `estAdmin` (et le document est un BL, la comparaison n'existant
    pas pour un enlèvement — `ingest/comparaison_bl.py`) ; la section de
    correction n'est montée que lorsque le document est `modifiable`
    (calculé côté serveur : admin et non archivé)."""
    page = (WEB / "pages" / "PageBl.tsx").read_text()

    assert "estAdmin && estBl && (" in page
    assert "donnees.modifiable && <SectionCorrection" in page
    assert "enabled: id !== undefined && estAdmin && estBl" in page


def test_page_bl_verdict_conforme_fonde_sur_le_serveur() -> None:
    """Constat de revue (tour de correction 1) : la page décidait elle-même
    du verdict « Conforme » (une ligne sans règle ouverte le devenait, la
    pastille l'affichait dès que la comparaison était chargée) — un bon
    jamais facturé (`facture_id` nul) s'affichait ainsi « Conforme » à tort,
    et `nbProblemes` était une somme calculée côté front à partir de
    données partielles (elle ne comptait ni R05 sur une ligne de facture
    jamais appariée, ni les anomalies portées par le bloc ou par le bon
    lui-même). `nb_problemes` (serveur, `ComparaisonBlReponse`) fonde
    désormais et le nombre affiché et l'éligibilité au verdict « Conforme »,
    jamais une somme de `regles_ouvertes` recalculée ici."""
    page = (WEB / "pages" / "PageBl.tsx").read_text()

    assert "comparaison.data?.nb_problemes ?? 0" in page
    assert "lignes.reduce" not in page
    assert "Pas encore facturé" in page
    assert "factureConnue" in page


def test_page_bl_invalide_la_comparaison_apres_une_correction() -> None:
    """Constat de revue (tour de correction 1) : la carte « Livré et
    facturé » restait périmée après une correction faite dans la section du
    bas (même page) — `surEcriture`, dans `DocumentDetail.tsx` (logique non
    touchée), ne sait rien de la clé de requête `cleComparaisonBl`, propre à
    `PageBl`."""
    page = (WEB / "pages" / "PageBl.tsx").read_text()

    assert "document.dataUpdatedAt" in page
    assert "queryClient.invalidateQueries({ queryKey: cleComparaisonBl(id) })" in page


def test_page_bl_reintroduit_les_champs_perdus_par_la_fusion() -> None:
    """Constat de revue (tour de correction 1) : le badge « Photo
    compressée » (CDC : « une photo compressée par Telegram est acceptée
    mais marquée comme telle »), le numéro interne (cité dans chaque
    message Telegram) et un document archivé consulté par un admin (plus
    aucun champ ni ligne visibles, faute d'être monté du tout) avaient
    disparu de l'ancien en-tête de `DocumentDetail.tsx` sans être repris
    ici."""
    page = (WEB / "pages" / "PageBl.tsx").read_text()

    assert "donnees.photo_compressee === true" in page
    assert "Photo compressée" in page
    assert "Document n° {donnees.numero_interne}" in page
    assert (
        '!donnees.modifiable && estAdmin && <SectionCorrection titre="Lecture du bon"'
        in page
    )


def test_documents_liste_contrat() -> None:
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    for chaine in (
        "Tous",
        "Factures",
        "Bons de livraison",
        "À corriger",
        "Déposer une facture",
        "md:hidden",
        "Filtres",
        "EnTetePage",
    ):
        assert chaine in page, chaine


def test_documents_liste_reserve_le_depot_et_les_factures_a_ladmin() -> None:
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    assert "if (!estAdmin) {" in page
    assert "return <VueAgent" in page
    assert "enabled: estAdmin" in page


def test_documents_liste_reintroduit_les_champs_perdus_par_la_fusion() -> None:
    """Constat de revue (tour de correction 1) : le badge « Photo
    compressée », le numéro interne (des bons dont le numéro n'a pas été lu
    deviennent sinon des « Livraison non détecté » indistinguables), la
    confirmation des quantités et le déposant avaient disparu de la liste
    unifiée par rapport à l'ancien `BlDeposes.tsx` ; la date de facture, le
    Total HT, le badge « Confiance réduite » et un libellé de statut adapté
    (jamais « Reçu ») avaient disparu par rapport à l'ancien
    `FacturesListe.tsx`."""
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    assert "numeroInterne" in page
    assert "Document n° {ligne.numeroInterne}" in page
    assert "deposant: document.deposant" in page
    # Tour de correction 2 : la colonne « Déposant » du tableau a été
    # repliée sous le numéro (comme « Document n° … », constat de revue
    # sur la largeur du tableau) — le déposant reste affiché, plus jamais
    # dans une colonne à part.
    assert "Déposé par {ligne.deposant}" in page
    assert "confirmation: document.confirmation" in page
    assert "BadgeConfirmation" in page
    assert "totalHt: facture.total_ht" in page
    assert "confianceReduite: facture.confiance_reduite" in page
    assert "BadgeConfianceReduite" in page

    # « Reçu » ne veut rien dire pour une facture (constat de revue) : la
    # pastille de statut renvoie un tiret pour une facture qui n'est pas
    # « à vérifier », jamais « Reçu ».
    fonction_pastille = page.split("function PastilleStatut", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert 'ligne.origine === "facture"' in fonction_pastille
    assert "TIRET" in fonction_pastille


def test_documents_liste_tableau_tient_a_1280_pixels() -> None:
    """Constat de revue (tour de correction 2) : l'ajout des colonnes
    Déposant/Montant au tour précédent avait fait passer le tableau de
    `min-w-[880px]` à `min-w-[1080px]` — à 1280 px (cible ordinateur
    explicite), la zone de contenu (~968 px, sidebar + `md:px-10` déduits)
    masquait presque entièrement la colonne Statut. Corrigé en repliant
    Déposant sous le numéro (voir le test ci-dessus) et en ne montrant
    Montant qu'à partir de 1440 px (`min-[1440px]:table-cell`, sous les 968
    px disponibles à 1280 mais au-dessus des ~1128 px disponibles à 1440) —
    revenant ainsi au `min-w-[880px]` d'avant l'ajout de ces deux colonnes.
    Largeur et absence de débordement vérifiées par mesure DOM réelle
    (capture Puppeteer à 1280, hors suite automatisée — voir le compte
    rendu de correction).

    Constat de revue (tour de correction 3) : masquer la colonne dédiée
    sous 1440 px avait fait disparaître le Total HT d'une facture sur toute
    cette plage (768-1439 px, portables compris), une régression par
    rapport à l'ancien `FacturesListe.tsx` qui l'affichait à toute largeur.
    Le montant est donc désormais aussi rendu dans la cellule du numéro
    (toujours présente, comme « Déposé par »), sans aucune classe liée à
    une largeur d'écran — la colonne dédiée (ci-dessus) peut rester
    masquée sous 1440 px, le montant restant visible ailleurs."""
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    assert "min-w-[880px]" in page
    assert "min-w-[1080px]" not in page
    entete_montant = page.split(">Montant</th>", 1)[0].rsplit("<th", 1)[1]
    assert "hidden" in entete_montant
    assert "min-[1440px]:table-cell" in entete_montant
    assert '<th scope="col" className="px-4 py-3">Déposant</th>' not in page

    fonction_ligne_tableau = page.split("function LigneTableau", 1)[1].split(
        "\nfunction ", 1
    )[0]
    cellule_numero = fonction_ligne_tableau.split("<td", 2)[1]
    assert "Total HT : {formaterMontant(ligne.totalHt)}" in cellule_numero
    assert "hidden" not in cellule_numero
    assert "min-[1440px]" not in cellule_numero


def test_documents_liste_filtre_chantier_par_identifiant() -> None:
    """Constat de revue (tour de correction 1) : le filtre `?chantier=`
    comparait `chantier_brut` (texte OCR non normalisé) par préfixe au nom
    canonique — des documents manquaient (rattachés par un alias, ou dont
    le texte ne commence pas par le nom canonique) ou apparaissaient en
    trop (un nom qui en préfixe un autre). `chantier_id`, ajouté à
    `DocumentReponse` (petit ajout serveur), permet désormais une
    comparaison par égalité stricte d'identifiant."""
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    assert "chantierId: document.chantier_id" in page
    assert "ligne.chantierId !== chantierCible.id" in page
    assert "startsWith" not in page
    assert 'id="documents-chantier"' in page


def test_documents_liste_filtre_fournisseur_accessible() -> None:
    """Spec §4 : filtre fournisseur, absent avant ce tour — sélecteur
    accessible (`<select>` + `<label>` associé, cible ≥ 44 px)."""
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    assert 'id="documents-fournisseur"' in page
    assert 'htmlFor="documents-fournisseur"' in page
    assert "min-h-[44px]" in page
    assert "listerFournisseurs" in page
    assert "ligne.fournisseur !== fournisseurCible.nom" in page


def test_documents_liste_filtre_mois_convertit_en_heure_de_paris() -> None:
    """Constat de revue (tour de correction 1) : le filtre `?mois=`
    comparait `cree_le` (UTC) par `startsWith`, faisant apparaître un dépôt
    entre minuit et 2 h (heure de Paris) le 1er du mois dans le mois
    précédent, et manquant les factures dont `date_doc` diffère du mois de
    dépôt. `moisLigne` retient `date_doc` (une facture) avec repli sur
    `cree_le` converti en heure de Paris (`moisParis`, `lib/formats.ts`),
    même convention que le mois d'une facture pour le bilan (L5-D4)."""
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    assert "moisLigne(ligne) !== mois" in page
    assert "moisParis(ligne.creeLe)" in page
    assert "ligne.dateDoc.slice(0, 7)" in page

    formats = (WEB / "lib" / "formats.ts").read_text()
    assert "export function moisParis" in formats


def test_documents_liste_filtre_mois_couvre_aussi_un_bl() -> None:
    """Constat de revue (tour de correction 2) : `depuisDocument` posait
    `dateDoc: null` pour tout BL/enlèvement, faisant retomber `moisLigne`
    sur `cree_le` (date de dépôt) plutôt que sur la date de livraison —
    un BL déposé un mois mais livré (et lu) un autre mois n'apparaissait
    jamais dans le filtre `?mois=` de son mois de livraison réel.
    `DocumentReponse.date_doc` (ajouté côté serveur à ce tour, voir
    `ingest/lecture.py::DocumentResume`) est désormais lu ici, comme pour
    une facture."""
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    assert "dateDoc: document.date_doc," in page
    assert "dateDoc: null" not in page


def test_documents_liste_affiche_la_date_de_livraison_dun_bl() -> None:
    """Constat de revue (tour de correction 3) : le filtre `?mois=` classe
    un BL sur `date_doc` (sa date de livraison, tour de correction 2), mais
    cette date n'apparaissait nulle part dans la ligne — seule la date de
    dépôt (`creeLe`, colonne « Déposé le ») était affichée. Un BL déposé un
    mois mais livré un autre mois paraissait donc mal classé par le filtre.
    `contexteDocument` affiche désormais « Livré le … » (avec le chantier)
    dans la cellule déjà utilisée pour le contexte, en carte comme en
    tableau, dès que `date_doc` est connu."""
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    assert "function contexteDocument" in page
    assert "Livré le ${formaterDate(document.date_doc)}" in page
    assert "contexte: contexteDocument(document)," in page

    # Repli sur le seul chantier (comportement d'avant ce tour) quand
    # `date_doc` est inconnue — jamais un texte vide.
    fonction_contexte = page.split("function contexteDocument", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "document.date_doc === null" in fonction_contexte
    assert "return document.chantier_brut;" in fonction_contexte


def test_routes_documents_montent_pagebl_et_documentsliste() -> None:
    app = (WEB / "App.tsx").read_text()

    for chemin, composant in (
        ('path="documents"', "DocumentsListe"),
        ('path="documents/:id"', "PageBl"),
        ('path="bl/:id"', "PageBl"),
    ):
        assert chemin in app
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert f"<{composant}" in declaration, chemin
        assert "GardeAdmin" not in declaration, chemin


def test_anciennes_routes_factures_redirigent_vers_documents() -> None:
    """Reprise complète (brief Task 8) : `DocumentsListe` couvre le dépôt et
    la liste des factures, `/documents/:id` sait afficher une facture — les
    deux anciennes routes deviennent de vraies redirections, plus des
    écrans transitoires (contrairement à `/anomalies`, toujours sans
    remplaçant)."""
    app = (WEB / "App.tsx").read_text()

    for chemin in ('path="factures"', 'path="factures/:id"'):
        assert chemin in app
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert "RedirectionAncienneUrl" in declaration, chemin
        assert "FacturesListe" not in declaration, chemin
        assert "FactureDetail" not in declaration, chemin

    declaration = app.split('path="factures/:id"', 1)[1].split("path=", 1)[0]
    assert "/documents/${p.id" in declaration


def test_anciens_fichiers_supprimes_apres_reprise() -> None:
    for nom in ("BlDeposes.tsx", "FacturesListe.tsx"):
        assert not (WEB / "pages" / nom).exists(), nom

    app = (WEB / "App.tsx").read_text()
    assert "BlDeposes" not in app
    assert "FacturesListe" not in app


def test_facture_detail_habille_en_livraisons_et_garde_lancre_de_bloc() -> None:
    """Détail facture (`/documents/:id` quand le type est une facture,
    brief) : les blocs sont présentés comme des « livraisons » — jamais un
    « bloc » dans le texte affiché — et l'ancre `id={`bloc-${bloc.id}`}`,
    ciblée depuis d'autres écrans (`BilanFournisseur.tsx`, ancre `#bloc-`),
    reste inchangée malgré l'habillage."""
    page = (WEB / "pages" / "FactureDetail.tsx").read_text()

    assert "Livraisons (" in page
    assert "id={`bloc-${bloc.id}`}" in page
    assert "Blocs BL" not in page
    assert "OCR" not in page
    assert "FilAriane" in page

    # Tour de correction 1 : le reste du jargon interdit (spec §5), hors
    # « bloc » — un identifiant de variable/type légitime ici
    # (`bloc`/`BlocFacture`, requis par l'ancre ci-dessus), impossible à
    # vérifier par une recherche de mot entier sur tout le fichier sans
    # faux positifs (voir `test_document_detail_sans_jargon_visible`
    # ci-dessous pour ce type de recherche, sur un fichier qui n'a pas ce
    # problème).
    for jargon in ("alias", "rapprochement", "anomalie"):
        assert re.search(rf"\b{jargon}\b", page) is None, jargon


def test_document_detail_sans_jargon_visible() -> None:
    """Tour de correction 1 (constat de revue) : `DocumentDetail.tsx`
    (section « Corriger la lecture du bon », montée par `PageBl`) contenait
    encore « OCR » et « anomalies » dans des chaînes affichées (« Valeur
    OCR : … », « … nouvelle lecture OCR. », « … des anomalies
    subsistent. ») — le test de jargon de `test_page_bl_contrat` ne
    contrôlait que `PageBl.tsx`, jamais ce fichier."""
    page = (WEB / "pages" / "DocumentDetail.tsx").read_text()

    # Pas de recherche de code de règle brut (`R01`…`R17`) ici, contrairement
    # à `test_page_bl_contrat` : ce fichier ne rend jamais `regles_ouvertes`
    # (seulement `motifs`/`libelleMotif`) mais porte, dans un commentaire
    # préexistant sans rapport, une référence de décision interne au motif
    # identique (« Ruling L5-R11 ») — un faux positif pour cette recherche,
    # pas pour les cinq mots de jargon ci-dessous.
    for jargon in ("bloc", "alias", "rapprochement", "OCR", "anomalie"):
        assert re.search(rf"\b{jargon}\b", page) is None, jargon


def test_documents_liste_sans_jargon_visible() -> None:
    """Tour de correction 1 : même contrôle que `test_document_detail_sans
    _jargon_visible`, pour la liste unifiée « Documents »."""
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    for jargon in ("bloc", "alias", "rapprochement", "OCR", "anomalie"):
        assert re.search(rf"\b{jargon}\b", page) is None, jargon


def test_motifs_sans_jargon_visible() -> None:
    """Tour de correction 2 (constat de revue) : `lib/motifs.ts` (rendu par
    la section de correction de `DocumentDetail.tsx` et par
    `FactureDetail.tsx`) affichait encore « Échec de la lecture OCR »
    (`libelleMotif`, code `ocr_echec`) — les tests de jargon des pages ne
    lisent que le fichier de page, jamais ce libellé partagé qu'elles
    rendent. Le code API `"ocr_echec"` (minuscule, jamais affiché) reste
    légitime : la recherche est sensible à la casse, comme pour `bloc`/
    `BlocFacture` dans `test_facture_detail_habille_en_livraisons_et_garde_
    lancre_de_bloc`."""
    fichier = (WEB / "lib" / "motifs.ts").read_text()

    for jargon in ("bloc", "alias", "rapprochement", "OCR", "anomalie"):
        assert re.search(rf"\b{jargon}\b", fichier) is None, jargon


def test_document_detail_reste_la_correction_montee_par_pagebl() -> None:
    """La logique de correction existante (formulaire, ré-extraction,
    validation, archivage) est conservée intégralement — seulement habillée
    et amputée de son ancien en-tête de page (photo, titre, badge, ligne de
    confirmation, tous désormais affichés par `PageBl`)."""
    page = (WEB / "pages" / "DocumentDetail.tsx").read_text()

    for fonction in (
        "FormulaireEntete",
        "TableauLignesEdition",
        "corrigerEntete",
        "corrigerLignes",
        "validerDocument",
        "archiverDocument",
        "relancerExtraction",
    ):
        assert fonction in page, fonction

    # Plus d'en-tête de page dupliqué : ni photo, ni titre, ni statut/
    # confirmation redondants avec `PageBl` (le composant local `Photo` et
    # les libellés de statut du document ont été retirés à la Task 8).
    assert "function Photo(" not in page
    assert "<h1" not in page

    for jargon in (
        "bg-slate-",
        "text-slate-",
        "bg-blue-",
        "bg-orange-",
        "bg-red-",
        "bg-green-",
    ):
        assert jargon not in page, jargon
