"""Dépôt Telegram (`POST /tg/webhook`) : dédoublonnage, liste blanche,
téléchargement et enregistrement d'un fichier déposé, OCR et extraction
complète du BL (`ingest/extraction_bl.py`, L3-T6), notifications de
supervision, et traitement des clics sur les boutons de confirmation.

Sous-module de `ingest` (D10) : `ingest` est le seul module métier autorisé
à importer un autre module métier (`messaging`, `extract`), garde vérifiée
par `tests/test_frontieres.py`. Nommé `depot_telegram` (et non `telegram`)
pour ne pas entrer en conflit, à la lecture, avec
`app/modules/messaging/telegram.py` — décision de la tâche de découpage
(vague finale du lot 2, point 1 : simple déplacement de code depuis
`ingest/service.py`, aucun changement de comportement ; l'écriture
atomique, la journalisation d'échec et le mapping MIME partagés avec
`ingest/factures.py`/`ingest/lecture.py` vivent désormais dans
`ingest/commun.py`).

Responsabilités :
- `enregistrer_update` (T6) : dédoublonnage des webhooks Telegram
  (`INSERT ... ON CONFLICT DO NOTHING` sur la clé primaire `update_id` de
  `telegram_update` — atomique côté base, donc sûr même si deux requêtes
  concurrentes portent le même `update_id`) ;
- `utilisateur_rattache` (L2-T2) : liste blanche (L2-D7) — résout
  `telegram_user_id` en `Deposant` (`ingest/commun.py`, utilisateur actif
  rattaché), `None` sinon ;
- `signaler_expediteur_inconnu` (L2-T2) : notifie le groupe de supervision
  qu'un expéditeur non rattaché a tenté un dépôt (L2-D7), sans rien écrire
  ni télécharger ;
- `traiter_fichier` (T6, complété T6b puis L3-T6, L2-T2, puis Task 9) :
  téléchargement, écriture atomique sur disque, enregistrement du `document`
  (décisions du contrôleur T6), OCR puis extraction complète du BL déléguée
  à `ingest/extraction_bl.py` (`_executer_ocr`, décisions du contrôleur T6b
  et L3-T6 ci-dessous), lien physique posé sur le serveur
  (`ingest/rangement.py`, spec §5, `_ranger_photo_sans_lever`), puis ligne
  de supervision (remplace L2-D8) et notification d'échec à l'agent (Ruling
  R22, ci-dessous) ;
- `traiter_clic` (L2-T3, L2-D10) : clic sur un des deux boutons de
  confirmation (« Quantités vérifiées » / « Écart constaté »).

Décisions du contrôleur T6b sur `traiter_fichier` :
- Le document est déjà enregistré (`statut="recu"`) avant l'appel OCR : le
  dépôt est acquis quoi qu'il arrive, y compris si l'OCR échoue.
- L'OCR est appelé via une fonction injectée (`ocr`), plutôt qu'un appel
  direct à `app.modules.ingest.mistral.ocr_document` : ce module n'a donc
  besoin ni de `httpx` ni de la clé API, et les tests substituent un faux
  OCR sans construire de client HTTP (production : le routeur construit
  cette fonction à partir du client HTTP du lifespan et de
  `Settings.mistral_api_key`, voir `ingest/router.py`).
- La réponse « reçu » part après la tentative d'OCR, dans tous les cas
  (extraction complète, annotation illisible, ou échec complet de l'OCR,
  L3-D10 : ce dernier cas ne laisse plus jamais le document `recu` sans
  extraction, contrairement au lot 2).

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

Audit rapidité et sécurité (T9, 25/09/2026, constat CRITIQUE) — signature du
fichier reçu vérifiée avant tout traitement :
- `messagerie.telecharger` déduit `FichierTelecharge.extension` du type MIME
  *déclaré* par le client Telegram (`messaging.telegram
  ._fichier_depuis_document`) ou, pour une photo compressée, du chemin
  renvoyé par `getFile` — jamais confronté au contenu réel jusqu'ici, alors
  que le dépôt de facture (`factures.deposer_facture`) vérifie déjà
  `%PDF-`.
- `ingest.commun.signature_conforme(fichier.extension, fichier.contenu)` est
  appelée juste après le téléchargement, avant toute écriture disque et
  avant tout appel OCR : une signature non conforme suit exactement le
  chemin d'échec d'un échec de téléchargement (journalisation sans donnée
  client, message de supervision, réponse d'échec à l'agent) — rien n'est
  jamais écrit sur disque ni transmis à Mistral pour un fichier dont le
  contenu ne correspond pas à l'extension annoncée.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.commun import (
    Deposant,
    _ecrire_atomique,
    _journaliser_echec,
    _mime_pour_extension,
    _supprimer_si_existe,
    signature_conforme,
)
from app.modules.ingest.extraction_bl import (
    enregistrer_echec_ocr,
    enregistrer_extraction_bl,
)
from app.modules.ingest.models import Document, Journal, TelegramUpdate, Utilisateur
from app.modules.ingest.rangement import ranger_document
from app.modules.messaging.base import (
    PREFIXE_ECART_CONSTATE,
    PREFIXE_QUANTITES_VERIFIEES,
    ClicBouton,
    FichierEntrant,
    Messagerie,
)

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
    numero_interne: int,
    numero_bl: str | None,
    fournisseur_nom: str | None,
    chantier_brut: str | None,
    statut: str,
    deposant_nom: str,
) -> str:
    """Format T6 (remplace L2-D8) : `Document n° <interne> · BL <n° détecté
    ou « non détecté »> · fournisseur <nom du référentiel ou « — »> ·
    chantier <chantier brut ou « — »> · <déposant> · <HH:MM> · <statut>`.
    `fournisseur_nom` est toujours le nom du référentiel (jamais le brut lu,
    décision du contrôleur) ; `chantier_brut`, lui, est le libellé tel
    qu'imprimé (aucun référentiel de libellé canonique avant résolution d'un
    alias). Heure de Paris (décision du contrôleur), calculée au moment de
    l'envoi (après la tentative d'OCR, donc après le traitement complet du
    dépôt)."""
    heure = datetime.now(FUSEAU_PARIS).strftime("%H:%M")
    bl = numero_bl if numero_bl is not None else _BL_NON_DETECTE
    fournisseur = fournisseur_nom if fournisseur_nom is not None else "—"
    chantier = chantier_brut if chantier_brut is not None else "—"
    return (
        f"Document n° {numero_interne} · BL {bl} · fournisseur {fournisseur} · "
        f"chantier {chantier} · {deposant_nom} · {heure} · {statut}"
    )


@dataclass(frozen=True)
class _ResultatOcr:
    """État final du document après la tentative d'OCR de `_executer_ocr`,
    quelle que soit l'issue (extraction complète, annotation illisible, ou
    échec complet de l'OCR) — utilisé pour la ligne de supervision (T6) sans
    relire le document en base une troisième fois."""

    numero: str | None
    statut: str
    fournisseur_nom: str | None
    chantier_brut: str | None


async def _enregistrer_echec_ocr_sans_lever(
    sessions: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
    update_id: int,
) -> _ResultatOcr:
    """`enregistrer_echec_ocr` dans une session neuve (décision du
    contrôleur, Ruling R5) : seule une exception de cette fonction elle-même
    (base injoignable) est journalisée et avalée ici, avec le résultat
    `numero=None, statut="recu"` comme avant T6 — rien d'autre à faire."""
    try:
        async with sessions() as session:
            resultat = await enregistrer_echec_ocr(session, document_id)
        return _ResultatOcr(
            numero=resultat.numero,
            statut=resultat.statut,
            fournisseur_nom=resultat.fournisseur_nom,
            chantier_brut=resultat.chantier_brut,
        )
    except Exception as exc:
        _journaliser_echec("échec ocr", update_id, exc)
        return _ResultatOcr(
            numero=None, statut="recu", fournisseur_nom=None, chantier_brut=None
        )


