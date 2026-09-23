from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).parents[1]
WEB = RACINE / "web" / "src"


def _lire(*segments: str) -> str:
    chemin = WEB
    for segment in segments:
        chemin = chemin / segment
    return chemin.read_text(encoding="utf-8")


def test_client_referentiels_expose_modifier_chantier_en_put() -> None:
    client = _lire("api", "referentiels.ts")

    assert "modifierChantier" in client
    assert '"PUT"' in client
    assert "/api/chantiers/{chantier_id}" in client
    # `client` transmis à la création (Task 1), pas seulement à la
    # modification.
    signature_creation = client.split("export async function creerChantier", 1)[
        1
    ].split("export interface ModificationChantier", 1)[0]
    assert "client: string | null" in signature_creation
    assert "agence, client }" in signature_creation


def test_ecran_liste_chantiers_a_la_creation_et_au_bandeau_silencieux() -> None:
    page = _lire("pages", "ChantiersListe.tsx")

    assert "Nouveau chantier" in page
    # Revue finale (constat COUVERTURE-20) : le délai du bandeau est un
    # réglage, lu sur `GET /api/parametres` -- plus « 7 jours » écrit en dur.
    assert "`Chantiers sans bon déposé depuis ${delaiJours} jours`" in page
    assert '"delai_chantier_silencieux_j"' in page
    assert "Chantiers sans bon déposé depuis 7 jours" not in page
    assert "obtenirChantiersSansDepot" in page
    assert "useSearchParams" in page
    assert 'type="month"' in page
    assert "obtenirAgences" in page
    assert "md:hidden" in page
    assert "md:block" in page
    assert "Exporter pour Excel" in page
    assert "Exporter le détail pour Excel" in page
    assert "urlExportBilanDetail" in page
    assert "Aucun chantier pour ces filtres." in page
    # Dépôts par agent (CDC §4 « Chantiers & fournisseurs ») : repris ici,
    # faute d'un autre écran de la refonte qui les affiche (Task 7).
    assert "obtenirDepotsParAgent" in page


def test_fiche_chantier_couvre_le_contrat() -> None:
    page = _lire("pages", "FicheChantier.tsx")

    assert "Client :" in page
    assert "Modifier" in page
    assert "Livraisons" in page
    assert "Problèmes ouverts" in page
    assert "FilAriane" in page
    assert "md:hidden" in page
    assert "`/bl/${" in page
    assert "/documents/${" in page
    assert "modifierChantier" in page
    assert "Voir les documents du chantier" in page
    assert "Exporter pour Excel" in page
    assert "?chantier=" in page
    # Aucun calcul métier : ni sur les montants du bilan, ni de somme
    # « conforme » inventée côté front (donnée absente de l'API par
    # chantier — voir docs/dette.md).
    assert "parseFloat" not in page
    assert "Conforme = " not in page


def test_fiche_chantier_est_montee_et_les_anciennes_routes_redirigent() -> None:
    app = _lire("App.tsx")

    assert 'path="chantiers"' in app
    declaration_liste = app.split('path="chantiers"', 1)[1].split("path=", 1)[0]
    assert "<ChantiersListe" in declaration_liste
    assert "GardeAdmin" in declaration_liste

    assert 'path="chantiers/:chantierId"' in app
    declaration_fiche = app.split('path="chantiers/:chantierId"', 1)[1].split(
        "path=", 1
    )[0]
    assert "<FicheChantier" in declaration_fiche
    assert "GardeAdmin" in declaration_fiche

    # `chantiers/referentiel` (ex-« Chantiers & fournisseurs ») et
    # `chantiers/:chantierId/:fournisseurId` (ex-`BilanBl`) sont maintenant
    # de simples redirections (contenu repris par ChantiersListe/
    # FicheChantier), gardées pour les anciens favoris — le sous-lien
    # « Gérer les chantiers » de Gabarit.tsx, qui ne menait plus qu'à
    # « Chantiers », est retiré (revue finale, constats LIENS-7/ECRAN-17).
    assert 'path="chantiers/referentiel"' in app
    declaration_referentiel = app.split('path="chantiers/referentiel"', 1)[1].split(
        "path=", 1
    )[0]
    assert "RedirectionAncienneUrl" in declaration_referentiel
    assert '"/chantiers"' in declaration_referentiel

    assert 'path="chantiers/:chantierId/:fournisseurId"' in app
    declaration_bl = app.split('path="chantiers/:chantierId/:fournisseurId"', 1)[
        1
    ].split("path=", 1)[0]
    assert "RedirectionAncienneUrl" in declaration_bl
    assert "/chantiers/${p.chantierId" in declaration_bl

    gabarit = _lire("components", "Gabarit.tsx")
    assert 'to="/chantiers/referentiel"' not in gabarit


