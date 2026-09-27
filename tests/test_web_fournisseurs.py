"""Contrat front de l'écran « Fournisseurs » (Task 9, plan de la refonte du
front §4) : mêmes principes que `test_web_bilan.py`/`test_web_socle.py`,
lecture du texte source des pages plutôt qu'un rendu (pas d'environnement
navigateur dans cette suite) — les chaînes exactes ci-dessous sont celles de
`task-9-brief.md`."""

from __future__ import annotations

from pathlib import Path

RACINE_WEB = Path(__file__).parents[1] / "web" / "src"


def _page(nom: str) -> str:
    return (RACINE_WEB / "pages" / nom).read_text()


def test_liste_fournisseurs_couvre_le_contrat_responsive() -> None:
    page = _page("FournisseursListe.tsx")

    # Colonnes exactes du brief (Task 9) : Fournisseur, Facturé, Écart, Sans
    # bon, Problèmes.
    assert "Fournisseur" in page
    assert "Facturé" in page
    assert "Écart" in page
    assert "Sans bon" in page
    assert "Problèmes" in page

    # Téléphone = cible à part entière (spec §7) : cartes empilées sous
    # `md`, tableau au-dessus.
    assert "md:hidden" in page
    assert "hidden" in page and "md:block" in page

    # Export CSV existant (`api/bilan.ts`), jamais un second calcul.
    assert "urlExportBilanFournisseurs" in page
    assert "listerBilanFournisseursGlobal" in page

    # État vide en français courant, jamais un tableau silencieusement vide.
    assert "EtatVide" in page

    # Charte « Registre » : composants partagés, jamais un habillage local
    # divergent.
    assert "EnTetePage" in page

    # Aucun calcul métier dans le front (aucune somme, différence ou
    # pourcentage sur des montants) : les valeurs affichées viennent telles
    # quelles du serveur.
    assert "parseFloat" not in page
    assert "Number(" not in page

    # Aucun jargon technique visible (spec §5) : ni « bloc », « alias »,
    # « rapprochement », « OCR », « anomalie » comme texte affiché (motif
    # `>mot<`, même principe que `test_web_socle.py` — un identifiant de
    # code comme `Anomalie`/`anomalies.ts` reste légitime).
    for jargon in ("bloc", "alias", "rapprochement", "OCR", "anomalie", "Anomalies"):
        assert f">{jargon}<" not in page, jargon

    # « Fournisseur non résolu » est du jargon technique (résolution
    # d'entité) sans action possible ; « Fournisseur non identifié » est le
    # texte attendu (correction de revue, tour 1).
    assert "Fournisseur non résolu" not in page
    assert "Fournisseur non identifié" in page


def test_liste_fournisseurs_filtre_par_mois_et_agence() -> None:
    """Correction de revue (tour 1) : le brief et le plan (`GET
    /api/bilan/fournisseurs?mois`) attendent un filtre mois/agence, comme
    « Chantiers » — le socle transmet déjà `?mois=...&agence=...` en
    redirigeant `/bilan/fournisseurs` vers `/fournisseurs`."""
    page = _page("FournisseursListe.tsx")

    assert "useSearchParams" in page
    assert 'parametres.get("mois")' in page
    assert 'parametres.get("agence")' in page
    assert 'type="month"' in page
    assert "Toutes les agences" in page

    # Filtres transmis à la requête et à l'export, jamais ignorés.
    assert "listerBilanFournisseursGlobal(filtres)" in page
    assert "urlExportBilanFournisseurs(null, filtres)" in page

    # La période affichée (spec : un non-technicien doit savoir sur quelle
    # période portent les montants) — « Tous les mois » par défaut.
    assert "Tous les mois" in page
    assert "surtitre" in page

    # Les filtres sont reportés dans le lien vers la fiche.
    assert "lienAvecFiltres" in page


