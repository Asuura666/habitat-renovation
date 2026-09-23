"""Contrat de la Task 5 (Vue d'ensemble, refonte front, maquette `Main`) —
chaînes exactes exigées par le brief `task-5-brief.md`. Aucun rendu React
ici (même principe que `tests/test_web_socle.py`) : ces tests ne vérifient
que le texte source des fichiers, avant tout `npm run build`/typecheck."""

import re
from pathlib import Path

WEB = Path(__file__).parents[1] / "web"
SRC = WEB / "src"


def test_api_tableau_de_bord_existe_deja() -> None:
    """`web/src/api/tableauDeBord.ts` existe depuis la Task 2 : ce test
    documente le contrat qu'il doit garder, il ne le crée pas."""
    api = (SRC / "api" / "tableauDeBord.ts").read_text()
    assert '"/api/tableau-de-bord"' in api
    assert 'components["schemas"]["TableauDeBordReponse"]' in api
    assert "obtenirTableauDeBord" in api
    assert "cleTableauDeBord" in api


def test_vue_ensemble_contenu() -> None:
    page = (SRC / "pages" / "VueEnsemble.tsx").read_text()

    assert "obtenirTableauDeBord" in page
    assert "useSearchParams" in page
    assert 'type="month"' in page
    assert "PastilleEtat" in page

    # Les six tuiles chiffrées (maquette `Main`, brief T5) — libellés exacts.
    for libelle in (
        "Facturé ce mois",
        "Conforme",
        "Écart prix ou quantité",
        "Sans bon de livraison",
        "Problèmes à régler",
        "Bons de livraison reçus",
    ):
        assert libelle in page, libelle

    assert "Chantier à rattacher" in page
    assert "Aucune facture ce mois-ci." in page
    assert "Exporter pour Excel" in page

    # Tableau (ordinateur) / cartes empilées (téléphone).
    assert "md:hidden" in page

    # Aucun calcul métier sur des montants (CDC : le front affiche ce que le
    # serveur renvoie, jamais une somme/différence/pourcentage recalculée).
    assert "parseFloat" not in page
    assert "Number(" not in page


def test_vue_ensemble_aucun_jargon_visible() -> None:
    """Mots interdits en frontière de mot (brief T5) — `\\b` évite le faux
    positif de « bloc » sur la classe Tailwind `block`."""
    page = (SRC / "pages" / "VueEnsemble.tsx").read_text()
    for jargon in ("bloc", "alias", "rapprochement", "OCR", "R08"):
        assert re.search(rf"\b{jargon}\b", page) is None, jargon
    # « Anomalie »/« Anomalies » (casse d'un libellé affiché) jamais visible
    # — `anomalie` en minuscule reste légitime comme nom de variable/type.
    assert "Anomalie" not in page
    assert "problème" in page


def test_route_accueil_monte_vue_ensemble() -> None:
    accueil = (SRC / "routes" / "RedirectionAccueil.tsx").read_text()
    assert "<VueEnsemble" in accueil
    assert "<EcranEnConstruction" not in accueil
    assert "ui/EcranEnConstruction" not in accueil


def test_ecran_en_construction_supprime_si_inutilise() -> None:
    """Task 4 posait `EcranEnConstruction` en attendant cette tâche — plus
    aucune route ne le monte après la Task 5, il est donc supprimé (brief
    T5) plutôt que laissé mort dans le dépôt. Une mention en commentaire
    (historique, dans `App.tsx`/`RedirectionAccueil.tsx`) reste légitime :
    seuls l'import, l'usage JSX et le fichier lui-même sont vérifiés."""
    assert not (SRC / "ui" / "EcranEnConstruction.tsx").exists()
    index_ui = (SRC / "ui" / "index.ts").read_text()
    assert "EcranEnConstruction" not in index_ui
    for fichier in SRC.rglob("*.tsx"):
        contenu = fichier.read_text()
        assert "<EcranEnConstruction" not in contenu, fichier
        assert "ui/EcranEnConstruction" not in contenu, fichier