def test_bilan_et_chantiers_ne_sont_plus_importes() -> None:
    """`Bilan.tsx`/`Chantiers.tsx` sont supprimés une fois leur contenu repris
    (consigne Task 7) : plus aucune route ne les monte, et les fichiers
    n'existent plus."""
    app = _lire("App.tsx")

    assert 'pages/Bilan"' not in app
    assert 'from "./pages/Chantiers"' not in app
    assert not (WEB / "pages" / "Bilan.tsx").exists()
    assert not (WEB / "pages" / "Chantiers.tsx").exists()


def test_ancien_bilan_fournisseur_nest_plus_monte() -> None:
    """Après fusion des Tasks 7 et 9, plus aucune route ne monte les écrans
    de l'ancien bilan (`pages/BilanFournisseur.tsx`) : `chantiers*` passe
    par `ChantiersListe`/`FicheChantier`, `fournisseurs*` par
    `FournisseursListe`/`FicheFournisseur`."""
    app = _lire("App.tsx")

    for ancien in (
        "BilanFournisseursChantier",
        "BilanBl",
        "BilanFournisseursGlobal",
        "BilanChantiersFournisseur",
    ):
        assert f"<{ancien}" not in app, ancien
    assert 'from "./pages/BilanFournisseur"' not in app
    assert "<FicheChantier" in app
    assert "<FicheFournisseur" in app
    # Revue finale (constat LIENS-6) : le fichier mort et l'ancien module de
    # libellés (`lib/regles.ts`, ré-export pour des écrans supprimés) sont
    # supprimés, plus aucun fichier ne les importe.
    assert not (WEB / "pages" / "BilanFournisseur.tsx").exists()
    assert not (WEB / "lib" / "regles.ts").exists()
    for fichier in WEB.rglob("*.ts*"):
        contenu = fichier.read_text(encoding="utf-8")
        assert 'lib/regles"' not in contenu, fichier
        assert 'BilanFournisseur"' not in contenu, fichier


def test_referentiels_agences_et_silencieux_toujours_exposes() -> None:
    referentiels = _lire("api", "referentiels.ts")

    assert '"/api/referentiels/agences"' in referentiels
    assert "CLE_AGENCES" in referentiels
    assert '"/api/referentiels/chantiers-silencieux"' in referentiels
    assert '"/api/referentiels/depots-par-agent"' in referentiels


# ---------------------------------------------------------------------------
# Fix round 1 (revue de Task 7)
# ---------------------------------------------------------------------------


def test_liste_chantiers_expose_le_referentiel_complet() -> None:
    """Constat 1 (Important) : `GET /api/bilan/chantiers` (table financière)
    ne remonte que les chantiers ayant déjà au moins un bloc de facture — un
    chantier neuf, pas encore facturé, ou inactif, restait sans aucun lien
    vers sa fiche. Une carte alimentée par `listerChantiers` (référentiel
    complet, déjà chargé pour le formulaire de création) doit maintenant les
    lister tous, avec le statut Actif/Inactif."""
    page = _lire("pages", "ChantiersListe.tsx")

    assert "Tous les chantiers" in page
    assert "chantiers={chantiers.data}" in page
    assert 'chantier.actif ? "Actif" : "Inactif"' in page

    # Chaque nom du bandeau silencieux mène désormais à la fiche du
    # chantier (avant : du texte simple, sans lien).
    bandeau = page.split("function BandeauSilencieux", 1)[1].split(
        "function CarteTousLesChantiers", 1
    )[0]
    assert "<Link" in bandeau
    assert "lienChantier(chantier.chantier_id" in bandeau