def test_fiche_fournisseur_couvre_le_contrat_de_la_tache() -> None:
    page = _page("FicheFournisseur.tsx")

    # Step 1 du brief (Task 9) : chaînes et motifs exacts.
    assert "Chantiers concernés" in page
    assert "Problèmes ouverts" in page
    assert "FilAriane" in page
    assert "md:hidden" in page
    # Revue finale (constats LIENS-12/LIENS-13) : la destination d'un
    # chantier est construite par l'aide partagée `lib/liens.ts`, qui
    # reporte le mois affiché (fiche du chantier, ou « À régler » filtré
    # sur les chantiers à rattacher).
    assert "lienChantier(ligne.chantier_id, mois)" in page
    liens = (RACINE_WEB / "lib" / "liens.ts").read_text()
    assert "`/chantiers/${chantierId}`" in liens
    assert '"/a-regler?filtre=rattacher"' in liens
    assert "`/a-regler/${" in page

    # Quatre `Chiffre` (spec §4 « les quatre chiffres ») : le quatrième,
    # « Conforme », est fourni par le serveur depuis la revue finale
    # (`MontantsBilan.conforme`, constat COUVERTURE-12) — jamais recalculé
    # côté front.
    assert page.count("<Chiffre") == 4
    assert "ligneMontants.montants.conforme" in page

    # Agences connues + export, mêmes fonctions existantes que la liste.
    assert "Agences connues" in page
    assert "urlExportBilanChantiersFournisseur" in page
    assert "listerBilanChantiersFournisseur" in page
    assert "listerFournisseurs" in page
    assert "listerAnomalies" in page

    # Montants du serveur affichés tels quels (`ui/formats.ts`), jamais
    # recalculés.
    assert "formaterMontant" in page
    assert "parseFloat" not in page
    assert "Number(" not in page

    # Titres de règles et phrases chiffrées via le langage courant partagé
    # (spec §5), jamais un code de règle brut affiché.
    assert "titreRegle" in page
    assert "phraseProbleme" in page

    for jargon in ("bloc", "alias", "rapprochement", "OCR", "anomalie", "Anomalies"):
        assert f">{jargon}<" not in page, jargon

    # « Chantier non résolu » est du jargon sans aucune action possible ;
    # « Chantier à rattacher », avec un lien vers `/a-regler?filtre=
    # rattacher`, est le texte attendu (correction de revue, tour 1).
    assert "Chantier non résolu" not in page
    assert "Chantier à rattacher" in page


def test_fournisseurs_referentiel_complet_et_liens_de_la_fiche() -> None:
    """Revue finale : la liste montre tous les fournisseurs du référentiel,
    y compris sans facture (constat COUVERTURE-8 — Point.P, dont le parseur
    de facture n'existe pas encore, n'avait plus d'entrée vers sa fiche) ;
    la fiche mène aux factures du fournisseur (constat COUVERTURE-13) et à
    l'historique de ses problèmes (constat LIENS-14)."""
    liste = _page("FournisseursListe.tsx")
    assert "Tous les fournisseurs" in liste
    assert "listerFournisseurs" in liste
    assert "`/fournisseurs/${fournisseur.id}`" in liste

    fiche = _page("FicheFournisseur.tsx")
    assert "/documents?filtre=factures&fournisseur=" in fiche
    assert "Voir les factures de ce fournisseur" in fiche
    assert "/a-regler?filtre=regles&fournisseur=" in fiche


def test_fiche_fournisseur_filtre_par_mois_et_agence() -> None:
    """Mêmes filtres que la liste (correction de revue, tour 1) : la fiche
    lit `mois`/`agence` dans l'URL et les reporte à toutes ses requêtes, à
    son export et au fil d'Ariane -- `agence` reste posée uniquement par la
    liste (pas de sélecteur propre à la fiche pour ce filtre). `mois`, lui,
    gagne son propre sélecteur sur la fiche à la Task 13 (mise en production
    du 1er octobre, spec §4.2, correction 2) : même schéma que
    `FournisseursListe.tsx::FormulaireFiltres` (`<input type="month">` +
    `setSearchParams`/`{replace: true}`)."""
    page = _page("FicheFournisseur.tsx")

    assert "useSearchParams" in page
    assert 'parametres.get("mois")' in page
    assert 'parametres.get("agence")' in page
    assert "listerBilanFournisseursGlobal(filtres)" in page
    assert "listerBilanChantiersFournisseur(fournisseurId ?? " in page
    assert "urlExportBilanChantiersFournisseur(fournisseurId ?? " in page
    assert "lienAvecFiltres(" in page
    assert "Tous les mois" in page
    assert "surtitre" in page

    # Sélecteur de mois (Task 13) : `<input type="month">`, reporté dans
    # l'URL via `setSearchParams`, `{ replace: true }` (même idiome que
    # `FournisseursListe.tsx`, jamais un `setSearchParams` sans `replace`
    # qui empilerait une entrée d'historique par frappe).
    assert 'id="filtre-mois"' in page
    assert 'type="month"' in page
    assert "changerMois" in page
    assert "setParametres(suivants, { replace: true })" in page
    assert "value={filtresUrl.mois ?? " in page


