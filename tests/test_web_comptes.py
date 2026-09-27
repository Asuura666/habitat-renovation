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


def test_ecran_comptes_panneaux_de_modification_ont_une_cle_par_compte() -> None:
    """Fix round 1 (constat Important 1) : `FormulaireCompte` (panneau
    « modifier ») et `FormulaireMotDePasse` (panneau « mot-de-passe ») sont
    montés avec une `key` qui dépend du compte visé — sans elle, cliquer
    « Modifier » sur un second compte pendant qu'un premier panneau est
    déjà ouvert réutilisait l'instance en place (titre à jour, champs
    restés ceux du premier compte, soumission silencieuse sur le mauvais
    compte). Même correctif que `ARegler.tsx::ProblemeDetail`
    (`key={problemeActuel.id}`, fix round 1 finding 4)."""
    page = (WEB / "pages" / "Comptes.tsx").read_text(encoding="utf-8")

    assert "key={`modifier-${panneau.compte.id}`}" in page
    assert "key={`mot-de-passe-${panneau.compte.id}`}" in page


def test_ecran_comptes_identifiant_telegram_verifie() -> None:
    """Fix round 1 (constat Important 2) : un identifiant Telegram non
    numérique donnait `Number(...) === NaN`, silencieusement transformé en
    `null` par `JSON.stringify` — la requête réussissait comme si le champ
    était vide. Désormais vérifié par une expression régulière (vide
    toujours valide, facultatif), soumission bloquée et erreur affichée
    sous le champ, accessible (`aria-invalid`/`aria-describedby`)."""
    page = (WEB / "pages" / "Comptes.tsx").read_text(encoding="utf-8")

    assert (
        'const telegramValide = telegramTrim === "" || /^\\d+$/.test(telegramTrim);'
        in page
    )
    assert "telegramValide &&" in page  # dans `champsValides`
    assert "L'identifiant Telegram ne contient que des chiffres." in page
    assert "aria-invalid={!telegramValide}" in page
    assert (
        'aria-describedby={!telegramValide ? "compte-telegram-erreur" : undefined}'
        in page
    )
    assert 'id="compte-telegram-erreur"' in page


def test_ecran_comptes_changement_mot_de_passe_invalide_la_liste() -> None:
    """Minor du fix round 1 : `FormulaireMotDePasse` invalide `CLE_COMPTES`
    à son tour, comme les deux autres mutations d'écriture de l'écran
    (`FormulaireCompte`, `ActionsCompte`) — une seule convention partout."""
    page = (WEB / "pages" / "Comptes.tsx").read_text(encoding="utf-8")

    bloc = page.split("function FormulaireMotDePasse(", 1)[1].split(
        "function ActionsCompte(", 1
    )[0]
    assert "invalidateQueries({ queryKey: CLE_COMPTES })" in bloc


def test_ecran_comptes_boutons_action_sans_hauteur_minimale_inefficace() -> None:
    """Minor du fix round 1 : `min-h-[36px]` n'avait aucun effet sur les
    boutons d'action (le `min-h-[44px]` de `Bouton.tsx` l'emporte dans la
    cascade Tailwind) — classe morte retirée plutôt que laissée en place."""
    page = (WEB / "pages" / "Comptes.tsx").read_text(encoding="utf-8")

    assert "min-h-[36px]" not in page


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
