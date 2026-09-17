"""Tests de `POST /api/factures` (L2-T4) : autorisation, taille bornée,
traduction des erreurs de `ingest.service.deposer_facture` en codes HTTP.

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3) : les scénarios
métier détaillés (comptage blocs/lignes vs `analyser_facture_unikalo`,
commentaires joints, course entre deux dépôts) vivent dans
`app/modules/ingest/tests/test_deposer_facture.py`, le seul endroit
autorisé à importer `extract` (garde `tests/test_frontieres.py`) — `api` ne
peut importer que `app.core` et `app.modules.ingest`.

Chaque test construit un `FastAPI` isolé (jamais `app.main.app`), comme
`app/core/tests/test_auth.py` : `auth_router` + `api_router` (qui inclut
`/api/factures`), `app.state.sessions` branché sur `bl_test`. `get_settings`
est surchargé uniquement pour `docs_dir` (répertoire jetable, `tmp_path`) —
`model_copy` sur la config réelle (chargée depuis `.env` du worktree) évite
de reconstruire tous les secrets. `get_ocr_facture` est toujours surchargé :
aucun appel réseau réel (R17).

IP dédiées à ce fichier (`10.77.0.x`) pour ne jamais partager le quota de
`slowapi` (5/minute, singleton de process) avec `app/core/tests/test_auth.py`
(`10.66.0.x`)."""

from __future__ import annotations

import itertools
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.config import get_settings
from app.modules.api import router as api_router
from app.modules.api.factures import _TAILLE_MAX_OCTETS
from app.modules.ingest.mistral import ErreurOCR
from app.modules.ingest.models import BlocFacture, Document, Journal, Utilisateur
from app.modules.ingest.router import get_ocr_facture

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"
_SIGNATURE_PDF_INVENTEE = b"%PDF-1.4\n%invente-pour-les-tests\n"

_OcrFn = Callable[[bytes, str], Awaitable[dict[str, Any]]]

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.77.0.{next(_IPS)}"


_DOSSIER_FIXTURES = (
    Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "unikalo"
)
_FICHIER_FIXTURE_OCR = _DOSSIER_FIXTURES / "facture_2026-08.mistral-ocr.json"


@pytest.fixture
def reponse_ocr_reelle() -> dict[str, Any]:
    if not _FICHIER_FIXTURE_OCR.is_file():
        pytest.skip(
            "aucune fixture facture_2026-08.mistral-ocr.json dans "
            "tests/fixtures/unikalo/ (clone neuf ou fixtures non déposées)"
        )
    donnees: dict[str, Any] = json.loads(
        _FICHIER_FIXTURE_OCR.read_text(encoding="utf-8")
    )
    return donnees


async def _ocr_jamais_appele(contenu: bytes, mime: str) -> dict[str, Any]:
    raise AssertionError("l'OCR ne doit pas être appelé sur un fichier non PDF")


def _app_test(
    sessions: async_sessionmaker[AsyncSession], docs_dir: Path, ocr: _OcrFn
) -> FastAPI:
    app_test = FastAPI()
    app_test.state.sessions = sessions
    app_test.include_router(auth_router)
    app_test.include_router(api_router)

    def _settings_test() -> Any:
        # Réutilise la config réelle (`.env` du worktree, `COOKIE_SECURE`
        # inclus) pour ne changer que `docs_dir` : le routeur n'a besoin que
        # de ce champ, `get_ocr_facture` est surchargé séparément (jamais
        # d'appel Mistral réel, R17).
        return get_settings().model_copy(update={"docs_dir": docs_dir})

    app_test.dependency_overrides[get_settings] = _settings_test
    app_test.dependency_overrides[get_ocr_facture] = lambda: ocr
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


async def _deposer(
    app_test: FastAPI,
    *,
    cookie: str | None,
    contenu: bytes = _SIGNATURE_PDF_INVENTEE,
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=("10.0.0.1", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.post(
            "/api/factures",
            files={"fichier": ("facture.pdf", contenu, "application/pdf")},
        )


# --------------------------------------------------------------------------
# Autorisation
# --------------------------------------------------------------------------


async def test_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path, _ocr_jamais_appele)

    reponse = await _deposer(app_test, cookie=None)

    assert reponse.status_code == 401


async def test_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.factures@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path, _ocr_jamais_appele)
    cookie = await _login(app_test, email="agent.factures@example.invalid")

    reponse = await _deposer(app_test, cookie=cookie)

    assert reponse.status_code == 403


# --------------------------------------------------------------------------
# Taille bornée (413) — décision du contrôleur, avant tout appel au service
# --------------------------------------------------------------------------


