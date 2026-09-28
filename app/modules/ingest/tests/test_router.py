"""Tests de `POST /tg/webhook` (base de test réelle, `docs_dir` temporaire,
fausse `Messagerie`).

Chaque test construit un `FastAPI` dédié (jamais le cycle de vie ASGI de
`app/main.py`, qui n'est pas déclenché par `ASGITransport` — voir le
docstring de `app/core/tests/test_sante.py`) : ceci évite complètement de
muter puis restaurer l'état du singleton `app.main.app` entre les tests
(point de vigilance signalé par la revue de T4).

`CHAT_BL_TEST` (le `chat_id` par défaut de `_update_photo`) et
`CHAT_SUPERVISION_TEST` simulent `TELEGRAM_CHAT_BL_ID`/
`TELEGRAM_CHAT_SUPERVISION_ID` (L2-T2)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.ingest.router as ingest_router
from app.core.config import Settings, get_settings
from app.modules.ingest.depot_telegram import _MESSAGE_ECHEC_AGENT
from app.modules.ingest.models import Document, Journal, TelegramUpdate, Utilisateur
from app.modules.ingest.router import get_messagerie, get_ocr, router
from app.modules.messaging.base import FichierEntrant, FichierTelecharge

pytestmark = [pytest.mark.anyio, pytest.mark.db]

SECRET_TEST = "secret-webhook-invente-pour-les-tests"
TOKEN_TEST = "000000:jamais-appele-messagerie-surchargee"
CLE_MISTRAL_TEST = "cle-mistral-jamais-appelee-ocr-surcharge"
NUMERO_BL_TEST = "L209900000123"
CHAT_BL_TEST = 555
CHAT_SUPERVISION_TEST = 556
CHAT_ETRANGER_TEST = 777

# T9 (audit rapidité/sécurité du 25/09/2026) : `depot_telegram.traiter_fichier`
# vérifie désormais la signature du fichier téléchargé avant tout traitement
# -- signature JPEG valide (`FF D8 FF`) suivie du même repère de contenu
# qu'avant ce correctif (`contenu-invente-photo`), pour que
# `MessagerieFactice.telecharger` (toujours en `.jpg`) continue de passer le
# contrôle.
_CONTENU_TELECHARGE_TEST = b"\xff\xd8\xff" + b"contenu-invente-photo"

_RE_LIGNE_SUPERVISION = re.compile(
    r"^Document n° (?P<numero_interne>\d+) · BL (?P<bl>.+) · fournisseur — · "
    r"chantier — · (?P<deposant>.+) · (?P<heure>\d{2}:\d{2}) · (?P<statut>\w+)$"
)


async def _ocr_test(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (T6b), surchargé via `get_ocr` : jamais de client HTTP réel
    dans ces tests de webhook. Sans `document_annotation`, l'extraction
    (L3-T6) part en `annotation_illisible` (`a_verifier`, L3-D10) — seul le
    numéro de BL, détecté par le motif déterministe existant, est repris ;
    ces tests, centrés sur le webhook et non sur l'extraction elle-même,
    n'ont pas besoin d'une annotation complète (voir
    `app/modules/ingest/tests/test_extraction_bl.py` pour les tests dédiés à
    l'extraction, et `test_service.py` pour `_executer_ocr`)."""
    return {"pages": [{"markdown": f"LIVRAISON N°{NUMERO_BL_TEST}"}]}


