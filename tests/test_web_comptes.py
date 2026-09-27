from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).parents[1] / "web" / "src"


def test_route_comptes_est_admin() -> None:
    app = (WEB / "App.tsx").read_text(encoding="utf-8")

    assert 'path="comptes"' in app
    declaration = app.split('path="comptes"', 1)[1].split("path=", 1)[0]
    assert "GardeAdmin" in declaration
    assert "<Comptes />" in declaration


def test_navigation_comptes_a_cote_de_reglages_et_journal() -> None:
    """Lien discret « Comptes », comme Réglages/Journal (brief Task 11) —
    présent à la fois dans la barre latérale (ordinateur) et la seconde
    rangée de l'en-tête compact (téléphone)."""
    gabarit = (WEB / "components" / "Gabarit.tsx").read_text(encoding="utf-8")

    assert '<NavLink to="/comptes" className={classesLienDiscret}>' in gabarit
    assert '<NavLink to="/comptes" className={classesLienEnTete}>' in gabarit
    assert gabarit.count('to="/comptes"') == 2


def test_reglages_a_un_lien_vers_comptes() -> None:
    reglages = (WEB / "pages" / "Reglages.tsx").read_text(encoding="utf-8")

    assert 'to="/comptes"' in reglages
    assert "Gérer les comptes" in reglages


def test_ecran_comptes_actions_et_mots_de_passe() -> None:
    page = (WEB / "pages" / "Comptes.tsx").read_text(encoding="utf-8")

    for libelle in (
        "Nouveau compte",
        "Modifier",
        "Changer le mot de passe",
        "Retirer l'accès",
        "Rétablir l'accès",
    ):
        assert libelle in page

    # Confirmation de retrait d'accès : texte imposé par le brief.
    assert (
        "ne pourra plus se connecter ni déposer de bons. "
        "Son nom reste sur les bons déjà déposés." in page
    )

    # Mot de passe provisoire : jamais réaffiché, jamais en clair dans le
    # DOM (`type="password"`), jamais autocomplété comme un mot de passe
    # existant.
    assert page.count('type="password"') >= 2
    assert 'autoComplete="new-password"' in page
    assert "12 caractères minimum, à transmettre à la personne" in page
    assert "hashed_password" not in page
    assert "mdp_hash" not in page


def test_ecran_comptes_champs_de_liste() -> None:
    """Contenu de la liste (spec §3) : nom, e-mail, rôle, agence, Telegram,
    état d'accès — libellés en toutes lettres, jamais la valeur brute de
    l'API (`admin`/`agent`)."""
    page = (WEB / "pages" / "Comptes.tsx").read_text(encoding="utf-8")

    assert '"Administrateur"' in page
    assert '"Employé"' in page
    assert "relié" in page
    assert "non relié" in page
    assert "Accès actif" in page
    assert "Accès retiré" in page


def test_ecran_comptes_erreurs_serveur_affichees() -> None:
    page = (WEB / "pages" / "Comptes.tsx").read_text(encoding="utf-8")

    assert 'role="alert"' in page
    assert "erreur.detail" in page
    assert "ErreurApi" in page


def test_ecran_comptes_masque_retirer_acces_sur_sa_propre_ligne() -> None:
    """Note de la Task 10 : « Retirer l'accès » est refusé par le serveur
    sur son propre compte (`ActionSurSoiInterdite`) — le bouton est masqué
    plutôt que laissé à échouer systématiquement."""
    page = (WEB / "pages" / "Comptes.tsx").read_text(encoding="utf-8")

    assert "estSoi" in page


def test_ecran_comptes_a_la_charte() -> None:
    page = (WEB / "pages" / "Comptes.tsx").read_text(encoding="utf-8")

    assert '"../ui"' in page
    assert "<EnTetePage" in page
    assert "<Carte" in page
    assert "<Bouton" in page
    assert "slate-" not in page
    assert "blue-" not in page


def test_ecran_comptes_cartes_telephone_et_tableau_ordinateur() -> None:
    page = (WEB / "pages" / "Comptes.tsx").read_text(encoding="utf-8")

    assert "md:hidden" in page
    assert "hidden overflow-x-auto" in page and "md:block" in page


def test_client_comptes_appelle_les_six_routes() -> None:
    client = (WEB / "api" / "comptes.ts").read_text(encoding="utf-8")

    assert '"/api/comptes"' in client
    assert '"/api/comptes/{compte_id}"' in client
    assert '"/api/comptes/{compte_id}/mot-de-passe"' in client
    assert '"/api/comptes/{compte_id}/retirer-acces"' in client
    assert '"/api/comptes/{compte_id}/retablir-acces"' in client
    assert 'method: "POST"' in client
    assert 'method: "PUT"' in client
    assert "CompteReponse" in client
    assert "hashed_password" not in client
