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


def test_fournisseurs_sont_montes_sur_leurs_routes() -> None:
    app = (RACINE_WEB / "App.tsx").read_text()

    for chemin, composant in (
        ('path="fournisseurs"', "FournisseursListe"),
        ('path="fournisseurs/:fournisseurId"', "FicheFournisseur"),
    ):
        assert chemin in app
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert f"<{composant}" in declaration, chemin
        assert "GardeAdmin" in declaration, chemin

    # Task 7 (Chantiers) garde ses propres routes sur les mêmes anciens
    # composants (`BilanFournisseursChantier`, `BilanBl`) : cette tâche ne
    # les touche pas.
    declaration_chantier = app.split('path="chantiers/:chantierId"', 1)[1].split(
        "path=", 1
    )[0]
    assert "<BilanFournisseursChantier" in declaration_chantier
    declaration_bl = app.split('path="chantiers/:chantierId/:fournisseurId"', 1)[
        1
    ].split("path=", 1)[0]
    assert "<BilanBl" in declaration_bl


def test_bilan_fournisseur_reste_disponible_pour_les_routes_chantiers() -> None:
    """`BilanFournisseur.tsx` n'est pas supprimé par cette tâche : il porte
    encore `BilanFournisseursChantier`/`BilanBl`, montés par les routes
    `/chantiers/...` de la Task 7 (non touchées ici)."""
    fichier = RACINE_WEB / "pages" / "BilanFournisseur.tsx"
    assert fichier.exists()
    contenu = fichier.read_text()
    assert "export function BilanFournisseursChantier" in contenu
    assert "export function BilanBl" in contenu
