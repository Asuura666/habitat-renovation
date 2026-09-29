"""Contrat de la tâche LABO (Laboratoire IA, phase 4 IA) — écran d'essai
admin des trois usages de l'IA. Même principe que
`tests/test_web_synthese_commentaires.py`/`tests/test_web_avis_ia.py` :
lecture du texte source des fichiers front, aucun rendu React (le dépôt n'a
pas d'outil de test front, voir `CLAUDE.md`)."""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).parents[1] / "web"
SRC = WEB / "src"


def _lire(*chemins: str) -> str:
    chemin = SRC.joinpath(*chemins)
    assert chemin.exists(), f"{chemin} est introuvable"
    return chemin.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Route et navigation
# --------------------------------------------------------------------------


def test_route_ia_est_admin() -> None:
    app = _lire("App.tsx")

    assert 'path="ia"' in app
    assert "<LaboIA />" in app
    assert 'from "./pages/LaboIA"' in app

    # La route est bien gardée par `GardeAdmin` (même bloc, jusqu'à la
    # prochaine route déclarée -- jamais un simple `split("/>", 1)`, qui
    # coupe au premier tag auto-fermant rencontré (`<LaboIA />` lui-même)).
    bloc = app.split('path="ia"', 1)[1].split("<Route", 1)[0]
    assert "<GardeAdmin>" in bloc
    assert "<LaboIA />" in bloc


def test_lien_essayer_ia_dans_reglages() -> None:
    page = _lire("pages", "Reglages.tsx")

    assert 'to="/ia"' in page
    assert "Essayer l'IA" in page


# --------------------------------------------------------------------------
# Contrat de l'API front
# --------------------------------------------------------------------------


def test_api_ia_labo_contrat() -> None:
    api = _lire("api", "ia.ts")

    for schema in (
        "EtatLaboReponse",
        "ControleReponse",
        "OutilTraceReponse",
        "TraceEssaiReponse",
        "TraceEssaiResumeReponse",
        "AppelIALigneReponse",
        "EssaiLanceReponse",
    ):
        assert f'components["schemas"]["{schema}"]' in api, schema

    assert "export function lireEtatLabo" in api
    assert '"/api/ia/labo/etat"' in api

    assert "export function lancerEssaiPrixLabo" in api
    assert '"/api/ia/labo/essais/prix"' in api
    assert "export function lancerEssaiExplicationLabo" in api
    assert '"/api/ia/labo/essais/explication"' in api
    assert "export function lancerEssaiSyntheseLabo" in api
    assert '"/api/ia/labo/essais/synthese"' in api

    assert "export function lireEssaiLabo" in api
    assert '"/api/ia/labo/essais/{essai_id}"' in api
    assert "/api/ia/labo/essais/${essaiId}" in api

    assert "export function listerDerniersEssaisLabo" in api
    assert '"/api/ia/labo/essais"' in api
    assert "export function listerJournalAppelsLabo" in api
    assert '"/api/ia/labo/appels"' in api


def test_essais_lances_par_methode_post() -> None:
    api = _lire("api", "ia.ts")

    for fonction in (
        "lancerEssaiPrixLabo",
        "lancerEssaiExplicationLabo",
        "lancerEssaiSyntheseLabo",
    ):
        # Jusqu'à la prochaine fonction exportée (jamais `split("\n}", 1)`,
        # qui coupe à la première accolade fermante rencontrée -- souvent
        # celle du type d'un paramètre, avant même le corps de la fonction).
        bloc = api.split(f"export function {fonction}", 1)[1].split(
            "export function ", 1
        )[0]
        assert 'method: "POST"' in bloc, fonction


# --------------------------------------------------------------------------
# Écran LaboIA.tsx : bandeau, sections, pas de jargon en dehors des blocs
# tel-quel.
# --------------------------------------------------------------------------


def test_bandeau_essai_texte_exact() -> None:
    composant = _lire("pages", "LaboIA.tsx")

    assert (
        "Essai : rien n'est enregistré, mais l'appel compte dans le plafond du jour."
        in composant
    )


def test_bouton_lancer_essai_present_trois_fois() -> None:
    composant = _lire("pages", "LaboIA.tsx")

    assert composant.count("Lancer l'essai") == 3


