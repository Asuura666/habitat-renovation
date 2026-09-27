"""Tests de `GET /api/commentaires/documents/{document_id}` et `POST
/api/commentaires/lignes/{ligne_id}` (tâche C2 de la phase 3) :
autorisation, codes HTTP, forme JSON, contrôle d'origine.

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3) : les
scénarios métier détaillés (ordre des lignes/commentaires, libellé figé,
relance de la lecture, journal) vivent dans
`app/modules/ingest/tests/test_commentaires.py`, le seul endroit autorisé à
construire les dataclasses de service directement.

Même schéma que `test_documents_detail.py`/`test_factures.py` : `FastAPI`
isolé (jamais `app.main.app`), `app.state.sessions` branché sur `bl_test`,
IP dédiées (`10.81.0.x`) pour ne jamais partager le quota `slowapi` du login
avec un autre fichier de test.
"""

from __future__ import annotations

import itertools
import uuid

import httpx
import pytest
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.origine import ControleOrigineMiddleware
from app.modules.api import router as api_router
from app.modules.ingest.models import Document, Fournisseur, Ligne, Utilisateur

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.81.0.{next(_IPS)}"


def _app_test(sessions: async_sessionmaker[AsyncSession]) -> FastAPI:
    app_test = FastAPI()
    # Point 2 (vague finale du lot 2) : contrôle d'origine ajouté comme en
    # production (`app/main.py`) — voir `app/core/tests/test_origine.py`
    # pour les tests unitaires du middleware, et les tests dédiés plus bas
    # dans ce fichier pour son intégration avec `POST /api/commentaires/
    # lignes/{id}`.
    app_test.add_middleware(ControleOrigineMiddleware)
    app_test.state.sessions = sessions
    app_test.include_router(auth_router)
    app_test.include_router(api_router)
    return app_test


