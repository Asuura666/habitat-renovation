"""Interface d'abstraction de la messagerie entrante (décision D10).

`messaging` ne connaît que Telegram aujourd'hui (`telegram.py`), mais
`ingest/service.py` — le seul orchestrateur autorisé à importer un autre
module métier — ne dépend que de ce contrat (`Messagerie`), jamais d'une
implémentation concrète. `messaging` lui-même n'importe aucun autre module
de `app/modules` (garde de frontières, `tests/test_frontieres.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FichierEntrant:
    """Un fichier (photo ou document) détecté dans un update Telegram."""

    update_id: int
    chat_id: int
    message_id: int
    expediteur_id: int | None
    fichier_id: str
    mime_type: str | None
    nom_fichier: str | None
    compresse: bool  # True pour une photo Telegram (photo[-1])
    # L2-T2 : nom Telegram de l'expéditeur (`from.username`, sinon
    # `from.first_name`), utilisé uniquement pour le message de supervision
    # « expéditeur non rattaché » (L2-D7) — jamais pour une règle métier.
    # Défaut `None` pour ne pas casser les constructions existantes qui ne
    # le renseignent pas.
    expediteur_nom: str | None = None


@dataclass(frozen=True)
class FichierTelecharge:
    """Contenu binaire téléchargé, avec l'extension à utiliser pour le stocker."""

    contenu: bytes
    extension: str  # "jpg", "png", "heic", "pdf", ...


class Messagerie(Protocol):
    """Contrat minimal requis par `ingest/service.py` pour traiter un fichier
    entrant : le télécharger, répondre au message d'origine, et (L2-T2)
    envoyer un message libre à un chat donné (notifications de supervision,
    L2-D7/L2-D8)."""

    async def telecharger(self, fichier: FichierEntrant) -> FichierTelecharge: ...

    async def repondre(self, chat_id: int, message_id: int, texte: str) -> None: ...

    async def envoyer(self, chat_id: int, texte: str) -> None: ...
