"""Tests de `POST/GET /api/grilles/...` (phase 3, tâche P4) : autorisation
(agent 403, anonyme 401), taille bornée (413), traduction des erreurs de
`ingest.grilles` en codes HTTP, contrôle d'origine sur les `POST`, en-tête
`Content-Disposition` du modèle.

Même harnais que `app/modules/api/tests/test_factures.py` (`FastAPI`
isolé, `ControleOrigineMiddleware`, cookies de session réels) -- les
scénarios métier détaillés (comparaison au prix en vigueur, historique
inaltérable, écriture disque) vivent dans
`app/modules/ingest/tests/test_grilles.py`, seul endroit autorisé à
importer `extract`/`normalize` (garde `tests/test_frontieres.py`)."""

from __future__ import annotations

import io
import itertools
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import openpyxl
import pytest
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.config import get_settings
from app.core.origine import ControleOrigineMiddleware
from app.modules.api import router as api_router
from app.modules.ingest.models import (
    Document,
    Fournisseur,
    GrillePrix,
    Ligne,
    PrixObserve,
    Utilisateur,
)
from app.modules.ingest.tests.test_contestations_prix import _creer_anomalie_fermee

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.78.0.{next(_IPS)}"


def _classeur_grille(contenu: bytes | None = None) -> bytes:
    if contenu is not None:
        return contenu
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    assert feuille is not None
    feuille.title = "Grille"
    feuille.append(
        ("Référence", "Désignation", "Unité", "Prix unitaire HT (€)", "Remise %")
    )
    feuille.append(("REF-1", "Produit inventé", "sac", 5.5, None))
    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


def _app_test(sessions: async_sessionmaker[AsyncSession], docs_dir: Path) -> FastAPI:
    app_test = FastAPI()
    app_test.add_middleware(ControleOrigineMiddleware)
    app_test.state.sessions = sessions
    app_test.include_router(auth_router)
    app_test.include_router(api_router)

    def _settings_test() -> Any:
        return get_settings().model_copy(update={"docs_dir": docs_dir})

    app_test.dependency_overrides[get_settings] = _settings_test
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


async def _creer_fournisseur(db_session: AsyncSession) -> Fournisseur:
    fournisseur = Fournisseur(nom=f"Fournisseur test {uuid.uuid4()}")
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


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


