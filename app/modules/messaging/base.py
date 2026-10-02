"""Interface d'abstraction de la messagerie entrante (décision D10).

`messaging` ne connaît que Telegram aujourd'hui (`telegram.py`), mais
`ingest/service.py` — le seul orchestrateur autorisé à importer un autre
module métier — ne dépend que de ce contrat (`Messagerie`), jamais d'une
implémentation concrète. `messaging` lui-même n'importe aucun autre module
de `app/modules` (garde de frontières, `tests/test_frontieres.py`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

# Préfixes du `callback_data` des boutons de confirmation (L2-D9/L2-T3) :
# `"<préfixe>:<numero_interne>"`. Constantes partagées entre `telegram.py`
# (construit `ClicBouton.action` depuis le préfixe reçu) et
# `ingest/service.py` (construit le `callback_data` envoyé dans
# `traiter_fichier`, seul module métier autorisé à importer `messaging`) :
# un seul et même contrat, jamais dupliqué en dur des deux côtés.
PREFIXE_QUANTITES_VERIFIEES = "v"
PREFIXE_ECART_CONSTATE = "e"


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
    # Légende Telegram (`message.caption`, avenant du 27/09/2026) : nom de
    # chantier tapé par l'employé au moment d'envoyer la photo, déjà
    # nettoyée par `telegram.lire_update` (`strip()`, vide -> `None`,
    # tronquée à 200 caractères). Dernier champ, défaut `None`, pour ne pas
    # casser les constructions existantes qui ne le renseignent pas.
    legende: str | None = None
    # Nom complet Telegram de l'expéditeur (`first_name` + `last_name`, sinon
    # `username`), décision d'Ilane du 02/10/2026 : nom du compte créé
    # automatiquement au premier envoi d'un employé inconnu
    # (`ingest.depot_telegram.rattacher_ou_creer_deposant`). Dernier champ,
    # défaut `None`, pour ne pas casser les constructions existantes.
    expediteur_nom_complet: str | None = None


@dataclass(frozen=True)
class FichierTelecharge:
    """Contenu binaire téléchargé, avec l'extension à utiliser pour le stocker."""

    contenu: bytes
    extension: str  # "jpg", "png", "heic", "pdf", ...


@dataclass(frozen=True)
class ClicBouton:
    """Un clic sur un des deux boutons de confirmation (L2-D9/L2-D10),
    détecté dans un `callback_query` Telegram par `lire_update`.

    `action` vaut `PREFIXE_QUANTITES_VERIFIEES` ou `PREFIXE_ECART_CONSTATE`
    (préfixe du `callback_data` reçu, jamais un libellé métier : `messaging`
    ne connaît pas le vocabulaire du journal — c'est `ingest/service.py`, le
    seul orchestrateur, qui traduit `action` en `quantites_verifiees` /
    `ecart_constate` pour la colonne `journal.action`)."""

    update_id: int
    callback_id: str
    chat_id: int
    message_id: int
    expediteur_id: int | None
    action: str
    numero_interne: int


class Messagerie(Protocol):
    """Contrat minimal requis par `ingest/service.py` pour traiter un fichier
    entrant : le télécharger, répondre au message d'origine, et (L2-T2)
    envoyer un message libre à un chat donné (notifications de supervision,
    L2-D7/L2-D8). L2-T3 ajoute les boutons de la réponse au dépôt ainsi que
    l'accusé et l'édition du message lors du clic sur un bouton (L2-D9/L2-D10)."""

    async def telecharger(self, fichier: FichierEntrant) -> FichierTelecharge: ...

    async def repondre(
        self,
        chat_id: int,
        message_id: int,
        texte: str,
        boutons: Sequence[tuple[str, str]] | None = None,
    ) -> None: ...

    async def envoyer(self, chat_id: int, texte: str) -> None: ...

    async def accuser_clic(self, callback_id: str, texte: str) -> None: ...

    async def editer_message(
        self, chat_id: int, message_id: int, texte: str
    ) -> None: ...
