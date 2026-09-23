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


def test_regex_mois_rejette_00_et_13_a_99() -> None:
    """Correction de revue, tour 1 : l'ancienne regex `^\\d{4}-\\d{2}$`
    acceptait les mois `00` et `13` à `99` — `new Date("2026-13-01")` est
    invalide et fait lever `Intl.DateTimeFormat.format` (`RangeError:
    Invalid time value`), sans `ErrorBoundary` dans l'app, d'où un écran
    blanc sur `/?mois=2026-13`. On extrait la regex telle qu'écrite dans
    `VueEnsemble.tsx` (syntaxe compatible `re`, aucune fonctionnalité propre
    à JS) et on la teste directement plutôt que de dupliquer une constante
    dans le test — une regression sur la ligne source fait échouer ce test
    autant que sur une regex qui aurait divergé silencieusement."""
    page = (SRC / "pages" / "VueEnsemble.tsx").read_text()
    correspondance = re.search(r"const REGEX_MOIS = /(\^.*\$)/;", page)
    assert correspondance is not None
    motif = re.compile(correspondance.group(1))

    for valide in ("2026-01", "2026-09", "2026-12", "2000-06"):
        assert motif.match(valide), valide
    for invalide in (
        "2026-00",
        "2026-13",
        "2026-19",
        "2026-99",
        "2026-1",
        "2026-1a",
        "26-09",
        "2026/09",
        "",
    ):
        assert motif.match(invalide) is None, invalide


def test_vue_ensemble_mois_utilise_un_brouillon_local() -> None:
    """Correction de revue, tour 1 : le champ `<input type="month">` ne
    doit plus être contrôlé directement par le mois *effectif* (`mois`,
    qui retombe sur le mois courant dès qu'une valeur est invalide/absente)
    — sur Firefox (`type="month"` en repli texte), chaque frappe
    intermédiaire invalide (« 2026-0 ») repassait alors par ce repli et
    réécrasait le champ en pleine saisie, empêchant de taper un mois valide.
    Un état local (`brouillonMois`) affiche exactement ce qui est tapé ;
    seule une valeur qui passe `REGEX_MOIS` est poussée dans l'URL."""
    page = (SRC / "pages" / "VueEnsemble.tsx").read_text()
    assert "brouillonMois" in page
    assert "value={brouillonMois}" in page
    # Le champ n'est plus jamais recontrôlé par `mois` directement.
    assert "value={mois}" not in page


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
