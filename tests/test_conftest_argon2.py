"""`conftest.py` (racine du dépôt) : coût Argon2 réduit pendant la suite.

Le patch qui remplace `fastapi_users.password.Argon2Hasher` par une version
à coût minimal est appliqué au niveau module, dès l'import de
`conftest.py`, avant toute collecte de test (voir son docstring). Ce
fichier vérifie qu'il est bien actif — sur `app.core.auth._password_helper`
comme sur un `PasswordHelper()` neuf — et qu'un hachage/vérification
aller-retour continue de fonctionner avec ces paramètres réduits.
"""

from __future__ import annotations

from fastapi_users.password import PasswordHelper

from app.core import auth

_MOT_DE_PASSE = "mot-de-passe-invente-pour-le-test-1234"


def test_password_helper_de_app_core_auth_est_a_cout_reduit() -> None:
    """`app.core.auth._password_helper` est construit à l'import du module
    `app.core.auth`, donc après le patch de `conftest.py` (chargé avant tout
    autre module par pytest) : son hachage porte les paramètres de test
    (`t=1`, `m=8`), pas ceux par défaut de `pwdlib`/`argon2-cffi` (`t=3`,
    `m=65536`, ≈120-136 ms par hachage d'après l'audit)."""
    hachage = auth._password_helper.hash(_MOT_DE_PASSE)

    assert "t=1" in hachage
    assert "m=8" in hachage


def test_un_nouveau_password_helper_est_aussi_a_cout_reduit() -> None:
    """Le patch vise l'attribut `Argon2Hasher` de `fastapi_users.password`
    lui-même, pas seulement l'instance déjà construite par
    `app.core.auth` : tout `PasswordHelper()` construit après coup (comme
    les `_PASSWORD_HELPER` locaux de `app/modules/api/tests/`, ou celui que
    `GestionnaireUtilisateurs` reconstruit par défaut quand aucun ne lui est
    fourni) en profite aussi."""
    hachage = PasswordHelper().hash(_MOT_DE_PASSE)

    assert "t=1" in hachage
    assert "m=8" in hachage


def test_hachage_verification_aller_retour_reussit_avec_le_bon_mot_de_passe() -> None:
    """Cas positif : malgré le coût réduit, un hachage/vérification
    aller-retour reste correct pour le bon mot de passe."""
    hachage = auth._password_helper.hash(_MOT_DE_PASSE)

    valide, _ = auth._password_helper.verify_and_update(_MOT_DE_PASSE, hachage)

    assert valide is True


def test_hachage_verification_aller_retour_echoue_avec_mauvais_mot_de_passe() -> None:
    """Cas négatif : un mauvais mot de passe reste rejeté, coût réduit ou
    non."""
    hachage = auth._password_helper.hash(_MOT_DE_PASSE)

    valide, _ = auth._password_helper.verify_and_update(
        "un-autre-mot-de-passe-invente-5678", hachage
    )

    assert valide is False
