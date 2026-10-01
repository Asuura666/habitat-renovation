"""Contrat de la tâche T10b (phase 4 IA, spec §6.4) — colonne « Internet »
de la page « Prix à vérifier » (front). Même principe que
`tests/test_web_avis_ia.py` : lecture du texte source des fichiers front,
aucun rendu React (le dépôt n'a pas d'outil de test front, voir
`CLAUDE.md`)."""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).parents[1] / "web"
SRC = WEB / "src"

# Même liste que `test_web_avis_ia.py::MOTS_INTERDITS` -- jargon technique
# jamais montré à l'écran.
MOTS_INTERDITS = [
    "rapproch",
    "alias",
    "bloc",
    "ocr",
    "uuid",
    "opencode",
    "json",
    "modèle",
    "identifiant",
    "confiance",
]


def _lire(*chemins: str) -> str:
    chemin = SRC.joinpath(*chemins)
    assert chemin.exists(), f"{chemin} est introuvable"
    return chemin.read_text(encoding="utf-8")


def _sans_commentaires(source: str) -> str:
    """Même fonction que `test_web_avis_ia.py::_sans_commentaires`."""
    sans_blocs = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    return re.sub(r"//[^\n]*", " ", sans_blocs)


def _textes_affiches(source: str) -> str:
    """Même extraction que `test_web_avis_ia.py::_textes_affiches`."""
    textes = re.findall(r">([^<{]+)<", source)
    textes += re.findall(r'placeholder="([^"]*)"', source)
    textes += re.findall(r'aria-label="([^"]*)"', source)
    return " ".join(textes)


def _gabarits_statiques(source: str) -> str:
    """Même extraction que `test_web_avis_ia.py::_gabarits_statiques` --
    couvre les textes construits par interpolation (`` `... ${expr} ...` ``),
    invisibles pour `_textes_affiches` seul."""
    gabarits = re.findall(r"`([^`]*)`", _sans_commentaires(source), re.S)
    return " ".join(re.sub(r"\$\{[^}]*\}", " ", gabarit) for gabarit in gabarits)


# ---------------------------------------------------------------------------
# api/ia.ts — clePrixInternet, lirePrixInternet
# ---------------------------------------------------------------------------


def test_api_ia_prix_internet_contrat() -> None:
    api = _lire("api", "ia.ts")

    assert 'components["schemas"]["PrixInternetLotReponse"]' in api
    assert "export function clePrixInternet" in api
    assert "export function lirePrixInternet" in api
    assert '"/api/ia/prix-internet"' in api


def test_lire_prix_internet_repete_le_parametre_anomalie_id() -> None:
    """Route groupée `GET /api/ia/prix-internet?anomalie_id=…` (T10a) : un
    paramètre `anomalie_id` répété, jamais une liste encodée autrement
    (virgules, JSON) -- `URLSearchParams.append` en boucle, même idiome que
    `api/prix.ts` pour les paramètres simples."""
    api = _lire("api", "ia.ts")
    fonction = api.split("export function lirePrixInternet", 1)[1]
    assert 'parametres.append("anomalie_id", id)' in fonction
    assert "/api/ia/prix-internet?" in fonction


# ---------------------------------------------------------------------------
# lib/prixInternet.ts — logique partagée avec AvisIA.tsx
# ---------------------------------------------------------------------------


def test_lib_prix_internet_expose_les_fonctions_partagees() -> None:
    partage = _lire("lib", "prixInternet.ts")
    assert "export function domaineSource" in partage
    assert "export function texteMontantPrixInternet" in partage


def test_texte_montant_prix_internet_taxes_et_conditionnement_sinon_unite() -> None:
    partage = _lire("lib", "prixInternet.ts")
    fonction = partage.split("export function texteMontantPrixInternet", 1)[1]
    # HT/TTC seulement si présent (`taxes`).
    assert "prixInternet.taxes !== null" in fonction
    assert "parentheseConditionnement(prixInternet)" in fonction
    # Conditionnement sinon unité, jamais les deux à la fois (même règle
    # qu'avant l'extraction T7) -- factorisé dans une fonction interne non
    # exportée, appelée par `texteMontantPrixInternet` ci-dessus.
    assert "prixInternet.conditionnement ?? prixInternet.unite" in partage


# ---------------------------------------------------------------------------
# components/PrixInternetCellule.tsx
# ---------------------------------------------------------------------------


def test_cellule_reutilise_la_logique_partagee() -> None:
    """Brief T10b : « réutilise sa logique d'affichage ... en l'extrayant
    dans une petite fonction/composant partagé plutôt qu'en la recopiant » --
    la cellule appelle les fonctions de `lib/prixInternet.ts`, jamais une
    seconde implémentation locale du calcul du domaine ou du montant."""
    cellule = _lire("components", "PrixInternetCellule.tsx")
    assert 'from "../lib/prixInternet"' in cellule
    assert "domaineSource(prixInternet.source_url)" in cellule
    assert "texteMontantPrixInternet(prixInternet)" in cellule
    assert "function domaineSource(" not in cellule
    assert "new URL(" not in cellule