class MessagerieFactice:
    def __init__(self, *, echoue_telechargement: bool = False) -> None:
        self.echoue_telechargement = echoue_telechargement
        self.telechargements = 0
        self.reponses: list[
            tuple[int, int, str, tuple[tuple[str, str], ...] | None]
        ] = []
        self.supervisions: list[tuple[int, str]] = []
        self.accuses: list[tuple[str, str]] = []
        self.editions: list[tuple[int, int, str]] = []

    async def telecharger(self, fichier: FichierEntrant) -> FichierTelecharge:
        self.telechargements += 1
        if self.echoue_telechargement:
            raise RuntimeError("échec factice de téléchargement")
        return FichierTelecharge(contenu=_CONTENU_TELECHARGE_TEST, extension="jpg")

    async def repondre(
        self,
        chat_id: int,
        message_id: int,
        texte: str,
        boutons: Sequence[tuple[str, str]] | None = None,
    ) -> None:
        self.reponses.append(
            (chat_id, message_id, texte, tuple(boutons) if boutons else None)
        )

    async def envoyer(self, chat_id: int, texte: str) -> None:
        self.supervisions.append((chat_id, texte))

    async def accuser_clic(self, callback_id: str, texte: str) -> None:
        self.accuses.append((callback_id, texte))

    async def editer_message(self, chat_id: int, message_id: int, texte: str) -> None:
        self.editions.append((chat_id, message_id, texte))


def _app_test(
    sessions: async_sessionmaker[AsyncSession],
    messagerie: MessagerieFactice,
    docs_dir: Path,
) -> FastAPI:
    """`FastAPI` isolé pour un test : le seul état partagé avec la
    production est le contrat des dépendances (`get_settings`,
    `get_messagerie`), toutes deux surchargées."""
    app_test = FastAPI()
    app_test.state.sessions = sessions
    app_test.include_router(router)
    app_test.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://inutilise:inutilise@localhost/inutilise",
        docs_dir=docs_dir,
        telegram_bot_token=SecretStr(TOKEN_TEST),
        telegram_webhook_secret=SecretStr(SECRET_TEST),
        telegram_chat_bl_id=CHAT_BL_TEST,
        telegram_chat_supervision_id=CHAT_SUPERVISION_TEST,
        mistral_api_key=SecretStr(CLE_MISTRAL_TEST),
    )
    app_test.dependency_overrides[get_messagerie] = lambda: messagerie
    app_test.dependency_overrides[get_ocr] = lambda: _ocr_test
    return app_test


async def _poster(
    app_test: FastAPI, update: dict[str, Any], secret: str | None
) -> httpx.Response:
    entetes: dict[str, str] = {}
    if secret is not None:
        entetes["X-Telegram-Bot-Api-Secret-Token"] = secret
    transport = ASGITransport(app=app_test)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/tg/webhook", json=update, headers=entetes)


def _update_photo(
    update_id: int,
    chat_id: int = CHAT_BL_TEST,
    message_id: int = 7,
    expediteur_id: int | None = 999,
    expediteur_nom: str | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "message_id": message_id,
        "chat": {"id": chat_id},
        "photo": [{"file_id": "petite-invente"}, {"file_id": "grande-invente"}],
    }
    if expediteur_id is not None:
        message["from"] = {"id": expediteur_id}
        if expediteur_nom is not None:
            message["from"]["username"] = expediteur_nom
    return {"update_id": update_id, "message": message}


