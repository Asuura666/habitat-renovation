"""Client Telegram Bot API (webhook) : lecture des updates, téléchargement
des fichiers, réponse aux messages.

Décisions du contrôleur (brief T6) :
- `GET/POST https://api.telegram.org/bot<token>/getFile` (paramètre
  `file_id`) renvoie `{"ok": true, "result": {"file_path": "..."}}` ;
  téléchargement effectif sur
  `https://api.telegram.org/file/bot<token>/<file_path>` ;
  `POST https://api.telegram.org/bot<token>/sendMessage` avec le corps JSON
  `{"chat_id": ..., "text": ..., "reply_parameters": {"message_id": ...}}`
  (D11 : `reply_parameters.message_id` remplace `reply_to_message_id`
  depuis la Bot API 7.0).
- Le token Telegram apparaît dans ces URL : `ErreurTelegram` ne doit donc
  jamais chaîner l'exception httpx brute (qui embarque l'URL demandée) ni
  reprendre son message tel quel — uniquement un message construit à la
  main, sans URL ni token (`raise ... from None`).
- Extensions acceptées, mapping explicite (pas de `mimetypes`, qui devine à
  partir d'une base de données système non maîtrisée) : une photo Telegram
  (`photo[]`, qui ne porte pas de type MIME) donne toujours `jpg` ; un
  document d'un type hors de cette liste est ignoré par `lire_update`
  (renvoie `None`).
- `lire_update` ne lit que `update["message"]` (jamais `edited_message` ni
  `channel_post`).
"""

from __future__ import annotations

import hmac
from pathlib import PurePosixPath
from typing import Any

import httpx

from app.modules.messaging.base import FichierEntrant, FichierTelecharge

_BASE_URL = "https://api.telegram.org"

# Mapping explicite type MIME -> extension de stockage (décision du
# contrôleur : pas de `mimetypes`, qui dépend d'une base système variable
# selon la machine).
_EXTENSIONS_PAR_MIME: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "image/tiff": "tiff",
    "application/pdf": "pdf",
}


class ErreurTelegram(Exception):
    """Échec d'un appel à l'API Telegram. Son message ne contient jamais le
    token (présent dans les URL de l'API) : construit à la main, jamais à
    partir de l'exception httpx brute."""


def secret_valide(recu: str | None, attendu: str) -> bool:
    """Compare l'en-tête `X-Telegram-Bot-Api-Secret-Token` reçu à la valeur
    attendue, en temps constant (`hmac.compare_digest`). Absent -> `False`.
    """
    if recu is None:
        return False
    return hmac.compare_digest(recu, attendu)


def _fichier_depuis_document(
    update_id: int,
    chat_id: int,
    message_id: int,
    expediteur_id: int | None,
    expediteur_nom: str | None,
    document: dict[str, Any],
) -> FichierEntrant | None:
    mime_type = document.get("mime_type")
    if mime_type not in _EXTENSIONS_PAR_MIME:
        return None
    fichier_id = document.get("file_id")
    if not isinstance(fichier_id, str):
        return None
    return FichierEntrant(
        update_id=update_id,
        chat_id=chat_id,
        message_id=message_id,
        expediteur_id=expediteur_id,
        fichier_id=fichier_id,
        mime_type=mime_type,
        nom_fichier=document.get("file_name"),
        compresse=False,
        expediteur_nom=expediteur_nom,
    )


def _fichier_depuis_photo(
    update_id: int,
    chat_id: int,
    message_id: int,
    expediteur_id: int | None,
    expediteur_nom: str | None,
    photos: list[Any],
) -> FichierEntrant | None:
    if not photos:
        return None
    plus_grande = photos[-1]
    if not isinstance(plus_grande, dict):
        return None
    fichier_id = plus_grande.get("file_id")
    if not isinstance(fichier_id, str):
        return None
    return FichierEntrant(
        update_id=update_id,
        chat_id=chat_id,
        message_id=message_id,
        expediteur_id=expediteur_id,
        # Telegram ne fournit pas de type MIME pour une photo : `telecharger`
        # déduit l'extension ("jpg") depuis le chemin renvoyé par `getFile`.
        fichier_id=fichier_id,
        mime_type=None,
        nom_fichier=None,
        compresse=True,
        expediteur_nom=expediteur_nom,
    )


def _expediteur_nom(expediteur: dict[str, Any]) -> str | None:
    """Nom d'affichage Telegram de l'expéditeur (L2-T2, décision du
    contrôleur) : `username` (sans le `@`, tel que fourni par l'API) si
    présent, sinon `first_name`. N'est utilisé que pour le message de
    supervision « expéditeur non rattaché » (L2-D7) — jamais pour une
    décision métier (l'identification repose uniquement sur
    `telegram_user_id`)."""
    username = expediteur.get("username")
    if isinstance(username, str):
        return username
    first_name = expediteur.get("first_name")
    if isinstance(first_name, str):
        return first_name
    return None


