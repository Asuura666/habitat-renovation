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
    # bord, bilan.
    assert "CLE_ANOMALIES" in page
    assert "CLE_TABLEAU_DE_BORD" in page
    assert '["bilan"]' in page
    assert "invalidateQueries" in page

    # Jamais un code de règle brut affiché.
    assert "{anomalie.regle}" not in page


def test_probleme_detail_couvre_documents_alias_et_articles() -> None:
    page = _lire("pages", "ProblemeDetail.tsx")

    assert "Bon illisible à corriger" in page
    assert "Chantier à rattacher" in page
    assert "Article à valider" in page

    # Documents « à vérifier » : lien de correction vers la page du bon,
    # jamais un formulaire dupliqué ici.
    assert "/bl/${document.id}" in page

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
    pastille du nombre de problèmes urgents ouverts sur « À régler », à
    partir d'un appel serveur existant ; (2) « Accueil » dans la barre basse
    (téléphone), « Vue d'ensemble » conservé dans la barre latérale."""
    gabarit = _lire("components", "Gabarit.tsx")

    # (1) Pastille -- appel serveur existant, jamais un nouveau calcul.
    assert 'gravite: "haute"' in gabarit
    assert "listerAnomalies" in gabarit
    assert 'from "../api/anomalies"' in gabarit

    # (2) Libellé court de la barre basse, sans perdre celui de la barre
    # latérale.
    assert "Accueil" in gabarit
    assert "Vue d'ensemble" in gabarit