async def _creer_utilisateur(
    db_session: AsyncSession,
    *,
    telegram_user_id: int,
    actif: bool = True,
    nom: str | None = "Agent Testeur",
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=f"agent.{telegram_user_id}@example.invalid",
        role="agent",
        telegram_user_id=telegram_user_id,
        nom=nom,
        is_active=actif,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


def _parse_ligne_supervision(texte: str) -> re.Match[str]:
    match = _RE_LIGNE_SUPERVISION.match(texte)
    assert match is not None, f"ligne de supervision inattendue : {texte!r}"
    return match


def _boutons_confirmation(numero_interne: int) -> tuple[tuple[str, str], ...]:
    """Boutons attendus dans la réponse au dépôt (L2-D9)."""
    return (
        ("Quantités vérifiées", f"v:{numero_interne}"),
        ("Écart constaté", f"e:{numero_interne}"),
    )


def _update_callback(
    *,
    update_id: int,
    data: str,
    chat_id: int = CHAT_BL_TEST,
    message_id: int = 20,
    expediteur_id: int | None = 999,
) -> dict[str, Any]:
    """Update Telegram portant un `callback_query` (clic sur un bouton de
    confirmation, L2-T3)."""
    callback_query: dict[str, Any] = {
        "id": f"callback-{update_id}",
        "data": data,
        "message": {"message_id": message_id, "chat": {"id": chat_id}},
    }
    if expediteur_id is not None:
        callback_query["from"] = {"id": expediteur_id}
    return {"update_id": update_id, "callback_query": callback_query}


async def test_secret_absent_renvoie_403_sans_rien_ecrire(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)

    reponse = await _poster(app_test, _update_photo(1), None)

    assert reponse.status_code == 403
    assert (await db_session.execute(select(TelegramUpdate))).scalars().all() == []
    assert (await db_session.execute(select(Document))).scalars().all() == []


async def test_secret_invalide_renvoie_403_sans_rien_ecrire(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)

    reponse = await _poster(app_test, _update_photo(2), "mauvais-secret")

    assert reponse.status_code == 403
    assert (await db_session.execute(select(TelegramUpdate))).scalars().all() == []
    assert (await db_session.execute(select(Document))).scalars().all() == []


async def test_chat_etranger_ignore_sans_rien_ecrire(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """L2-D6 : un chat différent de `TELEGRAM_CHAT_BL_ID` est ignoré, sans
    même le dédoublonnage (`telegram_update` reste vide)."""
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(3, chat_id=CHAT_ETRANGER_TEST)

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(TelegramUpdate))).scalars().all() == []
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert messagerie.telechargements == 0
    assert messagerie.reponses == []
    assert messagerie.supervisions == []


async def test_photo_valide_cree_update_document_fichier_et_reponse(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=999)
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(42, chat_id=CHAT_BL_TEST, message_id=7, expediteur_id=999)

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200

    updates = (await db_session.execute(select(TelegramUpdate))).scalars().all()
    assert [u.update_id for u in updates] == [42]

    documents = (await db_session.execute(select(Document))).scalars().all()
    assert len(documents) == 1
    document = documents[0]
    # `_ocr_test` ne renvoie aucune `document_annotation` : l'extraction
    # (L3-T6) part donc en `annotation_illisible`, `a_verifier` (L3-D10) —
    # seul le numéro, détecté par le motif déterministe existant, est repris.
    assert (document.source, document.type, document.statut) == (
        "telegram",
        "bl",
        "a_verifier",
    )
    assert document.telegram_message_id == 7
    assert document.photo_compressee is True

    fichiers = list(tmp_path.glob("*.jpg"))
    assert len(fichiers) == 1
    assert fichiers[0].read_bytes() == _CONTENU_TELECHARGE_TEST
    assert document.fichier_path == str(fichiers[0])

    assert messagerie.reponses == [
        (
            555,
            7,
            f"Reçu — document n° {document.numero_interne}",
            _boutons_confirmation(document.numero_interne),
        )
    ]

    # L2-D8 : une ligne de supervision par dépôt traité.
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_TEST
    match = _parse_ligne_supervision(texte)
    assert match["numero_interne"] == str(document.numero_interne)
    assert match["bl"] == NUMERO_BL_TEST
    assert match["deposant"] == "Agent Testeur"
    assert match["statut"] == "a_verifier"


async def test_meme_update_id_envoye_deux_fois_ne_duplique_pas(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=999)
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(43)

    premiere = await _poster(app_test, update, SECRET_TEST)
    seconde = await _poster(app_test, update, SECRET_TEST)

    assert premiere.status_code == 200
    assert seconde.status_code == 200

    documents = (await db_session.execute(select(Document))).scalars().all()
    assert len(documents) == 1
    assert len(messagerie.reponses) == 1
    assert len(messagerie.supervisions) == 1


