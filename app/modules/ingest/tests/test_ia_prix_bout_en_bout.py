"""Essai de bout en bout sur une vraie anomalie R22 (T10a, phase 4 IA --
brief `task-10a-brief.md` §3) : contrairement à `test_ia_prix.py` (anomalies
R22 fabriquées à la main, lot Prix pas encore fusionné à l'écriture de ces
tests), ce fichier fait tourner les **vrais** services -- `ingest.prix_bl
.controler_prix_bl` (moteur de règles R19-R25) puis `ingest.ia_prix
.chercher_prix_internet`/`prix_internet_des_anomalies` -- et vérifie la
chaîne complète jusqu'aux deux routes HTTP consommées par l'écran :
`GET /api/ia/prix-internet` (la nouvelle route groupée) et
`GET /api/prix/alertes` (page « Prix à vérifier », lot Prix) montrent bien
la même anomalie.

Aucun appel réseau réel : seul le transport HTTP vers OpenCode est simulé
(`httpx.MockTransport`, même mécanique que `test_ia_prix.py`/
`test_opencode.py`) -- la recherche internet elle-même n'est jamais
atteinte. Toutes les données (fournisseur, grille, bon, facture) sont
entièrement inventées.

Deux essais :
- `test_bout_en_bout_r22_prix_internet_trouve_lie_page_prix` : un produit
  jamais facturé, absent de la grille -> R22 réelle, recherche internet
  réelle (faux transport), reliée à la page Prix et à la nouvelle route ;
- `test_bout_en_bout_r22_avec_dernier_prix_facture_aucune_recherche` : le
  même produit a déjà été facturé une fois (via une vraie ligne de facture
  en base, comme le font les tests du lot Prix, `test_prix_bl
  .test_r20_plus_cher_que_la_derniere_facture`) -- R22 se déclenche encore
  (toujours absent de la grille), mais son `detail` porte alors un
  `dernier_prix` utile : `chercher_prix_internet` ne doit faire strictement
  aucune requête vers le faux transport."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from httpx import ASGITransport
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import NOM_COOKIE
from app.core.auth import router as auth_router
from app.core.config import get_settings
from app.modules.api import router as api_router
from app.modules.ingest import opencode
from app.modules.ingest.ia_prix import (
    BilanIA,
    chercher_prix_internet,
    prix_internet_des_anomalies,
)
from app.modules.ingest.models import (
    Anomalie,
    Document,
    Fournisseur,
    GrillePrix,
    Ligne,
    PrixInternet,
    Utilisateur,
)
from app.modules.ingest.parametres import modifier_parametre
from app.modules.ingest.prix_bl import controler_prix_bl
from app.modules.normalize.prix import cle_produit, prix_net

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_PASSWORD_HELPER = PasswordHelper()
_MOT_DE_PASSE = "mot-de-passe-invente-bout-en-bout-1234"
_SESSION_ID = "ses_bout_en_bout"


# --------------------------------------------------------------------------
# App de test et connexion (même schéma qu'`api/tests/test_ia.py`, dupliqué
# ici -- `ingest` ne peut pas importer les tests d'un autre paquet).
# --------------------------------------------------------------------------


def _app_test(sessions: async_sessionmaker[AsyncSession], docs_dir: Path) -> FastAPI:
    app_test = FastAPI()
    app_test.state.sessions = sessions
    app_test.include_router(auth_router)
    app_test.include_router(api_router)

    def _settings_test() -> object:
        return get_settings().model_copy(update={"docs_dir": docs_dir})

    app_test.dependency_overrides[get_settings] = _settings_test
    return app_test


async def _creer_admin(db_session: AsyncSession, *, email: str) -> None:
    utilisateur = Utilisateur(
        email=email,
        hashed_password=_PASSWORD_HELPER.hash(_MOT_DE_PASSE),
        role="admin",
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()


async def _login(app_test: FastAPI, *, email: str) -> str:
    transport = ASGITransport(app=app_test, client=("10.89.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.post(
            "/api/auth/login", data={"username": email, "password": _MOT_DE_PASSE}
        )
    assert reponse.status_code == 204
    cookie = reponse.cookies.get(NOM_COOKIE)
    assert cookie is not None
    return cookie


# --------------------------------------------------------------------------
# Réglages IA (même idiome que `test_ia_prix.py`).
# --------------------------------------------------------------------------


class _SettingsIAFake:
    def __init__(self) -> None:
        self.ia_active = True
        self.opencode_url = "https://opencode-bout-en-bout.test"
        self.opencode_mot_de_passe = SecretStr("mdp-invente-bout-en-bout")
        self.ia_appels_max_jour = 40


# --------------------------------------------------------------------------
# Faux transport OpenCode : un seul scénario (prix trouvé, page lue) --
# les gardes de `extract.reponses_ia.lire_prix_internet` sont déjà
# exhaustivement testées ailleurs (`extract/tests/test_reponses_ia.py`,
# `ingest/tests/test_ia_prix.py`) ; ce fichier vérifie le branchement, pas
# les gardes elles-mêmes."""


