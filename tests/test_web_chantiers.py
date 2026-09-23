from __future__ import annotations

from pathlib import Path

RACINE = Path(__file__).parents[1]
WEB = RACINE / "web" / "src"


def _lire(*segments: str) -> str:
    chemin = WEB
    for segment in segments:
        chemin = chemin / segment
    return chemin.read_text(encoding="utf-8")


def test_client_referentiels_expose_modifier_chantier_en_put() -> None:
    client = _lire("api", "referentiels.ts")

    assert "modifierChantier" in client
    assert '"PUT"' in client
    assert "/api/chantiers/{chantier_id}" in client
    # `client` transmis à la création (Task 1), pas seulement à la
    # modification.
    signature_creation = client.split("export async function creerChantier", 1)[
        1
    ].split("export interface ModificationChantier", 1)[0]
    assert "client: string | null" in signature_creation
    assert "agence, client }" in signature_creation


def test_ecran_liste_chantiers_a_la_creation_et_au_bandeau_silencieux() -> None:
    page = _lire("pages", "ChantiersListe.tsx")

    assert "Nouveau chantier" in page
    assert "Chantiers sans bon déposé depuis 7 jours" in page
    assert "obtenirChantiersSansDepot" in page
    assert "useSearchParams" in page
    assert 'type="month"' in page
    assert "obtenirAgences" in page
    assert "md:hidden" in page
    assert "md:block" in page
    assert "Exporter en CSV" in page
    assert "Export détaillé (CSV)" in page
    assert "urlExportBilanDetail" in page
    assert "Aucun chantier pour ces filtres." in page
    # Dépôts par agent (CDC §4 « Chantiers & fournisseurs ») : repris ici,
    # faute d'un autre écran de la refonte qui les affiche (Task 7).
    assert "obtenirDepotsParAgent" in page


def test_fiche_chantier_couvre_le_contrat() -> None:
    page = _lire("pages", "FicheChantier.tsx")

    assert "Client :" in page
    assert "Modifier" in page
    assert "Livraisons" in page
    assert "Problèmes ouverts" in page
    assert "FilAriane" in page
    assert "md:hidden" in page
    assert "`/bl/${" in page
    assert "/documents/${" in page
    assert "modifierChantier" in page
    assert "Voir les documents du chantier" in page
    assert "Exporter pour Excel" in page
    assert "?chantier=" in page
    # Aucun calcul métier : ni sur les montants du bilan, ni de somme
    # « conforme » inventée côté front (donnée absente de l'API par
    # chantier — voir docs/dette.md).
    assert "parseFloat" not in page
    assert "Conforme = " not in page


def test_fiche_chantier_est_montee_et_les_anciennes_routes_redirigent() -> None:
    app = _lire("App.tsx")

    assert 'path="chantiers"' in app
    declaration_liste = app.split('path="chantiers"', 1)[1].split("path=", 1)[0]
    assert "<ChantiersListe" in declaration_liste
    assert "GardeAdmin" in declaration_liste

    assert 'path="chantiers/:chantierId"' in app
    declaration_fiche = app.split('path="chantiers/:chantierId"', 1)[1].split(
        "path=", 1
    )[0]
    assert "<FicheChantier" in declaration_fiche
    assert "GardeAdmin" in declaration_fiche

    # `chantiers/referentiel` (ex-« Chantiers & fournisseurs ») et
    # `chantiers/:chantierId/:fournisseurId` (ex-`BilanBl`) sont maintenant
    # de simples redirections (contenu repris par ChantiersListe/
    # FicheChantier) — le lien « Gérer les chantiers » de Gabarit.tsx reste
    # valide (redirige vers `/chantiers`).
    assert 'path="chantiers/referentiel"' in app
    declaration_referentiel = app.split('path="chantiers/referentiel"', 1)[1].split(
        "path=", 1
    )[0]
    assert "RedirectionAncienneUrl" in declaration_referentiel
    assert '"/chantiers"' in declaration_referentiel

    assert 'path="chantiers/:chantierId/:fournisseurId"' in app
    declaration_bl = app.split('path="chantiers/:chantierId/:fournisseurId"', 1)[
        1
    ].split("path=", 1)[0]
    assert "RedirectionAncienneUrl" in declaration_bl
    assert "/chantiers/${p.chantierId" in declaration_bl

    gabarit = _lire("components", "Gabarit.tsx")
    assert "/chantiers/referentiel" in gabarit


def test_bilan_et_chantiers_ne_sont_plus_importes() -> None:
    """`Bilan.tsx`/`Chantiers.tsx` sont supprimés une fois leur contenu repris
    (consigne Task 7) : plus aucune route ne les monte, et les fichiers
    n'existent plus."""
    app = _lire("App.tsx")

    assert 'pages/Bilan"' not in app
    assert 'from "./pages/Chantiers"' not in app
    assert not (WEB / "pages" / "Bilan.tsx").exists()
    assert not (WEB / "pages" / "Chantiers.tsx").exists()


def test_bilan_fournisseur_reste_mais_nest_plus_utilise_par_chantiers() -> None:
    """`BilanFournisseur.tsx` n'est pas supprimé (Task 9 le gère en
    parallèle) : App.tsx cesse seulement de l'utiliser pour les routes
    `chantiers*` (`BilanFournisseursChantier`/`BilanBl` ne sont plus
    montés), les routes `fournisseurs*` gardées par la Task 9 continuent de
    l'utiliser."""
    app = _lire("App.tsx")

    assert (WEB / "pages" / "BilanFournisseur.tsx").exists()
    assert "BilanFournisseursChantier" not in app
    assert "<BilanBl" not in app
    assert "BilanFournisseursGlobal" in app
    assert "BilanChantiersFournisseur" in app


