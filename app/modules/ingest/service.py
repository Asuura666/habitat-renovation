"""Orchestration de l'ingestion (D10) : `ingest` est le seul module métier
autorisé à importer un autre module métier (`messaging`, `extract`), garde
vérifiée par `tests/test_frontieres.py`.

Responsabilités :
- `enregistrer_update` (T6) : dédoublonnage des webhooks Telegram
  (`INSERT ... ON CONFLICT DO NOTHING` sur la clé primaire `update_id` de
  `telegram_update` — atomique côté base, donc sûr même si deux requêtes
  concurrentes portent le même `update_id`) ;
- `utilisateur_rattache` (L2-T2) : liste blanche (L2-D7) — résout
  `telegram_user_id` en `Deposant` (utilisateur actif rattaché), `None`
  sinon ;
- `signaler_expediteur_inconnu` (L2-T2) : notifie le groupe de supervision
  qu'un expéditeur non rattaché a tenté un dépôt (L2-D7), sans rien écrire
  ni télécharger ;
- `traiter_fichier` (T6, complété T6b, L2-T2) : téléchargement, écriture
  atomique sur disque, enregistrement du `document` (décisions du
  contrôleur T6), OCR et détection du numéro de BL (décisions du
  contrôleur T6b, ci-dessous), puis ligne de supervision (L2-D8) et
  notification d'échec à l'agent (Ruling R22, ci-dessous) ;
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

Décisions du contrôleur L2-T2 (liste blanche, groupe BL, supervision) :
- Le filtre de chat (`chat_id != TELEGRAM_CHAT_BL_ID`, L2-D6) et le
  dédoublonnage (`enregistrer_update`) restent dans le routeur (celui-ci
  reste mince : il ne fait qu'enchaîner ces fonctions, aucune règle
  métier) ; `utilisateur_rattache` est appelé avec la session de la
  requête, avant la mise en tâche de fond, pour décider laquelle des deux
  tâches (`signaler_expediteur_inconnu` ou `traiter_fichier`) planifier.
- `utilisateur_rattache` renvoie un `Deposant` (dataclass ne portant que
  `id`/`nom_affichage`), jamais l'entité ORM `Utilisateur` : la tâche de
  fond s'exécute après la fermeture de la session de la requête, et ce
  module évite de faire dépendre le reste du code d'un objet potentiellement
  détaché (même prudence que `_resoudre_deposant` en lot 1, qui ne
  sélectionnait déjà que `Utilisateur.id`).
- Ruling R22 (revue finale du lot 1) : un échec de `traiter_fichier` après
  l'accusé HTTP (téléchargement, écriture disque, insertion en base)
  envoie, en plus du message de supervision, une réponse à l'agent dans le
  groupe BL (« Échec de l'enregistrement, renvoyez la photo. », sans détail
  technique) — corrige la dette notée en lot 1 (`docs/dette.md`, T6).
- Un échec d'envoi d'un message de supervision est journalisé mais ne fait
  jamais échouer `traiter_fichier` (`_envoyer_supervision`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.modules.extract.facture import BlocBL, Facture, FactureIllisible
from app.modules.extract.ocr import detecter_numero_bl, texte_ocr
from app.modules.extract.unikalo import analyser_facture_unikalo
from app.modules.ingest.mistral import ErreurOCR
from app.modules.ingest.models import (
    BlocFacture,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    TelegramUpdate,
    Utilisateur,
)
from app.modules.messaging.base import (
    PREFIXE_ECART_CONSTATE,
    PREFIXE_QUANTITES_VERIFIEES,
    ClicBouton,
    FichierEntrant,
    Messagerie,
)

_FUSEAU_PARIS = ZoneInfo("Europe/Paris")
_MESSAGE_ECHEC_AGENT = "Échec de l'enregistrement, renvoyez la photo."
_BL_NON_DETECTE = "non détecté"

# L2-D9 : libellés des deux boutons de la réponse au dépôt.
_LIBELLE_QUANTITES_VERIFIEES = "Quantités vérifiées"
_LIBELLE_ECART_CONSTATE = "Écart constaté"

# L2-D10 : action journal (`journal.action`) associée à chaque préfixe de
# `callback_data` (`ClicBouton.action`, `messaging/base.py`).
_ACTIONS_JOURNAL: dict[str, str] = {
    PREFIXE_QUANTITES_VERIFIEES: "quantites_verifiees",
    PREFIXE_ECART_CONSTATE: "ecart_constate",
}
# Textes d'accusé (`answerCallbackQuery`) et de l'édition du message une fois
# la confirmation enregistrée (décision du contrôleur, exacts).
_TEXTES_CONFIRMATION: dict[str, tuple[str, str]] = {
    PREFIXE_QUANTITES_VERIFIEES: (
        "Quantités vérifiées enregistrées",
        "Quantités vérifiées",
    ),
    PREFIXE_ECART_CONSTATE: ("Écart enregistré", "Écart constaté"),
}

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


@dataclass(frozen=True)
class Deposant:
    """Utilisateur actif rattaché à un envoi Telegram, résolu par
    `utilisateur_rattache` (liste blanche, L2-D7). Ne porte que les champs
    utiles à `traiter_fichier`/la ligne de supervision (L2-D8), jamais
    l'entité ORM `Utilisateur` (la tâche de fond s'exécute après la
    fermeture de la session de la requête qui a fait la résolution)."""

    id: uuid.UUID
    nom_affichage: str


async def utilisateur_rattache(
    session: AsyncSession, telegram_user_id: int | None
) -> Deposant | None:
    """Liste blanche (L2-D7) : `None` si `telegram_user_id` est absent (pas
    d'expéditeur identifié) ou ne correspond à aucun `utilisateur` **actif**
    — contrairement à la décision D15 du lot 1 (tout `telegram_user_id`
    connu, actif ou non, remplissait `deposant_id`), le lot 2 rejette aussi
    un compte désactivé, traité comme un expéditeur inconnu."""
    if telegram_user_id is None:
        return None
    resultat = await session.execute(
        select(Utilisateur.id, Utilisateur.nom, Utilisateur.email).where(
            Utilisateur.telegram_user_id == telegram_user_id,
            Utilisateur.is_active.is_(True),
        )
    )
    ligne = resultat.first()
    if ligne is None:
        return None
    return Deposant(id=ligne.id, nom_affichage=ligne.nom or ligne.email)


async def signaler_expediteur_inconnu(
    entrant: FichierEntrant,
    messagerie: Messagerie,
    telegram_chat_supervision_id: int,
) -> None:
    """Notifie le groupe de supervision qu'un expéditeur non rattaché a
    tenté un dépôt (L2-D7) : identifiant Telegram et nom Telegram
    (`FichierEntrant.expediteur_nom`), jamais de contenu ni de fichier
    (aucun appel à `Messagerie.telecharger`). N'écrit rien en base et ne
    répond pas dans le groupe BL (décision D7 : « pas de réponse dans le
    groupe »). Un échec d'envoi est journalisé, jamais remonté (même
    politique que le reste de la supervision, `_envoyer_supervision`)."""
    identifiant = (
        entrant.expediteur_id if entrant.expediteur_id is not None else "inconnu"
    )
    nom = entrant.expediteur_nom or "nom inconnu"
    await _envoyer_supervision(
        messagerie,
        telegram_chat_supervision_id,
        entrant.update_id,
        f"Expéditeur Telegram non rattaché : id {identifiant} · {nom}",
    )


async def _envoyer_supervision(
    messagerie: Messagerie, chat_id: int, update_id: int, texte: str
) -> None:
    """Envoie `texte` au groupe de supervision. Un échec est journalisé
    (sans le texte, qui ne contient jamais de contenu de document ni de
    secret) mais ne remonte jamais à l'appelant : la supervision ne doit
    jamais faire échouer le traitement d'un dépôt."""
    try:
        await messagerie.envoyer(chat_id, texte)
    except Exception as exc:
        _journaliser_echec("supervision", update_id, exc)