async def _executer_ocr(
    sessions: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
    contenu: bytes,
    mime: str,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
    update_id: int,
) -> _ResultatOcr:
    """Appelle l'OCR injecté puis délègue à `ingest/extraction_bl.py` dans
    une seconde transaction (décisions du contrôleur T6, complète T6b) :
    - échec de l'appel OCR lui-même, ou réponse structurellement
      inexploitable (pas un objet JSON avec une liste `pages`) ->
      `enregistrer_echec_ocr` dans une session neuve (L3-D10 : le document
      part `a_verifier` avec le motif `ocr_echec`, plus jamais laissé `recu`
      sans extraction) ;
    - sinon `enregistrer_extraction_bl` (lecture complète du BL, résolution
      des référentiels, persistance) ; une exception inattendue de cette
      fonction (donnée OCR corrompue imprévue) est journalisée
      (`_journaliser_echec`, sans contenu) puis déclenche elle aussi
      `enregistrer_echec_ocr` dans une session neuve (Ruling R5 : aucun
      document ne reste `recu` sans extraction).

    Le contrat « `_executer_ocr` n'échoue jamais vers l'appelant » est
    conservé : toute exception est journalisée et avalée ici.
    """
    try:
        reponse = await ocr(contenu, mime)
    except Exception as exc:
        _journaliser_echec("ocr", update_id, exc)
        return await _enregistrer_echec_ocr_sans_lever(sessions, document_id, update_id)

    # Réponse structurellement inexploitable (pas un `dict` avec une liste
    # `pages`) : traitée comme un échec d'OCR, jamais transmise telle quelle
    # à `enregistrer_extraction_bl` (qui suppose une réponse Mistral OCR
    # normale).
    if not isinstance(reponse, dict) or not isinstance(reponse.get("pages"), list):
        _journaliser_echec(
            "ocr", update_id, ValueError("réponse OCR mal formée (pas de « pages »)")
        )
        return await _enregistrer_echec_ocr_sans_lever(sessions, document_id, update_id)

    try:
        async with sessions() as session:
            resultat = await enregistrer_extraction_bl(session, document_id, reponse)
    except Exception as exc:
        _journaliser_echec("extraction ocr", update_id, exc)
        return await _enregistrer_echec_ocr_sans_lever(sessions, document_id, update_id)

    return _ResultatOcr(
        numero=resultat.numero,
        statut=resultat.statut,
        fournisseur_nom=resultat.fournisseur_nom,
        chantier_brut=resultat.chantier_brut,
    )