def test_referentiels_agences_et_silencieux_toujours_exposes() -> None:
    referentiels = _lire("api", "referentiels.ts")

    assert '"/api/referentiels/agences"' in referentiels
    assert "CLE_AGENCES" in referentiels
    assert '"/api/referentiels/chantiers-silencieux"' in referentiels
    assert '"/api/referentiels/depots-par-agent"' in referentiels


# ---------------------------------------------------------------------------
# Fix round 1 (revue de Task 7)
# ---------------------------------------------------------------------------


def test_liste_chantiers_expose_le_referentiel_complet() -> None:
    """Constat 1 (Important) : `GET /api/bilan/chantiers` (table financière)
    ne remonte que les chantiers ayant déjà au moins un bloc de facture — un
    chantier neuf, pas encore facturé, ou inactif, restait sans aucun lien
    vers sa fiche. Une carte alimentée par `listerChantiers` (référentiel
    complet, déjà chargé pour le formulaire de création) doit maintenant les
    lister tous, avec le statut Actif/Inactif."""
    page = _lire("pages", "ChantiersListe.tsx")

    assert "Tous les chantiers" in page
    assert "chantiers={chantiers.data}" in page
    assert 'chantier.actif ? "Actif" : "Inactif"' in page

    # Chaque nom du bandeau silencieux mène désormais à la fiche du
    # chantier (avant : du texte simple, sans lien).
    bandeau = page.split("function BandeauSilencieux", 1)[1].split(
        "function CarteTousLesChantiers", 1
    )[0]
    assert "<Link" in bandeau
    assert "lienChantier(chantier.chantier_id" in bandeau


def test_fiche_chantier_dernier_bl_reflete_une_vraie_reception() -> None:
    """Constat 2 (Important) : « Dernier BL déposé » prenait `date_bl` (la
    date imprimée sur la facture) sur toutes les lignes, y compris « Jamais
    reçu »/« Livré sans bon », et affichait « Aucun dépôt enregistré »
    pendant le chargement. Seules les lignes où une photo de BL a été
    rattachée (`bl_document_id`) comptent désormais, le libellé ne prétend
    plus qu'il s'agit d'un dépôt, et rien ne s'affiche avant la fin du
    chargement."""
    page = _lire("pages", "FicheChantier.tsx")

    assert "Dernier BL déposé" not in page
    assert "Dernière livraison reçue" in page
    assert "livraison.ligne.bl_document_id !== null" in page
    assert "livraisonsRecues" in page

    entete = page.split("Dernière livraison reçue", 1)[1].split("chantier.actif &&", 1)[
        0
    ]
    assert "!livraisonsChargees" in entete
    assert "Chargement…" in entete
    assert "Aucune livraison reçue" in entete
    assert "derniereLivraisonRecue" in entete


def test_fiche_chantier_respecte_le_mois_choisi() -> None:
    """Constat 3 (Important) : la fiche ignorait `?mois`, y compris sur les
    anciens liens `/bilan/:c?mois=…` relayés par la redirection — chiffres
    et pastille d'état pouvaient porter sur deux périodes différentes sans
    aucun libellé. La fiche lit désormais `?mois`, le transmet à tous les
    appels et aux exports, n'affiche la pastille que si un mois est choisi,
    et `ChantiersListe` reporte le mois choisi dans ses liens vers la
    fiche."""
    page = _lire("pages", "FicheChantier.tsx")

    assert "useSearchParams" in page
    assert 'parametres.get("mois")' in page
    assert "listerBilanChantiers(filtresActifs)" in page
    assert "listerBilanFournisseurs(id, filtresActifs)" in page
    assert (
        "listerBilanBl(id, fournisseur.fournisseur_id as string, filtresActifs)" in page
    )
    assert "urlExportBilanFournisseurs(id, filtresActifs)" in page
    assert "enabled: moisChoisi" in page
    assert "etatChoisi !== undefined" in page
    assert "libelleAvecPeriode" in page
    assert "tous les mois" in page

    liste = _lire("pages", "ChantiersListe.tsx")
    assert "lienChantier(ligne.chantierId, mois)" in liste
    assert "mois={filtres.mois}" in liste


def test_fiche_chantier_exporte_les_livraisons_par_fournisseur() -> None:
    """Constat 4 (Important) : « Exporter pour Excel » de la fiche
    réutilisait l'export fournisseurs alors que la carte affichée est
    « Livraisons » (niveau BL). Un export CSV par fournisseur résolu, au
    même niveau que ce qui est affiché, s'ajoute désormais à l'export
    fournisseurs existant (gardé, pas retiré)."""
    page = _lire("pages", "FicheChantier.tsx")

    assert "urlExportBilanBl" in page
    assert "Exporter les livraisons" in page
    assert "Exporter pour Excel" in page
    assert (
        "urlExportBilanBl(id, fournisseur.fournisseur_id as string, filtresActifs)"
        in page
    )

    client = _lire("api", "bilan.ts")
    assert "export function urlExportBilanBl" in client
