"""`secret_valide` : comparaison en temps constant de l'en-tête
`X-Telegram-Bot-Api-Secret-Token`."""

from __future__ import annotations

from app.modules.messaging.telegram import secret_valide

ATTENDU = "secret-webhook-invente"


def test_secret_valide_bon_secret_renvoie_true() -> None:
    assert secret_valide(ATTENDU, ATTENDU) is True


def test_secret_valide_mauvais_secret_renvoie_false() -> None:
    assert secret_valide("mauvais-secret", ATTENDU) is False


def test_secret_valide_absent_renvoie_false() -> None:
    assert secret_valide(None, ATTENDU) is False
