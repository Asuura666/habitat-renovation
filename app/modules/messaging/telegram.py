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

L2-T3 (boutons de confirmation, L2-D9/L2-D10) :
- `lire_update` lit aussi `update["callback_query"]` (clic sur un des deux
  boutons) et renvoie alors un `ClicBouton`, jamais un `FichierEntrant` : un
  update Telegram ne porte jamais les deux à la fois, `callback_query` est
  donc regardé en premier.
- `callback_query.data` attendu : `"<préfixe>:<numero_interne>"`, préfixe
  `PREFIXE_QUANTITES_VERIFIEES`/`PREFIXE_ECART_CONSTATE`
  (`messaging/base.py`). Toute autre forme (préfixe inconnu, absence de
  séparateur, partie numérique absente ou non entière) renvoie `None` — même
  politique défensive que le reste de `lire_update`, jamais d'exception sur
  une entrée malformée.
- Correction (tour 1/5) : `_numero_interne_valide` validait via
  `str.isdigit()`, qui accepte des caractères Unicode que `int()` refuse
  (exposants, chiffres encerclés, ex. `"²"`, `"①"`) — `int()` levait alors
  une `ValueError` non rattrapée jusqu'à `webhook_telegram` (500). Et
  `str.isdigit()` n'impose aucune borne : un `numero_interne` de 25 chiffres
  passait la validation puis dépassait `bigint` côté base, plantant
  `_decider_clic` sans jamais accuser le clic (bouton bloqué en chargement).
  Validation désormais par une regex ASCII stricte, bornée
  (`^[0-9]{1,18}$`, 18 chiffres tenant toujours dans un `bigint`).
