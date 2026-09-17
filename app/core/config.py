"""Configuration de l'application, fail-fast.

`Settings` lit les variables d'environnement (et `.env` en local) ; toute
variable absente lève une `ValidationError` qui la nomme, avant même que
l'application ne démarre (voir `app/main.py`, qui appelle `get_settings()`
à l'import du module).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Variables d'environnement obligatoires de l'application.

    `extra="ignore"` : le `.env` contient aussi des variables lues par
    Docker Compose, restic ou les tests (ex. `TEST_DATABASE_URL`,
    `POSTGRES_PASSWORD`), qui ne sont pas des champs de `Settings`.

    `telegram_bot_token`, `telegram_webhook_secret` et `mistral_api_key` sont
    en `SecretStr` : ni leur valeur ni celle des autres champs sensibles
    n'apparaît dans un `repr()`, un message d'erreur de validation ou un log
    (aucun de ces secrets ne doit jamais être visible ailleurs que dans
    `.env`, décision du contrôleur T6b pour `mistral_api_key`).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    docs_dir: Path
    telegram_bot_token: SecretStr
    telegram_webhook_secret: SecretStr
    mistral_api_key: SecretStr
    cookie_secure: bool


@cache
def get_settings() -> Settings:
    """Instance unique de `Settings`, construite une seule fois par processus."""
    return Settings()  # type: ignore[call-arg]