def test_fiche_chantier_dernier_bl_reflete_une_vraie_reception() -> None:
    """Constat 2 (Important, tour 1) : « Dernier BL déposé » prenait
    `date_bl` (la date imprimée sur la facture) sur toutes les lignes, y
    compris « Jamais reçu »/« Livré sans bon », et affichait « Aucun dépôt
    enregistré » pendant le chargement. Seules les lignes où une photo de
    BL a été rattachée (`bl_document_id`) comptent désormais, le libellé ne
    prétend plus qu'il s'agit d'un dépôt, et rien ne s'affiche avant la fin
    du chargement. Libellé renommé « Dernier bon retrouvé sur une facture »
    aux corrections de revue (tour 3, constat 2) : « reçue » seule restait
    trompeur (voir test_fiche_chantier_dernier_bon_precise_ce_quil_mesure
    ci-dessous)."""
    page = _lire("pages", "FicheChantier.tsx")

    assert "Dernier BL déposé" not in page
    assert "Dernier bon retrouvé sur une facture" in page
    assert "livraison.ligne.bl_document_id !== null" in page
    assert "livraisonsRecues" in page

    entete = page.split("Dernier bon retrouvé sur une facture", 1)[1].split(
        "chantier.actif &&", 1
    )[0]
    # Fix round 2 (constat 1) : ce calcul ne porte plus sur `livraisons`
    # (filtrée par `?mois`) mais sur `livraisonsToutesChargees`, alimenté
    # par des requêtes sans filtre de mois — voir
    # test_fiche_chantier_dernier_bl_ignore_le_mois_choisi ci-dessous.
    assert "!livraisonsToutesChargees" in entete
    assert "Chargement…" in entete
    assert "Aucun bon retrouvé sur une facture" in entete
    assert "derniereLivraisonRecue" in entete


def test_fiche_chantier_dernier_bl_ignore_le_mois_choisi() -> None:
    """Constat 1 (Important, tour 2) : « Dernier bon retrouvé sur une
    facture » (alors « Dernière livraison reçue ») et l'état vide de la
    carte « Livraisons » étaient calculés sur `livraisons`, déjà filtrée
    par `?mois` — un chantier livré en août et en septembre, la liste
    filtrée sur octobre, affichait « Aucun bon retrouvé sur une facture »
    et « Aucune livraison enregistrée pour ce chantier. », une affirmation
    fausse. Ce calcul doit
    désormais venir de requêtes *sans* filtre de mois, distinctes de celles
    qui alimentent la carte « Livraisons » elle-même."""
    page = _lire("pages", "FicheChantier.tsx")

    # Requêtes dédiées, sans mois, pour la seule « Dernière livraison
    # reçue » — jamais `filtresActifs` (qui reste réservé à la carte
    # « Livraisons », aux trois `Chiffre` et aux exports).
    assert "cleBilanFournisseurs(id, FILTRES_TOUS_MOIS)" in page
    assert "listerBilanFournisseurs(id, FILTRES_TOUS_MOIS)" in page
    assert (
        "cleBilanBl(id, fournisseur.fournisseur_id as string, FILTRES_TOUS_MOIS)"
        in page
    )
    assert (
        "listerBilanBl(id, fournisseur.fournisseur_id as string, FILTRES_TOUS_MOIS)"
        in page
    )
    assert "fournisseursTous" in page
    assert "blTousParFournisseur" in page

    # Titre et état vide de la carte « Livraisons » indiquent maintenant la
    # période affichée, avec un moyen d'y échapper.
    assert "titreLivraisons" in page
    assert "messageAucuneLivraison" in page
    assert "Voir tous les mois" in page
    assert "to={`/chantiers/${id}`}" in page


def test_fiche_chantier_respecte_le_mois_choisi() -> None:
    """Constat 3 (Important) : la fiche ignorait `?mois`, y compris sur les
    anciens liens `/bilan/:c?mois=…` relayés par la redirection — chiffres
    et pastille d'état pouvaient porter sur deux périodes différentes sans
    aucun libellé. La fiche lit désormais `?mois`, le transmet à tous les
    appels et aux exports, n'affiche la pastille que si un mois est choisi,
    et `ChantiersListe` reporte le mois choisi dans ses liens vers la
    fiche."""
    page = _lire("pages", "FicheChantier.tsx")

    assert "useSearchParams" in page
    assert 'parametres.get("mois")' in page
    assert "listerBilanChantiers(filtresActifs)" in page
    assert "listerBilanFournisseurs(id, filtresActifs)" in page
    assert (
        "listerBilanBl(id, fournisseur.fournisseur_id as string, filtresActifs)" in page
    )
    assert "urlExportBilanFournisseurs(id, filtresActifs)" in page
    assert "enabled: moisChoisi" in page
    assert "etatChoisi !== undefined" in page
    assert "libelleAvecPeriode" in page
    assert "tous les mois" in page

    liste = _lire("pages", "ChantiersListe.tsx")
    assert "lienChantier(ligne.chantierId, mois)" in liste
    # Revue finale (constat LIENS-5) : mois de l'URL validé et au format
    # `AAAA-MM` partout, converti en `AAAA-MM-01` pour l'API seulement.
    assert 'lireMois(parametres.get("mois"))' in liste
    assert "mois={mois}" in liste
    assert 'lireMois(parametres.get("mois"))' in page