async def _signaler_echec_traitement(
    messagerie: Messagerie,
    telegram_chat_supervision_id: int,
    entrant: FichierEntrant,
    etape: str,
) -> None:
    """Ruling R22 (revue finale du lot 1) : un échec de `traiter_fichier`
    après l'accusé HTTP (téléchargement, écriture, insertion) est signalé en
    supervision (sans contenu ni détail technique) **et** répond à l'agent,
    dans le groupe BL, au message d'origine — pour qu'il sache renvoyer la
    photo plutôt que de croire le dépôt acquis sans nouvelle de « reçu »."""
    await _envoyer_supervision(
        messagerie,
        telegram_chat_supervision_id,
        entrant.update_id,
        f"Échec du dépôt (update {entrant.update_id}) : {etape}",
    )
    try:
        await messagerie.repondre(
            entrant.chat_id, entrant.message_id, _MESSAGE_ECHEC_AGENT
        )
    except Exception as exc:
        _journaliser_echec("réponse échec", entrant.update_id, exc)


def _ligne_supervision(
    numero_interne: int, numero_bl: str | None, statut: str, deposant_nom: str
) -> str:
    """Format L2-D8 : `Document n° <interne> · BL <n° détecté ou « non
    détecté »> · fournisseur — · chantier — · <déposant> · <HH:MM> ·
    <statut>`. Fournisseur et chantier restent à « — » jusqu'au lot 3.
    Heure de Paris (décision du contrôleur), calculée au moment de l'envoi
    (après la tentative d'OCR, donc après le traitement complet du dépôt)."""
    heure = datetime.now(_FUSEAU_PARIS).strftime("%H:%M")
    bl = numero_bl if numero_bl is not None else _BL_NON_DETECTE
    return (
        f"Document n° {numero_interne} · BL {bl} · fournisseur — · chantier — · "
        f"{deposant_nom} · {heure} · {statut}"
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


@dataclass(frozen=True)
class _ResultatOcr:
    """État final (`numero`, `statut`) du document après la tentative d'OCR
    de `_executer_ocr`, quelle que soit l'issue (numéro détecté, non
    détecté, ou échec complet) — utilisé pour la ligne de supervision
    (L2-D8) sans relire le document en base une troisième fois."""

    numero: str | None
    statut: str


async def _executer_ocr(
    sessions: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
    contenu: bytes,
    mime: str,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
    update_id: int,
) -> _ResultatOcr:
    """Appelle l'OCR injecté puis met à jour le document dans une seconde
    transaction (décisions du contrôleur T6b) :
    - numéro détecté -> `numero` et `type` remplis, `statut` reste `recu` ;
    - aucun numéro détecté (absent ou ambigu) -> `numero` reste `NULL`,
      `statut` passe à `a_verifier` ;
    - échec de l'OCR lui-même, réponse OCR mal formée (pas un objet JSON
      avec une liste `pages`), ou échec de la mise à jour en base -> rien
      n'est modifié (document déjà `recu` sans numéro), erreur journalisée
      sans contenu ni clé API (correction tour 1/5 : une réponse mal formée
      ne doit jamais faire remonter d'exception jusqu'à `traiter_fichier`,
      qui n'enverrait alors jamais la réponse « reçu »).
    """
    try:
        reponse = await ocr(contenu, mime)
    except Exception as exc:
        _journaliser_echec("ocr", update_id, exc)
        return _ResultatOcr(numero=None, statut="recu")

    try:
        # Réponse structurellement inexploitable (pas un `dict` avec une
        # liste `pages`) : traitée comme un échec d'OCR, pas comme une
        # réponse valide où aucun numéro n'a été trouvé (`texte_ocr` est
        # volontairement permissif — cf. son docstring — donc cette
        # vérification vit ici, avant de lui déléguer la lecture du texte).
        if not isinstance(reponse, dict) or not isinstance(reponse.get("pages"), list):
            raise ValueError("réponse OCR mal formée (pas de « pages » exploitable)")

        numero_bl = detecter_numero_bl(texte_ocr(reponse))

        async with sessions() as session:
            document = await session.get(Document, document_id)
            if document is None:
                return _ResultatOcr(numero=None, statut="recu")
            document.ocr_brut = reponse
            if numero_bl is not None:
                document.numero = numero_bl.numero
                document.type = numero_bl.type_bl.value
                document.statut = "recu"
            else:
                document.statut = "a_verifier"
            await session.commit()
            return _ResultatOcr(numero=document.numero, statut=document.statut)
    except Exception as exc:
        _journaliser_echec("traitement ocr", update_id, exc)
        return _ResultatOcr(numero=None, statut="recu")


async def traiter_fichier(
    entrant: FichierEntrant,
    messagerie: Messagerie,
    sessions: async_sessionmaker[AsyncSession],
    docs_dir: Path,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
    deposant: Deposant,
    telegram_chat_supervision_id: int,
) -> None:
    """Télécharge le fichier, l'écrit sous `docs_dir/<uuid4>.<ext>`, insère
    le `document` correspondant, tente l'OCR (T6b) puis répond « reçu ».

    `deposant` est toujours renseigné (L2-T2) : seul le routeur planifie
    cette tâche de fond, et seulement après avoir vérifié via
    `utilisateur_rattache` que l'expéditeur est un utilisateur actif connu
    (liste blanche, L2-D7) — `deposant_id` n'est donc plus jamais `NULL`
    pour un document créé ici, contrairement au lot 1 (décision D15).

    En cas d'erreur de téléchargement, d'écriture ou d'enregistrement du
    document (Ruling R22, revue finale du lot 1), aucun document n'est
    inséré et aucun fichier partiel ne reste dans `docs_dir` (nettoyage
    explicite à chaque étape) — l'OCR n'est alors jamais appelé, un message
    de supervision part (sans contenu) et l'agent reçoit une réponse
    d'échec dans le groupe BL (`_signaler_echec_traitement`).

    Une fois le document enregistré, le dépôt est acquis : l'OCR est tenté
    (`_executer_ocr`, qui n'échoue jamais vers l'appelant), une ligne de
    supervision part (L2-D8) puis la réponse « reçu » part dans tous les
    cas. Ouvre sa propre session (la session de la requête HTTP est déjà
    fermée quand cette tâche de fond s'exécute).
    """
    try:
        fichier = await messagerie.telecharger(entrant)
    except Exception as exc:
        # Toute erreur de téléchargement est journalisée puis avalée : la
        # tâche de fond n'a personne à qui remonter l'exception.
        _journaliser_echec("téléchargement", entrant.update_id, exc)
        await _signaler_echec_traitement(
            messagerie, telegram_chat_supervision_id, entrant, "téléchargement"
        )
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
        await _signaler_echec_traitement(
            messagerie, telegram_chat_supervision_id, entrant, "écriture"
        )
        return

    try:
        async with sessions() as session:
            document = Document(
                type="bl",
                source="telegram",
                statut="recu",
                fichier_path=str(chemin_final),
                telegram_message_id=entrant.message_id,
                deposant_id=deposant.id,
                photo_compressee=entrant.compresse,
            )
            session.add(document)
            # `flush` (pas seulement `commit`) : peuple `document.id` et
            # `document.numero_interne` (générés côté base, respectivement
            # `gen_random_uuid()` et l'identité `bigint`) pendant que la
            # session est encore active, pour les utiliser juste après —
            # après `commit`, l'attribut est expiré et sa lecture hors
            # session lèverait (accès implicite interdit en async).
            await session.flush()
            document_id = document.id
            numero_interne = document.numero_interne
            await session.commit()
    except Exception as exc:
        # Le fichier est déjà écrit sur disque : il ne doit pas rester seul
        # (sans document associé) si l'enregistrement en base échoue.
        await asyncio.to_thread(_supprimer_si_existe, chemin_final)
        _journaliser_echec("enregistrement document", entrant.update_id, exc)
        await _signaler_echec_traitement(
            messagerie, telegram_chat_supervision_id, entrant, "insertion"
        )
        return

    # Le document est déjà enregistré (`statut="recu"`) : le dépôt est
    # acquis à partir d'ici, y compris si l'OCR échoue complètement
    # (décision du contrôleur T6b). `_executer_ocr` n'échoue jamais vers
    # l'appelant (ses erreurs sont journalisées en interne).
    resultat_ocr = await _executer_ocr(
        sessions,
        document_id,
        fichier.contenu,
        _mime_pour_extension(fichier.extension),
        ocr,
        entrant.update_id,
    )

    await _envoyer_supervision(
        messagerie,
        telegram_chat_supervision_id,
        entrant.update_id,
        _ligne_supervision(
            numero_interne,
            resultat_ocr.numero,
            resultat_ocr.statut,
            deposant.nom_affichage,
        ),
    )

    try:
        # L2-D9 : numéro interne lisible + deux boutons de confirmation
        # (`callback_data` "v:<numero_interne>" / "e:<numero_interne>",
        # décodés par `messaging.telegram.lire_update` en `ClicBouton`, géré
        # par `traiter_clic` ci-dessous).
        await messagerie.repondre(
            entrant.chat_id,
            entrant.message_id,
            f"Reçu — document n° {numero_interne}",
            boutons=[
                (
                    _LIBELLE_QUANTITES_VERIFIEES,
                    f"{PREFIXE_QUANTITES_VERIFIEES}:{numero_interne}",
                ),
                (
                    _LIBELLE_ECART_CONSTATE,
                    f"{PREFIXE_ECART_CONSTATE}:{numero_interne}",
                ),
            ],
        )
    except Exception as exc:
        # Le document est déjà enregistré : on journalise sans revenir en
        # arrière (dédoublonnage déjà acquis, pas de nouvelle tentative).
        _journaliser_echec("réponse", entrant.update_id, exc)


# --------------------------------------------------------------------------
# `traiter_clic` (L2-T3, L2-D10) : clic sur un des deux boutons de
# confirmation d'un dépôt (« Quantités vérifiées » / « Écart constaté »).
#
# Décisions du contrôleur :
# - N'importe quel utilisateur rattaché actif peut cliquer (même liste
#   blanche que `traiter_fichier`, `utilisateur_rattache`) : refus sinon
#   (`accuser_clic("Non autorisé")` + une ligne de supervision, aucune
#   écriture).
# - `numero_interne` sans document correspondant -> `accuser_clic("Document
#   introuvable")`.
# - Le premier clic fait foi : mise à jour conditionnelle atomique
#   (`UPDATE ... WHERE numero_interne = :n AND confirme_le IS NULL
#   RETURNING ...`, une seule instruction SQL) — un second clic (ou deux
#   clics concurrents sur le même document) ne trouve alors aucune ligne à
#   mettre à jour -> `accuser_clic("Déjà enregistré")`, aucune écriture.
# - Une écriture réussie journalise l'action (`quantites_verifiees` /
#   `ecart_constate`), accuse le clic avec le texte de confirmation, puis
#   édite le message du bot (numéro, action, nom du confirmateur, heure de
#   Paris) — l'omission de `reply_markup` dans `editer_message` retire les
#   boutons.
# - Un échec Telegram (accusé ou édition) après l'écriture en base est
#   journalisé, jamais propagé (même politique que `_envoyer_supervision`).
#
# Corrections (tour 1/5) :
# - Un document `statut = "archive"` ne peut plus être confirmé ni passé
#   à `a_verifier` par un clic : `_decider_clic` refuse explicitement
#   (`accuser_clic("Document archivé")`, aucune écriture) dès qu'il constate
#   le statut, et l'UPDATE conditionnel ajoute `statut != "archive"` à son
#   `WHERE` (pour les deux actions) en défense en profondeur.
# - `traiter_clic` accuse **toujours** le clic, même si `_decider_clic` lève
#   une exception inattendue (ex. erreur base non prévue) : sans cela, le
#   bouton Telegram de l'agent reste bloqué en chargement sans aucune trace
#   (constat critique de la revue L2-T3). Seul le type de l'exception est
#   journalisé, jamais son message.
# --------------------------------------------------------------------------


async def _accuser_clic_sans_lever(
    messagerie: Messagerie, clic: ClicBouton, texte: str
) -> None:
    """`accuser_clic` ne doit jamais faire échouer `traiter_clic` (tâche de
    fond, personne à qui remonter l'exception) : un échec est journalisé."""
    try:
        await messagerie.accuser_clic(clic.callback_id, texte)
    except Exception as exc:
        _journaliser_echec("accusé clic", clic.update_id, exc)


@dataclass(frozen=True)
class _DecisionClic:
    """Issue de `_decider_clic` : tout ce dont `traiter_clic` a besoin pour
    parler à Telegram, calculé pendant que la session est encore ouverte
    (même raison que `Deposant` pour `traiter_fichier` : la session de
    base est fermée avant les appels réseau qui suivent, jamais tenue
    ouverte pendant un appel Telegram)."""

    texte_accuse: str
    identifiant_refuse: str | None = None
    texte_edition: str | None = None


async def _decider_clic(session: AsyncSession, clic: ClicBouton) -> _DecisionClic:
    """Toute la logique base de données de `traiter_clic` (L2-D10) : liste
    blanche, existence du document, mise à jour conditionnelle atomique,
    journal. Ne parle jamais à Telegram (fait par l'appelant, une fois la
    session refermée)."""
    deposant = await utilisateur_rattache(session, clic.expediteur_id)
    if deposant is None:
        identifiant = (
            str(clic.expediteur_id) if clic.expediteur_id is not None else "inconnu"
        )
        return _DecisionClic(
            texte_accuse="Non autorisé", identifiant_refuse=identifiant
        )

    ligne_document = (
        await session.execute(
            select(Document.id, Document.statut).where(
                Document.numero_interne == clic.numero_interne
            )
        )
    ).first()
    if ligne_document is None:
        return _DecisionClic(texte_accuse="Document introuvable")
    document_id = ligne_document.id
    statut_avant = ligne_document.statut

    if statut_avant == "archive":
        # Correction (tour 1/5, constat important) : un document archivé ne
        # doit plus pouvoir être confirmé ni repassé « à vérifier ».
        return _DecisionClic(texte_accuse="Document archivé")

    valeurs: dict[str, Any] = {
        "confirme_le": func.now(),
        "confirme_par": deposant.id,
    }
    statut_apres = statut_avant
    if clic.action == PREFIXE_ECART_CONSTATE:
        valeurs["statut"] = "a_verifier"
        statut_apres = "a_verifier"

    resultat = await session.execute(
        update(Document)
        .where(
            Document.numero_interne == clic.numero_interne,
            Document.confirme_le.is_(None),
            # Défense en profondeur (tour 1/5) : le pré-contrôle ci-dessus
            # couvre le cas normal, cette clause couvre un document archivé
            # entre le SELECT et cet UPDATE.
            Document.statut != "archive",
        )
        .values(**valeurs)
        .returning(Document.confirme_le)
    )
    ligne_mise_a_jour = resultat.first()
    if ligne_mise_a_jour is None:
        # Premier clic déjà enregistré (par ce document, éventuellement une
        # transaction concurrente) : la condition `confirme_le IS NULL` de
        # l'UPDATE ci-dessus ne matche plus aucune ligne — atomique côté
        # base, sûr même pour deux clics simultanés (une seule instruction
        # SQL, jamais un SELECT puis un UPDATE séparés).
        return _DecisionClic(texte_accuse="Déjà enregistré")
    confirme_le: datetime = ligne_mise_a_jour.confirme_le

    action_journal = _ACTIONS_JOURNAL[clic.action]
    session.add(
        Journal(
            utilisateur_id=deposant.id,
            action=action_journal,
            cible_table="document",
            cible_id=str(document_id),
            avant={
                "statut": statut_avant,
                "confirme_le": None,
                "confirme_par": None,
            },
            apres={
                "statut": statut_apres,
                "confirme_le": confirme_le.isoformat(),
                "confirme_par": str(deposant.id),
            },
        )
    )
    await session.commit()

    texte_accuse, libelle_action = _TEXTES_CONFIRMATION[clic.action]
    heure = confirme_le.astimezone(_FUSEAU_PARIS).strftime("%H:%M")
    texte_edition = (
        f"Reçu — document n° {clic.numero_interne} · {libelle_action} par "
        f"{deposant.nom_affichage} à {heure}"
    )
    return _DecisionClic(texte_accuse=texte_accuse, texte_edition=texte_edition)


async def traiter_clic(
    clic: ClicBouton,
    messagerie: Messagerie,
    sessions: async_sessionmaker[AsyncSession],
    telegram_chat_supervision_id: int,
) -> None:
    """Traite un clic sur un des deux boutons de confirmation (L2-D10).

    Ouvre sa propre session (même raison que `traiter_fichier` : cette
    tâche de fond s'exécute après la fermeture de la session de la requête
    HTTP). Toute la décision (autorisation, mise à jour atomique, journal)
    est prise dans `_decider_clic`, avant de refermer la session : les
    appels Telegram qui suivent (accusé, éventuelle supervision, édition du
    message) ne tiennent jamais une connexion base ouverte.

    Correction (tour 1/5) : une exception inattendue dans `_decider_clic`
    (bug non prévu, erreur base non couverte par les branches ci-dessus) ne
    doit jamais empêcher `accuser_clic` — sans accusé, le bouton reste
    bloqué en chargement côté Telegram, sans aucune trace pour l'agent.
    Seul le type de l'exception est journalisé, jamais son message.
    """
    try:
        async with sessions() as session:
            decision = await _decider_clic(session, clic)
    except Exception as exc:
        _journaliser_echec("décision clic", clic.update_id, exc)
        decision = _DecisionClic(texte_accuse="Erreur, réessayez")

    await _accuser_clic_sans_lever(messagerie, clic, decision.texte_accuse)

    if decision.identifiant_refuse is not None:
        await _envoyer_supervision(
            messagerie,
            telegram_chat_supervision_id,
            clic.update_id,
            f"Clic non autorisé : id {decision.identifiant_refuse} · "
            f"document n° {clic.numero_interne}",
        )
        return

    if decision.texte_edition is None:
        return

    try:
        await messagerie.editer_message(
            clic.chat_id, clic.message_id, decision.texte_edition
        )
    except Exception as exc:
        _journaliser_echec("édition message clic", clic.update_id, exc)


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


async def _lire_facture_ocr(
    contenu_pdf: bytes,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], Facture]:
    """Appelle l'OCR injecté sur `contenu_pdf` puis `analyser_facture_unikalo`
    sur sa réponse : aide interne partagée par `lire_facture` (T7, CLI
    `bl-non-recus`) et `deposer_facture` (L2-T4, décision du contrôleur), qui
    a en plus besoin de la réponse OCR brute pour `document.ocr_brut` — la
    signature publique de `lire_facture` ne change pas, elle jette juste la
    réponse brute. Ni `ErreurOCR` ni `FactureIllisible` ne sont interceptées
    ici : c'est à chaque appelant de décider quoi en faire (la CLI les
    propage telles quelles ; `deposer_facture` les traduit en erreurs
    typées HTTP)."""
    reponse = await ocr(contenu_pdf, "application/pdf")
    return reponse, analyser_facture_unikalo(reponse)


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
    _reponse, facture = await _lire_facture_ocr(contenu_pdf, ocr)
    return facture


