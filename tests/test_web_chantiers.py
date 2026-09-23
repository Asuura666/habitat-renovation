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
    assert "Chantiers sans bon déposé depuis 7 jours" in page
    assert "obtenirChantiersSansDepot" in page
    assert "useSearchParams" in page
    assert 'type="month"' in page
    assert "obtenirAgences" in page
    assert "md:hidden" in page
    assert "md:block" in page
    assert "Exporter en CSV" in page
    assert "Export détaillé (CSV)" in page
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
    # FicheChantier) — le lien « Gérer les chantiers » de Gabarit.tsx reste
    # valide (redirige vers `/chantiers`).
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
    assert "/chantiers/referentiel" in gabarit


def test_bilan_et_chantiers_ne_sont_plus_importes() -> None:
    """`Bilan.tsx`/`Chantiers.tsx` sont supprimés une fois leur contenu repris
    (consigne Task 7) : plus aucune route ne les monte, et les fichiers
    n'existent plus."""
    app = _lire("App.tsx")

    assert 'pages/Bilan"' not in app
    assert 'from "./pages/Chantiers"' not in app
    assert not (WEB / "pages" / "Bilan.tsx").exists()
    assert not (WEB / "pages" / "Chantiers.tsx").exists()


def test_bilan_fournisseur_reste_mais_nest_plus_utilise_par_chantiers() -> None:
    """`BilanFournisseur.tsx` n'est pas supprimé (Task 9 le gère en
    parallèle) : App.tsx cesse seulement de l'utiliser pour les routes
    `chantiers*` (`BilanFournisseursChantier`/`BilanBl` ne sont plus
    montés), les routes `fournisseurs*` gardées par la Task 9 continuent de
    l'utiliser."""
    app = _lire("App.tsx")

    assert (WEB / "pages" / "BilanFournisseur.tsx").exists()
    assert "BilanFournisseursChantier" not in app
    assert "<BilanBl" not in app
    assert "BilanFournisseursGlobal" in app
    assert "BilanChantiersFournisseur" in app


def test_referentiels_agences_et_silencieux_toujours_exposes() -> None:
    referentiels = _lire("api", "referentiels.ts")

    assert '"/api/referentiels/agences"' in referentiels
    assert "CLE_AGENCES" in referentiels
    assert '"/api/referentiels/chantiers-silencieux"' in referentiels
    assert '"/api/referentiels/depots-par-agent"' in referentiels