def _reponses_opencode_prix_trouve(
    *, prix: str, source_url: str, page_texte: str
) -> dict[tuple[str, str], httpx.Response]:
    structured: dict[str, Any] = {
        "statut": "trouve",
        "produit_trouve": "Plaque std 13 (revendeur invente)",
        "prix": float(prix),
        "devise": "EUR",
        "taxes": "TTC",
        "unite": "u",
        "conditionnement": "boîte de 10",
        "source_url": source_url,
        "confiance": "elevee",
        "raison": "",
    }
    info: dict[str, Any] = {
        "id": "msg_bout_en_bout_1",
        "sessionID": _SESSION_ID,
        "role": "assistant",
        "time": {"created": 1, "completed": 2},
        "parentID": "msg_bout_en_bout_0",
        "modelID": "modele-invente-bout-en-bout",
        "providerID": "fournisseur-invente-bout-en-bout",
        "mode": "habitat-prix",
        "agent": "habitat-prix",
        "path": {"cwd": "/", "root": "/"},
        "cost": 0,
        "tokens": {
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "cache": {"read": 0, "write": 0},
        },
        "structured": structured,
    }
    parts = [
        {
            "id": "prt_bout_en_bout_1",
            "sessionID": _SESSION_ID,
            "messageID": "msg_bout_en_bout_1",
            "type": "tool",
            "callID": "call_bout_en_bout_1",
            "tool": "webfetch",
            "state": {
                "status": "completed",
                "input": {"url": source_url},
                "output": page_texte,
                "title": "titre invente",
                "metadata": {},
                "time": {"start": 1, "end": 2},
            },
        }
    ]
    return {
        ("POST", "/session"): httpx.Response(200, json={"id": _SESSION_ID}),
        (
            "POST",
            f"/session/{_SESSION_ID}/message",
        ): httpx.Response(200, json={"info": info, "parts": parts}),
        ("DELETE", f"/session/{_SESSION_ID}"): httpx.Response(200, json=True),
    }


def _aucune_requete(request: httpx.Request) -> httpx.Response:
    raise AssertionError(
        f"aucune requête ne doit être faite vers l'IA : {request.method} {request.url}"
    )


# --------------------------------------------------------------------------
# Données de test (entièrement inventées).
# --------------------------------------------------------------------------


