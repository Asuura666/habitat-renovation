"""Authentification (L2-T1) : connexion par cookie, sessions en base,
limitation du login, expiration glissante.

Chaque test construit un `FastAPI` isolé (jamais `app.main.app`, voir le
docstring de `test_sante.py`), avec `app_test.state.sessions` branché sur
`bl_test` (fixtures locales de `conftest.py`, mêmes bases que `ingest`).

Limitation de débit (`slowapi`) : le `Limiter` de `app.core.auth` est un
singleton de process, partagé par tous les tests de ce fichier (et de toute
la suite). Chaque test qui appelle `/api/auth/login` utilise une adresse IP
simulée distincte (`ASGITransport(client=...)`) pour ne jamais consommer le
quota d'un autre test — sans ça, l'ordre d'exécution des tests changerait
leur résultat.
"""

from __future__ import annotations

import asyncio
import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.auth import (
    NOM_COOKIE,
    ActionSurSoiInterdite,
    DernierAdmin,
    EmailDejaUtilise,
    MotDePasseTropCourt,
    RoleInvalide,
    TelegramUserIdDejaAttribue,
    UtilisateurIntrouvable,
    admin_requis,
    changer_mot_de_passe,
    creer_compte,
    creer_utilisateur,
    desactiver_utilisateur,
    lister_comptes,
    modifier_compte,
    retablir_acces,
    retirer_acces,
)
from app.core.auth import router as auth_router
from app.core.db import creer_sessionmaker
from app.core.origine import ControleOrigineMiddleware
from app.modules.api import router as api_router
from app.modules.ingest.models import JetonSession, Journal, Utilisateur

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"

# Un octet différent par test qui touche `/api/auth/login`, pour ne jamais
# partager de compteur de limitation avec un autre test (voir docstring).
_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.66.0.{next(_IPS)}"


def _app_test(sessions: async_sessionmaker[AsyncSession]) -> FastAPI:
    """`FastAPI` isolé : seul l'état partagé avec la production est le
    contrat des dépendances (`get_session` lit `app.state.sessions`). Le
    contrôle d'origine (`ControleOrigineMiddleware`, point 2 de la vague
    finale du lot 2) est ajouté comme en production (`app/main.py`) : les
    tests existants ne sont pas affectés (httpx n'envoie ni `Origin` ni
    `Sec-Fetch-Site` par défaut), seuls les tests dédiés ci-dessous en
    tirent parti."""
    app_test = FastAPI()
    app_test.add_middleware(ControleOrigineMiddleware)
    app_test.state.sessions = sessions
    app_test.include_router(auth_router)
    app_test.include_router(api_router)

    @app_test.get("/admin-seulement")
    async def _admin_seulement(
        utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    ) -> dict[str, str]:
        return {"role": utilisateur.role}

    return app_test


