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
CLE_MISTRAL_INVENTEE = "cle-mistral-invente-pour-les-tests"
COMPTE_SERVICE_DRIVE_INVENTE = '{"private_key":"cle-privee-inventee"}'


def _regler_environnement_complet(
    monkeypatch: pytest.MonkeyPatch, docs_dir: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://bl:x@localhost:5432/bl")
    monkeypatch.setenv("DOCS_DIR", str(docs_dir))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN_INVENTE)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET_INVENTE)
    monkeypatch.setenv("TELEGRAM_CHAT_BL_ID", "-1000000000001")
    monkeypatch.setenv("TELEGRAM_CHAT_SUPERVISION_ID", "-1000000000002")
    monkeypatch.setenv("MISTRAL_API_KEY", CLE_MISTRAL_INVENTEE)
    monkeypatch.setenv("COOKIE_SECURE", "true")


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
    assert settings.telegram_chat_bl_id == -1000000000001
    assert settings.telegram_chat_supervision_id == -1000000000002
    assert settings.mistral_api_key.get_secret_value() == CLE_MISTRAL_INVENTEE


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


def test_telegram_chat_bl_id_manquant_leve_et_nomme_la_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("TELEGRAM_CHAT_BL_ID", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "telegram_chat_bl_id" in str(exc_info.value)


def test_telegram_chat_supervision_id_manquant_leve_et_nomme_la_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("TELEGRAM_CHAT_SUPERVISION_ID", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "telegram_chat_supervision_id" in str(exc_info.value)


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


def test_mistral_api_key_manquante_leve_et_nomme_la_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "mistral_api_key" in str(exc_info.value)


def test_mistral_api_key_absente_du_repr_de_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Même exigence que le token Telegram (`SecretStr`) : la clé Mistral ne
    doit jamais apparaître dans un affichage accidentel de `Settings`."""
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert CLE_MISTRAL_INVENTEE not in repr(settings)


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


def test_cookie_secure_manquant_leve_et_nomme_la_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("COOKIE_SECURE", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "cookie_secure" in str(exc_info.value)


def test_extra_est_ignoree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Le `.env` porte aussi des variables compose/restic/tests non lues."""
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.setenv("POSTGRES_PASSWORD", "ignoree-par-settings")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert not hasattr(settings, "postgres_password")


def test_controle_prix_actif_absent_vaut_faux(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Décision d'Ilane du 24/09/2026 (`docs/dette.md`) : `CONTROLE_PRIX_ACTIF`
    est optionnelle (contrairement aux variables ci-dessus, son absence ne
    lève jamais de `ValidationError`) et vaut `False` par défaut -- les
    contrôles de prix R07/R08/R09 restent désactivés tant qu'elle n'est pas
    explicitement mise à `true`."""
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("CONTROLE_PRIX_ACTIF", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.controle_prix_actif is False


def test_controle_prix_actif_peut_etre_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.setenv("CONTROLE_PRIX_ACTIF", "true")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.controle_prix_actif is True


def test_controle_livre_non_facture_actif_absent_vaut_faux(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Décision d'Ilane du 24/09/2026, seconde demande du jour (`docs/dette
    .md`) : `CONTROLE_LIVRE_NON_FACTURE_ACTIF` est optionnelle (son absence
    ne lève jamais de `ValidationError`) et vaut `False` par défaut -- R06
    reste désactivée tant qu'elle n'est pas explicitement mise à `true`."""
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("CONTROLE_LIVRE_NON_FACTURE_ACTIF", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.controle_livre_non_facture_actif is False


def test_controle_livre_non_facture_actif_peut_etre_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.setenv("CONTROLE_LIVRE_NON_FACTURE_ACTIF", "true")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.controle_livre_non_facture_actif is True


def test_controle_prix_et_controle_livre_non_facture_sont_independants(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Les deux drapeaux se lisent et s'activent indépendamment l'un de
    l'autre -- jamais un seul interrupteur qui gouvernerait les deux."""
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.setenv("CONTROLE_PRIX_ACTIF", "true")
    monkeypatch.delenv("CONTROLE_LIVRE_NON_FACTURE_ACTIF", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.controle_prix_actif is True
    assert settings.controle_livre_non_facture_actif is False


def test_drive_reste_optionnel_et_son_secret_est_masque(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")

    sans_drive = Settings(_env_file=None)  # type: ignore[call-arg]

    assert sans_drive.google_drive_service_account_json is None
    assert sans_drive.google_drive_folder_id is None

    monkeypatch.setenv(
        "GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", COMPTE_SERVICE_DRIVE_INVENTE
    )
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "dossier-invente")
    avec_drive = Settings(_env_file=None)  # type: ignore[call-arg]

    assert avec_drive.google_drive_service_account_json is not None
    assert (
        avec_drive.google_drive_service_account_json.get_secret_value()
        == COMPTE_SERVICE_DRIVE_INVENTE
    )
    assert avec_drive.google_drive_folder_id == "dossier-invente"
    assert COMPTE_SERVICE_DRIVE_INVENTE not in repr(avec_drive)


# --------------------------------------------------------------------------
# IA / OpenCode (phase 4, brief T3)
# --------------------------------------------------------------------------

MDP_OPENCODE_INVENTE = "mdp-opencode-invente-pour-les-tests"


def test_ia_active_absent_vaut_faux_et_opencode_reste_optionnel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Décision D6 (« Go, implémente déjà tout ») : `IA_ACTIVE` absente vaut
    `False`, et l'application démarre sans `OPENCODE_URL`/
    `OPENCODE_MOT_DE_PASSE`."""
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("IA_ACTIVE", raising=False)
    monkeypatch.delenv("OPENCODE_URL", raising=False)
    monkeypatch.delenv("OPENCODE_MOT_DE_PASSE", raising=False)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.ia_active is False
    assert settings.opencode_url is None
    assert settings.opencode_mot_de_passe is None
    assert settings.ia_appels_max_jour == 40


def test_ia_active_sans_opencode_url_refuse_et_nomme_la_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.setenv("IA_ACTIVE", "true")
    monkeypatch.delenv("OPENCODE_URL", raising=False)
    monkeypatch.setenv("OPENCODE_MOT_DE_PASSE", MDP_OPENCODE_INVENTE)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "OPENCODE_URL" in str(exc_info.value)


def test_ia_active_avec_opencode_url_vide_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """« Absent ou vide » (brief T3) : une chaîne vide vaut absence."""
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.setenv("IA_ACTIVE", "true")
    monkeypatch.setenv("OPENCODE_URL", "")
    monkeypatch.setenv("OPENCODE_MOT_DE_PASSE", MDP_OPENCODE_INVENTE)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "OPENCODE_URL" in str(exc_info.value)


def test_ia_active_sans_mot_de_passe_refuse_et_nomme_la_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.setenv("IA_ACTIVE", "true")
    monkeypatch.setenv("OPENCODE_URL", "http://opencode:4096")
    monkeypatch.delenv("OPENCODE_MOT_DE_PASSE", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "OPENCODE_MOT_DE_PASSE" in str(exc_info.value)


def test_ia_active_avec_mot_de_passe_vide_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fix round 1 : « absent ou vide » (brief T3) vaut aussi pour
    `OPENCODE_MOT_DE_PASSE`, même garde que pour `OPENCODE_URL` vide
    (`test_ia_active_avec_opencode_url_vide_refuse`)."""
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.setenv("IA_ACTIVE", "true")
    monkeypatch.setenv("OPENCODE_URL", "http://opencode:4096")
    monkeypatch.setenv("OPENCODE_MOT_DE_PASSE", "")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "OPENCODE_MOT_DE_PASSE" in str(exc_info.value)


def test_ia_active_complete_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.setenv("IA_ACTIVE", "true")
    monkeypatch.setenv("OPENCODE_URL", "http://opencode:4096")
    monkeypatch.setenv("OPENCODE_MOT_DE_PASSE", MDP_OPENCODE_INVENTE)
    monkeypatch.setenv("IA_APPELS_MAX_JOUR", "10")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.ia_active is True
    assert settings.opencode_url == "http://opencode:4096"
    assert settings.opencode_mot_de_passe is not None
    assert settings.opencode_mot_de_passe.get_secret_value() == MDP_OPENCODE_INVENTE
    assert settings.ia_appels_max_jour == 10


def test_ia_appels_max_jour_zero_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`Field(ge=1)` : vérifié même IA éteinte (pas de garde conditionnée à
    `ia_active`, contrairement à `OPENCODE_URL`/`OPENCODE_MOT_DE_PASSE`)."""
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.delenv("IA_ACTIVE", raising=False)
    monkeypatch.setenv("IA_APPELS_MAX_JOUR", "0")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    assert "ia_appels_max_jour" in str(exc_info.value)


def test_opencode_mot_de_passe_absent_du_repr_de_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _regler_environnement_complet(monkeypatch, tmp_path / "docs-inventes")
    monkeypatch.setenv("IA_ACTIVE", "true")
    monkeypatch.setenv("OPENCODE_URL", "http://opencode:4096")
    monkeypatch.setenv("OPENCODE_MOT_DE_PASSE", MDP_OPENCODE_INVENTE)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert MDP_OPENCODE_INVENTE not in repr(settings)
