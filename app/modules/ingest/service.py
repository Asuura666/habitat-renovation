"""Orchestration de l'ingestion (D10) : `ingest` est le seul module métier
autorisé à importer un autre module métier (`messaging`, `extract`), garde
vérifiée par `tests/test_frontieres.py`.

Responsabilités :
- `enregistrer_update` (T6) : dédoublonnage des webhooks Telegram
  (`INSERT ... ON CONFLICT DO NOTHING` sur la clé primaire `update_id` de
  `telegram_update` — atomique côté base, donc sûr même si deux requêtes
  concurrentes portent le même `update_id`) ;
- `traiter_fichier` (T6, complété T6b) : téléchargement, écriture atomique
  sur disque, enregistrement du `document` (décisions du contrôleur T6),
  puis OCR et détection du numéro de BL (décisions du contrôleur T6b,
  ci-dessous) ;
- `lire_facture`, `blocs_avec_reception`, `formater_blocs` (T7) : lecture
  d'une facture via l'OCR Mistral et rapprochement « photo reçue » par bloc
  BL, pour la CLI `python -m app.cli bl-non-recus` (livrable visible du
  lot 1, décisions du contrôleur en bas de fichier).

Décisions du contrôleur T6b sur `traiter_fichier` :
- Le document est déjà enregistré (`statut="recu"`) avant l'appel OCR : le
  dépôt est acquis quoi qu'il arrive, y compris si l'OCR échoue.
- L'OCR est appelé via une fonction injectée (`ocr`), plutôt qu'un appel
  direct à `app.modules.ingest.mistral.ocr_document` : `ingest/service.py`
  n'a donc besoin ni de `httpx` ni de la clé API, et les tests substituent
  un faux OCR sans construire de client HTTP (production : le routeur
  construit cette fonction à partir du client HTTP du lifespan et de
  `Settings.mistral_api_key`, voir `ingest/router.py`).
- La réponse « reçu » part après la tentative d'OCR, dans tous les cas
  (numéro détecté, non détecté, ou échec complet de l'OCR).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.extract.facture import Facture
from app.modules.extract.ocr import detecter_numero_bl, texte_ocr
from app.modules.extract.unikalo import analyser_facture_unikalo
from app.modules.ingest.models import Document, TelegramUpdate, Utilisateur
from app.modules.messaging.base import FichierEntrant, Messagerie

logger = logging.getLogger(__name__)

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


def _journaliser_echec(etape: str, update_id: int, exc: Exception) -> None:
    """Ne journalise jamais le token, le contenu d'un fichier ni le nom de
    fichier d'origine : uniquement l'`update_id` et le type de l'exception."""
    logger.error(
        "échec ingest (%s) pour update_id=%s : %s",
        etape,
        update_id,
        type(exc).__name__,
    )


async def enregistrer_update(session: AsyncSession, update_id: int) -> bool:
    """Enregistre `update_id` dans `telegram_update`.

    Renvoie `True` s'il s'agit d'un nouvel update (à traiter), `False` s'il
    a déjà été vu (webhook Telegram redélivré). `ON CONFLICT DO NOTHING`
    rend l'opération atomique au niveau de la base : deux requêtes
    concurrentes pour le même `update_id` ne peuvent jamais toutes les deux
    obtenir `True`.
    """
    resultat = await session.execute(
        insert(TelegramUpdate)
        .values(update_id=update_id)
        .on_conflict_do_nothing(index_elements=[TelegramUpdate.update_id])
        .returning(TelegramUpdate.update_id)
    )
    await session.commit()
    return resultat.scalar_one_or_none() is not None


async def _resoudre_deposant(
    session: AsyncSession, telegram_user_id: int | None
) -> uuid.UUID | None:
    """`deposant_id` selon la décision D15 : rempli si `telegram_user_id`
    correspond à un `utilisateur` connu, `None` sinon (pas de whitelist au
    lot 1)."""
    if telegram_user_id is None:
        return None
    resultat = await session.execute(
        select(Utilisateur.id).where(Utilisateur.telegram_user_id == telegram_user_id)
    )
    return resultat.scalar_one_or_none()


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


async def _executer_ocr(
    sessions: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
    contenu: bytes,
    mime: str,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
    update_id: int,
) -> None:
    """Appelle l'OCR injecté puis met à jour le document dans une seconde
    transaction (décisions du contrôleur T6b) :
    - numéro détecté -> `numero` et `type` remplis, `statut` reste `recu` ;
    - aucun numéro détecté (absent ou ambigu) -> `numero` reste `NULL`,
      `statut` passe à `a_verifier` ;
    - échec de l'OCR lui-même -> rien n'est modifié (document déjà `recu`
      sans numéro), erreur journalisée sans contenu ni clé API.
    """
    try:
        reponse = await ocr(contenu, mime)
    except Exception as exc:
        _journaliser_echec("ocr", update_id, exc)
        return

    numero_bl = detecter_numero_bl(texte_ocr(reponse))

    try:
        async with sessions() as session:
            document = await session.get(Document, document_id)
            if document is None:
                return
            document.ocr_brut = reponse
            if numero_bl is not None:
                document.numero = numero_bl.numero
                document.type = numero_bl.type_bl.value
                document.statut = "recu"
            else:
                document.statut = "a_verifier"
            await session.commit()
    except Exception as exc:
        _journaliser_echec("enregistrement ocr", update_id, exc)


