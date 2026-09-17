"""Client HTTP de l'API Mistral OCR (`ingest/mistral.py`, T6b, complété T6).

Seul point d'appel réseau vers Mistral de tout le dépôt (R17 : `extract`
reste pur, aucun appel n'y est fait). Appelé exclusivement par
`ingest/router.py`/`ingest/depot_telegram.py`, jamais par un module métier
pur.

Décisions du contrôleur (T6b, révision après T5 requalifiée ; complété T6) :
- `POST https://api.mistral.ai/v1/ocr`, en-tête `Authorization: Bearer
  <clé>`.
- Une image (`image/*`) est envoyée en `{"type": "image_url", "image_url":
  "data:<mime>;base64,<...>"}` ; un autre type (`application/pdf` en
  pratique) en `{"type": "document_url", "document_url":
  "data:<mime>;base64,<...>"}`.
- Corps construit à partir d'`options` (T6, `Mapping[str, Any] | None`,
  fusionné en premier), puis des clés imposées `model`, `document`,
  `table_format`, `include_image_base64` — toujours `"table_format":
  "markdown"`, `"include_image_base64": false`, modèle
  `mistral-ocr-latest` — qui gagnent toujours sur `options` (aucune ne peut
  être écrasée par l'appelant). `options` porte par exemple
  `extract.bl.OPTIONS_OCR_BL` (annotation structurée + scores de confiance
  par mot, lue par `ingest/extraction_bl.py`).
- Timeout explicite (60 s, appliqué à la requête) : un document de plusieurs
  pages peut prendre du temps à analyser, mais ne doit jamais bloquer
  indéfiniment la tâche de fond qui appelle cette fonction.
- `ErreurOCR` ne contient jamais la clé API ni le contenu du document
  (message fixe, construit à la main, jamais l'exception httpx brute qui
  embarquerait l'URL/le corps de la requête — même principe que
  `ErreurTelegram` dans `messaging/telegram.py`).

Cette fonction sert aussi bien à l'extraction d'un BL sur une photo
(`extract/bl.py`, T6) qu'au parseur de facture Unikalo (`extract/unikalo.py`,
T5) : elle est réutilisée telle quelle par la CLI de T7 pour les factures.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

import httpx

_URL_OCR = "https://api.mistral.ai/v1/ocr"
_MODELE = "mistral-ocr-latest"
_TIMEOUT_OCR = httpx.Timeout(60.0)


class ErreurOCR(Exception):
    """Échec d'un appel à l'API Mistral OCR. Son message ne contient jamais
    la clé API ni le contenu du document envoyé."""


def _document(contenu: bytes, mime: str) -> dict[str, Any]:
    """Corps `document` de la requête : image ou document selon `mime`."""
    data_uri = f"data:{mime};base64,{base64.b64encode(contenu).decode('ascii')}"
    if mime.startswith("image/"):
        return {"type": "image_url", "image_url": data_uri}
    return {"type": "document_url", "document_url": data_uri}


async def ocr_document(
    http: httpx.AsyncClient,
    cle_api: str,
    contenu: bytes,
    mime: str,
    *,
    delai: httpx.Timeout | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Envoie `contenu` (image ou PDF) à l'API Mistral OCR et renvoie sa
    réponse JSON brute (`{"pages": [...], ...}`), lue ensuite par
    `extract.bl.analyser_bl` (photo de BL, T6) ou par
    `extract.unikalo.analyser_facture_unikalo` (facture).

    `delai` (L2-T4) remplace le délai par défaut (60 s) quand fourni — utilisé
    pour le dépôt d'une facture (délai porté à 90 s,
    `ingest/router.py::get_ocr_facture`) et pour une photo de BL depuis T6
    (`ingest/router.py::get_ocr`, désormais 90 s également). Nommé `delai` et
    non `timeout` (ASYNC109) : un paramètre `timeout` sur une fonction
    `async` est un faux positif ici (c'est un réglage passé à `httpx`, pas un
    contrôle d'annulation façon `asyncio.timeout`).

    `options` (T6) : options Mistral OCR supplémentaires à fusionner dans le
    corps de la requête (ex. `extract.bl.OPTIONS_OCR_BL` : annotation
    structurée, scores de confiance par mot). Le corps est construit à
    partir d'`options`, puis les clés imposées (`model`, `document`,
    `table_format`, `include_image_base64`) sont posées par-dessus : elles ne
    peuvent jamais être écrasées par l'appelant, quel que soit le contenu
    d'`options`.

    Lève `ErreurOCR` si l'appel échoue (connexion, timeout, statut HTTP en
    échec), si le corps de la réponse n'est pas du JSON valide, ou si ce
    JSON n'est pas un objet (`{...}`) — jamais la clé API ni le contenu dans
    le message (correction tour 1/5 : un corps 200 inattendu ne doit jamais
    remonter tel quel jusqu'à `extract.ocr.texte_ocr`, qui suppose un
    `dict`).
    """
    corps: dict[str, Any] = dict(options) if options is not None else {}
    corps.update(
        {
            "model": _MODELE,
            "document": _document(contenu, mime),
            "table_format": "markdown",
            "include_image_base64": False,
        }
    )
    try:
        reponse = await http.post(
            _URL_OCR,
            headers={"Authorization": f"Bearer {cle_api}"},
            json=corps,
            timeout=delai if delai is not None else _TIMEOUT_OCR,
        )
        reponse.raise_for_status()
    except httpx.HTTPError:
        raise ErreurOCR("Échec de l'appel à l'API Mistral OCR") from None

    try:
        resultat = reponse.json()
    except ValueError:
        raise ErreurOCR("Réponse Mistral OCR illisible (JSON invalide)") from None
    if not isinstance(resultat, dict):
        raise ErreurOCR("Réponse Mistral OCR invalide (objet JSON attendu)") from None
    return resultat
