from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).parents[1]
WEB = RACINE / "web" / "src"


def test_routes_bilan_couvrent_navigation_directe_et_inverse() -> None:
    app = (WEB / "App.tsx").read_text()

    assert 'path="bilan/:chantierId"' in app
    assert 'path="bilan/:chantierId/:fournisseurId"' in app
    assert 'path="bilan/fournisseurs"' in app
    assert 'path="bilan/fournisseurs/:fournisseurId"' in app


def test_client_bilan_couvre_fournisseurs_bl_et_vue_inverse() -> None:
    client = (WEB / "api" / "bilan.ts").read_text()

    assert 'components["schemas"]["LigneBilanFournisseurReponse"]' in client
    assert 'components["schemas"]["LigneBilanBlReponse"]' in client
    assert "/fournisseurs/{fournisseur_id}/chantiers" in client
    assert "/fournisseurs/{fournisseur_id}/bl" in client


def test_bilan_detail_lie_sources_et_anomalies_du_bloc() -> None:
    page = (WEB / "pages" / "BilanFournisseur.tsx").read_text()

    assert "bl_document_id" in page
    assert "#bloc-" in page
    assert "blocId=" in page
    assert "Vue par fournisseur" in (WEB / "pages" / "Bilan.tsx").read_text()


def test_tableau_bl_affiche_le_nombre_anomalies_ouvertes() -> None:
    page = (WEB / "pages" / "BilanFournisseur.tsx").read_text()

    assert ">Anomalies ouvertes</th>" in page
    assert (
        "ligne.montants.nb_anomalies_ouvertes" in page.split("function ListeBl", 1)[1]
    )


def test_filtre_anomalies_accepte_un_bloc_exact() -> None:
    service = (RACINE / "app" / "modules" / "ingest" / "anomalies.py").read_text()
    route = (RACINE / "app" / "modules" / "api" / "anomalies.py").read_text()
    client = (WEB / "api" / "anomalies.ts").read_text()
    page = (WEB / "pages" / "Anomalies.tsx").read_text()

    assert "bloc_id: uuid.UUID | None" in service
    assert "Anomalie.bloc_id == bloc_id" in service
    assert "bloc_id: Annotated[uuid.UUID | None, Query()]" in route
    assert 'params.set("bloc_id", filtres.blocId)' in client
    assert 'parametres.get("blocId")' in page


def test_detail_facture_expose_une_ancre_par_bloc() -> None:
    page = (WEB / "pages" / "FactureDetail.tsx").read_text()

    assert "id={`bloc-${bloc.id}`}" in page