async def traiter_fichier(
    entrant: FichierEntrant,
    messagerie: Messagerie,
    sessions: async_sessionmaker[AsyncSession],
    docs_dir: Path,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
) -> None:
    """Télécharge le fichier, l'écrit sous `docs_dir/<uuid4>.<ext>`, insère
    le `document` correspondant, tente l'OCR (T6b) puis répond « reçu ».

    En cas d'erreur de téléchargement, d'écriture ou d'enregistrement du
    document, aucun document n'est inséré et aucun fichier partiel ne reste
    dans `docs_dir` (nettoyage explicite à chaque étape) — l'OCR n'est alors
    jamais appelé. Une fois le document enregistré, le dépôt est acquis :
    l'OCR est tenté (`_executer_ocr`, qui n'échoue jamais vers l'appelant)
    puis la réponse « reçu » part dans tous les cas. Ouvre sa propre session
    (la session de la requête HTTP est déjà fermée quand cette tâche de fond
    s'exécute).
    """
    try:
        fichier = await messagerie.telecharger(entrant)
    except Exception as exc:
        # Toute erreur de téléchargement est journalisée puis avalée : la
        # tâche de fond n'a personne à qui remonter l'exception.
        _journaliser_echec("téléchargement", entrant.update_id, exc)
        return

    identifiant = uuid.uuid4()
    # `.absolute()` (pas `.resolve()`, qui ferait un accès disque pour
    # résoudre les liens symboliques) : garantit un `fichier_path` absolu
    # même si `docs_dir` était configuré en relatif, sans I/O bloquant ici.
    chemin_final = (docs_dir / f"{identifiant}.{fichier.extension}").absolute()
    chemin_temporaire = (docs_dir / f"{identifiant}.{fichier.extension}.tmp").absolute()

    try:
        await asyncio.to_thread(
            _ecrire_atomique, docs_dir, chemin_temporaire, chemin_final, fichier.contenu
        )
    except OSError as exc:
        await asyncio.to_thread(_supprimer_si_existe, chemin_temporaire)
        _journaliser_echec("écriture fichier", entrant.update_id, exc)
        return

    try:
        async with sessions() as session:
            deposant_id = await _resoudre_deposant(session, entrant.expediteur_id)
            document = Document(
                type="bl",
                source="telegram",
                statut="recu",
                fichier_path=str(chemin_final),
                telegram_message_id=entrant.message_id,
                deposant_id=deposant_id,
            )
            session.add(document)
            # `flush` (pas seulement `commit`) : peuple `document.id`
            # (`gen_random_uuid()` côté base) pendant que la session est
            # encore active, pour le passer à `_executer_ocr` juste après —
            # après `commit`, l'attribut est expiré et sa lecture hors
            # session lèverait (accès implicite interdit en async).
            await session.flush()
            document_id = document.id
            await session.commit()
    except Exception as exc:
        # Le fichier est déjà écrit sur disque : il ne doit pas rester seul
        # (sans document associé) si l'enregistrement en base échoue.
        await asyncio.to_thread(_supprimer_si_existe, chemin_final)
        _journaliser_echec("enregistrement document", entrant.update_id, exc)
        return

    # Le document est déjà enregistré (`statut="recu"`) : le dépôt est
    # acquis à partir d'ici, y compris si l'OCR échoue complètement
    # (décision du contrôleur T6b). `_executer_ocr` n'échoue jamais vers
    # l'appelant (ses erreurs sont journalisées en interne).
    await _executer_ocr(
        sessions,
        document_id,
        fichier.contenu,
        _mime_pour_extension(fichier.extension),
        ocr,
        entrant.update_id,
    )

    try:
        await messagerie.repondre(entrant.chat_id, entrant.message_id, "reçu")
    except Exception as exc:
        # Le document est déjà enregistré : on journalise sans revenir en
        # arrière (dédoublonnage déjà acquis, pas de nouvelle tentative).
        _journaliser_echec("réponse", entrant.update_id, exc)


# --------------------------------------------------------------------------
# T7 — lecture de facture et rapprochement « photo reçue » (`bl-non-recus`)
#
# Décision du contrôleur (révision après T5 requalifiée) : la facture est
# toujours lue via l'OCR Mistral, jamais via pdfplumber (l'unique facture
# disponible est un scan sans couche texte). `ocr` est injecté, même
# principe que `traiter_fichier` ci-dessus : en production, `app/cli.py`
# construit `partial(ocr_document, http, cle_api)` à partir de
# `get_settings()` ; les tests substituent une fonction qui renvoie une
# fixture ou une réponse synthétique (R17 : aucun appel réel à Mistral).
# --------------------------------------------------------------------------


