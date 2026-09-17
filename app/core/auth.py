"""Authentification (lot 2, L2-T1) : connexion par cookie, sessions en base,
limitation du login.

Décisions du brief L2-T1 :
- Transport cookie (`bl_session`, httpOnly, `SameSite=Lax`, `Secure` piloté
  par `Settings.cookie_secure`), stratégie `DatabaseStrategy` de
  fastapi-users sur la table `JetonSession` (L2-D2). Durée de vie 12 h,
  rafraîchie au plus toutes les 5 min par `utilisateur_courant` (expiration
  glissante).
- `POST /api/auth/login` et `POST /api/auth/logout` sont des routes
  minimales (pas le routeur généré par `fastapi_users.get_auth_router`,
  que `slowapi` ne peut pas décorer route par route une fois construit) qui
  réutilisent `GestionnaireUtilisateurs.authenticate` (le gestionnaire) et
  `auth_backend.login`/`strategy.destroy_token` (le backend et la
  stratégie) : aucune logique de hachage ni de session n'est réimplémentée.
- `L2-D4` : ce module importe `Utilisateur` et `JetonSession` depuis
  `app.modules.ingest.models` — le seul endroit de `app/core` autorisé à
  importer un module métier. Tout le reste de `app/modules/api` n'importe
  que ce module (`app.core.auth`), jamais `ingest` directement pour l'auth.
  `Utilisateur` est réexporté explicitement (`as Utilisateur`) : mypy strict
  désactive la réexportation implicite.

Note mypy (type: ignore justifiés) : `Utilisateur`/`JetonSession` ne
satisfont pas *structurellement* `UserProtocol`/`AccessTokenProtocol` selon
mypy, pour deux raisons assumées par L2-D1 : `hashed_password` (`mdp_hash`)
reste nullable — un compte rattaché seulement à Telegram peut n'avoir jamais
de mot de passe, alors que la bibliothèque suppose un mot de passe toujours
présent — et `is_verified`/`is_superuser` sont des propriétés en lecture
seule (dérivées, jamais des colonnes, jamais modifiées dans ce lot : aucune
route d'inscription ni de mise à jour n'est montée). Les alias `UtilisateurDB`,
`JetonSessionDB` et `StrategieSession` ci-dessous portent l'unique
`type: ignore[type-var]` de chaque paramétrage générique, pour ne pas le
répéter à chaque usage.

Gestion des comptes (L2-T1b, décisions du contrôleur) : `creer_utilisateur`
et `desactiver_utilisateur` en bas de fichier sont les seules fonctions
d'écriture sur `Utilisateur`, utilisées par les sous-commandes CLI
`utilisateur-creer`/`utilisateur-desactiver` (`app/cli.py`) — aucune route
HTTP ne les expose dans ce lot (Q3 du brief, décision provisoire). Elles
écrivent directement en base plutôt que de passer par
`BaseUserManager.create` (qui exigerait un schéma Pydantic `UserCreate` et
déclencherait `on_after_register`, tous deux hors périmètre : aucune route
d'inscription n'est montée). Le hachage n'est pas réimplémenté pour autant :
`_password_helper` est la même classe `PasswordHelper` (argon2id par
défaut) que celle que `GestionnaireUtilisateurs` utilise en interne —
stateless, sans configuration propre à une instance particulière.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import exceptions
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy import DatabaseStrategy
from fastapi_users.manager import BaseUserManager, UUIDIDMixin
from fastapi_users.password import PasswordHelper
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.modules.ingest.models import JetonSession, Journal
from app.modules.ingest.models import Utilisateur as Utilisateur

NOM_COOKIE = "bl_session"
DUREE_SESSION_S = 12 * 3600
DELAI_RAFRAICHISSEMENT_S = 5 * 60
# L2-T1b (décisions du contrôleur) : longueur minimale imposée à
# `creer_utilisateur` ci-dessous.
LONGUEUR_MOT_DE_PASSE_MIN = 12
ROLES_VALIDES = ("admin", "agent")

# Voir la note mypy en tête de fichier : chaque paramétrage générique porte
# ici son unique `type: ignore[type-var]`.
UtilisateurDB = SQLAlchemyUserDatabase[Utilisateur, uuid.UUID]  # type: ignore[type-var]
JetonSessionDB = SQLAlchemyAccessTokenDatabase[JetonSession]  # type: ignore[type-var]
StrategieSession = DatabaseStrategy[Utilisateur, uuid.UUID, JetonSession]  # type: ignore[type-var]

_settings = get_settings()

# Réutilisé par `creer_utilisateur` (bas de fichier, L2-T1b) : voir le
# docstring de module pour la justification de ne pas passer par
# `BaseUserManager.create`.
_password_helper = PasswordHelper()

cookie_transport = CookieTransport(
    cookie_name=NOM_COOKIE,
    cookie_max_age=None,
    cookie_secure=_settings.cookie_secure,
    cookie_httponly=True,
    cookie_samesite="lax",
)


def get_utilisateur_db(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UtilisateurDB:
    """Adaptateur générique de fastapi-users sur `Utilisateur` : les
    attributs `hashed_password`/`is_active` qu'il lit ou écrit sont portés
    par les colonnes `mdp_hash`/`actif` (L2-D1, voir `ingest/models.py`)."""
    return SQLAlchemyUserDatabase(session, Utilisateur)  # type: ignore[type-var]


class GestionnaireUtilisateurs(UUIDIDMixin, BaseUserManager[Utilisateur, uuid.UUID]):  # type: ignore[type-var]
    """Gestionnaire fastapi-users : hachage (argon2 par défaut, via
    `PasswordHelper`), authentification. Aucune route d'inscription ni de
    réinitialisation de mot de passe n'est montée dans ce lot (création des
    comptes en CLI, tâche L2-T1b) : les secrets de jeton JWT correspondants
    (`reset_password_token_secret`, `verification_token_secret`) ne sont
    donc pas définis."""

    async def authenticate(
        self, credentials: OAuth2PasswordRequestForm
    ) -> Utilisateur | None:
        """Identique à `BaseUserManager.authenticate` (délégation complète
        pour le cas normal), avec une garde supplémentaire trouvée en
        auto-relecture : `mdp_hash` reste nullable (L2-D1 — un compte
        rattaché seulement à Telegram peut n'avoir jamais de mot de passe).
        Sans cette garde, pwdlib lève `TypeError: hash must be str or bytes`
        sur un `hashed_password` `None`, ce qui ferait échouer la requête en
        500 au lieu du 400 attendu. Un hachage factice est calculé dans ce
        cas aussi, pour ne pas distinguer ce compte d'un mot de passe
        incorrect (mitigation temporelle déjà utilisée par la bibliothèque
        pour un e-mail inconnu)."""
        try:
            utilisateur = await self.get_by_email(credentials.username)
        except exceptions.UserNotExists:
            self.password_helper.hash(credentials.password)
            return None
        if utilisateur.hashed_password is None:
            self.password_helper.hash(credentials.password)
            return None
        return await super().authenticate(credentials)


def get_gestionnaire_utilisateurs(
    utilisateur_db: Annotated[UtilisateurDB, Depends(get_utilisateur_db)],
) -> GestionnaireUtilisateurs:
    return GestionnaireUtilisateurs(utilisateur_db)


def get_jeton_session_db(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JetonSessionDB:
    return SQLAlchemyAccessTokenDatabase(session, JetonSession)  # type: ignore[type-var]


def get_database_strategy(
    jeton_session_db: Annotated[JetonSessionDB, Depends(get_jeton_session_db)],
) -> StrategieSession:
    return DatabaseStrategy(  # type: ignore[type-var]
        jeton_session_db, lifetime_seconds=DUREE_SESSION_S
    )


auth_backend = AuthenticationBackend(  # type: ignore[type-var]
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_database_strategy,
)


async def utilisateur_courant(
    request: Request,
    gestionnaire: Annotated[
        GestionnaireUtilisateurs, Depends(get_gestionnaire_utilisateurs)
    ],
    jeton_session_db: Annotated[JetonSessionDB, Depends(get_jeton_session_db)],
    strategy: Annotated[StrategieSession, Depends(get_database_strategy)],
) -> Utilisateur:
    """Dépendance FastAPI « utilisateur courant » (L2-D2) :

    - 401 si le cookie est absent, si le jeton est inconnu ou expiré (plus
      de 12 h sans activité — vérifié par `DatabaseStrategy.read_token` via
      un filtre SQL sur `created_at`), ou si le compte est désactivé.
    - Sinon, expiration glissante : `created_at` est rafraîchi si plus de 5
      minutes se sont écoulées depuis la dernière activité, pour ne pas
      écrire en base à chaque requête.
    """
    jeton_brut = request.cookies.get(NOM_COOKIE)
    if jeton_brut is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentification requise"
        )

    utilisateur = await strategy.read_token(jeton_brut, gestionnaire)
    if utilisateur is None or not utilisateur.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentification requise"
        )

    jeton = await jeton_session_db.get_by_token(jeton_brut)
    if jeton is not None:
        maintenant = datetime.now(UTC)
        if maintenant - jeton.created_at >= timedelta(seconds=DELAI_RAFRAICHISSEMENT_S):
            await jeton_session_db.update(jeton, {"created_at": maintenant})

    return utilisateur


async def admin_requis(
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
) -> Utilisateur:
    """Réservé au rôle `admin` (403 pour un `agent`)."""
    if utilisateur.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="réservé aux administrateurs"
        )
    return utilisateur


limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
@limiter.limit("5/minute")
async def se_connecter(
    request: Request,
    identifiants: Annotated[OAuth2PasswordRequestForm, Depends()],
    gestionnaire: Annotated[
        GestionnaireUtilisateurs, Depends(get_gestionnaire_utilisateurs)
    ],
    strategy: Annotated[StrategieSession, Depends(get_database_strategy)],
) -> Response:
    """Réutilise `GestionnaireUtilisateurs.authenticate` (mitige déjà les
    attaques temporelles : un hachage factice est calculé même si l'e-mail
    est inconnu) puis `auth_backend.login` (écrit le jeton, pose le cookie).
    Un identifiant invalide et un compte désactivé renvoient la même erreur
    générique, pour ne pas révéler quels comptes existent."""
    utilisateur = await gestionnaire.authenticate(identifiants)
    if utilisateur is None or not utilisateur.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="identifiants invalides"
        )
    return await auth_backend.login(strategy, utilisateur)


@router.post("/logout")
async def se_deconnecter(
    request: Request,
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
    strategy: Annotated[StrategieSession, Depends(get_database_strategy)],
) -> Response:
    """Révoque le jeton courant (supprimé en base, pas seulement le
    cookie) puis renvoie la réponse de déconnexion du transport (cookie vidé,
    `Max-Age=0`)."""
    jeton_brut = request.cookies.get(NOM_COOKIE)
    if jeton_brut is not None:
        await strategy.destroy_token(jeton_brut, utilisateur)
    return await cookie_transport.get_logout_response()


# ---------------------------------------------------------------------------
# Gestion des comptes (L2-T1b) : utilisées par `app/cli.py`
# (`utilisateur-creer` / `utilisateur-desactiver`), seules routes d'écriture
# sur `Utilisateur` de ce lot.
# ---------------------------------------------------------------------------


class RoleInvalide(Exception):
    """Rôle hors de `ROLES_VALIDES` (`admin`, `agent`)."""


class MotDePasseTropCourt(Exception):
    """Moins de `LONGUEUR_MOT_DE_PASSE_MIN` caractères."""


class EmailDejaUtilise(Exception):
    """Un compte existe déjà avec cet e-mail."""


class TelegramUserIdDejaAttribue(Exception):
    """`telegram_user_id` déjà porté par un autre compte."""


class UtilisateurIntrouvable(Exception):
    """Aucun compte n'a cet e-mail."""


async def creer_utilisateur(
    session: AsyncSession,
    *,
    email: str,
    nom: str,
    role: str,
    agence: str,
    mot_de_passe: str,
    telegram_user_id: int | None = None,
) -> Utilisateur:
    """Crée un compte (`utilisateur-creer`).

    Lève `RoleInvalide`, `MotDePasseTropCourt`, `EmailDejaUtilise` ou
    `TelegramUserIdDejaAttribue` (décisions du contrôleur L2-T1b : la CLI
    traduit chacune en code de sortie 2, message court sur stderr, jamais le
    mot de passe). Journalise `utilisateur_cree` avec `utilisateur_id` NULL
    (action d'exploitation hors application, comme une migration) et un
    `apres` qui ne contient jamais le hash ni le mot de passe en clair.

    Les vérifications d'unicité ci-dessous sont de simples `SELECT` avant
    l'écriture, non atomiques avec elle (`email` reste protégé par la
    contrainte `UNIQUE` de la table en dernier recours, mais celle-ci reste
    sensible à la casse en base — voir `docs/dette.md` ; `telegram_user_id`
    n'a aucune protection en base — L2-T1b n'ajoute pas de migration).
    Acceptable pour une commande d'exploitation qu'un seul administrateur
    exécute à la fois, jamais deux créations concurrentes du même compte.

    `email` est normalisé (`strip()` + minuscules) avant toute vérification
    et avant l'écriture (constat de revue, tour de correction 1/5) : c'est
    la même comparaison, insensible à la casse, que
    `SQLAlchemyUserDatabase.get_by_email` applique en lecture pour le login
    (`func.lower` des deux côtés). Sans cette normalisation, créer
    `Agent@Ex.invalid` alors que `agent@ex.invalid` existe déjà passait la
    vérification d'unicité (sensible à la casse) mais faisait ensuite
    échouer le login des deux comptes en 500 (`MultipleResultsFound`,
    `get_by_email` les traitant comme un seul compte).
    """
    if role not in ROLES_VALIDES:
        raise RoleInvalide(f"rôle invalide : {role!r} (attendu admin ou agent)")
    if len(mot_de_passe) < LONGUEUR_MOT_DE_PASSE_MIN:
        raise MotDePasseTropCourt(
            f"mot de passe trop court (minimum {LONGUEUR_MOT_DE_PASSE_MIN} caractères)"
        )

    email_normalise = email.strip().lower()

    email_pris = (
        await session.execute(
            select(Utilisateur.id).where(
                func.lower(Utilisateur.email) == email_normalise
            )
        )
    ).first()
    if email_pris is not None:
        raise EmailDejaUtilise(f"e-mail déjà utilisé : {email_normalise}")

    if telegram_user_id is not None:
        telegram_pris = (
            await session.execute(
                select(Utilisateur.id).where(
                    Utilisateur.telegram_user_id == telegram_user_id
                )
            )
        ).first()
        if telegram_pris is not None:
            raise TelegramUserIdDejaAttribue(
                f"identifiant Telegram déjà attribué : {telegram_user_id}"
            )

    utilisateur = Utilisateur(
        email=email_normalise,
        nom=nom,
        hashed_password=_password_helper.hash(mot_de_passe),
        role=role,
        agence=agence,
        telegram_user_id=telegram_user_id,
    )
    session.add(utilisateur)
    await session.flush()

    session.add(
        Journal(
            utilisateur_id=None,
            action="utilisateur_cree",
            cible_table="utilisateur",
            cible_id=str(utilisateur.id),
            avant=None,
            apres={
                "email": email_normalise,
                "nom": nom,
                "role": role,
                "agence": agence,
                "telegram_user_id": telegram_user_id,
            },
        )
    )
    await session.commit()
    await session.refresh(utilisateur)
    return utilisateur


async def desactiver_utilisateur(session: AsyncSession, email: str) -> Utilisateur:
    """Désactive un compte (`utilisateur-desactiver`).

    `is_active = False` (colonne `actif`) : `utilisateur_courant` refuse
    déjà toute requête d'un compte inactif (voir plus haut), sans qu'il soit
    nécessaire de révoquer une à une ses `JetonSession` existantes. Lève
    `UtilisateurIntrouvable` si `email` ne correspond à aucun compte.
    Journalise `utilisateur_desactive` (mêmes conventions que
    `creer_utilisateur` ci-dessus : `utilisateur_id` NULL, pas de hash).

    `email` est normalisé (`strip()` + minuscules) avant la recherche, pour
    retrouver un compte quelle que soit la casse saisie (même normalisation
    que `creer_utilisateur`, tour de correction 1/5).
    """
    email_normalise = email.strip().lower()
    utilisateur = (
        await session.execute(
            select(Utilisateur).where(func.lower(Utilisateur.email) == email_normalise)
        )
    ).scalar_one_or_none()
    if utilisateur is None:
        raise UtilisateurIntrouvable(f"utilisateur introuvable : {email}")

    actif_avant = utilisateur.is_active
    utilisateur.is_active = False
    await session.flush()

    session.add(
        Journal(
            utilisateur_id=None,
            action="utilisateur_desactive",
            cible_table="utilisateur",
            cible_id=str(utilisateur.id),
            avant={"actif": actif_avant},
            apres={"actif": False},
        )
    )
    await session.commit()
    await session.refresh(utilisateur)
    return utilisateur
