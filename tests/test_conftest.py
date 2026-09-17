"""`tests/conftest.py::url_base_migrations` (L3-D22) : dérivation pure du nom
de la base de migrations à partir de celui de la base de test.

Ni base ni réseau : ces tests portent uniquement sur la construction de
l'URL (`sqlalchemy.engine.make_url`/`URL.set`), pas sur une connexion réelle
— contrairement à `tests/test_migrations.py`, qui vérifie que la base ainsi
nommée est effectivement utilisable.
"""

from __future__ import annotations

from tests.conftest import url_base_migrations


def test_derive_le_nom_de_base_par_defaut() -> None:
    """Arbre de travail principal : `bl_test` -> `bl_test_migrations`
    (inchangé par rapport au nom auparavant codé en dur)."""
    url = url_base_migrations("postgresql+asyncpg://bl:secret@127.0.0.1:5450/bl_test")

    assert url == "postgresql+asyncpg://bl:secret@127.0.0.1:5450/bl_test_migrations"


def test_derive_le_nom_de_base_pour_un_autre_arbre_de_travail() -> None:
    """Un second arbre de travail, avec sa propre `TEST_DATABASE_URL`
    (`bl_test_wt`), obtient sa propre base de migrations (`bl_test_wt_migrations`)
    plutôt que le nom fixe `bl_test_migrations` de l'arbre principal :
    permet à deux arbres de tester en parallèle sur le même Postgres sans se
    marcher sur les pieds (constat 9 du plan du lot 3)."""
    url = url_base_migrations(
        "postgresql+asyncpg://bl:secret@127.0.0.1:5450/bl_test_wt"
    )

    assert url == "postgresql+asyncpg://bl:secret@127.0.0.1:5450/bl_test_wt_migrations"


def test_conserve_le_mot_de_passe_dans_l_url_rendue() -> None:
    """`str(URL)` masque le mot de passe par défaut : `url_base_migrations`
    doit rendre une URL réellement utilisable (mot de passe en clair)."""
    url = url_base_migrations("postgresql+asyncpg://bl:secret@127.0.0.1:5450/bl_test")

    assert "secret" in url