def test_fiche_fournisseur_precise_la_portee_des_problemes_ouverts() -> None:
    """Correction de revue (tour 2, constat 1) : `GET /api/anomalies` ne
    sait filtrer que sur `created_at` (date de constat d'un problème),
    jamais sur le mois de la facture — la section « Problèmes ouverts » ne
    doit donc jamais être elle-même filtrée par mois/agence (ce serait un
    filtre silencieux, en contradiction avec le chiffre « Problèmes » de la
    colonne de la liste et avec les trois `Chiffre` de cette même fiche, qui
    eux sont filtrés). La fiche affiche donc une portée explicite dès qu'un
    filtre est actif ailleurs sur la page, plutôt que de recalculer ou de
    masquer silencieusement un chiffre."""
    page = _page("FicheFournisseur.tsx")

    # La requête « problèmes ouverts » n'est jamais filtrée par mois/agence :
    # seul `fournisseurId` est transmis à `listerAnomalies`/`cleAnomalies`
    # (avec la limite maximale de l'API depuis la revue finale, constat
    # COUVERTURE-22 : jamais un plafond silencieux à 100).
    assert "listerAnomalies({ fournisseurId, limite: 500 })" in page
    assert "cleAnomalies({ fournisseurId, limite: 500 })" in page

    # Portée explicite affichée dès qu'un filtre (mois ou agence) est actif
    # ailleurs sur la page, pour qu'un non-technicien ne lise jamais deux
    # chiffres « Problèmes » contradictoires sans explication.
    assert "filtres.mois || filtres.agence" in page
    assert "Tous les problèmes encore ouverts chez ce fournisseur," in page
    assert "quel que soit le mois ou" in page
    assert "l'agence." in page


def test_fournisseurs_sont_montes_sur_leurs_routes() -> None:
    """Cette tâche ne possède que `/fournisseurs` et `/fournisseurs/:id` :
    les routes `/chantiers/...` appartiennent à la Task 7 et ne sont pas
    vérifiées ici (correction de revue, tour 1 — ce contrat figeait un état
    d'une autre tâche, en parallèle, qui les remplace)."""
    app = (RACINE_WEB / "App.tsx").read_text()

    for chemin, composant in (
        ('path="fournisseurs"', "FournisseursListe"),
        ('path="fournisseurs/:fournisseurId"', "FicheFournisseur"),
    ):
        assert chemin in app
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert f"<{composant}" in declaration, chemin
        assert "GardeAdmin" in declaration, chemin


def test_fournisseurs_n_importent_pas_bilan_fournisseur() -> None:
    """`pages/BilanFournisseur.tsx` porte encore les écrans des routes
    `/chantiers/...` (Task 7, non touchées ici) : les deux écrans de cette
    tâche ne doivent rien en importer (correction de revue, tour 1). Le
    module `api/bilan.ts` expose légitimement des identifiants comme
    `listerBilanFournisseursGlobal` (qui contiennent la sous-chaîne
    « BilanFournisseur ») : seul un import depuis `./BilanFournisseur` est
    interdit."""
    for nom in ("FournisseursListe.tsx", "FicheFournisseur.tsx"):
        page = _page(nom)
        assert 'BilanFournisseur"' not in page, nom
        assert "./BilanFournisseur" not in page, nom


# ---------------------------------------------------------------------------
# Task 13 (mise en production du 1er octobre, spec §4.2/§4.3) : fiche
# fournisseur par mois et bons conformes cliquables.
# ---------------------------------------------------------------------------


def test_fiche_fournisseur_a_une_carte_livraisons() -> None:
    """Spec §4.3, deuxième volet : la fiche fournisseur montre désormais
    aussi les livraisons (« pas seulement les problèmes »), via le nouveau
    `GET /api/bilan/livraisons` (Task 13) filtré sur ce fournisseur, tous
    chantiers confondus -- le composant partagé `TableauLivraisons`
    (extrait de la fiche chantier) affiche le chantier de chaque ligne
    (`colonneChantier`, la fiche chantier ne l'affiche pas -- elle fixe déjà
    le sien par son URL)."""
    page = _page("FicheFournisseur.tsx")

    assert 'from "../components/TableauLivraisons"' in page
    assert "<TableauLivraisons" in page
    assert "colonneChantier" in page
    assert "listerLivraisons" in page
    assert "cleLivraisons" in page
    assert "fournisseurId" in page.split("filtresLivraisons = ", 1)[1].split(";", 1)[0]


def test_fiche_fournisseur_tuile_conforme_ouvre_les_livraisons_conformes() -> None:
    """Spec §4.3, premier volet : le montant « Conforme » de la fiche
    fournisseur devient cliquable et mène à la liste des bons conformes du
    même périmètre (mois, agence, fournisseur) -- ancre `#livraisons` vers
    la carte ci-dessus, filtrée sur l'état « conforme »."""
    page = _page("FicheFournisseur.tsx")

    assert "lienLivraisonsConformes" in page
    assert 'parametresLivraisonsConformes.set("etat", "conforme")' in page
    assert "#livraisons" in page
    assert "vers={lienLivraisonsConformes}" in page

    # Défilement jusqu'à la carte une fois chargée (même mécanique que
    # `#bloc-…` sur `FactureDetail.tsx`).
    assert "useLocation" in page
    assert 'hash === "#livraisons"' in page
    assert 'getElementById("livraisons")?.scrollIntoView' in page
