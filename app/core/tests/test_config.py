"""Configuration fail-fast : `Settings` refuse de se construire sans ses
variables obligatoires, en nommant celle(s) qui manque(nt).

`_env_file=None` neutralise la lecture du `.env` réel du dépôt : seul
l'environnement contrôlé par `monkeypatch` compte, pour que ces tests
restent déterministes quel que soit le contenu du `.env` de dev.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

TOKEN_INVENTE = "000000:token-invente-pour-les-tests"
SECRET_INVENTE = "secret-webhook-invente-pour-les-tests"


def _regler_environnement_complet(
    monkeypatch: pytest.MonkeyPatch, docs_dir: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://bl:x@localhost:5432/bl")
    monkeypatch.setenv("DOCS_DIR", str(docs_dir))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN_INVENTE)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET_INVENTE)


def test_toutes_les_variables_presentes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docs_dir = tmp_path / "docs-inventes"
    _regler_environnement_complet(monkeypatch, docs_dir)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.database_url == "postgresql+asyncpg://bl:x@localhost:5432/bl"
    assert settings.docs_dir == docs_dir
    assert settings.telegram_bot_token.get_secret_value() == TOKEN_INVENTE
    assert settings.telegram_webhook_secret.get_secret_value() == SECRET_INVENTE


def test_telegram_bot_token_manquant_leve_et_nomme_la_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "telegram_bot_token" in str(exc_info.value)


def test_telegram_webhook_secret_manquant_leve_et_nomme_la_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "telegram_webhook_secret" in str(exc_info.value)


def test_telegram_bot_token_absent_du_repr_de_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`SecretStr` masque la valeur dans tout affichage (repr/str) : le
    token ne doit jamais apparaître, y compris dans un log accidentel d'un
    objet `Settings`."""
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert TOKEN_INVENTE not in repr(settings)
    assert SECRET_INVENTE not in repr(settings)


def test_database_url_manquante_leve_et_nomme_la_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "database_url" in str(exc_info.value)


def test_docs_dir_manquante_leve_et_nomme_la_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("DOCS_DIR", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "docs_dir" in str(exc_info.value)


def test_extra_est_ignoree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Le `.env` porte aussi des variables compose/restic/tests non lues."""
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.setenv("POSTGRES_PASSWORD", "ignoree-par-settings")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert not hasattr(settings, "postgres_password")