async def _creer_fournisseur(db_session: AsyncSession, *, nom: str) -> Fournisseur:
    fournisseur = Fournisseur(nom=f"{nom} {uuid.uuid4()}")
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_grille_autre_produit(
    db_session: AsyncSession, *, fournisseur: Fournisseur
) -> GrillePrix:
    """Une grille qui existe bien pour ce fournisseur, mais qui ne contient
    pas le produit du bon (brief T10a §3.1) -- référence et désignation sans
    rapport avec `PL13`/`Plaque std 13`."""
    ligne = GrillePrix(
        fournisseur_id=fournisseur.id,
        cle_produit=cle_produit("AUTRE-REF", "Sac de ciment 25kg"),
        reference="AUTRE-REF",
        designation="Sac de ciment 25kg",
        unite_brut="u",
        unite="u",
        prix_ht=Decimal("6.50"),
        prix_net=prix_net(Decimal("6.50"), None),
        date_effet=date(2026, 1, 1),
        source="saisie",
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _creer_bl_plaque(
    db_session: AsyncSession, *, fournisseur: Fournisseur, date_doc: date
) -> tuple[Document, Ligne]:
    document = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path=f"bl-invente-bout-en-bout-{uuid.uuid4()}.jpg",
        numero=f"BOUT-{uuid.uuid4()}",
        fournisseur_id=fournisseur.id,
        date_doc=date_doc,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)

    ligne = Ligne(
        document_id=document.id,
        type_ligne="article",
        code_brut="PL13",
        article_brut="Plaque std 13",
        pu_ht=Decimal("7.90"),
        unite_brut="u",
        ordre=0,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return document, ligne


async def _activer_controle_prix_bl(db_session: AsyncSession) -> None:
    await modifier_parametre(db_session, "prix_controle_bl_actif", "1", auteur_id=None)
    await modifier_parametre(
        db_session, "prix_alerte_absent_grille", "1", auteur_id=None
    )


async def _anomalie_r22_du_document(
    db_session: AsyncSession, document_id: uuid.UUID
) -> Anomalie:
    anomalies = (
        (
            await db_session.execute(
                select(Anomalie).where(
                    Anomalie.document_id == document_id, Anomalie.regle == "R22"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(anomalies) == 1
    return anomalies[0]


# --------------------------------------------------------------------------
# Essai 1 : produit jamais facturé -> recherche internet réelle, reliée à la
# page Prix et à la nouvelle route.
# --------------------------------------------------------------------------


async def test_bout_en_bout_r22_prix_internet_trouve_lie_page_prix(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Fournisseur, grille sans le produit, bon avec une ligne à prix > 0,
    #    interrupteurs du lot Prix allumés.
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Bout En Bout")
    await _creer_grille_autre_produit(db_session, fournisseur=fournisseur)
    document, _ligne = await _creer_bl_plaque(
        db_session, fournisseur=fournisseur, date_doc=date(2026, 9, 21)
    )
    await _activer_controle_prix_bl(db_session)

    # 2. Vrai moteur de règles (`controler_prix_bl`) -> une vraie anomalie
    #    R22 ouverte, avec les clés exactement lues par `ia_prix.py`.
    nb_ouvertes = await controler_prix_bl(db_session, document.id)
    await db_session.commit()
    assert nb_ouvertes == 1

    anomalie = await _anomalie_r22_du_document(db_session, document.id)
    assert anomalie.statut == "ouverte"
    assert anomalie.detail["produit"] == "Plaque std 13"
    assert anomalie.detail["code"] == "PL13"
    assert anomalie.detail["unite_bon"] == "u"
    assert anomalie.detail["dernier_prix"] == "—"

    # 3. IA allumée, faux transport OpenCode -> prix trouvé, page webfetch
    #    contenant bien le prix (garde 4 de `lire_prix_internet`).
    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())
    source_url = "https://exemple.invalid/plaque-std-13"
    requetes: list[httpx.Request] = []
    reponses = _reponses_opencode_prix_trouve(
        prix="89.90",
        source_url=source_url,
        page_texte="Plaque std 13 -- Prix : 89,90 € TTC.",
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        cle = (request.method, request.url.path)
        if cle not in reponses:
            raise AssertionError(f"requête inattendue : {request.method} {request.url}")
        return reponses[cle]

    http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA(ok=1)
    assert len(requetes) == 3  # session + message + suppression de session

    lignes_prix_internet = (
        (await db_session.execute(select(PrixInternet))).scalars().all()
    )
    assert len(lignes_prix_internet) == 1
    assert lignes_prix_internet[0].statut == "trouve"

    # 4a. `prix_internet_des_anomalies` renvoie ce prix.
    lot = await prix_internet_des_anomalies(db_session, [anomalie.id])
    assert anomalie.id in lot.par_anomalie
    vue = lot.par_anomalie[anomalie.id]
    assert vue is not None
    assert vue.statut == "trouve"
    assert vue.prix == Decimal("89.9000")
    assert vue.source_url == source_url

    # 4b. `GET /api/ia/prix-internet` et `GET /api/prix/alertes` (vrai
    #     service du lot Prix) : le même identifiant s'y retrouve.
    await _creer_admin(db_session, email="admin.bout-en-bout@example.invalid")
    app_test = _app_test(sessions_test, tmp_path)
    cookie = await _login(app_test, email="admin.bout-en-bout@example.invalid")

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app_test),
        base_url="http://test",
        cookies={NOM_COOKIE: cookie},
    ) as client:
        reponse_ia = await client.get(
            "/api/ia/prix-internet", params={"anomalie_id": str(anomalie.id)}
        )
        reponse_alertes = await client.get("/api/prix/alertes")

    assert reponse_ia.status_code == 200
    corps_ia = reponse_ia.json()
    assert corps_ia["prix"][str(anomalie.id)]["statut"] == "trouve"
    assert corps_ia["prix"][str(anomalie.id)]["prix"] == "89.9000"

    assert reponse_alertes.status_code == 200
    lignes_page = reponse_alertes.json()
    ligne_produit = next(
        (ligne for ligne in lignes_page if str(anomalie.id) in ligne["anomalie_ids"]),
        None,
    )
    assert ligne_produit is not None
    assert ligne_produit["produit"] == "Plaque std 13"
    assert "R22" in ligne_produit["regles"]


# --------------------------------------------------------------------------
# Essai 2 : produit déjà facturé -> dernier_prix utile, aucune recherche.
# --------------------------------------------------------------------------


async def test_bout_en_bout_r22_avec_dernier_prix_facture_aucune_recherche(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fournisseur = await _creer_fournisseur(
        db_session, nom="Fournisseur Bout En Bout Facture"
    )
    await _creer_grille_autre_produit(db_session, fournisseur=fournisseur)

    # Une vraie ligne de facture antérieure, même référence/désignation que
    # le bon -- même construction que `test_prix_bl
    # .test_r20_plus_cher_que_la_derniere_facture` (services du lot Prix).
    facture = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"facture-invente-bout-en-bout-{uuid.uuid4()}.pdf",
        numero=f"FA-BOUT-{uuid.uuid4()}",
        fournisseur_id=fournisseur.id,
        date_doc=date(2026, 8, 1),
    )
    db_session.add(facture)
    await db_session.commit()
    await db_session.refresh(facture)
    ligne_facture = Ligne(
        document_id=facture.id,
        type_ligne="article",
        code_brut="PL13",
        article_brut="Plaque std 13",
        pu_ht=Decimal("8.20"),
        unite_brut="u",
        ordre=0,
    )
    db_session.add(ligne_facture)
    await db_session.commit()

    document, _ligne = await _creer_bl_plaque(
        db_session, fournisseur=fournisseur, date_doc=date(2026, 9, 21)
    )
    await _activer_controle_prix_bl(db_session)

    await controler_prix_bl(db_session, document.id)
    await db_session.commit()

    anomalie = await _anomalie_r22_du_document(db_session, document.id)
    # Toujours absente de la grille (R22 ne regarde que la grille) -- mais
    # `dernier_prix` porte désormais le prix de la facture d'août, plus le
    # tiret cadratin (brief T10a §3.5, la variante attendue) ; toujours à
    # quatre décimales (`normalize.prix.prix_net`, même format que
    # `test_prix_bl.test_r20_plus_cher_que_la_derniere_facture`).
    assert anomalie.detail["dernier_prix"] == "8.2000"

    monkeypatch.setattr(opencode, "get_settings", lambda: _SettingsIAFake())
    http = httpx.AsyncClient(transport=httpx.MockTransport(_aucune_requete))

    bilan = await chercher_prix_internet(db_session, http)

    assert bilan == BilanIA()  # aucun candidat retenu, aucune requête faite