@dataclass(frozen=True)
class BlocReception:
    """Un bloc « Concerne le B.L. » de la facture, avec l'indicateur
    « photo reçue » (livrable visible du lot 1, T7)."""

    numero_bl: str
    date_bl: date | None
    chantier_brut: str | None
    montant_ht: Decimal
    photo_recue: bool


def _normaliser_numero(numero: str) -> str:
    """`strip()` puis majuscules (décision du contrôleur T7, reprise telle
    quelle par L2-T5) : le préfixe `L` est parfois en minuscule sur les OCR,
    aucune autre normalisation (cf. `docs/dette.md`)."""
    return numero.strip().upper()


async def documents_bl_par_numeros(
    session: AsyncSession, numeros: Iterable[str]
) -> dict[str, uuid.UUID]:
    """Correspondance numéro de BL -> `id` du `document` reçu (BL ou
    enlèvement), factorisée pour être partagée par `blocs_avec_reception`
    (CLI `bl-non-recus`, T7) et `facture_detail`/`lister_factures` (L2-T5).

    Clé = numéro normalisé (`_normaliser_numero`, décision du contrôleur
    T7/L2-T5). Ne considère que les documents de type `bl`/`enlevement`, de
    statut différent de `archive` (L2-D12 : la correspondance est calculée à
    la lecture, jamais persistée dans `bloc_facture.bl_document_id`). En cas
    de plusieurs documents pour un même numéro normalisé (décision du
    contrôleur L2-T5), le plus ancien (`created_at` croissant) fait foi.

    Une seule requête, filtrée en SQL sur les numéros normalisés
    (`upper(trim(...))`) plutôt qu'en récupérant tous les documents reçus de
    l'application : reste correct même si le nombre de BL/enlèvements
    déposés grossit avec le temps. `numeros` vide -> aucune requête, `{}`.
    """
    normalises = {_normaliser_numero(numero) for numero in numeros if numero}
    if not normalises:
        return {}

    resultat = await session.execute(
        select(Document.numero, Document.id)
        .where(
            Document.type.in_(("bl", "enlevement")),
            Document.statut != "archive",
            Document.numero.is_not(None),
            func.upper(func.trim(Document.numero)).in_(normalises),
        )
        .order_by(Document.created_at.asc())
    )
    documents_par_numero: dict[str, uuid.UUID] = {}
    for numero, document_id in resultat.all():
        cle = _normaliser_numero(numero)
        # Premier vu (le plus ancien, grâce à l'`ORDER BY` ci-dessus) fait
        # foi : ne jamais écraser par un document plus récent du même numéro.
        documents_par_numero.setdefault(cle, document_id)
    return documents_par_numero


