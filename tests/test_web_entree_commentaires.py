"""Touche Entrée dans les champs de commentaire (demande d'Ilane du
29/09/2026) : sur ordinateur, Entrée enregistre ; Maj+Entrée ou Alt+Entrée
passe à la ligne. Sur téléphone, rien ne change (Entrée passe à la ligne,
bouton « Enregistrer »). Même principe que les autres tests du front :
lecture du texte source, aucun rendu React (le dépôt n'a pas d'outil de
test front, voir `CLAUDE.md`)."""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).parents[1] / "web" / "src"


def _lire(*chemins: str) -> str:
    chemin = SRC.joinpath(*chemins)
    assert chemin.exists(), f"{chemin} est introuvable"
    return chemin.read_text(encoding="utf-8")


def test_module_commun_reserve_a_l_ordinateur() -> None:
    module = _lire("lib", "entreeClavier.ts")

    assert "export function gererEntreeCommentaire" in module
    # Ordinateur = souris ou pavé tactile (pointeur fin qui survole) ; un
    # téléphone ou une tablette n'est jamais concerné.
    assert "(hover: hover) and (pointer: fine)" in module
    assert 'evenement.key !== "Enter"' in module


def test_maj_et_alt_passent_a_la_ligne_sans_enregistrer() -> None:
    module = _lire("lib", "entreeClavier.ts")

    assert "evenement.shiftKey" in module
    assert "evenement.altKey" in module
    # Alt+Entrée n'insère rien de lui-même dans un `<textarea>` : le saut de
    # ligne est inséré à la place du curseur.
    assert '"\\n"' in module
    assert "selectionStart" in module


def test_saisie_en_cours_de_composition_jamais_interrompue() -> None:
    """Accents composés, clavier asiatique : Entrée valide la composition,
    jamais le commentaire."""
    module = _lire("lib", "entreeClavier.ts")

    assert "isComposing" in module


def test_commentaire_de_ligne_utilise_le_module_commun() -> None:
    composant = _lire("components", "CommentairesLignes.tsx")

    assert "gererEntreeCommentaire" in composant
    assert "onKeyDown" in composant
    assert "Entrée pour enregistrer, Maj+Entrée pour aller à la ligne" in composant


def test_panneau_contester_ou_ignorer_de_la_page_prix_utilise_le_module_commun() -> (
    None
):
    page = _lire("pages", "Prix.tsx")

    assert "gererEntreeCommentaire" in page
    assert "onKeyDown" in page
    assert "Entrée pour valider, Maj+Entrée pour aller à la ligne" in page


def test_indication_affichee_seulement_sur_ordinateur() -> None:
    for fichier in (("components", "CommentairesLignes.tsx"), ("pages", "Prix.tsx")):
        assert "[@media(hover:hover)_and_(pointer:fine)]:" in _lire(*fichier), fichier
