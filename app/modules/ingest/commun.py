"""Aides internes partagées par les sous-modules de `ingest` : écriture
atomique sur disque, journalisation d'échec, correspondance extension ->
type MIME, et le `Deposant` partagé par le dépôt Telegram
(`ingest/depot_telegram.py`) et le dépôt de facture (`ingest/factures.py`).

Issu du découpage de l'ancien `ingest/service.py` (vague finale du lot 2,
point 1 : simple déplacement de code, aucun changement de comportement).
N'est pas un module façade : chaque symbole d'ici est repris par au moins
deux des autres sous-modules d'`ingest`, jamais un ré-export de
complaisance.

`logger` garde le nom historique `"app.modules.ingest.service"` (plutôt que
`__name__`, qui vaudrait `"app.modules.ingest.commun"`) : les tests qui
filtrent les journaux avec
`caplog.at_level(..., logger="app.modules.ingest.service")` n'ont donc pas
besoin d'être modifiés par ce découpage (règle de la tâche : seuls les
imports changent).
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("app.modules.ingest.service")


def _journaliser_echec(etape: str, update_id: int, exc: Exception) -> None:
    """Ne journalise jamais le token, le contenu d'un fichier ni le nom de
    fichier d'origine : uniquement l'`update_id` et le type de l'exception."""
    logger.error(
        "échec ingest (%s) pour update_id=%s : %s",
        etape,
        update_id,
        type(exc).__name__,
    )


def _supprimer_si_existe(chemin: Path) -> None:
    chemin.unlink(missing_ok=True)


def _ecrire_atomique(
    docs_dir: Path, chemin_temporaire: Path, chemin_final: Path, contenu: bytes
) -> None:
    """Écriture atomique (décision du contrôleur T6) : fichier temporaire
    dans `docs_dir`, rempli, puis `os.replace` (rename atomique sur un même
    système de fichiers). Fonction synchrone, exécutée hors de la boucle
    asyncio via `asyncio.to_thread` (I/O disque bloquante)."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    chemin_temporaire.write_bytes(contenu)
    os.replace(chemin_temporaire, chemin_final)


# Mapping extension de stockage (`FichierTelecharge.extension`, décidée par
# `Messagerie.telecharger` — pas le type MIME Telegram d'origine, absent pour
# une photo) -> type MIME attendu par l'API Mistral OCR (`ingest/mistral.py`,
# `ocr_document`). Mapping explicite, même esprit que
# `messaging/telegram.py` : pas de bibliothèque `mimetypes` dépendante de la
# machine.
_MIME_PAR_EXTENSION: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "heic": "image/heic",
    "heif": "image/heif",
    "tiff": "image/tiff",
    "pdf": "application/pdf",
}


def _mime_pour_extension(extension: str) -> str:
    return _MIME_PAR_EXTENSION.get(extension, "application/octet-stream")


@dataclass(frozen=True)
class Deposant:
    """Auteur d'un dépôt : un utilisateur actif rattaché à un envoi Telegram
    (résolu par `depot_telegram.utilisateur_rattache`, liste blanche L2-D7,
    et utilisé par `traiter_fichier`/la ligne de supervision L2-D8), ou déjà
    authentifié via l'API (`api/factures.py`, dépôt d'une facture, L2-T4).
    Ne porte que les champs utiles à ces deux appelants, jamais l'entité ORM
    `Utilisateur` (le dépôt Telegram s'exécute en tâche de fond, après la
    fermeture de la session de la requête qui a fait la résolution)."""

    id: uuid.UUID
    nom_affichage: str
