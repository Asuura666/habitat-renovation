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
        "Sans bon de livraison",
        "Problèmes à régler",
        "Bons de livraison reçus",
    ):
        assert libelle in page, libelle

    # « Écart prix ou quantité » (décision d'Ilane du 24/09/2026, `docs/
    # dette.md`) : appelle désormais `libelleEcart(controlePrixActif)`
    # (`ui/libelles.ts`, contrat couvert par `tests/test_web_socle.py::
    # test_tuiles_ecart_utilisent_libelle_ecart_partage`) plutôt que le
    # texte figé, devenu faux quand les contrôles de prix sont désactivés.
    # `controlePrixActif` : repli `?? false` (constat mineur 2 de la revue
    # des contrôles de prix), même valeur que le défaut serveur.
    assert (
        "const controlePrixActif = compteARegler.data?.controle_prix_actif ?? false;"
        in page
    )
    assert "libelleEcart(controlePrixActif)" in page
    assert "sousTexteEcart(controlePrixActif)" in page
    assert '"Écart prix ou quantité"' not in page

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


# ---------------------------------------------------------------------------
# Revue finale de la refonte du front
# ---------------------------------------------------------------------------


def test_vue_ensemble_ne_promet_pas_un_nombre_que_la_cible_ne_montre_pas() -> None:
    """Constats LIENS-2, ECRAN-6, TELEPHONE-2, COUVERTURE-2 : la tuile
    compte les problèmes des factures du mois (et le dit), l'écran « À
    régler » tous les problèmes -- le lien annonce le compte unique « en
    tout » du serveur, celui que l'écran cible affiche en tête, jamais le
    nombre du mois ; le lien a une cible de 44 px."""
    page = (SRC / "pages" / "VueEnsemble.tsx").read_text()
    assert "Voir les {donnees" not in page
    assert "Voir les ${compte.nb_problemes} problèmes à régler en tout →" in page
    assert 'libelle="Problèmes à régler ce mois"' in page
    lien = page.split("{libelleLienARegler(compte)}", 1)[0].rsplit("<Link", 1)[1]
    assert "inline-flex min-h-[44px] items-center" in lien


def test_vue_ensemble_bons_a_reclamer_comptes_par_le_serveur() -> None:
    """Constats SERVEUR-1/COUVERTURE-4 : le nombre de bons à réclamer vient
    du serveur (`nb_bl_manquants`), plus d'une soustraction côté front qui
    comptait aussi les livraisons « sans bon » et les bons déjà réglés."""
    page = (SRC / "pages" / "VueEnsemble.tsx").read_text()
    assert "donnees.nb_bl_manquants" in page
    assert "nb_bl_factures - donnees.nb_bl_recus" not in page
    assert "BL à réclamer à l'équipe" not in page
    assert "à contester au fournisseur" not in page


def test_vue_ensemble_liens_vers_la_fiche_et_le_probleme() -> None:
    """Constats ECRAN-4, COUVERTURE-3 : la fiche chantier s'ouvre au mois
    affiché (mêmes montants, pastille d'état) ; un problème prioritaire
    ouvre son détail dans « À régler ». Constat COUVERTURE-23 (RF2) : le
    chantier non rattaché mène à « À régler » filtré sur les chantiers à
    rattacher."""
    page = (SRC / "pages" / "VueEnsemble.tsx").read_text()
    assert "lienChantier(chantier.chantier_id, mois)" in page
    assert "`/a-regler/${priorite.anomalie.id}`" in page
    liens = (SRC / "lib" / "liens.ts").read_text()
    assert 'LIEN_CHANTIERS_A_RATTACHER = "/a-regler?filtre=rattacher"' in liens
    assert "chantierId === null ? LIEN_CHANTIERS_A_RATTACHER" in liens


def test_vue_ensemble_tableau_aligne_et_client_nomme() -> None:
    """Constat COUVERTURE-6 : un vrai tableau (colonnes alignées d'une
    ligne à l'autre). Constat ECRAN-19 : « Client non renseigné » plutôt que
    l'agence seule, lue comme un client. Constat COUVERTURE-26 : lien vers
    le dernier mois facturé quand le mois affiché est vide."""
    page = (SRC / "pages" / "VueEnsemble.tsx").read_text()
    assert "<table" in page
    assert "grid-cols-[2.2fr_1.4fr_1fr_1fr_1fr]" not in page
    assert '"Client non renseigné"' in page
    assert "dernier_mois_facture" in page
    assert "dernier mois facturé" in page


def test_mois_de_l_url_valide_partout() -> None:
    """Constat LIENS-5 : un seul format de mois dans l'URL (`AAAA-MM`),
    validé par `lireMois` sur chaque écran qui le lit -- une valeur
    illisible ne fait plus lever `Intl.DateTimeFormat` (écran blanc)."""
    formats = (SRC / "lib" / "formats.ts").read_text()
    correspondance = re.search(r"const REGEX_MOIS_URL = /(\^.*\$)/;", formats)
    assert correspondance is not None
    motif = re.compile(correspondance.group(1))
    for valide in ("2026-09", "2026-09-01", "2026-12"):
        assert motif.match(valide), valide
    for invalide in ("2026-13", "2026-00", "", "2026-09-15", "texte"):
        assert motif.match(invalide) is None, invalide
    for page in (
        "VueEnsemble.tsx",
        "ChantiersListe.tsx",
        "FicheChantier.tsx",
        "FournisseursListe.tsx",
        "FicheFournisseur.tsx",
        "DocumentsListe.tsx",
    ):
        contenu = (SRC / "pages" / page).read_text()
        assert 'lireMois(parametres.get("mois"))' in contenu, page
