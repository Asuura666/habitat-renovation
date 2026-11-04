"""Tests de `GET /api/documents/{id}`, `PATCH /api/documents/{id}`, `PUT
/api/documents/{id}/lignes`, `POST /api/documents/{id}/validation`, `POST
/api/documents/{id}/archivage` et `POST /api/documents/{id}/extraction`
(L3-T8a) : autorisation, portée par rôle, codes HTTP, forme JSON.

Ce fichier ne teste que le routeur (couche d'entrée, L2-D3) : les scénarios
métier détaillés (résolution chantier/article, motifs, journal complet)
vivent dans `app/modules/ingest/tests/test_corrections.py`, le seul endroit
autorisé à construire les dataclasses de service directement.

Même schéma que `test_documents.py` : `FastAPI` isolé, `app.state.sessions`
branché sur `bl_test`, IP dédiées (`10.80.0.x`) pour ne jamais partager le
quota `slowapi` du login avec un autre fichier de test.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.config import get_settings
from app.modules.api import router as api_router
from app.modules.ingest.mistral import ErreurOCR
from app.modules.ingest.models import Document, Fournisseur, Ligne, Utilisateur
from app.modules.ingest.router import get_ocr

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-1234"
_OcrFn = Callable[[bytes, str], Awaitable[dict[str, Any]]]

_IPS = itertools.count(1)


def _ip_isolee() -> str:
    return f"10.80.0.{next(_IPS)}"


def _app_test(
    sessions: async_sessionmaker[AsyncSession],
    docs_dir: Path,
    *,
    ocr: _OcrFn | None = None,
) -> FastAPI:
    app_test = FastAPI()
    app_test.state.sessions = sessions
    app_test.include_router(auth_router)
    app_test.include_router(api_router)

    def _settings_test() -> Any:
        return get_settings().model_copy(update={"docs_dir": docs_dir})

    app_test.dependency_overrides[get_settings] = _settings_test
    if ocr is not None:
        app_test.dependency_overrides[get_ocr] = lambda: ocr
    return app_test


async def _creer_utilisateur(
    db_session: AsyncSession, *, email: str, role: str, nom: str | None = None
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email,
        nom=nom,
        hashed_password=_PASSWORD_HELPER.hash(_MOT_DE_PASSE),
        role=role,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _creer_fournisseur(db_session: AsyncSession, *, nom: str) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_document(
    db_session: AsyncSession,
    *,
    type_: str = "bl",
    statut: str = "a_verifier",
    numero: str | None = None,
    fournisseur: Fournisseur | None = None,
    chantier_brut: str | None = None,
    total_ht: Decimal | None = None,
    date_doc: object = None,
    deposant: Utilisateur | None = None,
    fichier_path: str | None = None,
) -> Document:
    document = Document(
        type=type_,
        source="telegram",
        statut=statut,
        fichier_path=fichier_path or f"chemin-invente-{uuid.uuid4()}.jpg",
        numero=numero,
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
        chantier_brut=chantier_brut,
        total_ht=total_ht,
        date_doc=date_doc,
        deposant_id=deposant.id if deposant is not None else None,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_ligne(
    db_session: AsyncSession,
    *,
    document: Document,
    ordre: int,
    montant_ht: Decimal | None = Decimal("10.00"),
    confiance: Decimal | None = Decimal("0.9"),
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        type_ligne="article",
        code_brut="ART1",
        article_brut="Article inventé",
        qte_livree=Decimal("1"),
        qte_totale=Decimal("1"),
        unite_brut="U",
        pu_ht=Decimal("10.00"),
        montant_ht=montant_ht,
        confiance=confiance,
        ordre=ordre,
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


async def _requete(
    app_test: FastAPI,
    methode: str,
    chemin: str,
    *,
    cookie: str | None,
    json_body: object = None,
) -> httpx.Response:
    transport = ASGITransport(app=app_test, client=("10.0.3.1", 12345))
    cookies = {NOM_COOKIE: cookie} if cookie is not None else None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        return await client.request(methode, chemin, json=json_body)


async def _ocr_jamais_appele(contenu: bytes, mime: str) -> dict[str, Any]:
    raise AssertionError("l'OCR ne doit pas être appelé")


async def _ocr_en_echec(contenu: bytes, mime: str) -> dict[str, Any]:
    raise ErreurOCR("échec inventé pour le test")


def _reponse_ocr_minimale(numero: str, montant: str) -> dict[str, Any]:
    """Réponse OCR synthétique minimale (annotation + pages vides, sans
    scores de confiance) : suffisante pour `analyser_bl` (une valeur non
    trouvée dans le texte OCR obtient simplement confiance 0/`None`, jamais
    d'erreur)."""
    annotation: dict[str, Any] = {
        "type_bon": "livraison",
        "fournisseur": "FOURNISSEUR OCR RELANCE",
        "agence_fournisseur": None,
        "siret": None,
        "tva_intracommunautaire": None,
        "numero": numero,
        "date_doc": "01/01/2026",
        "chantier_brut": "CHANTIER OCR RELANCE",
        "numero_commande": None,
        "enleve_par": None,
        "total_ht": montant,
        "total_tva": None,
        "total_ttc": None,
        "lignes": [],
    }
    return {
        "pages": [{"index": 0, "markdown": "", "tables": []}],
        "model": "mistral-ocr-latest",
        "document_annotation": annotation,
        "usage_info": {"pages_processed": 1, "doc_size_bytes": 10},
    }


# --------------------------------------------------------------------------
# GET /api/documents/{id}
# --------------------------------------------------------------------------


async def test_detail_anonyme_renvoie_401(
    sessions_test: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    app_test = _app_test(sessions_test, tmp_path)

    reponse = await _requete(
        app_test,
        "GET",
        "/api/documents/00000000-0000-0000-0000-000000000000",
        cookie=None,
    )

    assert reponse.status_code == 401


async def test_detail_agent_voit_son_document(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.detail1@example.invalid", role="agent"
    )
    document = await _creer_document(db_session, deposant=agent, numero="L700")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse = await _requete(
        app_test, "GET", f"/api/documents/{document.id}", cookie=cookie
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["id"] == str(document.id)
    assert corps["modifiable"] is False
    assert set(corps["champs"].keys()) == {
        "fournisseur",
        "numero",
        "date_doc",
        "chantier_brut",
        "numero_commande",
        "enleve_par",
        "total_ht",
        "total_tva",
        "total_ttc",
    }


async def test_detail_agent_autre_document_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent_1 = await _creer_utilisateur(
        db_session, email="agent1.detail2@example.invalid", role="agent"
    )
    agent_2 = await _creer_utilisateur(
        db_session, email="agent2.detail2@example.invalid", role="agent"
    )
    document = await _creer_document(db_session, deposant=agent_1)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent_2.email)

    reponse = await _requete(
        app_test, "GET", f"/api/documents/{document.id}", cookie=cookie
    )

    assert reponse.status_code == 404


async def test_detail_facture_renvoie_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.detail3@example.invalid", role="admin"
    )
    facture = await _creer_document(db_session, type_="facture")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "GET", f"/api/documents/{facture.id}", cookie=cookie
    )

    assert reponse.status_code == 404