async def _creer_utilisateur(
    db_session: AsyncSession, *, email: str, role: str
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email,
        hashed_password=_PASSWORD_HELPER.hash(_MOT_DE_PASSE),
        role=role,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _creer_document(
    db_session: AsyncSession, *, deposant: Utilisateur | None = None
) -> Document:
    fournisseur = Fournisseur(nom="Fournisseur Invente API Commentaires")
    db_session.add(fournisseur)
    await db_session.flush()
    document = Document(
        type="bl",
        source="telegram",
        statut="a_verifier",
        fichier_path=f"bl-invente-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id,
        deposant_id=deposant.id if deposant is not None else None,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_ligne(db_session: AsyncSession, document: Document) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        type_ligne="article",
        code_brut="ART-INVENTE",
        article_brut="Article inventé",
        ordre=0,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _login(app_test: FastAPI, *, email: str) -> str:
    transport = ASGITransport(app=app_test, client=(_ip_isolee(), 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.post(
            "/api/auth/login", data={"username": email, "password": _MOT_DE_PASSE}
        )
    assert reponse.status_code == 204
    cookie = reponse.cookies.get(NOM_COOKIE)
    assert cookie is not None
    return cookie


async def _lire_commentaires(
    app_test: FastAPI, document_id: uuid.UUID, *, cookie: str | None
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=("10.0.0.1", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.get(f"/api/commentaires/documents/{document_id}")


async def _poster_commentaire(
    app_test: FastAPI,
    ligne_id: uuid.UUID,
    *,
    cookie: str | None,
    texte: str = "Commentaire inventé.",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=("10.0.0.1", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.post(
            f"/api/commentaires/lignes/{ligne_id}",
            json={"texte": texte},
            headers=headers or {},
        )


# --------------------------------------------------------------------------
# GET /api/commentaires/documents/{id}
# --------------------------------------------------------------------------


async def test_lecture_anonyme_renvoie_401(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    document = await _creer_document(db_session)
    app_test = _app_test(sessions_test)

    reponse = await _lire_commentaires(app_test, document.id, cookie=None)

    assert reponse.status_code == 401


async def test_lecture_document_inconnu_renvoie_404(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.commentaires@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="admin.commentaires@example.invalid")

    reponse = await _lire_commentaires(app_test, uuid.uuid4(), cookie=cookie)

    assert reponse.status_code == 404


async def test_lecture_reussie_renvoie_le_commentaire_sous_sa_ligne(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.lecture@example.invalid", role="admin"
    )
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="admin.lecture@example.invalid")
    reponse_ajout = await _poster_commentaire(app_test, ligne.id, cookie=cookie)
    assert reponse_ajout.status_code == 201

    reponse = await _lire_commentaires(app_test, document.id, cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["nb_commentaires"] == 1
    assert corps["sans_ligne"] == []
    assert len(corps["lignes"]) == 1
    assert corps["lignes"][0]["ligne_id"] == str(ligne.id)
    assert len(corps["lignes"][0]["commentaires"]) == 1
    assert corps["lignes"][0]["commentaires"][0]["texte"] == "Commentaire inventé."
    assert corps["lignes"][0]["commentaires"][0]["auteur"] == admin.email


async def test_agent_sur_bon_dun_autre_lecture_renvoie_404(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    proprietaire = await _creer_utilisateur(
        db_session, email="agent.proprietaire@example.invalid", role="agent"
    )
    await _creer_utilisateur(
        db_session, email="agent.autre@example.invalid", role="agent"
    )
    document = await _creer_document(db_session, deposant=proprietaire)
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="agent.autre@example.invalid")

    reponse = await _lire_commentaires(app_test, document.id, cookie=cookie)

    assert reponse.status_code == 404


async def test_agent_sur_son_propre_bon_lecture_acceptee(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.proprio@example.invalid", role="agent"
    )
    document = await _creer_document(db_session, deposant=agent)
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="agent.proprio@example.invalid")

    reponse = await _lire_commentaires(app_test, document.id, cookie=cookie)

    assert reponse.status_code == 200
    assert reponse.json()["nb_commentaires"] == 0


# --------------------------------------------------------------------------
# POST /api/commentaires/lignes/{id}
# --------------------------------------------------------------------------


async def test_ajout_anonyme_renvoie_401(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    app_test = _app_test(sessions_test)

    reponse = await _poster_commentaire(app_test, ligne.id, cookie=None)

    assert reponse.status_code == 401


async def test_ajout_ligne_inconnue_renvoie_404(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.ajout404@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="admin.ajout404@example.invalid")

    reponse = await _poster_commentaire(app_test, uuid.uuid4(), cookie=cookie)

    assert reponse.status_code == 404


async def test_ajout_texte_vide_renvoie_422(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.vide@example.invalid", role="admin"
    )
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="admin.vide@example.invalid")

    reponse = await _poster_commentaire(app_test, ligne.id, cookie=cookie, texte="   ")

    assert reponse.status_code == 422


async def test_ajout_texte_trop_long_renvoie_422(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.long@example.invalid", role="admin"
    )
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="admin.long@example.invalid")

    reponse = await _poster_commentaire(
        app_test, ligne.id, cookie=cookie, texte="a" * 1001
    )

    assert reponse.status_code == 422


async def test_ajout_reussi_renvoie_201_et_le_commentaire(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.201@example.invalid", role="admin"
    )
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="admin.201@example.invalid")

    reponse = await _poster_commentaire(
        app_test, ligne.id, cookie=cookie, texte="Commentaire de test."
    )

    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps["texte"] == "Commentaire de test."
    assert corps["ligne_libelle"] == "ART-INVENTE — Article inventé"
    assert corps["auteur"] == "admin.201@example.invalid"
    assert "id" in corps
    assert "cree_le" in corps


async def test_agent_sur_bon_dun_autre_ajout_renvoie_404(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    proprietaire = await _creer_utilisateur(
        db_session, email="agent.proprietaire2@example.invalid", role="agent"
    )
    await _creer_utilisateur(
        db_session, email="agent.autre2@example.invalid", role="agent"
    )
    document = await _creer_document(db_session, deposant=proprietaire)
    ligne = await _creer_ligne(db_session, document)
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="agent.autre2@example.invalid")

    reponse = await _poster_commentaire(app_test, ligne.id, cookie=cookie)

    assert reponse.status_code == 404


async def test_agent_sur_son_propre_bon_ajout_accepte(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.proprio2@example.invalid", role="agent"
    )
    document = await _creer_document(db_session, deposant=agent)
    ligne = await _creer_ligne(db_session, document)
    app_test = _app_test(sessions_test)
    cookie = await _login(app_test, email="agent.proprio2@example.invalid")

    reponse = await _poster_commentaire(app_test, ligne.id, cookie=cookie)

    assert reponse.status_code == 201


# --------------------------------------------------------------------------
# Contrôle d'origine (point 2, vague finale du lot 2) — le middleware
# refuse avant même l'authentification (aucun cookie ici) : tests unitaires
# du middleware dans `app/core/tests/test_origine.py`.
# --------------------------------------------------------------------------


async def test_ajout_origine_etrangere_refusee_403(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    app_test = _app_test(sessions_test)

    reponse = await _poster_commentaire(
        app_test, ligne.id, cookie=None, headers={"Origin": "https://evil.example"}
    )

    assert reponse.status_code == 403
    assert reponse.json() == {"detail": "Origine refusée."}


async def test_ajout_meme_origine_atteint_lauthentification(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    """Même origine (ou absence d'`Origin`) : le contrôle laisse passer la
    requête, qui échoue ensuite normalement en 401 (aucun cookie) — preuve
    qu'elle a bien dépassé le middleware d'origine."""
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    app_test = _app_test(sessions_test)

    reponse = await _poster_commentaire(
        app_test, ligne.id, cookie=None, headers={"Origin": "http://test"}
    )

    assert reponse.status_code == 401


async def test_ajout_sec_fetch_site_cross_site_refuse_403(
    db_session: AsyncSession, sessions_test: async_sessionmaker[AsyncSession]
) -> None:
    document = await _creer_document(db_session)
    ligne = await _creer_ligne(db_session, document)
    app_test = _app_test(sessions_test)

    reponse = await _poster_commentaire(
        app_test, ligne.id, cookie=None, headers={"Sec-Fetch-Site": "cross-site"}
    )

    assert reponse.status_code == 403
    assert reponse.json() == {"detail": "Origine refusée."}