def test_cellule_couvre_toutes_les_alertes_de_prix() -> None:
    """Décision D1 (01/10/2026) : la colonne « Internet » et son bouton
    couvrent toutes les alertes de prix, plus seulement R22 -- la cellule ne
    filtre plus sur la règle et ne reçoit plus la rangée."""
    cellule = _lire("components", "PrixInternetCellule.tsx")
    assert '"R22"' not in _sans_commentaires(cellule)
    assert "produit.regles" not in cellule
    assert "AlerteProduit" not in cellule


def test_cellule_pas_encore_cherche_bouton_chercher_sur_internet() -> None:
    """Spec 2026-10-01 §3 : sans résultat, ni recherche, ni message, la
    cellule montre le bouton « Chercher sur internet » (plus « en
    attente »)."""
    cellule = _lire("components", "PrixInternetCellule.tsx")
    assert "Chercher sur internet" in cellule
    assert "en attente" not in _sans_commentaires(cellule)
    fin = cellule.split("<Bouton", 1)[1].split("</Bouton>", 1)[0]
    assert "onClick={onRechercher}" in fin
    assert "Chercher sur internet" in fin


def test_cellule_recherche_en_cours_message_et_relance() -> None:
    cellule = _lire("components", "PrixInternetCellule.tsx")
    garde = 'if (lancementEnCours || recherche?.etat === "en_cours") {'
    assert garde in cellule
    suite = cellule.split(garde, 1)[1].split("}", 1)[0]
    assert "Recherche en cours…" in suite
    # Le message d'un refus (409) ou d'un échec s'affiche dans la cellule de
    # la rangée, avec « Réessayer » ; un résultat déjà là garde « Relancer ».
    assert "erreurLancement ??" in cellule
    assert '"Réessayer"' in cellule
    assert '"Relancer"' in cellule
    assert "La recherche a échoué" in cellule


def test_cellule_trouve_montant_date_et_lien_source() -> None:
    cellule = _lire("components", "PrixInternetCellule.tsx")
    assert 'prixInternet.statut === "trouve" && prixInternet.prix !== null' in cellule
    assert "· ${formaterJourMois(prixInternet.consulte_le)}" in cellule
    assert "`source (${sourceDomaine})`" in cellule


def test_cellule_non_verifiable_raison_en_title() -> None:
    cellule = _lire("components", "PrixInternetCellule.tsx")
    garde = 'prixInternet.statut === "non_verifiable"'
    assert garde in cellule
    bloc = cellule.split(garde, 1)[1].split("return", 1)[1].split(";\n  }", 1)[0]
    assert "title={prixInternet.raison ?? undefined}" in bloc
    assert "introuvable" in bloc
    # La raison n'est jamais affichée en clair dans le texte du bloc (elle
    # ne vit que dans l'attribut `title`, jamais lu par un lecteur d'écran
    # au premier plan) -- seule sa présence dans l'attribut compte.
    assert bloc.count("prixInternet.raison") == 1


def test_cellule_lien_source_securise() -> None:
    """Même garde que `AvisIA.tsx` (auto-revue T7, reprise ici, brief
    T10b : « lien ... en https: seulement, rel="noopener noreferrer" »)."""
    cellule = _lire("components", "PrixInternetCellule.tsx")
    assert 'target="_blank"' in cellule
    assert 'rel="noopener noreferrer"' in cellule
    bloc_lien = cellule.split('target="_blank"', 1)[1].split("</a>", 1)[0]
    assert 'rel="noopener noreferrer"' in bloc_lien
    garde_lien = "sourceDomaine !== null && prixInternet.source_url !== null && ("
    assert garde_lien in cellule
    bloc_garde = cellule.split(garde_lien, 1)[1].split(")}", 1)[0]
    assert "href={prixInternet.source_url}" in bloc_garde
    assert cellule.count("href={") == 1
    # Le texte affiché du lien (les enfants de `<a>`, après sa balise
    # ouvrante) montre le domaine calculé, jamais `prixInternet.source_url`
    # recopié tel quel -- seul `href` (l'attribut, jamais lu par un
    # utilisateur) porte l'adresse complète.
    enfants_lien = bloc_lien.split(">", 1)[1]
    assert "source_url" not in enfants_lien
    assert "sourceDomaine" in enfants_lien


def test_cellule_aucun_jargon_visible() -> None:
    cellule = _lire("components", "PrixInternetCellule.tsx")
    texte = f"{_textes_affiches(cellule)} {_gabarits_statiques(cellule)}".lower()
    for mot in MOTS_INTERDITS:
        assert mot not in texte, (
            f"mot interdit « {mot} » visible sur PrixInternetCellule.tsx"
        )
    assert "chercher sur internet" in texte
    assert "recherche en cours" in texte
    assert "introuvable" in texte