async def _ranger_photo_sans_lever(
    sessions: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
    docs_dir: Path,
    update_id: int,
) -> None:
    """Pose (ou renomme) le lien physique du bon (Task 9, spec §5, `ingest
    .rangement`) dans une session neuve -- toujours après `_executer_ocr`
    (le chantier lu a pu y être résolu). N'échoue jamais vers l'appelant :
    `ranger_document` absorbe déjà toute `OSError`, cette fonction absorbe
    en plus tout le reste (session injoignable, ...) -- le rangement n'est
    qu'un confort de consultation sur le serveur (jamais une sauvegarde),
    un échec ne doit jamais faire échouer un dépôt (rattrapé par `python -m
    app.cli ranger-photos`)."""
    try:
        async with sessions() as session:
            await ranger_document(session, docs_dir, document_id)
    except Exception as exc:
        _journaliser_echec("rangement", update_id, exc)


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

    # T9 (audit rapidité/sécurité du 25/09/2026, constat CRITIQUE) : le
    # contenu réellement téléchargé doit correspondre à l'extension déduite
    # par `messagerie.telecharger` (elle-même déduite du type MIME déclaré
    # par le client Telegram, jamais garanti) -- avant toute écriture disque
    # et avant tout appel OCR, même chemin d'échec qu'un échec de
    # téléchargement (journalisation sans donnée client, supervision,
    # réponse d'échec à l'agent).
    if not signature_conforme(fichier.extension, fichier.contenu):
        _journaliser_echec(
            "signature fichier",
            entrant.update_id,
            ValueError("signature de fichier non conforme à l'extension déclarée"),
        )
        await _signaler_echec_traitement(
            messagerie, telegram_chat_supervision_id, entrant, "signature"
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
                legende=entrant.legende,
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

    # Task 9 (spec §5) : posé après la lecture du bon (le chantier lu a pu
    # être résolu par `_executer_ocr`), jamais avant -- voir
    # `_ranger_photo_sans_lever`, qui n'échoue jamais vers l'appelant.
    await _ranger_photo_sans_lever(sessions, document_id, docs_dir, entrant.update_id)

    await _envoyer_supervision(
        messagerie,
        telegram_chat_supervision_id,
        entrant.update_id,
        _ligne_supervision(
            numero_interne,
            resultat_ocr.numero,
            resultat_ocr.fournisseur_nom,
            resultat_ocr.chantier_brut,
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
    heure = confirme_le.astimezone(FUSEAU_PARIS).strftime("%H:%M")
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