async def lire_facture(
    contenu_pdf: bytes,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
) -> Facture:
    """Lit une facture PDF via l'OCR injecté puis `analyser_facture_unikalo`.

    Lève `ErreurOCR` (`ingest/mistral.py`) si l'appel OCR échoue, ou
    `FactureIllisible` (`extract/facture.py`) si la réponse n'a pas la
    structure attendue d'une facture Unikalo. Ni l'une ni l'autre n'est
    interceptée ici : c'est à l'appelant (la CLI) de décider du code de
    sortie et du message.
    """
    reponse = await ocr(contenu_pdf, "application/pdf")
    return analyser_facture_unikalo(reponse)


@dataclass(frozen=True)
class BlocReception:
    """Un bloc « Concerne le B.L. » de la facture, avec l'indicateur
    « photo reçue » (livrable visible du lot 1, T7)."""

    numero_bl: str
    date_bl: date | None
    chantier_brut: str | None
    montant_ht: Decimal
    photo_recue: bool


async def blocs_avec_reception(
    session: AsyncSession, facture: Facture
) -> list[BlocReception]:
    """Une `BlocReception` par bloc de `facture`, dans l'ordre de la facture.

    « Photo reçue » (décisions du contrôleur T7) : il existe un `document`
    de type `bl` ou `enlevement`, de statut différent de `archive`, dont le
    `numero` correspond exactement à celui du bloc après `strip()` et mise
    en majuscules des deux côtés (le préfixe `L` est parfois en minuscule
    sur les OCR ; aucune autre normalisation, cf. `docs/dette.md`). Une
    seule requête pour tous les numéros reçus, pas une par bloc.
    """
    resultat = await session.execute(
        select(Document.numero).where(
            Document.type.in_(("bl", "enlevement")),
            Document.statut != "archive",
            Document.numero.is_not(None),
        )
    )
    numeros_recus = {
        numero.strip().upper() for numero in resultat.scalars() if numero is not None
    }

    return [
        BlocReception(
            numero_bl=bloc.numero_bl,
            date_bl=bloc.date_bl,
            chantier_brut=bloc.chantier_brut,
            montant_ht=bloc.montant_ht,
            photo_recue=bloc.numero_bl.strip().upper() in numeros_recus,
        )
        for bloc in facture.blocs
    ]


_ENTETE_TABLEAU = ("N° BL", "Date", "Chantier brut", "Montant HT", "Photo reçue")


def _formater_montant_fr(montant: Decimal) -> str:
    """Format français d'un montant : séparateur de milliers (espace),
    virgule décimale, toujours deux décimales (`Decimal("1234.5")` ->
    `"1 234,50"`). Le mini-langage de format de `Decimal` fait tout le
    travail (groupement, arrondi) : seuls les séparateurs sont substitués,
    jamais de conversion en `float`."""
    brut = f"{montant.quantize(Decimal('0.01')):,.2f}"
    return brut.replace(",", " ").replace(".", ",")


def _ligne_tableau(bloc: BlocReception) -> tuple[str, str, str, str, str]:
    return (
        bloc.numero_bl,
        bloc.date_bl.strftime("%d/%m/%Y") if bloc.date_bl is not None else "",
        bloc.chantier_brut or "",
        _formater_montant_fr(bloc.montant_ht),
        "oui" if bloc.photo_recue else "non",
    )


def formater_blocs(blocs: list[BlocReception]) -> str:
    """Tableau aligné (`N° BL | Date | Chantier brut | Montant HT | Photo
    reçue`), puis une ligne de synthèse `N blocs — X reçus — Y non reçus`
    (décision du contrôleur T7). Fonction pure : aucune base, aucun réseau."""
    lignes_donnees = [_ligne_tableau(bloc) for bloc in blocs]
    largeurs = [
        max(len(_ENTETE_TABLEAU[i]), *(len(ligne[i]) for ligne in lignes_donnees), 0)
        for i in range(len(_ENTETE_TABLEAU))
    ]

    def _formater_ligne(valeurs: tuple[str, ...]) -> str:
        return " | ".join(
            valeur.ljust(largeur)
            for valeur, largeur in zip(valeurs, largeurs, strict=True)
        ).rstrip()

    lignes = [_formater_ligne(_ENTETE_TABLEAU)]
    lignes.extend(_formater_ligne(ligne) for ligne in lignes_donnees)

    recus = sum(1 for bloc in blocs if bloc.photo_recue)
    non_recus = len(blocs) - recus
    lignes.append(f"{len(blocs)} blocs — {recus} reçus — {non_recus} non reçus")

    return "\n".join(lignes)