def lire_update(update: dict[str, Any]) -> FichierEntrant | None:
    """Extrait le fichier à traiter d'un update Telegram, s'il y en a un.

    `None` si l'update ne porte pas de `message` (`edited_message`,
    `channel_post`, ... ignorés), si le message ne contient ni photo ni
    document, ou si le document n'est pas d'un type accepté.
    """
    message = update.get("message")
    if not isinstance(message, dict):
        return None

    update_id = update.get("update_id")
    chat = message.get("chat")
    message_id = message.get("message_id")
    if (
        not isinstance(update_id, int)
        or not isinstance(chat, dict)
        or not isinstance(message_id, int)
    ):
        return None
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return None

    expediteur = message.get("from")
    expediteur_id = expediteur.get("id") if isinstance(expediteur, dict) else None
    if not isinstance(expediteur_id, int):
        expediteur_id = None
    expediteur_nom = (
        _expediteur_nom(expediteur) if isinstance(expediteur, dict) else None
    )

    photos = message.get("photo")
    if isinstance(photos, list):
        return _fichier_depuis_photo(
            update_id, chat_id, message_id, expediteur_id, expediteur_nom, photos
        )

    document = message.get("document")
    if isinstance(document, dict):
        return _fichier_depuis_document(
            update_id, chat_id, message_id, expediteur_id, expediteur_nom, document
        )

    return None


def _extension(fichier: FichierEntrant, file_path: str) -> str:
    """Extension déduite du type MIME connu, sinon du chemin renvoyé par
    Telegram (cas d'une photo, sans type MIME)."""
    if fichier.mime_type is not None and fichier.mime_type in _EXTENSIONS_PAR_MIME:
        return _EXTENSIONS_PAR_MIME[fichier.mime_type]
    suffixe = PurePosixPath(file_path).suffix.lstrip(".")
    return suffixe or "bin"


class TelegramClient:
    """Implémentation `Messagerie` pour l'API Bot Telegram."""

    def __init__(self, token: str, http: httpx.AsyncClient) -> None:
        self._token = token
        self._http = http

    async def telecharger(self, fichier: FichierEntrant) -> FichierTelecharge:
        try:
            reponse = await self._http.get(
                f"{_BASE_URL}/bot{self._token}/getFile",
                params={"file_id": fichier.fichier_id},
            )
            reponse.raise_for_status()
        except httpx.HTTPError:
            raise ErreurTelegram("Échec de l'appel Telegram getFile") from None

        corps: dict[str, Any] = reponse.json()
        if not corps.get("ok"):
            raise ErreurTelegram("Réponse Telegram getFile en échec (ok=false)")
        resultat = corps.get("result")
        if not isinstance(resultat, dict) or not isinstance(
            resultat.get("file_path"), str
        ):
            raise ErreurTelegram("Réponse Telegram getFile sans file_path exploitable")
        file_path: str = resultat["file_path"]

        try:
            reponse_fichier = await self._http.get(
                f"{_BASE_URL}/file/bot{self._token}/{file_path}"
            )
            reponse_fichier.raise_for_status()
        except httpx.HTTPError:
            raise ErreurTelegram(
                "Échec du téléchargement du fichier Telegram"
            ) from None

        return FichierTelecharge(
            contenu=reponse_fichier.content,
            extension=_extension(fichier, file_path),
        )

    async def repondre(self, chat_id: int, message_id: int, texte: str) -> None:
        try:
            reponse = await self._http.post(
                f"{_BASE_URL}/bot{self._token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": texte,
                    "reply_parameters": {"message_id": message_id},
                },
            )
            reponse.raise_for_status()
        except httpx.HTTPError:
            raise ErreurTelegram("Échec de l'appel Telegram sendMessage") from None

    async def envoyer(self, chat_id: int, texte: str) -> None:
        """Message libre à `chat_id`, sans réponse à un message d'origine
        (L2-T2) : notifications de supervision (L2-D7, L2-D8), envoyées vers
        `TELEGRAM_CHAT_SUPERVISION_ID`, jamais vers le groupe BL."""
        try:
            reponse = await self._http.post(
                f"{_BASE_URL}/bot{self._token}/sendMessage",
                json={"chat_id": chat_id, "text": texte},
            )
            reponse.raise_for_status()
        except httpx.HTTPError:
            raise ErreurTelegram("Échec de l'appel Telegram sendMessage") from None