async def _requete(
    app_test: FastAPI,
    methode: str,
    chemin: str,
    *,
    cookie: str | None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=(_ip_isolee(), 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.request(methode, chemin, headers=headers or {}, **kwargs)


# --------------------------------------------------------------------------
# Autorisation (échantillon : une route GET, une route POST)
# --------------------------------------------------------------------------


async def test_modele_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(app_test, "GET", "/api/grilles/modele", cookie=None)

    assert reponse.status_code == 401


async def test_modele_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.grilles@example.invalid", role="agent"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.grilles@example.invalid")

    reponse = await _requete(app_test, "GET", "/api/grilles/modele", cookie=cookie)

    assert reponse.status_code == 403


async def test_modele_admin_recoit_le_fichier_avec_content_disposition(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.modele@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.modele@example.invalid")

    reponse = await _requete(app_test, "GET", "/api/grilles/modele", cookie=cookie)

    assert reponse.status_code == 200
    assert (
        reponse.headers["content-disposition"]
        == 'attachment; filename="modele-grille-de-prix.xlsx"'
    )


async def test_enregistrer_prix_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{uuid.uuid4()}/prix",
        cookie=None,
        json={"designation": "Produit", "prix_ht": "5.00", "date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 401


async def test_enregistrer_prix_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.prix@example.invalid", role="agent"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.prix@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/prix",
        cookie=cookie,
        json={"designation": "Produit", "prix_ht": "5.00", "date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 403


# --------------------------------------------------------------------------
# Contrôle d'origine (un `POST`, un `GET`)
# --------------------------------------------------------------------------


async def test_enregistrer_prix_origine_etrangere_refusee_403(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{uuid.uuid4()}/prix",
        cookie=None,
        headers={"Origin": "https://evil.example"},
        json={"designation": "Produit", "prix_ht": "5.00", "date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 403
    assert reponse.json() == {"detail": "Origine refusée."}


# --------------------------------------------------------------------------
# 404 fournisseur inconnu
# --------------------------------------------------------------------------


async def test_grille_fournisseur_inconnu_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.404@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.404@example.invalid")

    reponse = await _requete(
        app_test, "GET", f"/api/grilles/fournisseurs/{uuid.uuid4()}", cookie=cookie
    )

    assert reponse.status_code == 404


async def test_historique_produit_inconnu_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.404hist@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.404hist@example.invalid")

    reponse = await _requete(
        app_test,
        "GET",
        f"/api/grilles/fournisseurs/{fournisseur.id}/produits/nom:jamais-vu/historique",
        cookie=cookie,
    )

    assert reponse.status_code == 404


# --------------------------------------------------------------------------
# Contestations de prix du fournisseur
# --------------------------------------------------------------------------


async def _creer_bon_et_ligne(
    db_session: AsyncSession, fournisseur: Fournisseur
) -> tuple[Document, Ligne]:
    document = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        numero="BL-INVENTE-1",
        fournisseur_id=fournisseur.id,
        date_doc=date(2026, 9, 1),
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    ligne = Ligne(
        document_id=document.id,
        type_ligne="article",
        code_brut="REF1",
        article_brut="Produit inventé",
        pu_ht=Decimal("12.00"),
        ordre=0,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return document, ligne


async def test_contestations_fournisseur_admin_200(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.contest@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    document, ligne = await _creer_bon_et_ligne(db_session, fournisseur)
    await _creer_anomalie_fermee(
        db_session,
        document=document,
        ligne=ligne,
        commentaire="Contesté : remise oubliée inventée",
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.contest@example.invalid")

    reponse = await _requete(
        app_test,
        "GET",
        f"/api/grilles/fournisseurs/{fournisseur.id}/contestations",
        cookie=cookie,
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps) == 1
    assert corps[0]["commentaire"] == "remise oubliée inventée"
    assert corps[0]["numero_bon"] == "BL-INVENTE-1"
    assert corps[0]["document_id"] == str(document.id)
    assert corps[0]["regles"] == ["R19"]
    assert corps[0]["prix_bon"] == "12.00"
    assert corps[0]["dans_la_grille"] is False


async def test_contestations_fournisseur_produit_retrouve_par_le_nom(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.contest-nom@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    db_session.add(
        GrillePrix(
            fournisseur_id=fournisseur.id,
            cle_produit="ref:ref1",
            reference="REF1",
            designation="Produit inventé",
            unite_brut=None,
            unite=None,
            prix_ht=Decimal("10"),
            prix_net=Decimal("10.0000"),
            date_effet=date(2020, 1, 1),
            source="saisie",
        )
    )
    await db_session.commit()
    document, ligne = await _creer_bon_et_ligne(db_session, fournisseur)
    await _creer_anomalie_fermee(
        db_session,
        document=document,
        ligne=ligne,
        commentaire="Contesté : remise oubliée inventée",
        detail={
            "produit": "Produit inventé",
            "code": "—",
            "prix_bon": "12.00",
            "prix_grille": "10.00",
            "designation_grille": "Produit inventé",
            "methode": "nom",
        },
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.contest-nom@example.invalid")

    reponse = await _requete(
        app_test,
        "GET",
        f"/api/grilles/fournisseurs/{fournisseur.id}/contestations",
        cookie=cookie,
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps) == 1
    assert corps[0]["cle_produit"] == "ref:ref1"
    assert corps[0]["dans_la_grille"] is True


async def test_contestations_fournisseur_sans_contestation_renvoie_liste_vide(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.contest-vide@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.contest-vide@example.invalid")

    reponse = await _requete(
        app_test,
        "GET",
        f"/api/grilles/fournisseurs/{fournisseur.id}/contestations",
        cookie=cookie,
    )

    assert reponse.status_code == 200
    assert reponse.json() == []


async def test_contestations_fournisseur_inconnu_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.contest-404@example.invalid", role="admin"
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.contest-404@example.invalid")

    reponse = await _requete(
        app_test,
        "GET",
        f"/api/grilles/fournisseurs/{uuid.uuid4()}/contestations",
        cookie=cookie,
    )

    assert reponse.status_code == 404


async def test_contestations_fournisseur_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="agent.contest@example.invalid", role="agent"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="agent.contest@example.invalid")

    reponse = await _requete(
        app_test,
        "GET",
        f"/api/grilles/fournisseurs/{fournisseur.id}/contestations",
        cookie=cookie,
    )

    assert reponse.status_code == 403


# --------------------------------------------------------------------------
# Saisie : succès, 422 (prix invalide, prix inchangé)
# --------------------------------------------------------------------------


async def test_enregistrer_prix_succes_201(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.saisie@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.saisie@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/prix",
        cookie=cookie,
        json={
            "designation": "Produit saisi",
            "prix_ht": "9.90",
            "date_effet": "2026-01-01",
        },
    )

    assert reponse.status_code == 201
    assert reponse.json()["prix_net"] == "9.9000"


async def test_enregistrer_prix_negatif_renvoie_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.422saisie@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.422saisie@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/prix",
        cookie=cookie,
        json={"designation": "Produit", "prix_ht": "-1.00", "date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 422


# --------------------------------------------------------------------------
# Retrait : 404 produit inconnu
# --------------------------------------------------------------------------


async def test_retirer_produit_inconnu_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.retrait404@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.retrait404@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/retrait",
        cookie=cookie,
        json={"cle_produit": "nom:jamais-vu", "date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 404


# --------------------------------------------------------------------------
# Import : 413, 422 (fichier invalide), 201, aucune ligne valide -> 422
# --------------------------------------------------------------------------


async def test_import_apercu_fichier_trop_volumineux_413(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.413grille@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.413grille@example.invalid")
    contenu_trop_gros = b"PK\x03\x04" + b"0" * (5 * 1024 * 1024)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/import/apercu",
        cookie=cookie,
        files={
            "fichier": ("grille.xlsx", contenu_trop_gros, "application/octet-stream")
        },
        data={"date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 413


async def test_import_apercu_fichier_invalide_renvoie_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.422grille@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.422grille@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/import/apercu",
        cookie=cookie,
        files={"fichier": ("grille.xlsx", b"pas-un-xlsx", "application/octet-stream")},
        data={"date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 422


async def test_import_apercu_200_avec_ligne_modifiee(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Constat de la relecture finale : les tests API de l'aperçu ne
    couvraient que les erreurs (413, 422), jamais une réponse 200 avec du
    contenu -- une inversion ancien/nouveau prix ou unité, côté sérialisation
    (`ApercuImportReponse`) comme côté calcul, passerait inaperçue."""
    await _creer_utilisateur(
        db_session, email="admin.apercu200@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    db_session.add(
        GrillePrix(
            fournisseur_id=fournisseur.id,
            cle_produit="nom:produit existant",
            reference=None,
            designation="Produit existant",
            unite_brut=None,
            unite="kg",
            prix_ht=Decimal("10"),
            prix_net=Decimal("10.0000"),
            date_effet=date(2020, 1, 1),
            source="saisie",
        )
    )
    await db_session.commit()

    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.apercu200@example.invalid")

    classeur = openpyxl.Workbook()
    feuille = classeur.active
    assert feuille is not None
    feuille.title = "Grille"
    feuille.append(
        ("Référence", "Désignation", "Unité", "Prix unitaire HT (€)", "Remise %")
    )
    feuille.append((None, "Produit existant", "l", 12.0, None))
    tampon = io.BytesIO()
    classeur.save(tampon)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/import/apercu",
        cookie=cookie,
        files={
            "fichier": (
                "grille.xlsx",
                tampon.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["nb_modifies"] == 1
    assert corps["nb_nouveaux"] == 0
    modifie = corps["modifies"][0]
    assert modifie["designation"] == "Produit existant"
    assert modifie["nouveau_prix_net"] == "12.0000"
    assert modifie["ancien_prix_net"] == "10.0000"
    assert modifie["nouvelle_unite"] == "l"
    assert modifie["ancienne_unite"] == "kg"


async def test_import_succes_201(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.import201@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.import201@example.invalid")

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/import",
        cookie=cookie,
        files={
            "fichier": (
                "grille.xlsx",
                _classeur_grille(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 201
    assert reponse.json()["nb_nouveaux"] == 1


async def test_import_aucune_ligne_valide_renvoie_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.422vide@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.422vide@example.invalid")

    classeur = openpyxl.Workbook()
    feuille = classeur.active
    assert feuille is not None
    feuille.append(
        ("Référence", "Désignation", "Unité", "Prix unitaire HT (€)", "Remise %")
    )
    tampon = io.BytesIO()
    classeur.save(tampon)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/grilles/fournisseurs/{fournisseur.id}/import",
        cookie=cookie,
        files={
            "fichier": (
                "grille.xlsx",
                tampon.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"date_effet": "2026-01-01"},
    )

    assert reponse.status_code == 422
    assert (await db_session.execute(select(GrillePrix))).scalars().all() == []


# --------------------------------------------------------------------------
# Historique complet d'un produit (lot 2 du 31/10/2026, B4)
# --------------------------------------------------------------------------


async def test_historique_complet_admin_et_agent(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(
        db_session, email="admin.histcomplet@example.invalid", role="admin"
    )
    await _creer_utilisateur(
        db_session, email="agent.histcomplet@example.invalid", role="agent"
    )
    fournisseur = await _creer_fournisseur(db_session)
    db_session.add(
        GrillePrix(
            fournisseur_id=fournisseur.id,
            cle_produit="ref:ab12",
            reference="AB12",
            designation="Enduit",
            prix_ht=Decimal("10.00"),
            prix_net=Decimal("10.00"),
            date_effet=date(2026, 8, 1),
            source="saisie",
        )
    )
    db_session.add(
        PrixObserve(
            fournisseur_id=fournisseur.id,
            cle_produit="ref:ab12",
            designation="Enduit",
            date_observation=date(2026, 7, 1),
            prix_ht=Decimal("9.50"),
            piece="F-1",
            source_libelle="Fichier inventé",
        )
    )
    await db_session.commit()
    app_test = _app_test(sessions_test, tmp_path)
    url = (
        f"/api/grilles/fournisseurs/{fournisseur.id}"
        "/produits/ref:ab12/historique-complet"
    )

    cookie_agent = await _login(app_test, email="agent.histcomplet@example.invalid")
    refus = await _requete(app_test, "GET", url, cookie=cookie_agent)
    assert refus.status_code == 403

    cookie = await _login(app_test, email="admin.histcomplet@example.invalid")
    reponse = await _requete(app_test, "GET", url, cookie=cookie)

    assert reponse.status_code == 200
    corps = reponse.json()
    assert [(e["type"], e["date"]) for e in corps] == [
        ("grille", "2026-08-01"),
        ("observe", "2026-07-01"),
    ]
    assert corps[0]["origine"] == "Saisi à l'écran"
    assert corps[0]["prix_ht"] == "10.00"
    assert corps[1]["origine"] == "Fichier inventé"
    assert corps[1]["numero_document"] == "F-1"

    inconnu = await _requete(
        app_test,
        "GET",
        f"/api/grilles/fournisseurs/{uuid.uuid4()}/produits/ref:x/historique-complet",
        cookie=cookie,
    )
    assert inconnu.status_code == 404