def test_fiche_chantier_exporte_les_livraisons_par_fournisseur() -> None:
    """Constat 4 (Important) : « Exporter pour Excel » de la fiche
    réutilisait l'export fournisseurs alors que la carte affichée est
    « Livraisons » (niveau BL). Un export CSV par fournisseur résolu, au
    même niveau que ce qui est affiché, s'ajoute désormais à l'export
    fournisseurs existant (gardé, pas retiré)."""
    page = _lire("pages", "FicheChantier.tsx")

    assert "urlExportBilanBl" in page
    assert "Exporter les livraisons" in page
    assert "Exporter pour Excel" in page
    assert (
        "urlExportBilanBl(id, fournisseur.fournisseur_id as string, filtresActifs)"
        in page
    )

    client = _lire("api", "bilan.ts")
    assert "export function urlExportBilanBl" in client


# ---------------------------------------------------------------------------
# Fix round 2 (relecture du tour 1)
# ---------------------------------------------------------------------------


def test_liste_chantiers_ne_reporte_pas_le_mois_dans_le_referentiel_complet() -> None:
    """Constat 1 (Important) — volet `ChantiersListe.tsx` : la carte « Tous
    les chantiers » n'est filtrée que par agence, jamais par mois (un
    chantier existe indépendamment de toute facturation), mais ses liens
    reportaient quand même `?mois` : un clic sur un chantier sans facture
    ce mois-ci ouvrait sa fiche filtrée sur ce mois, qui affichait alors des
    informations fausses (voir `test_fiche_chantier_dernier_bl_ignore_le_
    mois_choisi`). Ses liens ne reportent plus aucun mois."""
    page = _lire("pages", "ChantiersListe.tsx")

    carte = page.split("function CarteTousLesChantiers", 1)[1]
    assert "lienChantier(chantier.id, undefined)" in carte
    assert "lienChantier(chantier.id, mois)" not in carte
    # La signature de `CarteTousLesChantiers` n'a plus de prop `mois`.
    signature = page.split("function CarteTousLesChantiers", 1)[1].split(
        "): ReactElement", 1
    )[0]
    assert "mois" not in signature


def test_fiche_chantier_ligne_livraison_ne_navigue_pas_deux_fois() -> None:
    """Constat 2 (Important) : la `<tr>` de la carte « Livraisons » navigue
    au clic (`onClick`) et porte aussi un vrai `<Link>` sur le n° BL, dont
    le gestionnaire de clic navigue déjà sans `stopPropagation` — le clic
    remontait ensuite jusqu'à la `<tr>`, qui navigue une seconde fois (deux
    entrées d'historique identiques). Le gestionnaire de la `<tr>` doit
    désormais ignorer les clics déjà traités par un lien et les clics avec
    modificateur (Ctrl/Cmd/Maj/Alt) ou autre que le bouton gauche."""
    page = _lire("pages", "FicheChantier.tsx")

    ligne = page.split("function LigneLivraisonTableau", 1)[1].split(
        "function TableauLivraisons", 1
    )[0]
    assert "evenement.defaultPrevented" in ligne
    assert '.closest("a")' in ligne
    assert "evenement.metaKey" in ligne
    assert "evenement.ctrlKey" in ligne
    assert "onClick={gererClicLigne}" in ligne
    # Toujours un vrai <Link> accessible sur le n° BL (contrat Step 1).
    assert "<Link" in ligne