# ---------------------------------------------------------------------------
# pages/Prix.tsx — requête, colonne conditionnelle, montage
# ---------------------------------------------------------------------------


def test_prix_page_importe_la_cellule_partagee() -> None:
    page = _lire("pages", "Prix.tsx")
    assert 'from "../components/PrixInternetCellule"' in page
    # Montée une fois dans le tableau, une fois dans la carte -- jamais plus.
    assert page.count("<PrixInternetCellule") == 2


def test_id_internet_pour_un_identifiant_par_rangee() -> None:
    """Décision D1 : toutes les alertes de prix sont couvertes ; une rangée
    est représentée par son premier identifiant d'anomalie (le serveur
    retrouve le produit et le fournisseur à partir de cette alerte)."""
    page = _lire("pages", "Prix.tsx")

    fonction = (
        "function idInternetPour(produit: AlerteProduit): string | undefined {\n"
        "  return produit.anomalie_ids[0];\n"
        "}"
    )
    assert fonction in page
    assert page.count("function idInternetPour(") == 1
    assert "idsInternetPour" not in page


def test_prix_page_requete_un_id_par_rangee_dedoublonne_et_relue_en_cours() -> None:
    page = _lire("pages", "Prix.tsx")

    assert "const id = idInternetPour(produit);" in page
    assert "Array.from(\n        new Set(" in page
    assert ".slice(0, MAX_IDS_PRIX_INTERNET)" in page
    assert "queryKey: clePrixInternet(ids)" in page
    assert "enabled: alertesChargees && ids.length > 0" in page
    # Relecture toutes les 10 s tant qu'une recherche est en cours.
    assert 'some((r) => r.etat === "en_cours")' in page
    assert "10_000" in page


def test_proprietes_internet_lit_la_rangee_par_son_identifiant() -> None:
    """La cellule d'une rangée lit le résultat, l'état de la recherche et le
    message de refus de l'identifiant de la rangée, et lance la recherche
    pour ce même identifiant ; le message d'un 409 reste dans la cellule de
    la rangée cliquée (un message par identifiant)."""
    page = _lire("pages", "Prix.tsx")

    assert page.count("function proprietesInternet(") == 1
    fonction = page.split("function proprietesInternet(", 1)[1].split(
        "async function apresAction", 1
    )[0]
    assert "const id = idInternetPour(produit);" in fonction
    assert "prix[id]" in fonction
    assert "prixInternetLot.data?.recherches?.[id]" in fonction
    assert "erreursRecherche[id]" in fonction
    assert "rechercheMutation.mutate(id)" in fonction
    assert "rechercheMutation.variables === id" in fonction
    assert "lancerRecherchePrix(anomalieId)" in page
    assert "[anomalieId]: messageErreur(erreur," in page


def test_prix_page_colonne_seulement_si_ia_active() -> None:
    """Brief T10b : « si ia_active est faux, ou si la requête échoue, ou
    pendant son chargement : rien ne change » -- `colonneInternetVisible`
    ne dépend que de `prixInternetLot.data?.ia_active`, qui reste
    `undefined` (donc faux une fois comparé à `true`) dans les trois cas."""
    page = _lire("pages", "Prix.tsx")
    assert (
        "const colonneInternetVisible = prixInternetLot.data?.ia_active === true;"
        in page
    )

    # En-tête du tableau : la colonne « Internet » n'apparaît que sous cette
    # garde, juste après « Dernier prix facturé ».
    entete = page.split(
        '<th scope="col" className="px-5 py-3">Dernier prix facturé</th>', 1
    )[1]
    entete_colonne = entete.split(
        '<th scope="col" className="px-5 py-3">Écart</th>', 1
    )[0]
    assert "colonneInternetVisible &&" in entete_colonne
    assert ">Internet<" in entete_colonne


def test_prix_page_carte_telephone_ligne_internet_au_meme_endroit() -> None:
    page = _lire("pages", "Prix.tsx")
    bloc = page.split("Dernier prix facturé</dt>", 1)[1].split("Écart</dt>", 1)[0]
    assert "colonneInternetVisible &&" in bloc
    assert ">Internet<" in bloc
    assert "<PrixInternetCellule {...internet} />" in bloc
    assert "<PrixInternetCellule {...proprietesInternet(produit)} />" in page


def test_prix_page_colspan_actions_suit_la_colonne_internet() -> None:
    page = _lire("pages", "Prix.tsx")
    assert "colSpan={colonneInternetVisible ? 7 : 6}" in page


def test_prix_page_sans_jargon_sur_la_colonne_internet() -> None:
    page = _lire("pages", "Prix.tsx")
    texte = f"{_textes_affiches(page)} {_gabarits_statiques(page)}".lower()
    for mot in MOTS_INTERDITS:
        assert mot not in texte, f"mot interdit « {mot} » visible sur Prix.tsx"
