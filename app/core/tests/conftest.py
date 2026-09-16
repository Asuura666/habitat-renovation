"""Fixtures locales à `app/core/tests/` : `tests/conftest.py` ne s'applique
qu'aux tests situés sous `tests/`, donc ce dossier a besoin de son propre
backend anyio et de sa propre garantie que `bl_test` est prête. On réutilise
les fonctions pures de `tests/conftest.py` (pas les fixtures, invisibles ici)
pour ne pas dupliquer la logique de création/migration.
"""

from __future__ import annotations

import pytest

from tests.conftest import lire_test_database_url, preparer_base


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def url_base_test_prete() -> str:
    """URL de `bl_test`, garantie créée et migrée à `head`.

    Fixture **synchrone** à dessein : `preparer_base` appelle en interne
    `asyncio.run(...)`, qui échoue si une boucle asyncio tourne déjà (cas
    d'une fixture async, ou d'un appel direct depuis un test `anyio`).
    """
    url = lire_test_database_url()
    preparer_base(url)
    return url