async def blocs_avec_reception(
    session: AsyncSession, facture: Facture
) -> list[BlocReception]:
    """Une `BlocReception` par bloc de `facture`, dans l'ordre de la facture.

    « Photo reçue » (décisions du contrôleur T7, refactor L2-T5 sans
    changement de comportement) : correspondance factorisée dans
    `documents_bl_par_numeros` ci-dessus, réutilisée telle quelle."""
    documents_par_numero = await documents_bl_par_numeros(
        session, (bloc.numero_bl for bloc in facture.blocs)
    )

    return [
        BlocReception(
            numero_bl=bloc.numero_bl,
            date_bl=bloc.date_bl,
            chantier_brut=bloc.chantier_brut,
            montant_ht=bloc.montant_ht,
            photo_recue=_normaliser_numero(bloc.numero_bl) in documents_par_numero,
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


# --------------------------------------------------------------------------
# `deposer_facture` (L2-T4) : dépôt d'une facture PDF Unikalo via
# `POST /api/factures` (traité dans la requête, synchrone, L2-D11).
#
# Décisions du contrôleur :
# - Ordre : signature `%PDF-` (sinon `FichierInvalide`) -> OCR injecté
#   (`ErreurOCR` -> `LectureImpossible`) -> `analyser_facture_unikalo`
#   (`FactureIllisible` -> `FormatNonPrisEnCharge`) -> fournisseur
#   « Unikalo » get-or-create (normalisation SIRET/TVA réservée au lot 3,
#   un seul fournisseur nommé exactement « Unikalo » fait foi pour
#   l'instant) -> doublon `(fournisseur_id, numero)` parmi les documents de
#   type `facture` (`FactureEnDouble(original_id)`) -> écriture atomique du
#   fichier (`<uuid>.pdf`, réutilise `_ecrire_atomique`/`_supprimer_si_existe`
#   ci-dessus) -> insertions (`document`, `bloc_facture`, `ligne`, `journal`)
#   dans une seule transaction.
# - En cas d'échec d'insertion (y compris une `IntegrityError` d'unicité :
#   course entre deux dépôts concurrents du même fournisseur/numéro, la
#   vérification applicative ci-dessus n'étant pas atomique), le fichier
#   déjà écrit est supprimé et la transaction est annulée. Une
#   `IntegrityError` est retraduite en `FactureEnDouble` (409 aussi) en
#   requêtant à nouveau l'original après le `rollback`.
# - `commentaire` d'un `bloc_facture` : lignes `COMMENTAIRE` du bloc jointes
#   par `\n`, `NULL` s'il n'y en a aucune.
# - `ligne` : mapping direct des champs de `LigneFacture` (designation ->
#   `article_brut`, code_article -> `code_brut`, unite -> `unite_brut`,
#   `type_ligne.value`, `ordre` inchangé).
#
# Correction (revue L2-T4, Ruling L2-R5, constat mineur) :
# - L'écriture disque (`_ecrire_atomique`) est protégée comme dans
#   `traiter_fichier` : un `OSError` (ex. disque plein) nettoie le fichier
#   temporaire déjà écrit et est retraduit en `EcritureImpossible`, jamais
#   laissé remonter brut (le routeur la traduit en 500 neutre).
#
# Hors périmètre du lot 2 (Ruling L2-R5, décision du contrôleur, voir
# `docs/dette.md`) :
# - `confiance_min` n'est jamais renseignée pour une facture lue par OCR
#   (score de confiance par champ défini au lot 3 Extraction, CDC §4.2).
# - Un avoir Unikalo (CDC §4.2 « facture ou d'avoir ») serait aujourd'hui
#   typé `facture` comme n'importe quel dépôt (aucun exemple disponible pour
#   distinguer les deux formats) — question posée à Ilane
#   (`docs/plan-lot-2.md` §3, Q5).
# --------------------------------------------------------------------------

_SIGNATURE_PDF = b"%PDF-"
_NOM_FOURNISSEUR_UNIKALO = "Unikalo"


class FichierInvalide(Exception):
    """Le contenu envoyé n'a pas la signature d'un PDF (`%PDF-`)."""


class LectureImpossible(Exception):
    """Échec de l'appel OCR pour lire la facture (`ErreurOCR`)."""


class FormatNonPrisEnCharge(Exception):
    """La réponse OCR n'a pas la structure d'une facture Unikalo reconnue
    (`FactureIllisible`)."""


class EcritureImpossible(Exception):
    """Échec de l'écriture du fichier sur disque (`OSError`, ex. disque
    plein) — le fichier temporaire éventuellement écrit est nettoyé avant
    que cette exception ne soit levée."""


class FactureEnDouble(Exception):
    """Une facture du même fournisseur avec le même numéro est déjà déposée."""

    def __init__(self, original_id: uuid.UUID) -> None:
        super().__init__("facture déjà déposée")
        self.original_id = original_id


@dataclass(frozen=True)
class FactureDeposee:
    """Résultat d'un dépôt réussi, tout ce dont le routeur a besoin pour sa
    réponse 201 (`{"id", "numero", "nb_blocs"}`)."""

    id: uuid.UUID
    numero: str
    nb_blocs: int


async def _fournisseur_unikalo(session: AsyncSession) -> Fournisseur:
    """Fournisseur « Unikalo », créé s'il n'existe pas encore (décision du
    contrôleur : la normalisation SIRET/TVA n'arrive qu'au lot 3, un seul
    fournisseur nommé exactement « Unikalo » fait foi pour l'instant)."""
    resultat = await session.execute(
        select(Fournisseur).where(Fournisseur.nom == _NOM_FOURNISSEUR_UNIKALO)
    )
    fournisseur = resultat.scalar_one_or_none()
    if fournisseur is not None:
        return fournisseur
    fournisseur = Fournisseur(nom=_NOM_FOURNISSEUR_UNIKALO)
    session.add(fournisseur)
    await session.flush()
    return fournisseur


async def _facture_en_double(
    session: AsyncSession, fournisseur_id: uuid.UUID, numero: str
) -> uuid.UUID | None:
    """`id` du document `facture` existant pour ce fournisseur et ce numéro,
    `None` si aucun. Un seul point de vérité, réutilisé aussi pour retrouver
    l'original après une `IntegrityError` d'unicité (course entre deux
    dépôts)."""
    resultat = await session.execute(
        select(Document.id).where(
            Document.type == "facture",
            Document.fournisseur_id == fournisseur_id,
            Document.numero == numero,
        )
    )
    return resultat.scalar_one_or_none()


def _commentaire_bloc(bloc: BlocBL) -> str | None:
    commentaires = bloc.commentaires
    return "\n".join(commentaires) if commentaires else None


async def deposer_facture(
    session: AsyncSession,
    contenu: bytes,
    deposant: Deposant,
    docs_dir: Path,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
) -> FactureDeposee:
    """Dépose une facture PDF Unikalo : lecture, fournisseur, doublon,
    stockage et insertions dans une seule transaction (L2-T4).

    Lève `FichierInvalide` (pas un PDF), `LectureImpossible` (échec de
    l'OCR), `FormatNonPrisEnCharge` (facture non reconnue comme Unikalo),
    `EcritureImpossible` (échec de l'écriture disque) ou
    `FactureEnDouble(original_id)` (même fournisseur, même numéro, déjà
    déposé) — le routeur (`app/modules/api/factures.py`) traduit chacune en
    code HTTP. Aucun fichier n'est stocké et rien n'est inséré en base tant
    que la facture n'est pas entièrement lue et validée.
    """
    if contenu[: len(_SIGNATURE_PDF)] != _SIGNATURE_PDF:
        raise FichierInvalide("Le fichier n'est pas un PDF.")

    try:
        reponse_ocr, facture = await _lire_facture_ocr(contenu, ocr)
    except ErreurOCR as exc:
        raise LectureImpossible("Lecture de la facture impossible, réessayez.") from exc
    except FactureIllisible as exc:
        raise FormatNonPrisEnCharge(
            "Format de facture non pris en charge "
            "(seules les factures Unikalo sont reconnues)."
        ) from exc

    fournisseur = await _fournisseur_unikalo(session)
    # Capturé tout de suite : un `rollback()` plus bas expirerait cet objet
    # (inconditionnellement, indépendamment d'`expire_on_commit`) — relire
    # `fournisseur.id` après coup lèverait `MissingGreenlet` (accès implicite
    # hors contexte async). Même prudence que `traiter_fichier` ci-dessus
    # pour `document.id`/`numero_interne`, capturés avant tout risque de
    # rollback.
    fournisseur_id = fournisseur.id

    original_id = await _facture_en_double(session, fournisseur_id, facture.numero)
    if original_id is not None:
        raise FactureEnDouble(original_id)

    identifiant = uuid.uuid4()
    chemin_final = (docs_dir / f"{identifiant}.pdf").absolute()
    chemin_temporaire = (docs_dir / f"{identifiant}.pdf.tmp").absolute()
    try:
        await asyncio.to_thread(
            _ecrire_atomique, docs_dir, chemin_temporaire, chemin_final, contenu
        )
    except OSError as exc:
        # Correction (Ruling L2-R5, constat mineur) : même protection que
        # `traiter_fichier` — le `.tmp` éventuellement écrit ne doit jamais
        # rester orphelin, et l'`OSError` brute (chemins disque) ne doit
        # jamais remonter telle quelle jusqu'au routeur.
        await asyncio.to_thread(_supprimer_si_existe, chemin_temporaire)
        raise EcritureImpossible("Enregistrement impossible, réessayez.") from exc

    try:
        document = Document(
            type="facture",
            source="upload",
            statut="recu",
            fichier_path=str(chemin_final),
            fournisseur_id=fournisseur_id,
            numero=facture.numero,
            date_doc=facture.date_facture,
            total_ht=facture.total_ht,
            deposant_id=deposant.id,
            ocr_brut=reponse_ocr,
        )
        session.add(document)
        await session.flush()
        document_id = document.id

        for position, bloc in enumerate(facture.blocs):
            bloc_facture = BlocFacture(
                facture_id=document_id,
                # Position sur la facture (constat T5, voir le commentaire de
                # `BlocFacture.ordre` dans `ingest/models.py`) : `created_at`
                # ne peut pas en tenir lieu, tous les blocs d'une même
                # facture étant insérés dans la même transaction.
                ordre=position,
                numero_bl=bloc.numero_bl,
                date_bl=bloc.date_bl,
                numero_commande=bloc.numero_commande,
                chantier_brut=bloc.chantier_brut,
                commentaire=_commentaire_bloc(bloc),
            )
            session.add(bloc_facture)
            await session.flush()
            bloc_id = bloc_facture.id

            for ligne in bloc.lignes:
                session.add(
                    Ligne(
                        document_id=document_id,
                        bloc_id=bloc_id,
                        article_brut=ligne.designation,
                        code_brut=ligne.code_article,
                        unite_brut=ligne.unite,
                        qte_livree=ligne.qte_livree,
                        qte_totale=ligne.qte_totale,
                        pu_ht=ligne.pu_ht,
                        pu_cdt=ligne.pu_cdt,
                        remise_pct=ligne.remise_pct,
                        montant_ht=ligne.montant_ht,
                        tva=ligne.tva,
                        type_ligne=ligne.type_ligne.value,
                        ordre=ligne.ordre,
                    )
                )

        session.add(
            Journal(
                utilisateur_id=deposant.id,
                action="facture_deposee",
                cible_table="document",
                cible_id=str(document_id),
                avant=None,
                apres={
                    "numero": facture.numero,
                    "fournisseur_id": str(fournisseur_id),
                    "total_ht": str(facture.total_ht),
                    "nb_blocs": len(facture.blocs),
                },
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        await asyncio.to_thread(_supprimer_si_existe, chemin_final)
        original_id_apres_course = await _facture_en_double(
            session, fournisseur_id, facture.numero
        )
        if original_id_apres_course is None:
            raise
        raise FactureEnDouble(original_id_apres_course) from None
    except Exception:
        await session.rollback()
        await asyncio.to_thread(_supprimer_si_existe, chemin_final)
        raise

    return FactureDeposee(
        id=document_id, numero=facture.numero, nb_blocs=len(facture.blocs)
    )


# --------------------------------------------------------------------------
# L2-T5 — `api/factures.py` et `api/documents.py` (lecture seule) : toute la
# requête SQL et toute règle (droits, correspondance BL) vivent ici, jamais
# dans les routeurs (décision du contrôleur) — les routeurs ne font que
# traduire les exceptions ci-dessous en codes HTTP.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FactureResume:
    """Une ligne de `GET /api/factures` (L2-T5)."""

    id: uuid.UUID
    numero: str
    fournisseur: str
    date_doc: date | None
    total_ht: Decimal | None
    nb_blocs: int
    nb_blocs_recus: int
    cree_le: datetime


async def lister_factures(session: AsyncSession) -> list[FactureResume]:
    """Liste des factures, triée par `date_doc` puis `created_at`
    décroissants (décision du contrôleur L2-T5).

    `nb_blocs`/`nb_blocs_recus` sans N+1 : trois requêtes au total, quel que
    soit le nombre de factures ou de blocs — une pour les factures (jointure
    fournisseur), une pour tous leurs blocs, une pour la correspondance BL
    (`documents_bl_par_numeros`, elle-même une seule requête).
    """
    resultat_factures = await session.execute(
        select(Document, Fournisseur.nom)
        .join(Fournisseur, Fournisseur.id == Document.fournisseur_id)
        .where(Document.type == "facture")
        .order_by(Document.date_doc.desc(), Document.created_at.desc())
    )
    lignes_factures = resultat_factures.all()
    if not lignes_factures:
        return []

    facture_ids = [document.id for document, _nom in lignes_factures]
    resultat_blocs = await session.execute(
        select(BlocFacture.facture_id, BlocFacture.numero_bl).where(
            BlocFacture.facture_id.in_(facture_ids)
        )
    )
    numeros_par_facture: dict[uuid.UUID, list[str | None]] = defaultdict(list)
    for facture_id, numero_bl in resultat_blocs.all():
        numeros_par_facture[facture_id].append(numero_bl)

    tous_numeros = (
        numero_bl
        for numeros in numeros_par_facture.values()
        for numero_bl in numeros
        if numero_bl is not None
    )
    documents_par_numero = await documents_bl_par_numeros(session, tous_numeros)

    resumes: list[FactureResume] = []
    for document, nom_fournisseur in lignes_factures:
        numeros_bloc = numeros_par_facture.get(document.id, [])
        nb_blocs_recus = sum(
            1
            for numero_bl in numeros_bloc
            if numero_bl is not None
            and _normaliser_numero(numero_bl) in documents_par_numero
        )
        resumes.append(
            FactureResume(
                id=document.id,
                numero=document.numero or "",
                fournisseur=nom_fournisseur,
                date_doc=document.date_doc,
                total_ht=document.total_ht,
                nb_blocs=len(numeros_bloc),
                nb_blocs_recus=nb_blocs_recus,
                cree_le=document.created_at,
            )
        )
    return resumes


class FactureIntrouvable(Exception):
    """Aucun document de type `facture` avec cet identifiant."""


@dataclass(frozen=True)
class LigneFactureLue:
    """Une ligne d'un bloc, telle que lue en base (`GET /api/factures/{id}`)."""

    ordre: int
    type_ligne: str
    code_brut: str | None
    article_brut: str | None
    qte_livree: Decimal | None
    qte_totale: Decimal | None
    pu_ht: Decimal | None
    pu_cdt: Decimal | None
    remise_pct: Decimal | None
    montant_ht: Decimal | None
    tva: Decimal | None


@dataclass(frozen=True)
class BlocFactureLu:
    """Un bloc, avec ses lignes et son indicateur « BL reçu » calculé à la
    lecture (L2-D12, jamais persisté dans `bl_document_id`)."""

    id: uuid.UUID
    numero_bl: str | None
    date_bl: date | None
    numero_commande: str | None
    chantier_brut: str | None
    commentaire: str | None
    montant_ht: Decimal
    bl_recu: bool
    bl_document_id: uuid.UUID | None
    lignes: list[LigneFactureLue]


@dataclass(frozen=True)
class FactureDetail:
    """En-tête et blocs d'une facture (`GET /api/factures/{id}`, L2-T5)."""

    id: uuid.UUID
    numero: str
    fournisseur: str
    date_doc: date | None
    total_ht: Decimal | None
    cree_le: datetime
    deposant: str | None
    blocs: list[BlocFactureLu]


async def facture_detail(session: AsyncSession, facture_id: uuid.UUID) -> FactureDetail:
    """En-tête puis blocs (avec leurs lignes) d'une facture, blocs et lignes
    dans l'ordre (`BlocFacture.ordre`, `Ligne.ordre` — jamais `created_at`,
    identique pour toutes les lignes d'une même facture insérées dans la
    même transaction par `deposer_facture`, voir le commentaire de
    `BlocFacture.ordre` dans `ingest/models.py`). `montant_ht` de chaque bloc
    recalculé comme la somme des montants non nuls de ses lignes (décision du
    contrôleur L2-T5 : jamais une colonne stockée, toujours à jour).

    Lève `FactureIntrouvable` si `facture_id` est absent ou si le document
    n'est pas de type `facture` (décision du contrôleur : même 404 dans les
    deux cas, pour ne jamais distinguer un id inexistant d'un BL/enlèvement
    existant). Quatre requêtes au total (en-tête, blocs, lignes,
    correspondance BL), jamais une par bloc ni par ligne.
    """
    deposant_alias = aliased(Utilisateur)
    ligne_entete = (
        await session.execute(
            select(
                Document,
                Fournisseur.nom,
                func.coalesce(deposant_alias.nom, deposant_alias.email),
            )
            .join(Fournisseur, Fournisseur.id == Document.fournisseur_id)
            .outerjoin(deposant_alias, deposant_alias.id == Document.deposant_id)
            .where(Document.id == facture_id, Document.type == "facture")
        )
    ).first()
    if ligne_entete is None:
        raise FactureIntrouvable(str(facture_id))
    document, nom_fournisseur, nom_deposant = ligne_entete

    blocs_db = (
        (
            await session.execute(
                select(BlocFacture)
                .where(BlocFacture.facture_id == facture_id)
                .order_by(BlocFacture.ordre.asc())
            )
        )
        .scalars()
        .all()
    )

    lignes_db = (
        (
            await session.execute(
                select(Ligne)
                .where(Ligne.document_id == facture_id)
                .order_by(Ligne.ordre.asc())
            )
        )
        .scalars()
        .all()
    )
    lignes_par_bloc: dict[uuid.UUID, list[Ligne]] = defaultdict(list)
    for ligne in lignes_db:
        if ligne.bloc_id is not None:
            lignes_par_bloc[ligne.bloc_id].append(ligne)

    documents_par_numero = await documents_bl_par_numeros(
        session, (bloc.numero_bl for bloc in blocs_db if bloc.numero_bl is not None)
    )

    blocs: list[BlocFactureLu] = []
    for bloc in blocs_db:
        bl_document_id = (
            documents_par_numero.get(_normaliser_numero(bloc.numero_bl))
            if bloc.numero_bl is not None
            else None
        )
        blocs.append(
            BlocFactureLu(
                id=bloc.id,
                numero_bl=bloc.numero_bl,
                date_bl=bloc.date_bl,
                numero_commande=bloc.numero_commande,
                chantier_brut=bloc.chantier_brut,
                commentaire=bloc.commentaire,
                montant_ht=sum(
                    (
                        ligne.montant_ht
                        for ligne in lignes_par_bloc.get(bloc.id, [])
                        if ligne.montant_ht is not None
                    ),
                    Decimal("0"),
                ),
                bl_recu=bl_document_id is not None,
                bl_document_id=bl_document_id,
                lignes=[
                    LigneFactureLue(
                        ordre=ligne.ordre,
                        type_ligne=ligne.type_ligne,
                        code_brut=ligne.code_brut,
                        article_brut=ligne.article_brut,
                        qte_livree=ligne.qte_livree,
                        qte_totale=ligne.qte_totale,
                        pu_ht=ligne.pu_ht,
                        pu_cdt=ligne.pu_cdt,
                        remise_pct=ligne.remise_pct,
                        montant_ht=ligne.montant_ht,
                        tva=ligne.tva,
                    )
                    for ligne in lignes_par_bloc.get(bloc.id, [])
                ],
            )
        )

    return FactureDetail(
        id=document.id,
        numero=document.numero or "",
        fournisseur=nom_fournisseur,
        date_doc=document.date_doc,
        total_ht=document.total_ht,
        cree_le=document.created_at,
        deposant=nom_deposant,
        blocs=blocs,
    )


@dataclass(frozen=True)
class DocumentResume:
    """Une ligne de `GET /api/documents` (L2-T5)."""

    id: uuid.UUID
    numero_interne: int
    type: str
    numero: str | None
    statut: str
    deposant: str | None
    cree_le: datetime
    confirme_le: datetime | None
    confirme_par: str | None
    photo_compressee: bool | None


LIMITE_DOCUMENTS_MIN = 1
LIMITE_DOCUMENTS_MAX = 500
LIMITE_DOCUMENTS_DEFAUT = 100


async def lister_documents(
    session: AsyncSession,
    *,
    utilisateur_id: uuid.UUID,
    role: str,
    depuis: datetime | None = None,
    limite: int = LIMITE_DOCUMENTS_DEFAUT,
) -> list[DocumentResume]:
    """BL et enlèvements visibles par l'appelant — droit vérifié ici, jamais
    dans le routeur (décision du contrôleur L2-T5) : un admin voit tous les
    documents `bl`/`enlevement` non archivés, un agent seulement ceux qu'il a
    déposés. Triés par `created_at` décroissant ; `depuis` filtre sur
    `created_at >= depuis` (borne incluse) ; `limite` borne le nombre de
    lignes (validée par le routeur, `1..500`). Une seule requête (jointures
    sur le déposant et le confirmateur), jamais de N+1.
    """
    deposant_alias = aliased(Utilisateur)
    confirmateur_alias = aliased(Utilisateur)

    conditions = [
        Document.type.in_(("bl", "enlevement")),
        Document.statut != "archive",
    ]
    if role != "admin":
        conditions.append(Document.deposant_id == utilisateur_id)
    if depuis is not None:
        conditions.append(Document.created_at >= depuis)

    resultat = await session.execute(
        select(
            Document,
            func.coalesce(deposant_alias.nom, deposant_alias.email),
            func.coalesce(confirmateur_alias.nom, confirmateur_alias.email),
        )
        .outerjoin(deposant_alias, deposant_alias.id == Document.deposant_id)
        .outerjoin(confirmateur_alias, confirmateur_alias.id == Document.confirme_par)
        .where(*conditions)
        .order_by(Document.created_at.desc())
        .limit(limite)
    )
    return [
        DocumentResume(
            id=document.id,
            numero_interne=document.numero_interne,
            type=document.type,
            numero=document.numero,
            statut=document.statut,
            deposant=nom_deposant,
            cree_le=document.created_at,
            confirme_le=document.confirme_le,
            confirme_par=nom_confirmateur,
            photo_compressee=document.photo_compressee,
        )
        for document, nom_deposant, nom_confirmateur in resultat.all()
    ]


class DocumentIntrouvable(Exception):
    """Document absent, non autorisé pour l'appelant, ou fichier inaccessible
    (chemin hors `docs_dir`, ou absent du disque) — toujours le même 404
    côté routeur, pour ne jamais distinguer ces cas (décision du contrôleur
    L2-T5)."""


@dataclass(frozen=True)
class FichierDocument:
    """Chemin (résolu, garanti à l'intérieur de `docs_dir`) et type MIME d'un
    fichier de document, prêt pour `fastapi.responses.FileResponse`."""

    chemin: Path
    type_mime: str


def _chemin_dans_docs_dir(document: Document, docs_dir: Path) -> Path | None:
    """`None` si le chemin enregistré (`document.fichier_path`) ne résout pas
    à l'intérieur de `docs_dir` (défense en profondeur, décision du
    contrôleur L2-T5 : jamais un chemin arbitraire servi) ou si le fichier
    n'existe plus sur disque. Jamais d'exception : l'appelant traduit `None`
    en `DocumentIntrouvable`, sans jamais journaliser le chemin lui-même."""
    chemin = Path(document.fichier_path).resolve()
    racine = docs_dir.resolve()
    if not chemin.is_relative_to(racine):
        return None
    if not chemin.is_file():
        return None
    return chemin


def _fichier_ou_404(document: Document, docs_dir: Path) -> FichierDocument:
    chemin = _chemin_dans_docs_dir(document, docs_dir)
    if chemin is None:
        # Décision du contrôleur : jamais le chemin en clair dans le journal.
        logger.error(
            "fichier inaccessible pour document %s (hors docs_dir ou absent du disque)",
            document.id,
        )
        raise DocumentIntrouvable(str(document.id))
    return FichierDocument(
        chemin=chemin,
        type_mime=_mime_pour_extension(chemin.suffix.lstrip(".").lower()),
    )


async def fichier_facture(
    session: AsyncSession, facture_id: uuid.UUID, docs_dir: Path
) -> FichierDocument:
    """Fichier PDF d'une facture (admin uniquement, vérifié par le routeur
    via `admin_requis`). Lève `DocumentIntrouvable` si absente, si le
    document n'est pas de type `facture`, ou si son chemin ne résout pas à
    l'intérieur de `docs_dir`."""
    document = await session.get(Document, facture_id)
    if document is None or document.type != "facture":
        raise DocumentIntrouvable(str(facture_id))
    return _fichier_ou_404(document, docs_dir)


async def fichier_document(
    session: AsyncSession,
    document_id: uuid.UUID,
    docs_dir: Path,
    *,
    utilisateur_id: uuid.UUID,
    role: str,
) -> FichierDocument:
    """Fichier d'un document (droit vérifié ici, décision du contrôleur
    L2-T5) : un admin peut télécharger n'importe quel document, un agent
    seulement ceux qu'il a déposés. Lève `DocumentIntrouvable` (404) dans
    tous les autres cas — absent, déposé par un autre agent, ou chemin hors
    `docs_dir` — sans jamais distinguer ces cas dans la réponse."""
    document = await session.get(Document, document_id)
    if document is None:
        raise DocumentIntrouvable(str(document_id))
    if role != "admin" and document.deposant_id != utilisateur_id:
        raise DocumentIntrouvable(str(document_id))
    return _fichier_ou_404(document, docs_dir)
