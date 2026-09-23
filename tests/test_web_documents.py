"""Contrats front de la Task 8 (refonte front) : page BL (`PageBl.tsx`),
liste unifiée « Documents » (`DocumentsListe.tsx`), routage (`App.tsx`) et
habillage de `DocumentDetail.tsx`/`FactureDetail.tsx`. Chaînes exactes
listées dans `.superpowers/sdd/2026-09-23-refonte-front/task-8-brief.md`."""

from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).parents[1]
WEB = RACINE / "web" / "src"


def test_client_documents_expose_comparaison_et_telechargement() -> None:
    client = (WEB / "api" / "documents.ts").read_text()

    assert "export function obtenirComparaisonBl" in client
    assert "/comparaison" in client
    assert "export function urlTelechargement" in client
    assert "telechargement=true" in client
    assert 'components["schemas"]["ComparaisonBlReponse"]' in client
    assert 'components["schemas"]["LigneCompareeReponse"]' in client


def test_page_bl_contrat() -> None:
    page = (WEB / "pages" / "PageBl.tsx").read_text()

    for chaine in (
        "Télécharger la photo",
        "download",
        "urlTelechargement",
        "Ouvrir en grand",
        "Livré et facturé",
        "Corriger la lecture du bon",
        "Quantités vérifiées par l'équipe",
        "obtenirComparaisonBl",
        "Prix unit.",
        "Contrôle",
        "md:hidden",
        "FilAriane",
    ):
        assert chaine in page, chaine

    assert "alt={`Photo du bon de livraison" in page

    # Sans jargon visible (spec §5) : aucun code de règle brut, aucun des
    # mots interdits dans les chaînes affichées. Mots entiers seulement
    # (`\b`) : « bloc » ne doit pas confondre `md:block` (classe Tailwind).
    for jargon in ("bloc", "alias", "rapprochement", "OCR", "anomalie"):
        assert re.search(rf"\b{jargon}\b", page) is None, jargon
    for n in range(1, 18):
        assert f"R{n:02d}" not in page, f"R{n:02d}"


def test_page_bl_reserve_la_comparaison_et_la_correction_a_ladmin() -> None:
    """Agent : image, téléchargement, statut de confirmation, pas de
    comparaison (brief) — la carte « Livré et facturé » n'est montée que
    lorsque `estAdmin` (et le document est un BL, la comparaison n'existant
    pas pour un enlèvement — `ingest/comparaison_bl.py`) ; la section de
    correction n'est montée que lorsque le document est `modifiable`
    (calculé côté serveur : admin et non archivé)."""
    page = (WEB / "pages" / "PageBl.tsx").read_text()

    assert "estAdmin && estBl && (" in page
    assert "donnees.modifiable && <SectionCorrection" in page
    assert "enabled: id !== undefined && estAdmin && estBl" in page


def test_documents_liste_contrat() -> None:
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    for chaine in (
        "Tous",
        "Factures",
        "Bons de livraison",
        "À corriger",
        "Déposer une facture",
        "md:hidden",
        "Filtres",
        "EnTetePage",
    ):
        assert chaine in page, chaine


def test_documents_liste_reserve_le_depot_et_les_factures_a_ladmin() -> None:
    page = (WEB / "pages" / "DocumentsListe.tsx").read_text()

    assert "if (!estAdmin) {" in page
    assert "return <VueAgent" in page
    assert "enabled: estAdmin" in page


def test_routes_documents_montent_pagebl_et_documentsliste() -> None:
    app = (WEB / "App.tsx").read_text()

    for chemin, composant in (
        ('path="documents"', "DocumentsListe"),
        ('path="documents/:id"', "PageBl"),
        ('path="bl/:id"', "PageBl"),
    ):
        assert chemin in app
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert f"<{composant}" in declaration, chemin
        assert "GardeAdmin" not in declaration, chemin


def test_anciennes_routes_factures_redirigent_vers_documents() -> None:
    """Reprise complète (brief Task 8) : `DocumentsListe` couvre le dépôt et
    la liste des factures, `/documents/:id` sait afficher une facture — les
    deux anciennes routes deviennent de vraies redirections, plus des
    écrans transitoires (contrairement à `/anomalies`, toujours sans
    remplaçant)."""
    app = (WEB / "App.tsx").read_text()

    for chemin in ('path="factures"', 'path="factures/:id"'):
        assert chemin in app
        declaration = app.split(chemin, 1)[1].split("path=", 1)[0]
        assert "RedirectionAncienneUrl" in declaration, chemin
        assert "FacturesListe" not in declaration, chemin
        assert "FactureDetail" not in declaration, chemin

    declaration = app.split('path="factures/:id"', 1)[1].split("path=", 1)[0]
    assert "/documents/${p.id" in declaration


def test_anciens_fichiers_supprimes_apres_reprise() -> None:
    for nom in ("BlDeposes.tsx", "FacturesListe.tsx"):
        assert not (WEB / "pages" / nom).exists(), nom

    app = (WEB / "App.tsx").read_text()
    assert "BlDeposes" not in app
    assert "FacturesListe" not in app


def test_facture_detail_habille_en_livraisons_et_garde_lancre_de_bloc() -> None:
    """Détail facture (`/documents/:id` quand le type est une facture,
    brief) : les blocs sont présentés comme des « livraisons » — jamais un
    « bloc » dans le texte affiché — et l'ancre `id={`bloc-${bloc.id}`}`,
    ciblée depuis d'autres écrans (`BilanFournisseur.tsx`, ancre `#bloc-`),
    reste inchangée malgré l'habillage."""
    page = (WEB / "pages" / "FactureDetail.tsx").read_text()

    assert "Livraisons (" in page
    assert "id={`bloc-${bloc.id}`}" in page
    assert "Blocs BL" not in page
    assert "OCR" not in page
    assert "FilAriane" in page


def test_document_detail_reste_la_correction_montee_par_pagebl() -> None:
    """La logique de correction existante (formulaire, ré-extraction,
    validation, archivage) est conservée intégralement — seulement habillée
    et amputée de son ancien en-tête de page (photo, titre, badge, ligne de
    confirmation, tous désormais affichés par `PageBl`)."""
    page = (WEB / "pages" / "DocumentDetail.tsx").read_text()

    for fonction in (
        "FormulaireEntete",
        "TableauLignesEdition",
        "corrigerEntete",
        "corrigerLignes",
        "validerDocument",
        "archiverDocument",
        "relancerExtraction",
    ):
        assert fonction in page, fonction

    # Plus d'en-tête de page dupliqué : ni photo, ni titre, ni statut/
    # confirmation redondants avec `PageBl` (le composant local `Photo` et
    # les libellés de statut du document ont été retirés à la Task 8).
    assert "function Photo(" not in page
    assert "<h1" not in page

    for jargon in (
        "bg-slate-",
        "text-slate-",
        "bg-blue-",
        "bg-orange-",
        "bg-red-",
        "bg-green-",
    ):
        assert jargon not in page, jargon
