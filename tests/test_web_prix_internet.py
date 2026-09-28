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


def test_cellule_rangee_sans_r22_tiret() -> None:
    cellule = _lire("components", "PrixInternetCellule.tsx")
    garde = 'if (!produit.regles.includes("R22")) {'
    assert garde in cellule
    suite = cellule.split(garde, 1)[1].split("}", 1)[0]
    assert "TIRET" in suite


def test_cellule_pas_encore_cherche_en_attente() -> None:
    """`undefined` (rangée absente de la réponse groupée) et `null`
    (recherchée sans résultat récent) donnent le même texte -- brief T10b :
    « pas encore cherché -> en attente »."""
    cellule = _lire("components", "PrixInternetCellule.tsx")
    garde = "if (prixInternet === undefined || prixInternet === null) {"
    assert garde in cellule
    suite = cellule.split(garde, 1)[1].split("}", 1)[0]
    assert "en attente" in suite


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
    assert "en attente" in texte
    assert "introuvable" in texte


# ---------------------------------------------------------------------------
# pages/Prix.tsx — requête, colonne conditionnelle, montage
# ---------------------------------------------------------------------------


def test_prix_page_importe_la_cellule_partagee() -> None:
    page = _lire("pages", "Prix.tsx")
    assert 'from "../components/PrixInternetCellule"' in page
    # Montée une fois dans le tableau, une fois dans la carte -- jamais plus.
    assert page.count("<PrixInternetCellule") == 2


def test_ids_internet_pour_envoie_tous_les_ids_dune_rangee_r22() -> None:
    """Fix round 1 (ruling du contrôleur, 28/09) : le brief T10b disait « le
    premier de `anomalie_ids` », mais `regles` et `anomalie_ids` sont deux
    tableaux indépendants -- R22 peut cohabiter avec R20/R24 sur la même
    ligne (`rules/rules/R22.py`, seules ces deux règles peuvent encore se
    déclencher sur une ligne déjà en R22) et une rangée peut grouper
    plusieurs lignes, donc `anomalie_ids[0]` n'est pas forcément celui de
    R22. `idsInternetPour` envoie donc tous les identifiants d'une rangée
    R22, jamais seulement le premier -- le serveur ne renvoie de toute façon
    jamais de clé pour un identifiant qui ne désigne pas une alerte R22
    ouverte et non masquée (brief T10a)."""
    page = _lire("pages", "Prix.tsx")

    fonction = (
        "function idsInternetPour(produit: AlerteProduit): readonly string[] {\n"
        '  return produit.regles.includes("R22") ? produit.anomalie_ids : [];\n'
        "}"
    )
    assert fonction in page
    # Plus aucune indexation par position pour choisir un identifiant --
    # hors commentaires (qui expliquent justement l'erreur corrigée, donc
    # mentionnent `anomalie_ids[0]` en toutes lettres).
    assert "anomalie_ids[0]" not in _sans_commentaires(page)


def test_prix_page_requete_agrege_tous_les_ids_r22_dedupliques() -> None:
    page = _lire("pages", "Prix.tsx")

    # La liste envoyée à la requête groupée agrège `idsInternetPour` de
    # toutes les rangées (donc tous les identifiants des rangées R22, pas un
    # par rangée), dédupliquée et plafonnée -- aucune requête si la liste
    # des alertes n'a pas de rangée R22 (brief T10b : « aucune requête s'il
    # n'y en a pas »), la clé de requête reste dérivée de cette même liste
    # ordonnée (`clePrixInternet(idsR22)`, inchangé).
    assert "alertes.data.flatMap((produit) => idsInternetPour(produit))" in page
    assert "Array.from(new Set(" in page
    assert ".slice(\n        0,\n        MAX_IDS_PRIX_INTERNET,\n      )" in page
    assert "queryKey: clePrixInternet(idsR22)" in page
    assert "enabled: alertesChargees && idsR22.length > 0" in page


def test_prix_internet_pour_selectionne_par_cle_jamais_par_index() -> None:
    """Fix round 1 : une rangée dont `regles` vaut `["R20", "R22"]` et
    `anomalie_ids` vaut `[idR20, idR22]` -- seul `idR22` est une clé de la
    réponse groupée (le serveur ne renvoie jamais de clé pour une anomalie
    qui n'est pas R22). La cellule doit donc afficher la valeur d'`idR22`,
    jamais celle d'`idR20` (« le premier de `anomalie_ids` », l'erreur du
    brief d'origine) : `prixInternetPour` doit chercher, dans l'ordre des
    identifiants de la rangée, le premier présent comme **clé** de la
    réponse (`.find((id) => id in prix)`), jamais indexer par position."""
    page = _lire("pages", "Prix.tsx")

    fonction = (
        "  function prixInternetPour(produit: AlerteProduit): PrixInternet | "
        "null | undefined {\n"
        "    const prix = prixInternetLot.data?.prix;\n"
        "    if (prix === undefined) {\n"
        "      return undefined;\n"
        "    }\n"
        "    const idConnu = produit.anomalie_ids.find((id) => id in prix);\n"
        "    return idConnu === undefined ? undefined : prix[idConnu];\n"
        "  }"
    )
    assert fonction in page
    # Une seule fonction de sélection dans tout le fichier, jamais une
    # variante qui indexerait par position (`anomalie_ids[0]`, l'erreur
    # d'origine du brief T10b) -- hors commentaires.
    assert page.count("function prixInternetPour(") == 1
    assert "anomalie_ids[0]" not in _sans_commentaires(page)


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
    assert (
        "<PrixInternetCellule produit={produit} prixInternet={prixInternet} />" in bloc
    )


def test_prix_page_colspan_actions_suit_la_colonne_internet() -> None:
    page = _lire("pages", "Prix.tsx")
    assert "colSpan={colonneInternetVisible ? 7 : 6}" in page


def test_prix_page_sans_jargon_sur_la_colonne_internet() -> None:
    page = _lire("pages", "Prix.tsx")
    texte = f"{_textes_affiches(page)} {_gabarits_statiques(page)}".lower()
    for mot in MOTS_INTERDITS:
        assert mot not in texte, f"mot interdit « {mot} » visible sur Prix.tsx"
