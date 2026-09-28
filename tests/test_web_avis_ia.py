"""Contrat de la Task T7 (phase 4 IA, spec §6.4) — encart « Avis de l'IA »
du détail d'un problème de prix dans « À régler ». Même principe que
`tests/test_web_synthese_commentaires.py`/`tests/test_web_a_regler.py` :
lecture du texte source des fichiers front, aucun rendu React (le dépôt n'a
pas d'outil de test front, voir `CLAUDE.md`)."""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).parents[1] / "web"
SRC = WEB / "src"

# Mots interdits sur cet encart (même liste que
# `test_web_synthese_commentaires.py::MOTS_INTERDITS`, autre écran qui
# affiche du texte produit ou informé par l'IA) : jargon technique jamais
# montré à l'écran -- « confiance » en particulier, brief T7 : « la
# confiance n'est pas affichée ». « IA » seul reste admis (le client
# l'emploie lui-même).
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


def _textes_affiches(source: str) -> str:
    """Même extraction que `test_web_synthese_commentaires.py::
    _textes_affiches` : texte JSX statique entre balises, plus
    `placeholder`/`aria-label` -- jamais une expression dynamique (`{...}`)
    ni un `className`."""
    textes = re.findall(r">([^<{]+)<", source)
    textes += re.findall(r'placeholder="([^"]*)"', source)
    textes += re.findall(r'aria-label="([^"]*)"', source)
    return " ".join(textes)


def test_api_ia_avis_contrat() -> None:
    api = _lire("api", "ia.ts")

    assert 'components["schemas"]["ExplicationAlerteReponse"]' in api
    assert 'components["schemas"]["PrixInternetReponse"]' in api
    assert 'components["schemas"]["AvisIAReponse"]' in api

    assert "export function cleAvisIA" in api
    assert "export function lireAvisIA" in api
    assert '"/api/ia/anomalies/{anomalie_id}"' in api
    assert "/api/ia/anomalies/${anomalieId}" in api


def test_avis_ia_appelle_la_route_avec_sa_propre_cle() -> None:
    composant = _lire("components", "AvisIA.tsx")

    assert "lireAvisIA" in composant
    assert "cleAvisIA" in composant
    assert "queryKey: cleAvisIA(anomalieId)" in composant


def test_probleme_detail_monte_avis_ia_une_seule_fois_pour_la_categorie_prix() -> None:
    detail = _lire("pages", "ProblemeDetail.tsx")

    assert 'from "../components/AvisIA"' in detail
    assert detail.count("<AvisIA") == 1

    # Même critère que celui déjà utilisé pour la catégorie affichée
    # (brief T7) : `categorieFiltreProbleme`, jamais une nouvelle table de
    # règles recopiée ici -- le montage tient sur une seule condition, juste
    # avant `<AvisIA`.
    montage = (
        'categorieFiltreProbleme({ kind: "anomalie", id: "", anomalie })'
        ' === "prix" && (\n'
        "        <AvisIA anomalieId={anomalie.id} />\n"
        "      )}"
    )
    assert montage in detail

    # Monté sous la phrase du problème (« Pourquoi c'est signalé »), jamais
    # avant.
    assert detail.index("phraseProbleme(anomalie)") < detail.index("<AvisIA")


def test_avis_ia_textes_exacts() -> None:
    composant = _lire("components", "AvisIA.tsx")

    for texte in (
        "Avis de l'IA — à titre indicatif",
        "Prix trouvé sur internet : ",
        "Voir la source (",
        "Prix introuvable sur internet : ",
        "consulté le ",
    ):
        assert texte in composant, texte


def test_avis_ia_rien_si_ia_eteinte_ou_avis_vide() -> None:
    """Brief T7 : « rien du tout si `ia_active` est faux, ou si ni
    explication ni prix »."""
    composant = _lire("components", "AvisIA.tsx")

    garde = "if (!iaActive || (explication === null && prixInternet === null)) {"
    assert garde in composant
    suite = composant.split(garde, 1)[1].split("}", 1)[0]
    assert "return null;" in suite


def test_avis_ia_rien_pendant_le_chargement_ou_en_cas_derreur() -> None:
    """Brief T7 : « pendant le chargement ou en cas d'erreur : rien
    (l'avis est un bonus, jamais un blocage) » -- jamais un message
    affiché, contrairement à `SyntheseCommentaires` (carte de la Vue
    d'ensemble, brief différent)."""
    composant = _lire("components", "AvisIA.tsx")

    garde = (
        "if (avis.isPending || avis.isError || avis.data === undefined) {\n"
        "    return null;\n"
        "  }"
    )
    assert garde in composant
    # Cette garde précède toute lecture de `avis.data` -- rien n'est monté
    # avant de savoir que la requête a réussi.
    assert composant.index(garde) < composant.index("avis.data;")
    # Aucun texte affiché pendant le chargement ou en erreur (pas de
    # `role="status"` ni de message, à la différence de
    # `SyntheseCommentaires`, dont le brief est différent).
    assert 'role="status"' not in composant
    assert 'role="alert"' not in composant


def test_avis_ia_lien_source_securise_et_domaine_seul() -> None:
    """Auto-revue T7 : `target="_blank"` toujours accompagné de `rel=
    "noopener noreferrer"`, adresse affichée seulement par son nom de
    domaine (jamais l'URL complète en clair dans le texte affiché)."""
    composant = _lire("components", "AvisIA.tsx")

    assert 'target="_blank"' in composant
    assert 'rel="noopener noreferrer"' in composant
    bloc_lien = composant.split('target="_blank"', 1)[1].split("</a>", 1)[0]
    assert 'rel="noopener noreferrer"' in bloc_lien

    assert "function domaine" in composant
    assert "new URL(url).hostname" in composant
    # Le texte affiché du lien montre le domaine calculé, jamais
    # `prixInternet.source_url` recopié tel quel comme texte -- seul `href`
    # (l'attribut, jamais lu par un utilisateur) porte l'adresse complète.
    assert "Voir la source (${sourceDomaine})" in composant
    texte_lien = composant.split("Voir la source", 1)[1].split("</a>", 1)[0]
    assert "source_url" not in texte_lien


def test_avis_ia_ne_montre_jamais_la_confiance() -> None:
    """Brief T7 : « la confiance n'est pas affichée » -- le champ
    `PrixInternetReponse.confiance` n'est même pas lu par ce composant (seule
    une mention en commentaire, expliquant pourquoi, reste admise)."""
    composant = _lire("components", "AvisIA.tsx")
    assert "prixInternet.confiance" not in composant
    assert "confiance:" not in composant
    assert ".confiance" not in composant


def test_avis_ia_aucun_jargon_visible() -> None:
    composant = _lire("components", "AvisIA.tsx")
    texte = _textes_affiches(composant).lower()
    for mot in MOTS_INTERDITS:
        assert mot not in texte, f"mot interdit « {mot} » visible sur AvisIA.tsx"
    assert "l'ia" in texte or "'ia" in texte
