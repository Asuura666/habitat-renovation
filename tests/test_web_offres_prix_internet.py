"""Contrat de la tâche 5 (prix internet, plusieurs sources) : écrans page
Prix, Avis de l'IA et Laboratoire. Tests texte, aucun rendu React."""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).parents[1] / "web" / "src"


def _lire(*chemins: str) -> str:
    chemin = SRC.joinpath(*chemins)
    assert chemin.exists(), f"{chemin} est introuvable"
    return chemin.read_text(encoding="utf-8")


def test_composant_offres_liste_sans_lien_non_https() -> None:
    source = _lire("components", "OffresPrixInternet.tsx")

    assert "export function OffresPrixInternet" in source
    assert "domaineSource(" in source
    assert 'rel="noopener noreferrer"' in source
    assert 'target="_blank"' in source
    assert "<details" in source
    assert "min-h-[44px]" in source
    assert "Voir les" in source


def test_resume_des_offres() -> None:
    source = _lire("lib", "prixInternet.ts")

    assert "export function texteResumeOffres" in source
    assert "dès" in source
    assert "sources" in source
    assert "jusqu'à" in source
    assert "nb_sources < 2" in source
    assert "prix_ht_min === null" in source
    # Relecture finale, point 4 : plusieurs sources sans aucun HT connu
    # gardent un résumé (et donc la liste des offres), jamais `null`.
    assert "sources · taxes non précisées" in source
    assert "nb_sources < 2 || prixInternet.prix_ht_min === null" not in source


def test_cellule_et_avis_utilisent_offres_et_resume() -> None:
    for fichier in (
        ("components", "PrixInternetCellule.tsx"),
        ("components", "AvisIA.tsx"),
    ):
        source = _lire(*fichier)
        assert "OffresPrixInternet" in source, fichier
        assert "texteResumeOffres" in source, fichier


def test_laboratoire_affiche_les_offres() -> None:
    source = _lire("pages", "LaboIA.tsx")

    assert "resultat.offres" in source
    assert "domaineSource(" in source