# --------------------------------------------------------------------------
# Écritures réservées à l'admin (403 pour un agent, avant tout accès au
# service).
# --------------------------------------------------------------------------


async def test_ecritures_agent_renvoie_403(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    agent = await _creer_utilisateur(
        db_session, email="agent.ecriture@example.invalid", role="agent"
    )
    document = await _creer_document(db_session, deposant=agent)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=agent.email)

    reponse_patch = await _requete(
        app_test,
        "PATCH",
        f"/api/documents/{document.id}",
        cookie=cookie,
        json_body={"numero_commande": "CDE"},
    )
    reponse_put = await _requete(
        app_test,
        "PUT",
        f"/api/documents/{document.id}/lignes",
        cookie=cookie,
        json_body={"lignes": []},
    )
    reponse_validation = await _requete(
        app_test, "POST", f"/api/documents/{document.id}/validation", cookie=cookie
    )
    reponse_archivage = await _requete(
        app_test,
        "POST",
        f"/api/documents/{document.id}/archivage",
        cookie=cookie,
        json_body={"commentaire": "doublon"},
    )
    reponse_extraction = await _requete(
        app_test, "POST", f"/api/documents/{document.id}/extraction", cookie=cookie
    )

    assert reponse_patch.status_code == 403
    assert reponse_put.status_code == 403
    assert reponse_validation.status_code == 403
    assert reponse_archivage.status_code == 403
    assert reponse_extraction.status_code == 403


# --------------------------------------------------------------------------
# PATCH /api/documents/{id}
# --------------------------------------------------------------------------