async def test_fichier_trop_volumineux_renvoie_413(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.413@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path, _ocr_jamais_appele)
    cookie = await _login(app_test, email="admin.413@example.invalid")
    contenu_trop_gros = _SIGNATURE_PDF_INVENTEE + b"0" * (_TAILLE_MAX_OCTETS + 1)

    reponse = await _deposer(app_test, cookie=cookie, contenu=contenu_trop_gros)

    assert reponse.status_code == 413
    assert (await db_session.execute(select(Document))).scalars().all() == []


# --------------------------------------------------------------------------
# Traduction des erreurs de `deposer_facture`
# --------------------------------------------------------------------------


async def test_fichier_non_pdf_renvoie_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.422pdf@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path, _ocr_jamais_appele)
    cookie = await _login(app_test, email="admin.422pdf@example.invalid")

    reponse = await _deposer(app_test, cookie=cookie, contenu=b"pas-un-pdf-du-tout")

    assert reponse.status_code == 422
    assert reponse.json()["detail"] == "Le fichier n'est pas un PDF."
    assert (await db_session.execute(select(Document))).scalars().all() == []


async def test_ocr_en_echec_renvoie_502_rien_stocke(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.502@example.invalid", role="admin"
    )

    async def _ocr_en_echec(contenu: bytes, mime: str) -> dict[str, Any]:
        raise ErreurOCR("échec factice de l'OCR")

    app_test = _app_test(sessions_test, tmp_path, _ocr_en_echec)
    cookie = await _login(app_test, email="admin.502@example.invalid")

    reponse = await _deposer(app_test, cookie=cookie)

    assert reponse.status_code == 502
    assert reponse.json()["detail"] == "Lecture de la facture impossible, réessayez."
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []


async def test_reponse_ocr_non_reconnue_renvoie_422_rien_stocke(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.422format@example.invalid", role="admin"
    )

    async def _ocr_reponse_quelconque(contenu: bytes, mime: str) -> dict[str, Any]:
        return {"pages": [{"markdown": "texte inventé sans structure Unikalo"}]}

    app_test = _app_test(sessions_test, tmp_path, _ocr_reponse_quelconque)
    cookie = await _login(app_test, email="admin.422format@example.invalid")

    reponse = await _deposer(app_test, cookie=cookie)

    assert reponse.status_code == 422
    assert "Unikalo" in reponse.json()["detail"]
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------
# Dépôt réussi (vraie fixture, skip si absente) : 201, journal, doublon
# --------------------------------------------------------------------------


async def test_depot_valide_renvoie_201_et_journal_ecrit(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    reponse_ocr_reelle: dict[str, Any],
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.201@example.invalid", role="admin"
    )

    async def _ocr(contenu: bytes, mime: str) -> dict[str, Any]:
        return reponse_ocr_reelle

    app_test = _app_test(sessions_test, tmp_path, _ocr)
    cookie = await _login(app_test, email="admin.201@example.invalid")

    reponse = await _deposer(app_test, cookie=cookie)

    assert reponse.status_code == 201
    corps = reponse.json()
    assert corps["numero"]
    assert corps["nb_blocs"] > 0

    document = await db_session.get(Document, corps["id"])
    assert document is not None
    assert document.numero == corps["numero"]

    blocs_db = (
        (
            await db_session.execute(
                select(BlocFacture.id).where(BlocFacture.facture_id == document.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(blocs_db) == corps["nb_blocs"]

    journaux = (
        (
            await db_session.execute(
                select(Journal).where(Journal.cible_id == str(document.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(journaux) == 1
    assert journaux[0].action == "facture_deposee"

    fichiers = list(tmp_path.glob("*.pdf"))
    assert len(fichiers) == 1


async def test_second_depot_meme_facture_renvoie_409_avec_original_id(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    reponse_ocr_reelle: dict[str, Any],
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.409@example.invalid", role="admin"
    )

    async def _ocr(contenu: bytes, mime: str) -> dict[str, Any]:
        return reponse_ocr_reelle

    app_test = _app_test(sessions_test, tmp_path, _ocr)
    cookie = await _login(app_test, email="admin.409@example.invalid")

    premiere = await _deposer(app_test, cookie=cookie)
    assert premiere.status_code == 201
    original_id = premiere.json()["id"]

    seconde = await _deposer(app_test, cookie=cookie)

    assert seconde.status_code == 409
    corps = seconde.json()
    assert corps["detail"] == "Facture déjà déposée."
    assert corps["original_id"] == original_id
    assert len(list(tmp_path.glob("*.pdf"))) == 1
