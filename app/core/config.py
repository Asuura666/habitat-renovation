"""Configuration de l'application, fail-fast.

`Settings` lit les variables d'environnement (et `.env` en local) ; toute
variable absente lève une `ValidationError` qui la nomme, avant même que
l'application ne démarre (voir `app/main.py`, qui appelle `get_settings()`
à l'import du module).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
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

    `telegram_chat_bl_id` et `telegram_chat_supervision_id` (L2-T2) : pas des
    secrets (identifiants de groupe Telegram, pas des jetons), donc des `int`
    ordinaires — le webhook (`app/modules/ingest/router.py`) n'écrit rien
    pour tout `chat_id` différent du premier (L2-D6), et les notifications de
    supervision (L2-D7, L2-D8) partent vers le second.

    `controle_prix_actif` (décision d'Ilane du 24/09/2026, `docs/dette.md`) :
    un seul mois de factures ne permet de fonder aucun « prix habituel » —
    les contrôles de prix (R07 « Prix un peu plus cher », R08 « Prix plus
    cher que d'habitude », R09 « Remise habituelle oubliée »,
    `app.modules.rules.engine`) sont désactivés côté serveur tant que cette
    variable n'est pas explicitement mise à `true`. **Optionnelle**, défaut
    `False` : contrairement aux variables ci-dessus, son absence ne bloque
    jamais le démarrage (aucun interrupteur n'est prévu à l'écran, la
    réactivation est un geste d'administrateur serveur, `.env` puis
    redémarrage). `ingest.commun.regles_desactivees` est la seule fonction
    qui la lit pour en dériver l'ensemble des règles à masquer — jamais une
    seconde lecture de ce drapeau ailleurs dans le code.

    `controle_livre_non_facture_actif` (même décision, 24/09/2026, seconde
    demande d'Ilane le même jour) : aucune preuve encore constatée que R06
    (« Livré mais pas facturé », contrôle différé, `app.modules.ingest
    .suivi`) se produise réellement — désactivée côté serveur par le même
    mécanisme que `controle_prix_actif` (optionnelle, défaut `False`,
    réactivable par le même geste d'administrateur), lue par la même seule
    fonction `ingest.commun.regles_desactivees`.

    `api_docs_actives` (constat sécurité du 24/09/2026) : `/docs`, `/redoc`
    et `/openapi.json` exposent en production le schéma complet de l'API
    (routes, formes de requêtes/réponses) sans aucune authentification —
    lisible par quiconque connaît le domaine. **Optionnelle, défaut
    `False`** : ces trois routes sont désactivées tant que cette variable
    n'est pas explicitement mise à `true` (`app.main` passe
    `docs_url`/`redoc_url`/`openapi_url` à `None` dans ce cas). Ne change
    rien à `web/package.json` (`api:schema`), qui appelle `app.openapi()`
    directement en Python plutôt que de lire l'URL HTTP.

    `ia_active`, `opencode_url`, `opencode_mot_de_passe`, `ia_appels_max_jour`
    (phase 4, D2/D6 de `docs/superpowers/specs/2026-09-27-phase-4-ia-design
    .md`, brief T3) : interrupteur et réglages du client OpenCode
    (`app.modules.ingest.opencode`, seul module qui les lit — `ia_active()`
    y est la seule lecture de `ia_active`). **`ia_active` optionnelle,
    défaut `False`** (« Go, implémente déjà tout, je rajouterai l'abonnement
    après », D6) : tant qu'elle n'est pas explicitement mise à `true`,
    `opencode_url`/`opencode_mot_de_passe` restent optionnelles et
    l'application démarre sans elles. Dès que `ia_active` est vraie, ces
    deux variables deviennent obligatoires (fail-fast, comme les variables
    ci-dessus) : le validateur croisé ci-dessous refuse alors le démarrage
    en nommant celle qui manque (`OPENCODE_URL`/`OPENCODE_MOT_DE_PASSE`),
    jamais sa valeur. `opencode_mot_de_passe` en `SecretStr` (authentification
    HTTP Basic, utilisateur `opencode`) : même garde d'affichage que les
    secrets ci-dessus. `ia_appels_max_jour` (`Field(ge=1)`, défaut `40`) :
    plafond quotidien de requêtes à l'IA, toutes tâches confondues, vérifié
    quel que soit `ia_active` (une valeur absurde reste refusée même IA
    éteinte).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    docs_dir: Path
    telegram_bot_token: SecretStr
    telegram_webhook_secret: SecretStr
    telegram_chat_bl_id: int
    telegram_chat_supervision_id: int
    mistral_api_key: SecretStr
    google_drive_service_account_json: SecretStr | None = None
    google_drive_folder_id: str | None = None
    cookie_secure: bool
    controle_prix_actif: bool = False
    controle_livre_non_facture_actif: bool = False
    api_docs_actives: bool = False
    ia_active: bool = False
    opencode_url: str | None = None
    opencode_mot_de_passe: SecretStr | None = None
    ia_appels_max_jour: int = Field(default=40, ge=1)

    @model_validator(mode="after")
    def _ia_active_exige_opencode(self) -> Settings:
        """Fail-fast (D6) : `ia_active` vraie sans `opencode_url`/
        `opencode_mot_de_passe` (absent ou vide) refuse le démarrage, en
        nommant la variable manquante, jamais sa valeur -- même principe
        que les variables obligatoires ci-dessus, mais conditionné à
        `ia_active` plutôt que toujours requis."""
        if not self.ia_active:
            return self
        if not self.opencode_url:
            raise ValueError(
                "OPENCODE_URL manquant : obligatoire quand IA_ACTIVE est activé"
            )
        if (
            self.opencode_mot_de_passe is None
            or not self.opencode_mot_de_passe.get_secret_value()
        ):
            raise ValueError(
                "OPENCODE_MOT_DE_PASSE manquant : obligatoire quand IA_ACTIVE "
                "est activé"
            )
        return self


@cache
def get_settings() -> Settings:
    """Instance unique de `Settings`, construite une seule fois par processus."""
    return Settings()  # type: ignore[call-arg]