def test_fiche_chantier_exports_livraisons_en_pied_de_carte_sur_telephone() -> None:
    """Constat 3 (Important) : les liens d'export de la carte « Livraisons »
    (« Voir les documents du chantier », l'export fournisseurs et un export
    par fournisseur) étaient dans l'action de la `Carte`, à côté du titre —
    à 375 px, cette zone se partage environ 190 px avec le titre, les liens
    passent sur 4 lignes ou plus et chaque cible ne fait plus 44 px de haut.
    Ils doivent être en pied de carte (comme la maquette FicheChantier),
    empilés en pleine largeur sous `md` avec des cibles d'au moins 44 px, et
    non plus dans l'action de la `Carte` « Livraisons »."""
    page = _lire("pages", "FicheChantier.tsx")

    carte_livraisons = page.split("<Carte titre={titreLivraisons}", 1)[1].split(
        "<Carte titre={`Problèmes ouverts", 1
    )[0]
    # Plus d'`action=` sur cette carte : les liens sont dans les enfants,
    # en pied de carte.
    assert "action={" not in carte_livraisons
    # Revue finale : classes des liens isolés factorisées (`CLASSES_LIEN`,
    # cible de 44 px) plutôt que recopiées sur chaque lien.
    assert "className={CLASSES_LIEN}" in carte_livraisons
    classes_lien = page.split("const CLASSES_LIEN =", 1)[1].split(";", 1)[0]
    assert "inline-flex min-h-[44px] items-center" in classes_lien
    # « (vue fournisseurs) », peu parlant pour un non-technicien, a été
    # renommé en langage courant.
    assert "(vue fournisseurs)" not in carte_livraisons
    assert "Récapitulatif par fournisseur" in carte_livraisons


# ---------------------------------------------------------------------------
# Corrections de revue (tour 3)
# ---------------------------------------------------------------------------


def test_carte_depots_recents_affiche_le_role() -> None:
    """Constat 1 (Important) : la carte « Dépôts récents (30 jours) »
    n'affichait plus le rôle (Administrateur/Agent) disparu depuis l'ancien
    `Chantiers.tsx::SectionDepotsParAgent` — une décision du contrôleur
    (L5-T8, Ruling L5-R7) que le serveur a même renforcée en ajoutant
    `DepotAgent.role` pour cette raison précise (« un écran qui l'ignorerait
    ferait croire à un agent de plus », `ingest/referentiels_vue.py`). Le
    rôle doit réapparaître, en carte téléphone comme en tableau."""
    page = _lire("pages", "ChantiersListe.tsx")

    assert "libelleRole" in page
    assert "depot.role" in page

    carte = page.split("function CarteDepotsRecents", 1)[1]
    # Cartes téléphone (< md) : rôle affiché avec le nombre de dépôts.
    cartes_telephone = carte.split("md:hidden", 1)[1].split("md:block", 1)[0]
    assert "libelleRole(depot.role)" in cartes_telephone
    # Tableau (md+) : une colonne « Rôle » dédiée.
    tableau = carte.split("md:block", 1)[1]
    assert "Rôle" in tableau
    assert "libelleRole(depot.role)" in tableau


def test_fiche_chantier_dernier_bon_precise_ce_quil_mesure() -> None:
    """Constat 2 (Important) : « Dernière livraison reçue » restait une
    affirmation fausse en usage normal — la date ne vient que des blocs
    d'une facture déjà arrivée (une fois par mois), jamais des dépôts
    Telegram quotidiens. Un chantier avec des bons déposés ce mois-ci mais
    pas encore facturés affichait « Aucune livraison reçue », contredisant
    le bandeau « Chantiers sans bon déposé » (qui lui se base sur le vrai
    dernier dépôt). Le libellé doit dire exactement ce qui est calculé, et
    « aucun bon retrouvé » doit être distingué de « bon retrouvé, date
    inconnue » (`livraisonsRecues[0]?.dateBl ?? null` confondait les deux :
    un bon sans `date_bl` renseignée affichait le même message qu'aucun bon
    du tout)."""
    page = _lire("pages", "FicheChantier.tsx")

    assert "Dernier bon retrouvé sur une facture" in page
    assert "Aucun bon retrouvé sur une facture" in page
    assert "Aucune livraison reçue" not in page
    assert "Dernière livraison reçue" not in page

    entete = page.split("Dernier bon retrouvé sur une facture", 1)[1].split(
        "chantier.actif &&", 1
    )[0]
    # Deux `null` distincts : `derniereLivraisonRecue === null` (aucun bon
    # retrouvé) et `derniereLivraisonRecue.dateBl === null` (un bon
    # retrouvé, sans date) — jamais confondus dans un seul test sur
    # `dateBl ?? null`.
    assert "derniereLivraisonRecue === null" in entete
    assert "derniereLivraisonRecue.dateBl === null" in entete
    assert "Date inconnue" in entete

    assert "const derniereLivraisonRecue = livraisonsRecues[0] ?? null;" in page


# ---------------------------------------------------------------------------
# Corrections de revue (tour 4)
# ---------------------------------------------------------------------------