async def test_patch_corrige_champ_et_journalise(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.patch1@example.invalid", role="admin"
    )
    document = await _creer_document(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "PATCH",
        f"/api/documents/{document.id}",
        cookie=cookie,
        json_body={"numero_commande": "CDE-API-1"},
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["champs"]["numero_commande"]["valeur"] == "CDE-API-1"
    assert corps["champs"]["numero_commande"]["corrige"] is True


async def test_patch_numero_deja_utilise_409_avec_original_id(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.patch2@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Patch")
    original = await _creer_document(
        db_session, statut="recu", fournisseur=fournisseur, numero="L800"
    )
    cible = await _creer_document(db_session, fournisseur=fournisseur, numero=None)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "PATCH",
        f"/api/documents/{cible.id}",
        cookie=cookie,
        json_body={"numero": "L800"},
    )

    assert reponse.status_code == 409
    corps = reponse.json()
    assert corps["original_id"] == str(original.id)


async def test_patch_fournisseur_introuvable_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.patch3@example.invalid", role="admin"
    )
    document = await _creer_document(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "PATCH",
        f"/api/documents/{document.id}",
        cookie=cookie,
        json_body={"fournisseur_id": str(uuid.uuid4())},
    )

    assert reponse.status_code == 422


async def test_patch_document_archive_409(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.patch4@example.invalid", role="admin"
    )
    document = await _creer_document(db_session, statut="archive")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "PATCH",
        f"/api/documents/{document.id}",
        cookie=cookie,
        json_body={"numero_commande": "CDE"},
    )

    assert reponse.status_code == 409


async def test_patch_facture_404(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.patch5@example.invalid", role="admin"
    )
    facture = await _creer_document(db_session, type_="facture")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "PATCH",
        f"/api/documents/{facture.id}",
        cookie=cookie,
        json_body={"numero_commande": "CDE"},
    )

    assert reponse.status_code == 404


# --------------------------------------------------------------------------
# PUT /api/documents/{id}/lignes
# --------------------------------------------------------------------------


async def test_put_lignes_modification_ajout_suppression(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.lignes1@example.invalid", role="admin"
    )
    document = await _creer_document(db_session)
    ligne_gardee = await _creer_ligne(
        db_session, document=document, ordre=0, montant_ht=Decimal("10.00")
    )
    await _creer_ligne(
        db_session, document=document, ordre=1, montant_ht=Decimal("5.00")
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "PUT",
        f"/api/documents/{document.id}/lignes",
        cookie=cookie,
        json_body={
            "lignes": [
                {
                    "id": str(ligne_gardee.id),
                    "code_brut": "ART1",
                    "article_brut": "Article inventé",
                    "qte_livree": "1",
                    "qte_totale": "1",
                    "unite_brut": "U",
                    "pu_ht": "10.00",
                    "montant_ht": "20.00",
                },
                {
                    "id": None,
                    "code_brut": "ART-NOUVEAU",
                    "article_brut": "Nouvel article",
                    "qte_livree": "2",
                    "qte_totale": "2",
                    "unite_brut": "U",
                    "pu_ht": "3.00",
                    "montant_ht": "6.00",
                },
            ]
        },
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps["lignes"]) == 2
    modifiee = next(ligne for ligne in corps["lignes"] if ligne["code_brut"] == "ART1")
    assert modifiee["montant_ht"] == "20.00"
    assert modifiee["confiance"] is None
    nouvelle = next(
        ligne for ligne in corps["lignes"] if ligne["code_brut"] == "ART-NOUVEAU"
    )
    assert nouvelle["confiance"] is None


async def test_put_lignes_id_etranger_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.lignes2@example.invalid", role="admin"
    )
    document = await _creer_document(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "PUT",
        f"/api/documents/{document.id}/lignes",
        cookie=cookie,
        json_body={
            "lignes": [
                {
                    "id": str(uuid.uuid4()),
                    "code_brut": "X",
                    "article_brut": None,
                    "qte_livree": None,
                    "qte_totale": None,
                    "unite_brut": None,
                    "pu_ht": None,
                    "montant_ht": None,
                }
            ]
        },
    )

    assert reponse.status_code == 422


# --------------------------------------------------------------------------
# POST /api/documents/{id}/validation
# --------------------------------------------------------------------------


