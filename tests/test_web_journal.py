from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).parents[1] / "web" / "src"


def test_route_et_navigation_journal_sont_admin() -> None:
    app = (WEB / "App.tsx").read_text(encoding="utf-8")
    gabarit = (WEB / "components" / "Gabarit.tsx").read_text(encoding="utf-8")

    assert 'path="journal"' in app
    assert "<Journal />" in app
    assert 'to="/journal"' in gabarit
    assert "Journal" in gabarit


def test_lib_journal_connait_chantier_modifie() -> None:
    journal_lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    assert 'chantier_modifie: "Chantier modifié"' in journal_lib


def test_ecran_journal_a_la_charte() -> None:
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    assert '"../ui"' in page
    assert "<EnTetePage" in page
    assert "<Carte" in page
    assert "<Filtres" in page
    assert "EtatVide" in page
    # Ancienne palette Tailwind par défaut entièrement remplacée par les
    # jetons de la charte (habillage complet, pas un correctif partiel).
    assert "slate-" not in page


def test_ecran_journal_tableau_ordinateur_cartes_telephone() -> None:
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    # Tableau conservé pour l'ordinateur (>= md), masqué sur téléphone ;
    # les mêmes entrées sont présentées en cartes empilées sous `md`
    # (contrainte téléphone = cible à part entière).
    assert "<table" in page
    assert "md:hidden" in page
    assert "hidden" in page and "md:block" in page


def test_ecran_journal_filtres_toujours_combinables() -> None:
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")

    assert "ACTIONS_CONNUES" in page
    assert "CIBLES_CONNUES" in page
    assert "utilisateurId" in page or "utilisateur_id" in page
    assert "depuis" in page
    assert "jusquA" in page


def test_ecran_journal_avant_apres_sans_calcul() -> None:
    page = (WEB / "pages" / "Journal.tsx").read_text(encoding="utf-8")
    lib = (WEB / "lib" / "journal.ts").read_text(encoding="utf-8")

    # Aucune règle métier dans le front : la comparaison `avant`/`apres`
    # reste déléguée à `lib/journal.ts` (mise en forme uniquement).
    assert "lignesAvantApres" in page
    assert "lignesAvantApres" in lib