def test_cartes_telephone_chantiers_sont_entierement_cliquables() -> None:
    """Constat 1 (Important) : sur téléphone, les liens qui ouvrent la fiche
    d'un chantier (nom dans `CarteChantier`, cartes de
    `CarteTousLesChantiers`) étaient de simples liens texte sans marge
    intérieure — une zone à toucher d'environ 20 à 24 px de haut, sous les
    44 px exigés, alors que le nom est le seul moyen d'ouvrir la fiche sur
    téléphone. La relecture de la Task 9 avait déjà fait corriger exactement
    ce défaut dans FicheFournisseur.tsx (CarteChantierConcerne) : toute la
    carte devient cliquable, un vrai <Link className="block … p-4"> autour
    de la carte plutôt qu'un padding sur le seul texte."""
    page = _lire("pages", "ChantiersListe.tsx")

    carte_chantier = page.split("function CarteChantier(", 1)[1].split(
        "function TableauChantiers", 1
    )[0]
    assert "to={destinationLigne(ligne, mois)}" in carte_chantier
    assert "block rounded-carte" in carte_chantier
    assert "p-4" in carte_chantier
    # Le nom n'est plus un lien imbriqué (un <a> ne peut pas en contenir un
    # autre) : toute la carte porte désormais le lien, le nom redevient un
    # texte simple à l'intérieur.
    assert "<NomChantier" not in carte_chantier
    assert "{nomAffiche(ligne)}" in carte_chantier

    carte_referentiel = page.split("function CarteTousLesChantiers", 1)[1]
    cartes_telephone = carte_referentiel.split("md:hidden", 1)[1].split("md:block", 1)[
        0
    ]
    assert "block rounded-lg" in cartes_telephone
    assert "p-3" in cartes_telephone
    # Une seule balise <Link> dans le gabarit de carte : elle enveloppe tout
    # le contenu (nom, client/agence, statut), pas seulement le nom.
    assert cartes_telephone.count("<Link") == 1


def test_liens_isoles_chantiers_atteignent_44px() -> None:
    """Constat 1 (Important) : le bandeau silencieux (`ChantiersListe.tsx`)
    et « Voir tous les mois » (`FicheChantier.tsx`) restent des liens isolés
    au milieu d'une ligne dense — pas des cartes entières — mais chacun doit
    quand même garantir une cible d'au moins 44 px de haut
    (`inline-flex min-h-[44px] items-center`)."""
    liste = _lire("pages", "ChantiersListe.tsx")
    bandeau = liste.split("function BandeauSilencieux", 1)[1].split(
        "function CarteTousLesChantiers", 1
    )[0]
    assert "inline-flex min-h-[44px] items-center" in bandeau

    fiche = _lire("pages", "FicheChantier.tsx")
    entete_lien = fiche.split("moisChoisi && (", 1)[1].split("Voir tous les mois", 1)[0]
    assert "inline-flex min-h-[44px] items-center" in entete_lien


def test_chantier_et_fournisseur_non_resolus_ont_un_libelle_courant() -> None:
    """Constat 2 (Important) : « Chantier non résolu » est un terme
    technique (la résolution d'un nom en entité) qui s'affichait dans le
    tableau principal comme dans les cartes téléphone, sans aucun lien.
    VueEnsemble.tsx/FicheFournisseur.tsx/PageBl.tsx (Tâches 5, 8, 9, déjà
    fusionnées dans `refonte-front`) écrivent « Chantier à rattacher », avec
    un lien vers « À régler » — la relecture de la Task 9 avait fait
    remplacer ce même terme. Le même repli existe pour les fournisseurs
    (« Fournisseur non résolu »), remplacé par un libellé courant."""
    liste = _lire("pages", "ChantiersListe.tsx")
    assert "Chantier non résolu" not in liste
    assert "Chantier à rattacher" in liste
    assert "/a-regler?filtre=rattacher" in liste
    # Le repli s'applique à la fois au nom affiché et à la destination du
    # lien (`nomAffiche`/`destinationLigne`), pour la carte comme pour la
    # ligne de tableau.
    assert 'return ligne.nom ?? "Chantier à rattacher";' in liste
    assert 'return "/a-regler?filtre=rattacher";' in liste

    fiche = _lire("pages", "FicheChantier.tsx")
    assert "Chantier non résolu" not in fiche
    assert "Fournisseur non résolu" not in fiche
    assert "Fournisseur à rattacher" in fiche