async def _creer_utilisateur(
    db_session: AsyncSession,
    *,
    email: str,
    mot_de_passe: str = _MOT_DE_PASSE,
    role: str = "agent",
    is_active: bool = True,
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email,
        hashed_password=_PASSWORD_HELPER.hash(mot_de_passe),
        role=role,
        is_active=is_active,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _login(
    app_test: FastAPI,
    *,
    email: str,
    mot_de_passe: str,
    ip: str,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=(ip, 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/api/auth/login",
            data={"username": email, "password": mot_de_passe},
            headers=headers or {},
        )


async def _appeler(
    app_test: FastAPI,
    methode: str,
    chemin: str,
    *,
    cookie: str | None = None,
    ip: str = "10.0.0.1",
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=(ip, 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.request(methode, chemin)


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------


async def test_login_reussi_pose_un_cookie_httponly_samesite_lax(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(db_session, email="agent.invente@example.invalid")
    app_test = _app_test(sessions_test)

    reponse = await _login(
        app_test,
        email="agent.invente@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=_ip_isolee(),
    )

    assert reponse.status_code == 204
    entete_cookie = reponse.headers.get("set-cookie")
    assert entete_cookie is not None
    assert entete_cookie.startswith(f"{NOM_COOKIE}=")
    assert "httponly" in entete_cookie.lower()
    assert "samesite=lax" in entete_cookie.lower()
    # `.env` du worktree : `COOKIE_SECURE=false` (dev, HTTP) — pas
    # d'attribut `Secure` sur le cookie.
    assert "secure" not in entete_cookie.lower()
    # Cookie de session (pas de `max_age`) : aucun attribut `Max-Age`.
    assert "max-age" not in entete_cookie.lower()


async def test_login_mauvais_mot_de_passe_renvoie_400(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(db_session, email="agent.invente2@example.invalid")
    app_test = _app_test(sessions_test)

    reponse = await _login(
        app_test,
        email="agent.invente2@example.invalid",
        mot_de_passe="mauvais-mot-de-passe",
        ip=_ip_isolee(),
    )

    assert reponse.status_code == 400


async def test_login_compte_inactif_renvoie_400(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.inactif@example.invalid", is_active=False
    )
    app_test = _app_test(sessions_test)

    reponse = await _login(
        app_test,
        email="agent.inactif@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=_ip_isolee(),
    )

    assert reponse.status_code == 400


async def test_login_compte_sans_mot_de_passe_renvoie_400_sans_planter(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    """Auto-relecture : `mdp_hash` reste nullable (L2-D1, un compte rattaché
    seulement à Telegram peut n'en avoir jamais eu). Sans la garde dans
    `GestionnaireUtilisateurs.authenticate`, pwdlib lève `TypeError` sur un
    `hashed_password` `None`, et la requête échouerait en 500 au lieu du
    400 attendu."""
    utilisateur = Utilisateur(
        email="agent.sans.mdp@example.invalid", role="agent", is_active=True
    )
    db_session.add(utilisateur)
    await db_session.commit()
    app_test = _app_test(sessions_test)

    reponse = await _login(
        app_test,
        email="agent.sans.mdp@example.invalid",
        mot_de_passe="peu-importe",
        ip=_ip_isolee(),
    )

    assert reponse.status_code == 400


async def test_login_ne_revele_pas_si_le_compte_existe(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    """Auto-relecture (énumération d'utilisateurs) : un e-mail inconnu et un
    mauvais mot de passe sur un compte existant renvoient exactement la même
    réponse (statut et corps), pour ne jamais laisser deviner qu'un compte
    existe."""
    await _creer_utilisateur(db_session, email="agent.invente3@example.invalid")
    app_test = _app_test(sessions_test)

    reponse_inconnu = await _login(
        app_test,
        email="personne.na.jamais.existe@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=_ip_isolee(),
    )
    reponse_mauvais_mdp = await _login(
        app_test,
        email="agent.invente3@example.invalid",
        mot_de_passe="mauvais-mot-de-passe",
        ip=_ip_isolee(),
    )

    assert reponse_inconnu.status_code == reponse_mauvais_mdp.status_code == 400
    assert reponse_inconnu.json() == reponse_mauvais_mdp.json()


async def test_login_6e_tentative_dans_la_minute_renvoie_429(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(db_session, email="agent.invente4@example.invalid")
    app_test = _app_test(sessions_test)
    ip = _ip_isolee()

    reponses = [
        await _login(
            app_test,
            email="agent.invente4@example.invalid",
            mot_de_passe="mauvais-mot-de-passe",
            ip=ip,
        )
        for _ in range(6)
    ]

    assert [r.status_code for r in reponses[:5]] == [400] * 5
    assert reponses[5].status_code == 429


# ---------------------------------------------------------------------------
# Contrôle d'origine (point 2, vague finale du lot 2) sur une vraie route
# modifiante (`POST /api/auth/login`) — tests unitaires du middleware dans
# `test_origine.py`.
# ---------------------------------------------------------------------------


async def test_login_origine_etrangere_refusee_403(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(db_session, email="agent.origine1@example.invalid")
    app_test = _app_test(sessions_test)

    reponse = await _login(
        app_test,
        email="agent.origine1@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=_ip_isolee(),
        headers={"Origin": "https://evil.example"},
    )

    assert reponse.status_code == 403
    assert reponse.json() == {"detail": "Origine refusée."}


async def test_login_meme_origine_accepte(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(db_session, email="agent.origine2@example.invalid")
    app_test = _app_test(sessions_test)

    reponse = await _login(
        app_test,
        email="agent.origine2@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=_ip_isolee(),
        headers={"Origin": "http://test"},
    )

    assert reponse.status_code == 204


async def test_login_sec_fetch_site_cross_site_refuse_403(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(db_session, email="agent.origine3@example.invalid")
    app_test = _app_test(sessions_test)

    reponse = await _login(
        app_test,
        email="agent.origine3@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=_ip_isolee(),
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert reponse.status_code == 403
    assert reponse.json() == {"detail": "Origine refusée."}


# ---------------------------------------------------------------------------
# GET /api/moi
# ---------------------------------------------------------------------------


async def test_moi_sans_cookie_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession],
) -> None:
    app_test = _app_test(sessions_test)

    reponse = await _appeler(app_test, "GET", "/api/moi")

    assert reponse.status_code == 401


async def test_moi_avec_cookie_renvoie_200_et_les_bons_champs(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    utilisateur = await _creer_utilisateur(
        db_session,
        email="agent.invente5@example.invalid",
        role="agent",
    )
    utilisateur.nom = "Agent Inventé"
    utilisateur.agence = "Toulouse"
    await db_session.commit()

    app_test = _app_test(sessions_test)
    ip = _ip_isolee()
    connexion = await _login(
        app_test,
        email="agent.invente5@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=ip,
    )
    jeton = connexion.cookies.get(NOM_COOKIE)
    assert jeton is not None

    reponse = await _appeler(app_test, "GET", "/api/moi", cookie=jeton, ip=ip)

    assert reponse.status_code == 200
    assert reponse.json() == {
        "id": str(utilisateur.id),
        "email": "agent.invente5@example.invalid",
        "nom": "Agent Inventé",
        "role": "agent",
        "agence": "Toulouse",
    }


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------


async def test_logout_supprime_le_jeton_puis_moi_renvoie_401(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(db_session, email="agent.invente6@example.invalid")
    app_test = _app_test(sessions_test)
    ip = _ip_isolee()
    connexion = await _login(
        app_test,
        email="agent.invente6@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=ip,
    )
    jeton = connexion.cookies.get(NOM_COOKIE)
    assert jeton is not None

    deconnexion = await _appeler(
        app_test, "POST", "/api/auth/logout", cookie=jeton, ip=ip
    )
    assert deconnexion.status_code == 204

    restants = (
        (
            await db_session.execute(
                select(JetonSession).where(JetonSession.token == jeton)
            )
        )
        .scalars()
        .all()
    )
    assert restants == []

    apres_logout = await _appeler(app_test, "GET", "/api/moi", cookie=jeton, ip=ip)
    assert apres_logout.status_code == 401


# ---------------------------------------------------------------------------
# Expiration glissante (L2-D2)
# ---------------------------------------------------------------------------


async def test_jeton_sans_activite_depuis_plus_de_12h_renvoie_401(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(db_session, email="agent.invente7@example.invalid")
    app_test = _app_test(sessions_test)
    ip = _ip_isolee()
    connexion = await _login(
        app_test,
        email="agent.invente7@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=ip,
    )
    jeton = connexion.cookies.get(NOM_COOKIE)
    assert jeton is not None

    il_y_a_douze_heures_une_seconde = datetime.now(UTC) - timedelta(hours=12, seconds=1)
    await db_session.execute(
        update(JetonSession)
        .where(JetonSession.token == jeton)
        .values(created_at=il_y_a_douze_heures_une_seconde)
    )
    await db_session.commit()

    reponse = await _appeler(app_test, "GET", "/api/moi", cookie=jeton, ip=ip)

    assert reponse.status_code == 401


async def test_jeton_actif_a_11h59_est_prolonge(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(db_session, email="agent.invente8@example.invalid")
    app_test = _app_test(sessions_test)
    ip = _ip_isolee()
    connexion = await _login(
        app_test,
        email="agent.invente8@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=ip,
    )
    jeton = connexion.cookies.get(NOM_COOKIE)
    assert jeton is not None

    il_y_a_onze_h_59 = datetime.now(UTC) - timedelta(hours=11, minutes=59)
    await db_session.execute(
        update(JetonSession)
        .where(JetonSession.token == jeton)
        .values(created_at=il_y_a_onze_h_59)
    )
    await db_session.commit()

    reponse = await _appeler(app_test, "GET", "/api/moi", cookie=jeton, ip=ip)
    assert reponse.status_code == 200

    apres = (
        await db_session.execute(
            select(JetonSession.created_at).where(JetonSession.token == jeton)
        )
    ).scalar_one()
    # Prolongée : le jeton n'est plus vieux de 11h59, il vient d'être
    # rafraîchi (largement moins d'une minute d'écart avec maintenant).
    assert datetime.now(UTC) - apres < timedelta(minutes=1)


async def test_jeton_de_moins_de_5_minutes_nest_pas_rafraichi(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    """L'expiration glissante ne réécrit `created_at` qu'au plus toutes les
    5 minutes (décision L2-D2), pas à chaque requête."""
    await _creer_utilisateur(db_session, email="agent.invente9@example.invalid")
    app_test = _app_test(sessions_test)
    ip = _ip_isolee()
    connexion = await _login(
        app_test,
        email="agent.invente9@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=ip,
    )
    jeton = connexion.cookies.get(NOM_COOKIE)
    assert jeton is not None

    il_y_a_deux_minutes = datetime.now(UTC) - timedelta(minutes=2)
    await db_session.execute(
        update(JetonSession)
        .where(JetonSession.token == jeton)
        .values(created_at=il_y_a_deux_minutes)
    )
    await db_session.commit()

    reponse = await _appeler(app_test, "GET", "/api/moi", cookie=jeton, ip=ip)
    assert reponse.status_code == 200

    apres = (
        await db_session.execute(
            select(JetonSession.created_at).where(JetonSession.token == jeton)
        )
    ).scalar_one()
    assert abs((apres - il_y_a_deux_minutes).total_seconds()) < 1


# ---------------------------------------------------------------------------
# Hachage et rôles
# ---------------------------------------------------------------------------


async def test_hash_stocke_au_format_argon2id(db_session: AsyncSession) -> None:
    utilisateur = await _creer_utilisateur(
        db_session, email="agent.invente10@example.invalid"
    )

    relu = (
        await db_session.execute(
            select(Utilisateur).where(Utilisateur.id == utilisateur.id)
        )
    ).scalar_one()

    assert relu.hashed_password is not None
    assert relu.hashed_password.startswith("$argon2id$")


async def test_admin_requis_refuse_un_agent(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.invente11@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test)
    ip = _ip_isolee()
    connexion = await _login(
        app_test,
        email="agent.invente11@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=ip,
    )
    jeton = connexion.cookies.get(NOM_COOKIE)
    assert jeton is not None

    reponse = await _appeler(app_test, "GET", "/admin-seulement", cookie=jeton, ip=ip)

    assert reponse.status_code == 403


async def test_admin_requis_autorise_un_admin(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.invente@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test)
    ip = _ip_isolee()
    connexion = await _login(
        app_test,
        email="admin.invente@example.invalid",
        mot_de_passe=_MOT_DE_PASSE,
        ip=ip,
    )
    jeton = connexion.cookies.get(NOM_COOKIE)
    assert jeton is not None

    reponse = await _appeler(app_test, "GET", "/admin-seulement", cookie=jeton, ip=ip)

    assert reponse.status_code == 200
    assert reponse.json() == {"role": "admin"}


# ---------------------------------------------------------------------------
# Gestion des comptes (L2-T1b) : `creer_utilisateur` / `desactiver_utilisateur`
# ---------------------------------------------------------------------------

_MOT_DE_PASSE_VALIDE = "mot-de-passe-invente-cli-1234"


async def _journal_pour(db_session: AsyncSession, utilisateur_id: uuid.UUID) -> Journal:
    """La seule ligne `journal` ciblant `utilisateur_id` (erreur si aucune
    ou plusieurs, pour ne jamais masquer un doublon inattendu)."""
    return (
        await db_session.execute(
            select(Journal).where(Journal.cible_id == str(utilisateur_id))
        )
    ).scalar_one()


async def test_creer_utilisateur_hash_argon2id_et_journal_sans_secret(
    db_session: AsyncSession,
) -> None:
    utilisateur = await creer_utilisateur(
        db_session,
        email="cli.cree1@example.invalid",
        nom="Agent Créé",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    assert utilisateur.hashed_password is not None
    assert utilisateur.hashed_password.startswith("$argon2id$")
    assert utilisateur.is_active is True

    relu = (
        await db_session.execute(
            select(Utilisateur).where(Utilisateur.id == utilisateur.id)
        )
    ).scalar_one()
    assert relu.role == "agent"
    assert relu.agence == "Toulouse"

    journal = await _journal_pour(db_session, utilisateur.id)
    assert journal.utilisateur_id is None
    assert journal.action == "utilisateur_cree"
    assert journal.cible_table == "utilisateur"
    assert journal.avant is None
    assert journal.apres is not None
    assert journal.apres["email"] == "cli.cree1@example.invalid"
    # Auto-relecture : ni le hash ni le mot de passe en clair ne doivent
    # apparaître dans le journal (append-only, consultable par un admin).
    assert "hashed_password" not in journal.apres
    assert "mdp_hash" not in journal.apres
    assert _MOT_DE_PASSE_VALIDE not in journal.apres.values()
    assert utilisateur.hashed_password not in journal.apres.values()


async def test_creer_utilisateur_email_deja_pris_refuse_sans_deuxieme_ligne(
    db_session: AsyncSession,
) -> None:
    await creer_utilisateur(
        db_session,
        email="cli.cree2@example.invalid",
        nom="Premier",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    with pytest.raises(EmailDejaUtilise):
        await creer_utilisateur(
            db_session,
            email="cli.cree2@example.invalid",
            nom="Second",
            role="agent",
            agence="Toulouse",
            mot_de_passe=_MOT_DE_PASSE_VALIDE,
        )

    lignes = (
        (
            await db_session.execute(
                select(Utilisateur).where(
                    Utilisateur.email == "cli.cree2@example.invalid"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(lignes) == 1
    assert lignes[0].nom == "Premier"


async def test_creer_utilisateur_role_invalide_refuse_sans_ecriture(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(RoleInvalide):
        await creer_utilisateur(
            db_session,
            email="cli.role.invalide@example.invalid",
            nom="Rôle invalide",
            role="superadmin",
            agence="Toulouse",
            mot_de_passe=_MOT_DE_PASSE_VALIDE,
        )

    reste = (
        await db_session.execute(
            select(Utilisateur.id).where(
                Utilisateur.email == "cli.role.invalide@example.invalid"
            )
        )
    ).first()
    assert reste is None


async def test_creer_utilisateur_mot_de_passe_trop_court_refuse_sans_ecriture(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(MotDePasseTropCourt):
        await creer_utilisateur(
            db_session,
            email="cli.mdp.court@example.invalid",
            nom="Mot de passe court",
            role="agent",
            agence="Toulouse",
            mot_de_passe="court12345",  # 10 caractères, < LONGUEUR_MOT_DE_PASSE_MIN
        )

    reste = (
        await db_session.execute(
            select(Utilisateur.id).where(
                Utilisateur.email == "cli.mdp.court@example.invalid"
            )
        )
    ).first()
    assert reste is None


async def test_creer_utilisateur_telegram_id_deja_attribue_refuse(
    db_session: AsyncSession,
) -> None:
    await creer_utilisateur(
        db_session,
        email="cli.telegram1@example.invalid",
        nom="Premier",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
        telegram_user_id=987654321,
    )

    with pytest.raises(TelegramUserIdDejaAttribue):
        await creer_utilisateur(
            db_session,
            email="cli.telegram2@example.invalid",
            nom="Second",
            role="agent",
            agence="Toulouse",
            mot_de_passe=_MOT_DE_PASSE_VALIDE,
            telegram_user_id=987654321,
        )

    porteurs = (
        (
            await db_session.execute(
                select(Utilisateur).where(Utilisateur.telegram_user_id == 987654321)
            )
        )
        .scalars()
        .all()
    )
    assert len(porteurs) == 1
    assert porteurs[0].email == "cli.telegram1@example.invalid"


async def test_desactiver_utilisateur_bascule_actif_et_journalise(
    db_session: AsyncSession,
) -> None:
    utilisateur = await creer_utilisateur(
        db_session,
        email="cli.desactive1@example.invalid",
        nom="À désactiver",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    desactive = await desactiver_utilisateur(
        db_session, "cli.desactive1@example.invalid"
    )

    assert desactive.is_active is False
    relu = (
        await db_session.execute(
            select(Utilisateur).where(Utilisateur.id == utilisateur.id)
        )
    ).scalar_one()
    assert relu.is_active is False

    journal = (
        await db_session.execute(
            select(Journal)
            .where(Journal.cible_id == str(utilisateur.id))
            .where(Journal.action == "utilisateur_desactive")
        )
    ).scalar_one()
    assert journal.utilisateur_id is None
    assert journal.avant == {"actif": True}
    assert journal.apres == {"actif": False}


async def test_desactiver_utilisateur_email_inconnu_leve_utilisateur_introuvable(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(UtilisateurIntrouvable):
        await desactiver_utilisateur(
            db_session, "personne.na.jamais.existe.cli@example.invalid"
        )


# ---------------------------------------------------------------------------
# Correction — tour de correction 1/5 : e-mail insensible à la casse
# ---------------------------------------------------------------------------


async def test_creer_utilisateur_email_casse_differente_refuse_et_stocke_en_minuscules(
    db_session: AsyncSession,
) -> None:
    """Constat de revue (Important) : sans normalisation, `Agent.Casse@...`
    et `agent.casse@...` étaient acceptés comme deux comptes distincts par
    `creer_utilisateur` (comparaison sensible à la casse), alors que
    `SQLAlchemyUserDatabase.get_by_email` (login) les traite comme un seul
    compte via `func.lower` des deux côtés — `MultipleResultsFound` au
    login pour l'un ou l'autre. `creer_utilisateur` normalise désormais
    (`strip()` + minuscules) avant l'écriture et la vérification
    d'unicité."""
    premier = await creer_utilisateur(
        db_session,
        email="Agent.Casse@Example.INVALID",
        nom="Premier",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    assert premier.email == "agent.casse@example.invalid"

    with pytest.raises(EmailDejaUtilise):
        await creer_utilisateur(
            db_session,
            email="agent.casse@example.invalid",
            nom="Second",
            role="agent",
            agence="Toulouse",
            mot_de_passe=_MOT_DE_PASSE_VALIDE,
        )

    lignes = (
        (
            await db_session.execute(
                select(Utilisateur).where(
                    func.lower(Utilisateur.email) == "agent.casse@example.invalid"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(lignes) == 1
    assert lignes[0].nom == "Premier"


async def test_desactiver_utilisateur_casse_differente_trouve(
    db_session: AsyncSession,
) -> None:
    await creer_utilisateur(
        db_session,
        email="agent.desactive.casse@example.invalid",
        nom="À désactiver",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    desactive = await desactiver_utilisateur(
        db_session, "Agent.Desactive.Casse@EXAMPLE.invalid"
    )

    assert desactive.email == "agent.desactive.casse@example.invalid"
    assert desactive.is_active is False


# ---------------------------------------------------------------------------
# Gestion des comptes par un admin (Task 10, spec §3) : `lister_comptes`/
# `creer_compte`/`modifier_compte`/`changer_mot_de_passe`/`retirer_acces`/
# `retablir_acces`. Tests au niveau fonction (pas de route HTTP ici) : voir
# `app/modules/api/tests/test_comptes.py` pour les routes, les codes HTTP et
# le comportement de bout en bout d'un cookie coupé.
# ---------------------------------------------------------------------------


async def _journal_action(
    db_session: AsyncSession, cible_id: uuid.UUID, action: str
) -> Journal:
    """L'unique ligne `journal` pour `(cible_id, action)` (erreur si aucune
    ou plusieurs) — plus précis que `_journal_pour` ci-dessus quand un compte
    porte déjà une entrée `utilisateur_cree`/`compte_cree` avant l'action
    testée."""
    return (
        await db_session.execute(
            select(Journal)
            .where(Journal.cible_id == str(cible_id))
            .where(Journal.action == action)
        )
    ).scalar_one()


async def test_creer_compte_journalise_sans_mot_de_passe(
    db_session: AsyncSession,
) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="cc.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    compte = await creer_compte(
        db_session,
        email="cc.cree@example.invalid",
        nom="Nouveau Compte",
        role="agent",
        agence="Bordeaux",
        telegram_user_id=None,
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
        auteur_id=admin.id,
    )

    assert compte.email == "cc.cree@example.invalid"
    assert compte.nom == "Nouveau Compte"
    assert compte.role == "agent"
    assert compte.agence == "Bordeaux"
    assert compte.telegram_user_id is None
    assert compte.actif is True

    relu = (
        await db_session.execute(select(Utilisateur).where(Utilisateur.id == compte.id))
    ).scalar_one()
    assert relu.hashed_password is not None
    assert relu.hashed_password.startswith("$argon2id$")

    journal = await _journal_action(db_session, compte.id, "compte_cree")
    assert journal.utilisateur_id == admin.id
    assert journal.avant is None
    assert journal.apres is not None
    # Même garde que `test_creer_utilisateur_hash_argon2id_et_journal_sans_
    # secret` ci-dessus : ni le hash ni le mot de passe en clair dans le
    # journal, cette fois avec `utilisateur_id=auteur_id` (jamais `None`,
    # contrairement à `creer_utilisateur`/`utilisateur_cree`).
    assert "hashed_password" not in journal.apres
    assert "mdp_hash" not in journal.apres
    assert _MOT_DE_PASSE_VALIDE not in journal.apres.values()
    assert relu.hashed_password not in journal.apres.values()


async def test_creer_compte_email_deja_utilise_insensible_casse(
    db_session: AsyncSession,
) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="cc.casse.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    await creer_compte(
        db_session,
        email="Agent.Casse@Example.INVALID",
        nom="Premier",
        role="agent",
        agence="Toulouse",
        telegram_user_id=None,
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
        auteur_id=admin.id,
    )

    with pytest.raises(EmailDejaUtilise):
        await creer_compte(
            db_session,
            email="agent.casse@example.invalid",
            nom="Second",
            role="agent",
            agence="Toulouse",
            telegram_user_id=None,
            mot_de_passe=_MOT_DE_PASSE_VALIDE,
            auteur_id=admin.id,
        )

    lignes = (
        (
            await db_session.execute(
                select(Utilisateur).where(
                    func.lower(Utilisateur.email) == "agent.casse@example.invalid"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(lignes) == 1
    assert lignes[0].nom == "Premier"


async def test_creer_compte_telegram_deja_attribue(db_session: AsyncSession) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="cc.telegram.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    await creer_compte(
        db_session,
        email="cc.telegram1@example.invalid",
        nom="Premier",
        role="agent",
        agence="Toulouse",
        telegram_user_id=111222333,
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
        auteur_id=admin.id,
    )

    with pytest.raises(TelegramUserIdDejaAttribue):
        await creer_compte(
            db_session,
            email="cc.telegram2@example.invalid",
            nom="Second",
            role="agent",
            agence="Toulouse",
            telegram_user_id=111222333,
            mot_de_passe=_MOT_DE_PASSE_VALIDE,
            auteur_id=admin.id,
        )

    porteurs = (
        (
            await db_session.execute(
                select(Utilisateur).where(Utilisateur.telegram_user_id == 111222333)
            )
        )
        .scalars()
        .all()
    )
    assert len(porteurs) == 1
    assert porteurs[0].email == "cc.telegram1@example.invalid"


async def test_lister_comptes_actifs_dabord_puis_nom_email(
    db_session: AsyncSession,
) -> None:
    inactif = await creer_utilisateur(
        db_session,
        email="liste.inactif@example.invalid",
        nom="Aaa Inactif",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    await desactiver_utilisateur(db_session, inactif.email)
    await creer_utilisateur(
        db_session,
        email="liste.zzz@example.invalid",
        nom="Zzz Actif",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    await creer_utilisateur(
        db_session,
        email="liste.aaa@example.invalid",
        nom="Aaa Actif",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    comptes = await lister_comptes(db_session)
    emails = [compte.email for compte in comptes]

    assert emails == [
        "liste.aaa@example.invalid",
        "liste.zzz@example.invalid",
        "liste.inactif@example.invalid",
    ]


async def test_modifier_compte(db_session: AsyncSession) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="mc.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    cible = await creer_utilisateur(
        db_session,
        email="mc.cible@example.invalid",
        nom="Ancien Nom",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    compte = await modifier_compte(
        db_session,
        cible.id,
        email="mc.cible.modifie@example.invalid",
        nom="Nouveau Nom",
        role="admin",
        agence="Bordeaux",
        telegram_user_id=444555666,
        auteur_id=admin.id,
    )

    assert compte.email == "mc.cible.modifie@example.invalid"
    assert compte.nom == "Nouveau Nom"
    assert compte.role == "admin"
    assert compte.agence == "Bordeaux"
    assert compte.telegram_user_id == 444555666

    relu = (
        await db_session.execute(select(Utilisateur).where(Utilisateur.id == cible.id))
    ).scalar_one()
    assert relu.email == "mc.cible.modifie@example.invalid"
    assert relu.role == "admin"
    # Le mot de passe n'est jamais touché par `modifier_compte`.
    assert relu.hashed_password == cible.hashed_password

    journal = await _journal_action(db_session, cible.id, "compte_modifie")
    assert journal.utilisateur_id == admin.id
    assert journal.avant == {
        "email": "mc.cible@example.invalid",
        "nom": "Ancien Nom",
        "role": "agent",
        "agence": "Toulouse",
        "telegram_user_id": None,
    }
    assert journal.apres == {
        "email": "mc.cible.modifie@example.invalid",
        "nom": "Nouveau Nom",
        "role": "admin",
        "agence": "Bordeaux",
        "telegram_user_id": 444555666,
    }


async def test_modifier_compte_email_unicite_exclut_le_compte_lui_meme(
    db_session: AsyncSession,
) -> None:
    """Sans l'exclusion (`exclu_id`), enregistrer une fiche sans changer ni
    l'e-mail ni l'identifiant Telegram serait refusé comme « déjà utilisé »
    par le compte lui-même."""
    admin = await creer_utilisateur(
        db_session,
        email="mc.exclu.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    cible = await creer_utilisateur(
        db_session,
        email="mc.exclu.cible@example.invalid",
        nom="Cible",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
        telegram_user_id=777888999,
    )

    compte = await modifier_compte(
        db_session,
        cible.id,
        email=cible.email,
        nom="Cible Renommée",
        role="agent",
        agence="Toulouse",
        telegram_user_id=777888999,
        auteur_id=admin.id,
    )

    assert compte.nom == "Cible Renommée"
    assert compte.email == "mc.exclu.cible@example.invalid"
    assert compte.telegram_user_id == 777888999


async def test_modifier_compte_introuvable(db_session: AsyncSession) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="mc.introuvable.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    with pytest.raises(UtilisateurIntrouvable):
        await modifier_compte(
            db_session,
            uuid.uuid4(),
            email="peu.importe@example.invalid",
            nom="Peu Importe",
            role="agent",
            agence=None,
            telegram_user_id=None,
            auteur_id=admin.id,
        )


async def test_dernier_admin_protege(db_session: AsyncSession) -> None:
    """Garde-fou (spec §3) : ni `modifier_compte` (passage au rôle `agent`)
    ni `retirer_acces` ne doivent pouvoir retirer le dernier administrateur
    actif — sans quoi plus personne ne pourrait gérer les comptes. Un second
    compte admin *inactif* ne compte pas comme protection (« dernier admin
    **actif** », spec §3)."""
    seul_admin_actif = await creer_utilisateur(
        db_session,
        email="dernier.admin@example.invalid",
        nom="Seul Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    autre_admin_inactif = await creer_utilisateur(
        db_session,
        email="autre.admin.inactif@example.invalid",
        nom="Autre Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    await desactiver_utilisateur(db_session, autre_admin_inactif.email)

    with pytest.raises(DernierAdmin):
        await modifier_compte(
            db_session,
            seul_admin_actif.id,
            email=seul_admin_actif.email,
            nom="Seul Admin",
            role="agent",
            agence=seul_admin_actif.agence,
            telegram_user_id=None,
            auteur_id=seul_admin_actif.id,
        )
    relu = (
        await db_session.execute(
            select(Utilisateur).where(Utilisateur.id == seul_admin_actif.id)
        )
    ).scalar_one()
    assert relu.role == "admin"

    with pytest.raises(DernierAdmin):
        await retirer_acces(
            db_session, seul_admin_actif.id, auteur_id=autre_admin_inactif.id
        )
    relu = (
        await db_session.execute(
            select(Utilisateur).where(Utilisateur.id == seul_admin_actif.id)
        )
    ).scalar_one()
    assert relu.is_active is True


async def test_changer_mot_de_passe_coupe_les_sessions(
    db_session: AsyncSession,
) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="cmdp.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    cible = await creer_utilisateur(
        db_session,
        email="cmdp.cible@example.invalid",
        nom="Cible",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    ancien_hash = cible.hashed_password
    db_session.add(
        JetonSession(token="jeton-cmdp-1", user_id=cible.id)  # noqa: S106 -- test, jamais un vrai secret
    )
    await db_session.commit()

    nouveau_mot_de_passe = "nouveau-mot-de-passe-invente-1234"
    await changer_mot_de_passe(
        db_session, cible.id, mot_de_passe=nouveau_mot_de_passe, auteur_id=admin.id
    )

    relu = (
        await db_session.execute(select(Utilisateur).where(Utilisateur.id == cible.id))
    ).scalar_one()
    assert relu.hashed_password is not None
    assert relu.hashed_password != ancien_hash
    assert relu.hashed_password.startswith("$argon2id$")

    jetons_restants = (
        (
            await db_session.execute(
                select(JetonSession).where(JetonSession.user_id == cible.id)
            )
        )
        .scalars()
        .all()
    )
    assert jetons_restants == []

    journal = await _journal_action(db_session, cible.id, "mot_de_passe_change")
    assert journal.utilisateur_id == admin.id
    assert journal.avant is None
    assert journal.apres is None


async def test_changer_mot_de_passe_trop_court(db_session: AsyncSession) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="cmdp.court.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    cible = await creer_utilisateur(
        db_session,
        email="cmdp.court.cible@example.invalid",
        nom="Cible",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    ancien_hash = cible.hashed_password

    with pytest.raises(MotDePasseTropCourt):
        await changer_mot_de_passe(
            db_session, cible.id, mot_de_passe="court12345", auteur_id=admin.id
        )

    relu = (
        await db_session.execute(select(Utilisateur).where(Utilisateur.id == cible.id))
    ).scalar_one()
    assert relu.hashed_password == ancien_hash


async def test_changer_mot_de_passe_introuvable(db_session: AsyncSession) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="cmdp.introuvable.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    with pytest.raises(UtilisateurIntrouvable):
        await changer_mot_de_passe(
            db_session,
            uuid.uuid4(),
            mot_de_passe=_MOT_DE_PASSE_VALIDE,
            auteur_id=admin.id,
        )


async def test_retirer_son_propre_acces_refuse(db_session: AsyncSession) -> None:
    admin1 = await creer_utilisateur(
        db_session,
        email="soi1@example.invalid",
        nom="Admin Un",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    # Un second admin actif, pour isoler `ActionSurSoiInterdite` du
    # garde-fou `DernierAdmin` (`test_dernier_admin_protege` ci-dessus).
    await creer_utilisateur(
        db_session,
        email="soi2@example.invalid",
        nom="Admin Deux",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    with pytest.raises(ActionSurSoiInterdite):
        await retirer_acces(db_session, admin1.id, auteur_id=admin1.id)

    relu = (
        await db_session.execute(select(Utilisateur).where(Utilisateur.id == admin1.id))
    ).scalar_one()
    assert relu.is_active is True


async def test_retirer_acces_coupe_les_sessions(db_session: AsyncSession) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="retire.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    cible = await creer_utilisateur(
        db_session,
        email="retire.cible@example.invalid",
        nom="Cible",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    db_session.add(
        JetonSession(token="jeton-retire-1", user_id=cible.id)  # noqa: S106 -- test, jamais un vrai secret
    )
    await db_session.commit()

    compte = await retirer_acces(db_session, cible.id, auteur_id=admin.id)

    assert compte.actif is False
    relu = (
        await db_session.execute(select(Utilisateur).where(Utilisateur.id == cible.id))
    ).scalar_one()
    assert relu.is_active is False
    jetons_restants = (
        (
            await db_session.execute(
                select(JetonSession).where(JetonSession.user_id == cible.id)
            )
        )
        .scalars()
        .all()
    )
    assert jetons_restants == []

    journal = await _journal_action(db_session, cible.id, "acces_retire")
    assert journal.utilisateur_id == admin.id
    assert journal.avant == {"actif": True}
    assert journal.apres == {"actif": False}


async def test_retirer_acces_introuvable(db_session: AsyncSession) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="retire.introuvable.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    with pytest.raises(UtilisateurIntrouvable):
        await retirer_acces(db_session, uuid.uuid4(), auteur_id=admin.id)


async def test_retablir_acces(db_session: AsyncSession) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="retablir.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    cible = await creer_utilisateur(
        db_session,
        email="retablir.cible@example.invalid",
        nom="Cible",
        role="agent",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )
    await retirer_acces(db_session, cible.id, auteur_id=admin.id)

    compte = await retablir_acces(db_session, cible.id, auteur_id=admin.id)

    assert compte.actif is True
    relu = (
        await db_session.execute(select(Utilisateur).where(Utilisateur.id == cible.id))
    ).scalar_one()
    assert relu.is_active is True

    journal = await _journal_action(db_session, cible.id, "acces_retabli")
    assert journal.utilisateur_id == admin.id
    assert journal.avant == {"actif": False}
    assert journal.apres == {"actif": True}


async def test_retablir_acces_introuvable(db_session: AsyncSession) -> None:
    admin = await creer_utilisateur(
        db_session,
        email="retablir.introuvable.admin@example.invalid",
        nom="Admin",
        role="admin",
        agence="Toulouse",
        mot_de_passe=_MOT_DE_PASSE_VALIDE,
    )

    with pytest.raises(UtilisateurIntrouvable):
        await retablir_acces(db_session, uuid.uuid4(), auteur_id=admin.id)


# ---------------------------------------------------------------------------
# Fix round 1 (constat de revue) : condition de course sur la garde
# « dernier administrateur actif » -- `pg_advisory_xact_lock(VERROU_ADMINS)`.
# Même schéma que `test_creation_concurrente_un_seul_chantier`
# (`app/modules/ingest/tests/test_rattachement_chantier.py`) : `db_engine`
# directement (pas `db_session`), une session indépendante par tâche
# concurrente (chacune ouvre/ferme sa propre transaction), `asyncio.gather`.
# ---------------------------------------------------------------------------


async def test_deux_retrogradations_croisees_simultanees_une_seule_reussit(
    db_engine: AsyncEngine,
) -> None:
    """Deux admins qui se rétrogradent l'un l'autre en `agent` en même temps
    (A rétrograde B, B rétrograde A) : sans verrou, chaque transaction peut
    lire « un autre admin actif existe » avant que l'autre n'ait commité, et
    les deux réussiraient -- plus aucun admin actif, contrairement au
    garde-fou (spec §3). Avec `pg_advisory_xact_lock(VERROU_ADMINS)`, les
    deux transactions sont sérialisées : exactement l'une réussit, l'autre
    lève `DernierAdmin` (à ce moment-là, sa propre cible est bien devenue le
    dernier admin actif puisque l'autre a déjà été rétrogradé)."""
    sessionmaker = creer_sessionmaker(db_engine)

    async with sessionmaker() as preparation:
        admin_a = await creer_utilisateur(
            preparation,
            email="course.admin.a@example.invalid",
            nom="Admin A",
            role="admin",
            agence="Toulouse",
            mot_de_passe=_MOT_DE_PASSE_VALIDE,
        )
        admin_b = await creer_utilisateur(
            preparation,
            email="course.admin.b@example.invalid",
            nom="Admin B",
            role="admin",
            agence="Toulouse",
            mot_de_passe=_MOT_DE_PASSE_VALIDE,
        )
    admin_a_id, admin_a_email = admin_a.id, admin_a.email
    admin_b_id, admin_b_email = admin_b.id, admin_b.email

    async def _retrograder(
        *, cible_id: uuid.UUID, cible_email: str, nom: str, auteur_id: uuid.UUID
    ) -> None:
        async with sessionmaker() as session:
            await modifier_compte(
                session,
                cible_id,
                email=cible_email,
                nom=nom,
                role="agent",
                agence="Toulouse",
                telegram_user_id=None,
                auteur_id=auteur_id,
            )

    resultats = await asyncio.gather(
        _retrograder(
            cible_id=admin_b_id,
            cible_email=admin_b_email,
            nom="Admin B",
            auteur_id=admin_a_id,
        ),
        _retrograder(
            cible_id=admin_a_id,
            cible_email=admin_a_email,
            nom="Admin A",
            auteur_id=admin_b_id,
        ),
        return_exceptions=True,
    )

    reussites = [r for r in resultats if r is None]
    echecs_dernier_admin = [r for r in resultats if isinstance(r, DernierAdmin)]
    autres_echecs = [
        r for r in resultats if r is not None and not isinstance(r, DernierAdmin)
    ]

    assert autres_echecs == []
    assert len(reussites) == 1
    assert len(echecs_dernier_admin) == 1

    async with sessionmaker() as verification:
        nb_admins_actifs = (
            await verification.execute(
                select(func.count())
                .select_from(Utilisateur)
                .where(Utilisateur.role == "admin")
                .where(Utilisateur.is_active.is_(True))
                .where(Utilisateur.id.in_([admin_a_id, admin_b_id]))
            )
        ).scalar_one()
    assert nb_admins_actifs == 1