async def test_message_texte_ne_cree_rien_et_ne_repond_pas(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = {
        "update_id": 44,
        "message": {
            "message_id": 1,
            "chat": {"id": CHAT_BL_TEST},
            "text": "bonjour",
        },
    }

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(TelegramUpdate))).scalars().all() == []
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert messagerie.reponses == []
    assert messagerie.supervisions == []


async def test_expediteur_inconnu_ne_cree_rien_et_signale_en_supervision(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """L2-D7 : un expéditeur non rattaché ne crée aucun document, aucun
    téléchargement n'est tenté, et un unique message de supervision part
    (contenant l'identifiant Telegram) — un rejeu du même update n'en
    envoie pas un second (dédoublonnage acquis avant la résolution de
    l'expéditeur)."""
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(46, expediteur_id=123456, expediteur_nom="Inconnu")

    premiere = await _poster(app_test, update, SECRET_TEST)
    seconde = await _poster(app_test, update, SECRET_TEST)

    assert premiere.status_code == 200
    assert seconde.status_code == 200
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert messagerie.telechargements == 0
    assert messagerie.reponses == []

    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_TEST
    assert "123456" in texte
    assert "Inconnu" in texte


async def test_expediteur_inactif_traite_comme_inconnu(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=888, actif=False)
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(47, expediteur_id=888)

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert messagerie.telechargements == 0
    assert messagerie.reponses == []
    assert len(messagerie.supervisions) == 1
    assert "888" in messagerie.supervisions[0][1]


async def test_telechargement_en_echec_signale_supervision_et_repond_echec_agent(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=999)
    messagerie = MessagerieFactice(echoue_telechargement=True)
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(48)

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []

    # Ruling R22 : réponse d'échec à l'agent, sans détail technique, jamais
    # de boutons (décision du contrôleur L2-T3).
    assert messagerie.reponses == [(CHAT_BL_TEST, 7, _MESSAGE_ECHEC_AGENT, None)]

    # Message de supervision sans token ni contenu du fichier.
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_TEST
    assert TOKEN_TEST not in texte
    assert "contenu-invente-photo" not in texte

    # Le dédoublonnage a bien enregistré l'update malgré l'échec du
    # traitement en tâche de fond (décision du contrôleur : le webhook
    # marque l'update comme vu dès qu'il décide de le traiter).
    updates = (await db_session.execute(select(TelegramUpdate))).scalars().all()
    assert [u.update_id for u in updates] == [48]


# --------------------------------------------------------------------------
# `callback_query` (L2-T3, L2-D9/L2-D10) : clic sur un des deux boutons de
# confirmation, routé vers `traiter_clic` en tâche de fond.
# --------------------------------------------------------------------------


async def _creer_document(
    db_session: AsyncSession, *, statut: str = "recu"
) -> Document:
    document = Document(
        type="bl",
        source="telegram",
        statut=statut,
        fichier_path="chemin-invente.jpg",
    )
    db_session.add(document)
    await db_session.commit()
    return document


async def test_callback_query_valide_confirme_journalise_et_edite(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=8100, nom="Confirmateur")
    document = await _creer_document(db_session)
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_callback(
        update_id=200,
        data=f"v:{document.numero_interne}",
        expediteur_id=8100,
    )

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200

    await db_session.refresh(document)
    assert document.confirme_le is not None

    journal = (await db_session.execute(select(Journal))).scalars().all()
    assert len(journal) == 1
    assert journal[0].action == "quantites_verifiees"

    assert messagerie.accuses == [("callback-200", "Quantités vérifiées enregistrées")]
    assert len(messagerie.editions) == 1


async def test_meme_update_id_callback_envoye_deux_fois_ignore_le_second(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Rejeu du même `update_id` (webhook Telegram redélivré) : le
    dédoublonnage (`enregistrer_update`, partagé avec les fichiers) ignore le
    second envoi avant même d'atteindre `traiter_clic`."""
    await _creer_utilisateur(db_session, telegram_user_id=8101, nom="Confirmateur")
    document = await _creer_document(db_session)
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_callback(
        update_id=201,
        data=f"v:{document.numero_interne}",
        expediteur_id=8101,
    )

    premiere = await _poster(app_test, update, SECRET_TEST)
    seconde = await _poster(app_test, update, SECRET_TEST)

    assert premiere.status_code == 200
    assert seconde.status_code == 200

    journal = (await db_session.execute(select(Journal))).scalars().all()
    assert len(journal) == 1
    assert len(messagerie.accuses) == 1
    assert len(messagerie.editions) == 1


async def test_callback_query_chat_etranger_ignore_sans_rien_ecrire(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """L2-D6 : le filtre de chat s'applique aussi à un `callback_query`
    (`ClicBouton.chat_id`, même champ commun que `FichierEntrant`)."""
    document = await _creer_document(db_session)
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_callback(
        update_id=202,
        data=f"v:{document.numero_interne}",
        chat_id=CHAT_ETRANGER_TEST,
        expediteur_id=999,
    )

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(TelegramUpdate))).scalars().all() == []
    assert messagerie.accuses == []
    assert messagerie.editions == []

    await db_session.refresh(document)
    assert document.confirme_le is None


# --------------------------------------------------------------------------
# Correction tour 1/5 (constat Critical) : un `callback_data` malformé ne
# doit jamais faire planter le webhook (500) — `lire_update` doit renvoyer
# `None` pour chacune de ces formes, traitées comme n'importe quel update
# inexploitable (200, rien n'est écrit).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    ["v:²", "v:①", "v:" + "9" * 25, "v:-1", "x:12", "v:12abc"],
    ids=[
        "exposant-unicode",
        "chiffre-encercle-unicode",
        "25-chiffres-hors-bigint",
        "negatif",
        "prefixe-inconnu",
        "suffixe-non-numerique",
    ],
)
async def test_callback_data_malforme_renvoie_200_sans_rien_ecrire(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    data: str,
) -> None:
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_callback(update_id=220, data=data)

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(TelegramUpdate))).scalars().all() == []
    assert (await db_session.execute(select(Journal))).scalars().all() == []
    assert messagerie.accuses == []
    assert messagerie.editions == []