- `POST .../answerCallbackQuery` (corps `{"callback_query_id": ...,
  "text": ...}`) pour `accuser_clic`, `POST .../editMessageText` (corps
  `{"chat_id": ..., "message_id": ..., "text": ...}`, sans `reply_markup` —
  décision du contrôleur : l'omettre retire les boutons) pour
  `editer_message`.

Audit rapidité et sécurité (T8) — taille d'un fichier Telegram plafonnée :
- Telegram refuse déjà `getFile` au-delà de 20 Mo, et `telecharger` chargeait
  jusque-là `reponse.content` en entier sans plafond applicatif, contrairement
  au dépôt de facture (`app.modules.api.factures._TAILLE_MAX_OCTETS`, même
  valeur, 20 Mio) — défense en profondeur, pas un scénario observé.
- `_TAILLE_MAX_OCTETS` : (1) si `getFile` renvoie un `file_size` dépassant le
  plafond, `ErreurTelegram` est levée avant toute requête de téléchargement ;
  (2) `file_size` n'est pas garanti par l'API — le téléchargement se fait
  donc en flux (`AsyncClient.stream`), `ErreurTelegram` levée dès que le
  cumul des morceaux reçus dépasse le plafond, sans jamais accumuler plus
  que nécessaire en mémoire.
- Pas de constante partagée avec `api/factures.py` : `messaging` n'importe
  aucun autre module de `app.modules` (garde de frontières,
  `tests/test_frontieres.py`) et `app.core` ne porte aujourd'hui aucune
  constante de ce genre — deux constantes de même valeur, à maintenir
  alignées si l'une change.
- `depot_telegram.traiter_fichier` (`ingest`) attrape déjà toute exception
  de `messagerie.telecharger` (`except Exception`) : `ErreurTelegram` y
  déclenche le même échec propre que les autres erreurs de téléchargement
  (journalisation, message de supervision, réponse d'échec à l'agent, aucun
  document inséré) — aucun changement nécessaire côté `ingest`.
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any

import httpx

from app.modules.messaging.base import (
    PREFIXE_ECART_CONSTATE,
    PREFIXE_QUANTITES_VERIFIEES,
    ClicBouton,
    FichierEntrant,
    FichierTelecharge,
)

_BASE_URL = "https://api.telegram.org"

_ACTIONS_VALIDES = frozenset({PREFIXE_QUANTITES_VERIFIEES, PREFIXE_ECART_CONSTATE})

# Correction (tour 1/5) : chiffres ASCII stricts uniquement (`str.isdigit()`
# accepte des caractères Unicode — exposants, chiffres encerclés — que
# `int()` refuse ensuite), et bornés à 18 chiffres (tient toujours dans un
# `bigint` Postgres, dont le maximum en compte 19) pour ne jamais transmettre
# à la base un entier hors plage.
_RE_NUMERO_INTERNE = re.compile(r"[0-9]{1,18}")

# Plafond applicatif de taille d'un fichier Telegram téléchargé (T8, défense
# en profondeur : Telegram refuse déjà `getFile` au-delà de 20 Mo). Même
# valeur que `app.modules.api.factures._TAILLE_MAX_OCTETS` (décision du
# contrôleur L2-D11) — non importée (`messaging` n'importe aucun autre
# module de `app.modules`, garde de frontières,
# `tests/test_frontieres.py`) : à maintenir alignée si l'une des deux
# valeurs change.
_TAILLE_MAX_OCTETS = 20 * 1024 * 1024

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


def _numero_interne_valide(reste: str) -> int | None:
    """`reste` (partie après `:` dans `callback_data`) doit être un entier
    positif ASCII littéral, 1 à 18 chiffres : ni vide, ni négatif, ni
    flottant, ni chiffre Unicode non-ASCII, ni hors plage `bigint` — toute
    autre forme renvoie `None` (décision du contrôleur : « numéro non
    entier » -> `None`, corrigée tour 1/5 pour couvrir aussi les chiffres
    Unicode et l'absence de borne de `str.isdigit()`)."""
    if _RE_NUMERO_INTERNE.fullmatch(reste) is None:
        return None
    return int(reste)


def _clic_depuis_callback_query(
    update_id: int, callback_query: dict[str, Any]
) -> ClicBouton | None:
    """Construit un `ClicBouton` depuis `update["callback_query"]`, `None`
    si sa forme ne correspond pas à un clic exploitable (L2-T3)."""
    callback_id = callback_query.get("id")
    data = callback_query.get("data")
    message = callback_query.get("message")
    if (
        not isinstance(callback_id, str)
        or not isinstance(data, str)
        or not isinstance(message, dict)
    ):
        return None

    chat = message.get("chat")
    message_id = message.get("message_id")
    if not isinstance(chat, dict) or not isinstance(message_id, int):
        return None
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return None

    prefixe, separateur, reste = data.partition(":")
    if not separateur or prefixe not in _ACTIONS_VALIDES:
        return None
    numero_interne = _numero_interne_valide(reste)
    if numero_interne is None:
        return None

    expediteur = callback_query.get("from")
    expediteur_id = expediteur.get("id") if isinstance(expediteur, dict) else None
    if not isinstance(expediteur_id, int):
        expediteur_id = None

    return ClicBouton(
        update_id=update_id,
        callback_id=callback_id,
        chat_id=chat_id,
        message_id=message_id,
        expediteur_id=expediteur_id,
        action=prefixe,
        numero_interne=numero_interne,
    )


def lire_update(update: dict[str, Any]) -> FichierEntrant | ClicBouton | None:
    """Extrait le fichier à traiter ou le clic sur un bouton de confirmation
    d'un update Telegram, s'il y en a un.

    `None` si l'update ne porte ni `callback_query` exploitable (L2-T3) ni
    `message` (`edited_message`, `channel_post`, ... ignorés), si le message
    ne contient ni photo ni document, ou si le document n'est pas d'un type
    accepté.
    """
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        return None

    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        return _clic_depuis_callback_query(update_id, callback_query)

    message = update.get("message")
    if not isinstance(message, dict):
        return None

    chat = message.get("chat")
    message_id = message.get("message_id")
    if not isinstance(chat, dict) or not isinstance(message_id, int):
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

        # T8 : `file_size` (octets, absent selon les versions de l'API) est
        # vérifié avant toute requête de téléchargement — évite de tirer un
        # fichier déjà connu comme trop volumineux.
        file_size = resultat.get("file_size")
        if isinstance(file_size, int) and file_size > _TAILLE_MAX_OCTETS:
            raise ErreurTelegram("Fichier Telegram trop volumineux (20 Mio maximum)")

        # T8 : téléchargement en flux, jamais `reponse.content` chargé d'un
        # coup — `file_size` n'étant pas garanti, le plafond est aussi
        # appliqué au cumul des morceaux reçus, arrêté dès le dépassement.
        morceaux: list[bytes] = []
        taille_cumulee = 0
        try:
            async with self._http.stream(
                "GET", f"{_BASE_URL}/file/bot{self._token}/{file_path}"
            ) as reponse_fichier:
                reponse_fichier.raise_for_status()
                async for morceau in reponse_fichier.aiter_bytes():
                    taille_cumulee += len(morceau)
                    if taille_cumulee > _TAILLE_MAX_OCTETS:
                        raise ErreurTelegram(
                            "Fichier Telegram trop volumineux (20 Mio maximum)"
                        )
                    morceaux.append(morceau)
        except httpx.HTTPError:
            raise ErreurTelegram(
                "Échec du téléchargement du fichier Telegram"
            ) from None

        return FichierTelecharge(
            contenu=b"".join(morceaux),
            extension=_extension(fichier, file_path),
        )

    async def repondre(
        self,
        chat_id: int,
        message_id: int,
        texte: str,
        boutons: Sequence[tuple[str, str]] | None = None,
    ) -> None:
        corps: dict[str, Any] = {
            "chat_id": chat_id,
            "text": texte,
            "reply_parameters": {"message_id": message_id},
        }
        if boutons:
            # Une seule ligne portant tous les boutons, dans l'ordre reçu
            # (L2-D9 : les deux boutons de confirmation côte à côte).
            corps["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {"text": libelle, "callback_data": donnee}
                        for libelle, donnee in boutons
                    ]
                ]
            }
        try:
            reponse = await self._http.post(
                f"{_BASE_URL}/bot{self._token}/sendMessage", json=corps
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

    async def accuser_clic(self, callback_id: str, texte: str) -> None:
        """`answerCallbackQuery` (L2-T3) : accusé de réception du clic sur un
        bouton, affiché par le client Telegram de l'utilisateur (bulle
        éphémère), indépendant de `editer_message`."""
        try:
            reponse = await self._http.post(
                f"{_BASE_URL}/bot{self._token}/answerCallbackQuery",
                json={"callback_query_id": callback_id, "text": texte},
            )
            reponse.raise_for_status()
        except httpx.HTTPError:
            raise ErreurTelegram(
                "Échec de l'appel Telegram answerCallbackQuery"
            ) from None

    async def editer_message(self, chat_id: int, message_id: int, texte: str) -> None:
        """`editMessageText` (L2-T3), sans `reply_markup` : décision du
        contrôleur, l'omettre retire les boutons du message édité."""
        try:
            reponse = await self._http.post(
                f"{_BASE_URL}/bot{self._token}/editMessageText",
                json={"chat_id": chat_id, "message_id": message_id, "text": texte},
            )
            reponse.raise_for_status()
        except httpx.HTTPError:
            raise ErreurTelegram("Échec de l'appel Telegram editMessageText") from None