async def test_post_validation_refusee_puis_acceptee_apres_correction(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.validation1@example.invalid", role="admin"
    )
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Validation API")
    document = await _creer_document(
        db_session,
        fournisseur=fournisseur,
        numero="L900",
        chantier_brut=None,
        total_ht=Decimal("10.00"),
        date_doc=date(2026, 1, 1),
    )
    await _creer_ligne(
        db_session, document=document, ordre=0, montant_ht=Decimal("10.00")
    )
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse_refusee = await _requete(
        app_test, "POST", f"/api/documents/{document.id}/validation", cookie=cookie
    )

    assert reponse_refusee.status_code == 409
    assert reponse_refusee.json()["motifs"]

    reponse_correction = await _requete(
        app_test,
        "PATCH",
        f"/api/documents/{document.id}",
        cookie=cookie,
        json_body={"chantier_brut": "CHANTIER API"},
    )
    assert reponse_correction.status_code == 200

    reponse_acceptee = await _requete(
        app_test, "POST", f"/api/documents/{document.id}/validation", cookie=cookie
    )

    assert reponse_acceptee.status_code == 200
    assert reponse_acceptee.json()["statut"] == "recu"


# --------------------------------------------------------------------------
# POST /api/documents/{id}/archivage
# --------------------------------------------------------------------------


async def test_post_archivage_commentaire_obligatoire_422(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.archivage1@example.invalid", role="admin"
    )
    document = await _creer_document(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/documents/{document.id}/archivage",
        cookie=cookie,
        json_body={"commentaire": "   "},
    )

    assert reponse.status_code == 422


async def test_post_archivage_ok_puis_ecriture_refusee(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.archivage2@example.invalid", role="admin"
    )
    document = await _creer_document(db_session)
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse_archivage = await _requete(
        app_test,
        "POST",
        f"/api/documents/{document.id}/archivage",
        cookie=cookie,
        json_body={"commentaire": "doublon d'un autre dépôt"},
    )

    assert reponse_archivage.status_code == 200
    assert reponse_archivage.json()["statut"] == "archive"

    reponse_correction = await _requete(
        app_test,
        "PATCH",
        f"/api/documents/{document.id}",
        cookie=cookie,
        json_body={"numero_commande": "CDE"},
    )

    assert reponse_correction.status_code == 409


async def test_post_archivage_accepte_une_facture(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Lot 2, B1 : le bouton « Archiver » de la page facture appelle cette
    même route ; elle doit accepter une facture."""
    admin = await _creer_utilisateur(
        db_session, email="admin.archivage3@example.invalid", role="admin"
    )
    facture = await _creer_document(db_session, type_="facture", statut="recu")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test,
        "POST",
        f"/api/documents/{facture.id}/archivage",
        cookie=cookie,
        json_body={"commentaire": "facture déposée deux fois"},
    )

    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "archive"


# --------------------------------------------------------------------------
# POST /api/documents/{id}/extraction
# --------------------------------------------------------------------------


async def test_post_extraction_relance_remplace_les_valeurs(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.extraction1@example.invalid", role="admin"
    )
    chemin = tmp_path / "photo.jpg"
    chemin.write_bytes(b"contenu-invente")
    document = await _creer_document(
        db_session, numero="ANCIEN-NUMERO-API", fichier_path=str(chemin)
    )

    async def _ocr_relance(contenu: bytes, mime: str) -> dict[str, Any]:
        return _reponse_ocr_minimale("L999-RELANCE", "42.00")

    app_test = _app_test(sessions_test, tmp_path, ocr=_ocr_relance)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "POST", f"/api/documents/{document.id}/extraction", cookie=cookie
    )

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["statut"] == "a_verifier"
    assert corps["champs"]["numero"]["valeur"] == "L999-RELANCE"


async def test_post_extraction_ocr_en_echec_502(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.extraction2@example.invalid", role="admin"
    )
    chemin = tmp_path / "photo.jpg"
    chemin.write_bytes(b"contenu-invente")
    document = await _creer_document(db_session, fichier_path=str(chemin))
    app_test = _app_test(sessions_test, tmp_path, ocr=_ocr_en_echec)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "POST", f"/api/documents/{document.id}/extraction", cookie=cookie
    )

    assert reponse.status_code == 502


async def test_post_extraction_statut_non_a_verifier_409(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    admin = await _creer_utilisateur(
        db_session, email="admin.extraction3@example.invalid", role="admin"
    )
    document = await _creer_document(db_session, statut="recu")
    app_test = _app_test(sessions_test, tmp_path, ocr=_ocr_jamais_appele)
    cookie = await _login(app_test, email=admin.email)

    reponse = await _requete(
        app_test, "POST", f"/api/documents/{document.id}/extraction", cookie=cookie
    )

    assert reponse.status_code == 409