# --------------------------------------------------------------------------
# `get_ocr_facture` (L3-T7, L3-D16) : confiance par page, jamais l'annotation
# ni les scores par mot d'`OPTIONS_OCR_BL` (réservés au BL, T6).
# --------------------------------------------------------------------------


async def test_get_ocr_facture_options_confidence_scores_granularity_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appels: list[dict[str, Any]] = []

    async def _ocr_document_factice(
        http: Any,
        cle_api: str,
        contenu: bytes,
        mime: str,
        *,
        delai: httpx.Timeout | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        appels.append(
            {"delai": delai, "options": dict(options) if options is not None else None}
        )
        return {}

    monkeypatch.setattr(ingest_router, "ocr_document", _ocr_document_factice)

    app_test = FastAPI()
    app_test.state.http = object()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://inutilise:inutilise@localhost/inutilise",
        docs_dir=Path("/inutilise"),
        telegram_bot_token=SecretStr(TOKEN_TEST),
        telegram_webhook_secret=SecretStr(SECRET_TEST),
        telegram_chat_bl_id=CHAT_BL_TEST,
        telegram_chat_supervision_id=CHAT_SUPERVISION_TEST,
        mistral_api_key=SecretStr(CLE_MISTRAL_TEST),
    )
    request = Request({"type": "http", "app": app_test})

    ocr = ingest_router.get_ocr_facture(request, settings)
    await ocr(b"contenu-invente", "application/pdf")

    assert appels == [
        {
            "delai": httpx.Timeout(90.0),
            "options": {"confidence_scores_granularity": "page"},
        }
    ]
