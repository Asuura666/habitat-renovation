"""Contrat de la Task T5 (phase 4 IA, spec §4.6) — carte « Commentaires de la
semaine » de la Vue d'ensemble. Mêmes principes que
`tests/test_web_vue_ensemble.py`/`tests/test_web_journal.py` : lecture du
texte source des fichiers front, aucun rendu React (le dépôt n'a pas d'outil
de test front, voir `CLAUDE.md`)."""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).parents[1] / "web"
SRC = WEB / "src"

# Mots interdits sur cette carte (brief T5, en plus de la liste déjà utilisée
# par `test_web_journal.py`/`test_web_vue_ensemble.py`) : code d'architecture
# interne et mots techniques de l'IA, jamais montrés à l'écran (« IA » seul
# reste admis, le client l'emploie lui-même).
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
]


def _textes_affiches(source: str) -> str:
    """Même extraction que `test_web_journal.py::_textes_affiches` : texte
    JSX statique entre balises, plus `placeholder`/`aria-label` — jamais une
    expression dynamique (`{...}`) ni un `className` (des utilitaires
    Tailwind comme `block` contiennent « bloc » sans rapport avec le
    jargon métier)."""
    textes = re.findall(r">([^<{]+)<", source)
    textes += re.findall(r'placeholder="([^"]*)"', source)
    textes += re.findall(r'aria-label="([^"]*)"', source)
    return " ".join(textes)


def test_api_ia_contrat() -> None:
    api = (SRC / "api" / "ia.ts").read_text(encoding="utf-8")

    assert 'components["schemas"]["SyntheseAccueilReponse"]' in api
    assert 'components["schemas"]["ActionSyntheseReponse"]' in api
    assert 'components["schemas"]["BonLieReponse"]' in api

    assert "export const cleSyntheseIA" in api
    assert "export function lireSyntheseIA" in api
    assert '"/api/ia/synthese"' in api

    assert "export function marquerActionSynthese" in api
    assert '"/api/ia/synthese/actions/{action_id}/faite"' in api
    assert '"/api/ia/synthese/actions/{action_id}/a-faire"' in api


def test_synthese_commentaires_appelle_les_deux_routes() -> None:
    composant = (SRC / "components" / "SyntheseCommentaires.tsx").read_text(
        encoding="utf-8"
    )

    assert "lireSyntheseIA" in composant
    assert "marquerActionSynthese" in composant
    assert "cleSyntheseIA" in composant
    # Invalidation après cochage/décochage (spec §4.6).
    assert "invalidateQueries" in composant


def test_vue_ensemble_monte_synthese_commentaires_une_seule_fois() -> None:
    page = (SRC / "pages" / "VueEnsemble.tsx").read_text(encoding="utf-8")

    assert 'from "../components/SyntheseCommentaires"' in page
    assert page.count("<SyntheseCommentaires") == 1


def test_synthese_commentaires_textes_exacts() -> None:
    composant = (SRC / "components" / "SyntheseCommentaires.tsx").read_text(
        encoding="utf-8"
    )

    for texte in (
        "Commentaires de la semaine",
        "Rédigé par l'IA — à vérifier",
        "La synthèse des commentaires de la semaine arrive chaque lundi matin.",
        "Encore à faire",
        "faite par",
        "L'envoi a échoué, réessayez.",
        "Voir le bon",
        "semaine du",
    ):
        assert texte in composant, texte


def test_synthese_commentaires_statut_vide() -> None:
    composant = (SRC / "components" / "SyntheseCommentaires.tsx").read_text(
        encoding="utf-8"
    )

    # Statut « vide » (brief T5) : le résumé lui-même porte déjà le texte
    # « Aucun commentaire cette semaine. » côté serveur (`ia_synthese.py::
    # _RESUME_VIDE`) — affiché tel quel, jamais un second message inventé ici.
    assert 'derniere.statut === "vide"' in composant
    assert "derniere.resume" in composant


def test_synthese_commentaires_ia_eteinte_ne_rend_rien() -> None:
    composant = (SRC / "components" / "SyntheseCommentaires.tsx").read_text(
        encoding="utf-8"
    )

    assert "derniere === null && !iaActive" in composant
    assert "return null;" in composant


