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
    assert "`/chantiers/${" in page
    assert "`/a-regler/${" in page

    # Trois `Chiffre` (brief : « fiche : FilAriane, trois Chiffre ») —
    # jamais un quatrième recalculé côté front.
    assert page.count("<Chiffre") == 3

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
    assert "/a-regler?filtre=rattacher" in page


def test_fiche_fournisseur_filtre_par_mois_et_agence() -> None:
    """Mêmes filtres que la liste (correction de revue, tour 1) : la fiche
    ne montre pas son propre sélecteur (c'est la liste qui filtre), mais lit
    `mois`/`agence` dans l'URL et les reporte à toutes ses requêtes, à son
    export et au fil d'Ariane."""
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
