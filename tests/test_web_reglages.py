from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).parents[1] / "web" / "src"


def test_route_et_navigation_reglages_sont_admin() -> None:
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    gabarit = (WEB / "components" / "Gabarit.tsx").read_text(encoding="utf-8")

    assert 'path="reglages"' in app
    assert "<Reglages />" in app
    assert '<NavLink to="/reglages"' in gabarit
    assert "Réglages" in gabarit


def test_ecran_reglages_affiche_unite_bornes_et_erreurs() -> None:
    page = (WEB / "pages" / "Reglages.tsx").read_text(encoding="utf-8")

    assert "minimum" in page
    assert "maximum" in page
    assert "unite" in page
    assert 'role="alert"' in page
    assert "Enregistrer" in page


def test_ecran_reglages_a_la_charte() -> None:
    page = (WEB / "pages" / "Reglages.tsx").read_text(encoding="utf-8")

    assert '"../ui"' in page
    assert "<EnTetePage" in page
    assert "<Carte" in page
    assert "<Bouton" in page
    # Ancienne palette Tailwind par défaut entièrement remplacée par les
    # jetons de la charte (habillage complet, pas un correctif partiel).
    assert "slate-" not in page
    assert "blue-" not in page


def test_ecran_reglages_largeur_plafonnee_sur_grand_ecran() -> None:
    page = (WEB / "pages" / "Reglages.tsx").read_text(encoding="utf-8")

    assert "max-w-4xl" in page


def test_client_parametres_lit_et_modifie_les_seuils() -> None:
    client = (WEB / "api" / "parametres.ts").read_text(encoding="utf-8")

    assert '"/api/parametres"' in client
    assert '"/api/parametres/{cle}"' in client
    assert 'method: "PUT"' in client


def test_journal_connait_les_modifications_de_parametres() -> None:
    journal = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")
    page = (WEB / "pages" / "Reglages.tsx").read_text(encoding="utf-8")

    assert 'parametre_modifie: "Réglage modifié"' in journal
    assert '"parametre"' in journal
    assert "modification.reset()" in page
