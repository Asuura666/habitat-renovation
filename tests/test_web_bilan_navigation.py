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

    # Task 7 de la refonte du front : `chantiers/:chantierId/:fournisseurId`
    # (ex-détail des BL d'un couple chantier/fournisseur, `BilanBl`) est
    # désormais une simple redirection vers la fiche chantier
    # (`FicheChantier` liste elle-même toutes les livraisons, tous
    # fournisseurs confondus) — plus un écran séparé par fournisseur.
    assert 'path="chantiers/:chantierId/:fournisseurId"' in app
    declaration = app.split('path="chantiers/:chantierId/:fournisseurId"', 1)[1].split(
        "path=", 1
    )[0]
    assert "RedirectionAncienneUrl" in declaration
    assert "/chantiers/${p.chantierId" in declaration

    # Les liens de la fiche fournisseur (encore montée sur `fournisseurs/
    # :fournisseurId`, Task 9 de la refonte du front) pointent
    # directement vers la nouvelle URL (pas via la redirection).
    page = (WEB / "pages" / "BilanFournisseur.tsx").read_text()
    assert "/bilan/${chantierId}/${id}" not in page
    assert "/bilan/${ligne.chantier_id}/${fournisseurId}" not in page
    assert "/chantiers/${chantierId}/${id}" in page
    assert "/chantiers/${ligne.chantier_id}/${fournisseurId}" in page


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
    # L'ancien lien « Vue par fournisseur » de `Bilan.tsx` (supprimé, Task 7
    # de la refonte du front) n'est plus nécessaire : « Fournisseurs » est
    # désormais une entrée de navigation principale à part entière (spec §3,
    # voir `test_web_socle.py::test_navigation_cinq_entrees_sans_jargon`).
    assert not (WEB / "pages" / "Bilan.tsx").exists()


def test_tableau_bl_affiche_le_nombre_anomalies_ouvertes() -> None:
    page = (WEB / "pages" / "BilanFournisseur.tsx").read_text()

    assert ">Anomalies ouvertes</th>" in page
    assert (
        "ligne.montants.nb_anomalies_ouvertes" in page.split("function ListeBl", 1)[1]
    )


def test_filtre_anomalies_accepte_un_bloc_exact() -> None:
    """`pages/Anomalies.tsx` (supprimé par la Task 6, refonte du front) lisait
    `?blocId=` : cette fonctionnalité est reprise telle quelle par
    `pages/ARegler.tsx`, qui remplace l'écran (le lien `/anomalies?blocId=
    ...` de `BilanFournisseur.tsx` ci-dessous continue de fonctionner via la
    redirection `/anomalies` -> `/a-regler`, `search` préservé)."""
    service = (RACINE / "app" / "modules" / "ingest" / "anomalies.py").read_text()
    route = (RACINE / "app" / "modules" / "api" / "anomalies.py").read_text()
    client = (WEB / "api" / "anomalies.ts").read_text()
    page = (WEB / "pages" / "ARegler.tsx").read_text()

    assert "bloc_id: uuid.UUID | None" in service
    assert "Anomalie.bloc_id == bloc_id" in service
    assert "bloc_id: Annotated[uuid.UUID | None, Query()]" in route
    assert 'params.set("bloc_id", filtres.blocId)' in client
    assert 'parametres.get("blocId")' in page


def test_detail_facture_expose_une_ancre_par_bloc() -> None:
    page = (WEB / "pages" / "FactureDetail.tsx").read_text()

    assert "id={`bloc-${bloc.id}`}" in page
