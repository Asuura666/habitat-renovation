"""Conftest racine (ancêtre commun de `app/` et `tests/`, voir `testpaths`
dans `pyproject.toml`) : allège le coût Argon2 **pendant la suite de
tests uniquement**.

Constat de l'audit « rapidité » : la suite hache ou vérifie un mot de passe
argon2 environ 500 fois (`app.core.auth._password_helper`, le
`_PASSWORD_HELPER` propre à chaque fichier de `app/modules/api/tests/`, et
`GestionnaireUtilisateurs` — qui reconstruit un `PasswordHelper()` par
défaut quand aucun ne lui est fourni). Aux paramètres réels de
`fastapi_users.password.PasswordHelper` (coût par défaut de
`pwdlib`/`argon2-cffi`, ≈120-136 ms par hachage), cela représente à lui
seul environ 65 s de la suite.

`PasswordHelper.__init__` instancie `Argon2Hasher()` sans paramètre ; ce
nom est résolu, à l'appel, dans l'espace de noms du module
`fastapi_users.password` (qui fait `from pwdlib.hashers.argon2 import
Argon2Hasher` en tête de fichier) — pas dans celui de `pwdlib` lui-même. On
remplace donc l'attribut `Argon2Hasher` de `fastapi_users.password` par une
sous-classe qui force un coût minimal (`time_cost=1, memory_cost=8,
parallelism=1` — le minimum accepté par `argon2-cffi`, qui exige
`memory_cost >= 8 * parallelism`), quels que soient les paramètres passés
par l'appelant.

Ce patch doit être en place avant le tout premier `PasswordHelper()`
construit par la suite, donc il s'exécute au niveau module (à l'import de
ce fichier), pas dans un hook comme `pytest_configure` : d'autres
`conftest.py` du dépôt (ex. `app/core/tests/conftest.py`) ou des modules de
test peuvent importer `app.core.auth` — qui construit son propre
`_password_helper` à l'import — avant qu'un hook ne soit exécuté. Pytest
importe toujours le `conftest.py` d'un répertoire avant ceux de ses
sous-répertoires ; celui-ci, à la racine du dépôt, est donc chargé avant
tous les autres.

Ce fichier n'existe que sous pytest : aucun fichier de `app/` n'est
modifié, et ce patch n'a donc aucun effet en production (le hachage y
reste au coût réel de `fastapi_users`).
"""

from __future__ import annotations

import fastapi_users.password as _fastapi_users_password
from pwdlib.hashers.argon2 import Argon2Hasher as _Argon2HasherReel

_COUT_TEST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


class _Argon2HasherCoutReduit(_Argon2HasherReel):
    """`Argon2Hasher` à coût minimal, pour la durée de la suite de tests
    uniquement (voir docstring de module). Les paramètres éventuellement
    passés par l'appelant (aucun en pratique : `PasswordHelper` construit
    `Argon2Hasher()` sans argument) sont ignorés à dessein."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        super().__init__(**_COUT_TEST)  # type: ignore[arg-type]


_fastapi_users_password.Argon2Hasher = (  # type: ignore[attr-defined]
    _Argon2HasherCoutReduit
)