def test_etapes_numerotees_du_deroule() -> None:
    composant = _lire("pages", "LaboIA.tsx")

    for etape in (
        "① Texte envoyé",
        "② Recherches et pages ouvertes",
        "③ Réponse brute",
        "④ Contrôles",
        "⑤ Résultat",
    ):
        assert etape in composant, etape

    # Dans l'ordre du brief.
    positions = [
        composant.index(etape)
        for etape in (
            "① Texte envoyé",
            "② Recherches et pages ouvertes",
            "③ Réponse brute",
            "④ Contrôles",
            "⑤ Résultat",
        )
    ]
    assert positions == sorted(positions)


def test_texte_envoye_vide_dit_que_rien_n_est_envoye() -> None:
    """Semaine sans commentaire : l'IA n'est pas appelée (comme en
    production), l'étape ① le dit au lieu d'un bloc vide."""
    composant = _lire("pages", "LaboIA.tsx")

    assert "Rien n'a été envoyé à l'IA." in composant


def test_lien_connexion_abonnement_present() -> None:
    composant = _lire("pages", "LaboIA.tsx")

    assert "docs/phase-4-ia.md §3.1" in composant
    commande = "docker compose -f deploy/opencode/docker-compose.yml run --rm opencode"
    assert f"{commande} opencode auth login" in composant
    # N'apparaît que dans le bloc « abonnement non connecté ».
    garde = "!etat.data.abonnement_connecte && ("
    assert garde in composant
    bloc = composant.split(garde, 1)[1].split("\n      )}", 1)[0]
    assert "docs/phase-4-ia.md" in bloc


def test_refetch_interval_2s_pendant_essai_en_cours() -> None:
    composant = _lire("pages", "LaboIA.tsx")

    assert 'requete.state.data?.statut === "en_cours" ? 2000 : false' in composant


def test_blocs_repliables_present() -> None:
    composant = _lire("pages", "LaboIA.tsx")

    assert composant.count("<details") >= 3


def test_liens_externes_securises() -> None:
    composant = _lire("pages", "LaboIA.tsx")

    assert 'target="_blank"' in composant
    # Chaque `target="_blank"` est accompagné de `rel="noopener noreferrer"`
    # avant la fermeture du lien suivant.
    morceaux = composant.split('target="_blank"')[1:]
    for morceau in morceaux:
        bloc = morceau.split("</a>", 1)[0]
        assert 'rel="noopener noreferrer"' in bloc


def test_cibles_tactiles_44px() -> None:
    composant = _lire("pages", "LaboIA.tsx")

    assert "min-h-[44px]" in composant


def test_sections_principales_presentes() -> None:
    composant = _lire("pages", "LaboIA.tsx")

    for titre in (
        "État de l'IA",
        "Essayer",
        "Déroulé de l'essai",
        "Derniers essais",
        "Journal des appels",
    ):
        assert f'titre="{titre}"' in composant, titre


def test_essai_ne_bloque_pas_rien_enregistre_visible() -> None:
    """Le texte du bandeau (`test_bandeau_essai_texte_exact`) est la seule
    mention requise par le brief -- ce test vérifie juste qu'il est bien
    monté dans la section « Essayer »."""
    composant = _lire("pages", "LaboIA.tsx")

    bloc_essayer = composant.split('titre="Essayer"', 1)[1].split("</Carte>", 1)[0]
    assert "rien n'est enregistré" in bloc_essayer


def test_formulaire_synthese_champ_date() -> None:
    composant = _lire("pages", "LaboIA.tsx")

    assert 'type="date"' in composant


def test_prix_trouve_affiche_comme_sur_la_page_prix() -> None:
    """29/09/2026 : le Laboratoire affichait « 21.2400 EUR TTC » (valeur
    brute) ; il réutilise la fonction d'affichage de la page Prix
    (`lib/prixInternet.ts`) -- « 21,24 € TTC (sac de 25 kg) »."""
    composant = _lire("pages", "LaboIA.tsx")

    assert "texteMontantPrixInternet" in composant
    assert "String(resultat.prix)" not in composant
