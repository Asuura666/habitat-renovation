from __future__ import annotations

from pathlib import Path

RACINE_WEB = Path(__file__).parents[1] / "web" / "src"


def test_ecran_bilan_couvre_le_contrat_responsive() -> None:
    page = (RACINE_WEB / "pages" / "Bilan.tsx").read_text()

    assert "useSearchParams" in page
    assert 'type="month"' in page
    assert 'id="filtre-agence"' in page
    assert "<select" in page
    assert '<option value="">Toutes les agences</option>' in page
    assert "obtenirAgences" in page
    assert 'type="search"' not in page
    referentiels = (RACINE_WEB / "api" / "referentiels.ts").read_text()
    assert '"/api/referentiels/agences"' in referentiels
    assert "CLE_AGENCES" in referentiels
    assert "Les quatre montants ne s" in page
    assert "md:hidden" in page
    assert "hidden" in page and "md:block" in page
    assert "Exporter en CSV" in page
    assert "Export détaillé (CSV)" in page
    assert "urlExportBilanDetail" in page
    assert "Aucun chantier pour ces filtres." in page


def test_client_bilan_transmet_les_filtres_et_reste_type_openapi() -> None:
    client = (RACINE_WEB / "api" / "bilan.ts").read_text()

    assert 'components["schemas"]["LigneBilanChantierReponse"]' in client
    assert 'params.set("mois", filtres.mois)' in client
    assert 'params.set("agence", filtres.agence)' in client
    assert '"/api/bilan/chantiers"' in client
    assert '"/api/bilan/chantiers.csv"' in client
    assert '"/api/bilan/detail.csv"' in client
    assert "export function urlExportBilanDetail" in client


def test_bilan_est_accessible_depuis_la_navigation_admin() -> None:
    app = (RACINE_WEB / "App.tsx").read_text()
    gabarit = (RACINE_WEB / "components" / "Gabarit.tsx").read_text()

    assert 'path="bilan"' in app
    assert 'to="/bilan"' in gabarit