def test_synthese_commentaires_erreur_non_bloquante() -> None:
    """Brief T5 : une erreur de chargement reste discrète, jamais bloquante
    pour le reste de l'accueil — pas de `role="alert"` proéminent pour cette
    carte, contrairement au reste de l'application (`CommentairesLignes.tsx`,
    par exemple)."""
    composant = (SRC / "components" / "SyntheseCommentaires.tsx").read_text(
        encoding="utf-8"
    )

    assert "synthese.isError" in composant
    bloc_erreur = composant.split("if (synthese.isError)", 1)[1].split("\n\n", 1)[0]
    assert 'role="alert"' not in bloc_erreur


def test_synthese_commentaires_case_a_cocher_accessible() -> None:
    composant = (SRC / "components" / "SyntheseCommentaires.tsx").read_text(
        encoding="utf-8"
    )

    assert 'type="checkbox"' in composant
    # Cible tactile 44 px (brief T5, même convention que le reste du
    # dépôt, ex. `CommentairesLignes.tsx`).
    assert "min-h-[44px]" in composant
    # Case associée à son `<label>` par `htmlFor`/`id` (jamais un lien
    # imbriqué dans ce `<label>` : un clic sur un lien à l'intérieur d'un
    # `<label>` coche aussi la case, comportement natif non voulu ici).
    assert "htmlFor={idCase}" in composant
    assert "id={idCase}" in composant
    bloc_label = composant.split("<label htmlFor={idCase}", 1)[1].split("</label>", 1)[
        0
    ]
    assert "<Link" not in bloc_label
    assert "disabled={mutation.isPending}" in composant


def test_synthese_commentaires_lien_bon_vers_document() -> None:
    composant = (SRC / "components" / "SyntheseCommentaires.tsx").read_text(
        encoding="utf-8"
    )

    assert "to={`/documents/${bon.document_id}`}" in composant
    assert "`Bon ${bon.numero}`" in composant


def test_synthese_commentaires_aucun_jargon_visible() -> None:
    composant = (SRC / "components" / "SyntheseCommentaires.tsx").read_text(
        encoding="utf-8"
    )
    texte = _textes_affiches(composant).lower()
    for mot in MOTS_INTERDITS:
        assert mot not in texte, (
            f"mot interdit « {mot} » visible sur SyntheseCommentaires.tsx"
        )
    # « IA » reste admis (le client l'emploie lui-même, brief T5).
    assert "l'ia" in texte or "'ia" in texte


def test_lib_journal_cibles_synthese() -> None:
    journal_lib = (SRC / "lib" / "journal.ts").read_text(encoding="utf-8")

    assert '"synthese_commentaires"' in journal_lib
    assert '"synthese_action"' in journal_lib
    assert 'synthese_commentaires: "Synthèse des commentaires"' in journal_lib
    assert 'synthese_action: "Action de la synthèse"' in journal_lib

    # `lienCible` : aucune fiche dédiée, les deux cibles renvoient à
    # l'accueil (brief T5, « lien vers `/` pour les deux »).
    assert 'case "synthese_commentaires":' in journal_lib
    assert 'case "synthese_action":' in journal_lib
    bloc = journal_lib.split('case "synthese_commentaires":', 1)[1].split(
        "default:", 1
    )[0]
    assert 'href: "/"' in bloc


def test_lib_journal_cles_detail_synthese() -> None:
    journal_lib = (SRC / "lib" / "journal.ts").read_text(encoding="utf-8")

    for cle, libelle in [
        ("semaine_debut", "Semaine du"),
        ("semaine_fin", "Jusqu'au"),
        ("nb_commentaires", "Commentaires"),
        ("nb_actions", "Actions"),
    ]:
        assert f'{cle}: "{libelle}"' in journal_lib


def test_lib_journal_libelles_action_synthese_non_dupliques() -> None:
    """T4 a déjà posé les trois libellés d'action de la synthèse (note du
    contrôleur du brief T5) : cette tâche ne les duplique pas, elle vérifie
    seulement qu'ils existent toujours, chacun une seule fois."""
    journal_lib = (SRC / "lib" / "journal.ts").read_text(encoding="utf-8")

    for action in (
        "synthese_generee",
        "synthese_action_faite",
        "synthese_action_a_faire",
    ):
        motif = rf'\b{action}:\s*"'
        occurrences = re.findall(motif, journal_lib)
        assert len(occurrences) == 1, (
            f"« {action} » doit apparaître une seule fois dans LIBELLES_ACTION"
        )
