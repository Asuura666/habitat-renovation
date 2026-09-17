"""Client HTTP de l'API Mistral OCR (`ingest/mistral.py`, T6b).

Seul point d'appel réseau vers Mistral de tout le dépôt (R17 : `extract`
reste pur, aucun appel n'y est fait). Appelé exclusivement par
`ingest/service.py`, jamais par un module métier pur.

Décisions du contrôleur (T6b, révision après T5 requalifiée) :
- `POST https://api.mistral.ai/v1/ocr`, en-tête `Authorization: Bearer
  <clé>`.
- Une image (`image/*`) est envoyée en `{"type": "image_url", "image_url":
  "data:<mime>;base64,<...>"}` ; un autre type (`application/pdf` en
  pratique) en `{"type": "document_url", "document_url":
  "data:<mime>;base64,<...>"}`.
- Options `"table_format": "markdown"`, `"include_image_base64": false`,
  modèle `mistral-ocr-latest` (même forme de requête que
  `extract/unikalo.py`, déjà validée en exploration T5).
- Timeout explicite (60 s, appliqué à la requête) : un document de plusieurs
  pages peut prendre du temps à analyser, mais ne doit jamais bloquer
  indéfiniment la tâche de fond qui appelle cette fonction.
- `ErreurOCR` ne contient jamais la clé API ni le contenu du document
  (message fixe, construit à la main, jamais l'exception httpx brute qui
  embarquerait l'URL/le corps de la requête — même principe que
  `ErreurTelegram` dans `messaging/telegram.py`).

Cette fonction sert aussi bien à la détection du numéro de BL sur une photo
(`extract/ocr.detecter_numero_bl`, T6b) qu'au parseur de facture Unikalo
(`extract/unikalo.py`, T5) : elle est réutilisée telle quelle par la CLI de
T7 pour les factures.
"""

from __future__ import annotations

import base64
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
    http: httpx.AsyncClient, cle_api: str, contenu: bytes, mime: str
) -> dict[str, Any]:
    """Envoie `contenu` (image ou PDF) à l'API Mistral OCR et renvoie sa
    réponse JSON brute (`{"pages": [...], ...}`), lue ensuite par
    `extract.ocr.texte_ocr` / `extract.ocr.detecter_numero_bl` ou par
    `extract.unikalo.analyser_facture_unikalo`.

    Lève `ErreurOCR` si l'appel échoue (connexion, timeout, statut HTTP en
    échec), si le corps de la réponse n'est pas du JSON valide, ou si ce
    JSON n'est pas un objet (`{...}`) — jamais la clé API ni le contenu dans
    le message (correction tour 1/5 : un corps 200 inattendu ne doit jamais
    remonter tel quel jusqu'à `extract.ocr.texte_ocr`, qui suppose un
    `dict`).
    """
    try:
        reponse = await http.post(
            _URL_OCR,
            headers={"Authorization": f"Bearer {cle_api}"},
            json={
                "model": _MODELE,
                "document": _document(contenu, mime),
                "table_format": "markdown",
                "include_image_base64": False,
            },
            timeout=_TIMEOUT_OCR,
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
