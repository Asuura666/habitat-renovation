"""Tests unitaires de `app/modules/ingest/depot_telegram.py` (base de test
réelle, `docs_dir` temporaire, fausse `Messagerie`). Toutes les valeurs
(identifiants, noms) sont inventées."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ingest import depot_telegram as ingest_depot_telegram
from app.modules.ingest.commun import Deposant
from app.modules.ingest.depot_telegram import (
    enregistrer_update,
    signaler_expediteur_inconnu,
    traiter_clic,
    traiter_fichier,
    utilisateur_rattache,
)
from app.modules.ingest.models import (
    Document,
    Fournisseur,
    Journal,
    TelegramUpdate,
    Utilisateur,
)
from app.modules.messaging.base import (
    PREFIXE_ECART_CONSTATE,
    PREFIXE_QUANTITES_VERIFIEES,
    ClicBouton,
    FichierEntrant,
    FichierTelecharge,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

NUMERO_BL_INVENTE = "L209900000123"
CHAT_SUPERVISION_INVENTE = 999999

# T9 : contenu par défaut téléchargé par `MessagerieFactice` -- signature
# JPEG valide (`FF D8 FF`) suivie du même repère de contenu qu'avant ce
# correctif (`contenu-invente-du-fichier`), pour que `signature_conforme`
# accepte le fichier `.jpg` que `MessagerieFactice.telecharger` renvoie
# toujours par défaut, sans changer ce que les tests existants vérifient
# au-delà de la signature elle-même.
_CONTENU_TELECHARGE_DEFAUT = b"\xff\xd8\xff" + b"contenu-invente-du-fichier"

_RE_LIGNE_SUPERVISION = re.compile(
    r"^Document n° (?P<numero_interne>\d+) · BL (?P<bl>.+) · fournisseur — · "
    r"chantier — · (?P<deposant>.+) · (?P<heure>\d{2}:\d{2}) · (?P<statut>\w+)$"
)

# Fix round 1, finding 2 : donnée synthétique complète (annotation + scores
# de confiance), pour un test bout en bout où fournisseur et chantier sont
# réellement résolus dans la ligne de supervision (tous les autres faux OCR
# de ce fichier n'ont pas d'annotation, donc toujours « fournisseur — ·
# chantier — » — voir `app/modules/ingest/tests/test_extraction_bl.py` pour
# le détail de cette donnée).
_DONNEES_SYNTHETIQUES = (
    Path(__file__).resolve().parent.parent.parent
    / "extract"
    / "tests"
    / "donnees"
    / "bl_synthetique.mistral-ocr.json"
)
with _DONNEES_SYNTHETIQUES.open(encoding="utf-8") as _fichier:
    _REPONSE_SYNTHETIQUE_BASE: dict[str, Any] = json.load(_fichier)


def _parse_ligne_supervision(texte: str) -> re.Match[str]:
    """Valide qu'une ligne de supervision respecte le format L2-D8, sans
    figer l'heure (dépendante de l'exécution)."""
    match = _RE_LIGNE_SUPERVISION.match(texte)
    assert match is not None, f"ligne de supervision inattendue : {texte!r}"
    return match


def _boutons_confirmation(numero_interne: int) -> tuple[tuple[str, str], ...]:
    """Boutons attendus dans la réponse au dépôt (L2-D9) : mêmes libellés et
    `callback_data` que ceux réellement envoyés par `traiter_fichier`."""
    return (
        ("Quantités vérifiées", f"{PREFIXE_QUANTITES_VERIFIEES}:{numero_interne}"),
        ("Écart constaté", f"{PREFIXE_ECART_CONSTATE}:{numero_interne}"),
    )


async def _ocr_avec_numero_bl(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (T6b) : réponse portant un numéro de BL détectable, utilisé
    par les tests qui ne portent pas sur l'OCR lui-même (le document doit
    rester `recu`)."""
    return {"pages": [{"markdown": f"LIVRAISON N°{NUMERO_BL_INVENTE}"}]}


async def _ocr_avec_annotation_complete(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (fix round 1, finding 2) : renvoie la donnée synthétique
    complète (annotation Mistral + scores de confiance), pour un test bout
    en bout où fournisseur et chantier sont réellement résolus dans la ligne
    de supervision — jamais mutée en place (`copy.deepcopy`)."""
    return copy.deepcopy(_REPONSE_SYNTHETIQUE_BASE)


async def _ocr_sans_numero_bl(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (T6b) : réponse sans motif de numéro de BL reconnaissable."""
    return {"pages": [{"markdown": "texte inventé sans motif de BL"}]}


async def _ocr_en_echec(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (T6b) : simule un échec complet de l'appel OCR."""
    raise RuntimeError("échec factice de l'OCR")


async def _ocr_jamais_appele(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (T6b) : prouve que l'OCR n'est jamais appelé quand le
    document n'a pas pu être enregistré (téléchargement, écriture ou base en
    échec)."""
    raise AssertionError("l'OCR ne doit pas être appelé dans ce scénario")


async def _ocr_reponse_liste(contenu: bytes, mime: str) -> Any:
    """Faux OCR (correction tour 1/5) : réponse 200 mal formée, une liste au
    lieu d'un objet — `texte_ocr` appellerait `.get` sur une `list` et
    lèverait `AttributeError` sans la protection ajoutée dans
    `_executer_ocr`."""
    return ["pas", "un", "dict"]


async def _ocr_reponse_sans_pages(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (correction tour 1/5) : objet JSON valide mais sans clé
    `pages` du tout — traité comme une réponse mal formée (pas comme une
    réponse valide sans numéro détecté)."""
    return {"quelque_chose_dautre": True}


async def _ocr_reponse_pages_non_liste(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (correction tour 1/5) : `pages` présent mais pas une liste."""
    return {"pages": "pas une liste"}


class MessagerieFactice:
    """Fausse `Messagerie` (aucune dépendance réseau réelle)."""

    def __init__(
        self,
        *,
        echoue_telechargement: bool = False,
        echoue_envoyer: bool = False,
        echoue_repondre: bool = False,
        echoue_accuser_clic: bool = False,
        echoue_editer_message: bool = False,
        # T9 : personnalisables pour le test négatif de signature (contenu
        # qui ne correspond pas à l'extension) -- signature JPEG valide par
        # défaut, comme avant ce correctif.
        contenu_telecharge: bytes = _CONTENU_TELECHARGE_DEFAUT,
        extension_telechargee: str = "jpg",
    ) -> None:
        self.echoue_telechargement = echoue_telechargement
        self.echoue_envoyer = echoue_envoyer
        self.echoue_repondre = echoue_repondre
        self.echoue_accuser_clic = echoue_accuser_clic
        self.echoue_editer_message = echoue_editer_message
        self.contenu_telecharge = contenu_telecharge
        self.extension_telechargee = extension_telechargee
        self.reponses: list[
            tuple[int, int, str, tuple[tuple[str, str], ...] | None]
        ] = []
        self.supervisions: list[tuple[int, str]] = []
        self.accuses: list[tuple[str, str]] = []
        self.editions: list[tuple[int, int, str]] = []

    async def telecharger(self, fichier: FichierEntrant) -> FichierTelecharge:
        if self.echoue_telechargement:
            raise RuntimeError("échec factice de téléchargement")
        return FichierTelecharge(
            contenu=self.contenu_telecharge, extension=self.extension_telechargee
        )

    async def repondre(
        self,
        chat_id: int,
        message_id: int,
        texte: str,
        boutons: Sequence[tuple[str, str]] | None = None,
    ) -> None:
        if self.echoue_repondre:
            raise RuntimeError("échec factice de réponse")
        self.reponses.append(
            (chat_id, message_id, texte, tuple(boutons) if boutons else None)
        )

    async def envoyer(self, chat_id: int, texte: str) -> None:
        if self.echoue_envoyer:
            raise RuntimeError("échec factice d'envoi de supervision")
        self.supervisions.append((chat_id, texte))

    async def accuser_clic(self, callback_id: str, texte: str) -> None:
        if self.echoue_accuser_clic:
            raise RuntimeError("échec factice d'accusé de clic")
        self.accuses.append((callback_id, texte))

    async def editer_message(self, chat_id: int, message_id: int, texte: str) -> None:
        if self.echoue_editer_message:
            raise RuntimeError("échec factice d'édition de message")
        self.editions.append((chat_id, message_id, texte))


def _entrant(
    update_id: int = 1,
    expediteur_id: int | None = None,
    expediteur_nom: str | None = None,
    legende: str | None = None,
) -> FichierEntrant:
    return FichierEntrant(
        update_id=update_id,
        chat_id=100 + update_id,
        message_id=200 + update_id,
        expediteur_id=expediteur_id,
        fichier_id="fichier-invente",
        mime_type=None,
        nom_fichier=None,
        compresse=True,
        expediteur_nom=expediteur_nom,
        legende=legende,
    )


async def _creer_utilisateur(
    db_session: AsyncSession,
    *,
    telegram_user_id: int,
    actif: bool = True,
    nom: str | None = "Agent Testeur",
    email: str | None = None,
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email or f"agent.{telegram_user_id}@example.invalid",
        role="agent",
        telegram_user_id=telegram_user_id,
        nom=nom,
        is_active=actif,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


def _deposant_depuis(utilisateur: Utilisateur) -> Deposant:
    return Deposant(
        id=utilisateur.id, nom_affichage=utilisateur.nom or utilisateur.email
    )


async def test_enregistrer_update_nouveau_renvoie_true(
    db_session: AsyncSession,
) -> None:
    assert await enregistrer_update(db_session, 1) is True


async def test_enregistrer_update_deja_vu_renvoie_false(
    db_session: AsyncSession,
) -> None:
    assert await enregistrer_update(db_session, 2) is True
    assert await enregistrer_update(db_session, 2) is False

    updates = (
        (
            await db_session.execute(
                select(TelegramUpdate).where(TelegramUpdate.update_id == 2)
            )
        )
        .scalars()
        .all()
    )
    assert len(updates) == 1


async def test_enregistrer_update_concurrent_un_seul_gagne(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    """Dédoublonnage concurrent : deux requêtes simultanées pour le même
    `update_id` ne doivent jamais toutes les deux recevoir `True`."""

    async def _tenter() -> bool:
        async with sessions_test() as session:
            return await enregistrer_update(session, 777)

    resultats = await asyncio.gather(_tenter(), _tenter())

    assert sorted(resultats) == [False, True]
    updates = (
        (
            await db_session.execute(
                select(TelegramUpdate).where(TelegramUpdate.update_id == 777)
            )
        )
        .scalars()
        .all()
    )
    assert len(updates) == 1


# --------------------------------------------------------------------------
# `utilisateur_rattache` (L2-T2) : liste blanche, L2-D7. Contrairement à la
# décision D15 du lot 1 (tout `telegram_user_id` connu, actif ou non,
# remplissait `deposant_id`), un compte désactivé est désormais traité comme
# un expéditeur inconnu.
# --------------------------------------------------------------------------


async def test_utilisateur_rattache_actif_renvoie_le_deposant(
    db_session: AsyncSession,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=5001)

    resultat = await utilisateur_rattache(db_session, 5001)

    assert resultat == Deposant(id=utilisateur.id, nom_affichage="Agent Testeur")


async def test_utilisateur_rattache_inactif_traite_comme_inconnu(
    db_session: AsyncSession,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=5002, actif=False)

    assert await utilisateur_rattache(db_session, 5002) is None


async def test_utilisateur_rattache_telegram_user_id_inconnu_renvoie_none(
    db_session: AsyncSession,
) -> None:
    assert await utilisateur_rattache(db_session, 5_000_000) is None


async def test_utilisateur_rattache_telegram_user_id_none_renvoie_none(
    db_session: AsyncSession,
) -> None:
    assert await utilisateur_rattache(db_session, None) is None


async def test_utilisateur_rattache_sans_nom_utilise_lemail(
    db_session: AsyncSession,
) -> None:
    utilisateur = await _creer_utilisateur(
        db_session, telegram_user_id=5003, nom=None, email="sans-nom@example.invalid"
    )

    resultat = await utilisateur_rattache(db_session, 5003)

    assert resultat == Deposant(
        id=utilisateur.id, nom_affichage="sans-nom@example.invalid"
    )


# --------------------------------------------------------------------------
# `signaler_expediteur_inconnu` (L2-D7) : notification de supervision, sans
# écriture ni téléchargement.
# --------------------------------------------------------------------------


async def test_signaler_expediteur_inconnu_envoie_id_et_nom_en_supervision() -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=40, expediteur_id=777, expediteur_nom="Curieux")

    await signaler_expediteur_inconnu(entrant, messagerie, CHAT_SUPERVISION_INVENTE)

    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    assert "777" in texte
    assert "Curieux" in texte
    assert messagerie.reponses == []


async def test_signaler_expediteur_inconnu_sans_nom_ne_leve_pas() -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=41, expediteur_id=778, expediteur_nom=None)

    await signaler_expediteur_inconnu(entrant, messagerie, CHAT_SUPERVISION_INVENTE)

    assert len(messagerie.supervisions) == 1
    assert "778" in messagerie.supervisions[0][1]


async def test_signaler_expediteur_inconnu_echec_envoi_journalise_sans_lever(
    caplog: pytest.LogCaptureFixture,
) -> None:
    messagerie = MessagerieFactice(echoue_envoyer=True)
    entrant = _entrant(update_id=42, expediteur_id=779)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await signaler_expediteur_inconnu(entrant, messagerie, CHAT_SUPERVISION_INVENTE)

    assert messagerie.supervisions == []
    assert str(entrant.update_id) in caplog.text


# --------------------------------------------------------------------------
# `traiter_fichier` : `deposant` est désormais toujours renseigné (L2-T2),
# résolu par le routeur via `utilisateur_rattache` avant la mise en tâche de
# fond — plus jamais `NULL` (contrairement au lot 1, décision D15).
# --------------------------------------------------------------------------


async def test_traiter_fichier_ecrit_le_fichier_le_document_et_repond(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9010)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=10)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_avec_numero_bl,
        deposant,
        CHAT_SUPERVISION_INVENTE,
    )

    documents = (await db_session.execute(select(Document))).scalars().all()
    assert len(documents) == 1
    document = documents[0]
    assert document.type == "bl"
    assert document.source == "telegram"
    # `_ocr_avec_numero_bl` ne renvoie aucune `document_annotation` :
    # l'extraction (L3-T6) part en `annotation_illisible`, `a_verifier`
    # (L3-D10) — seul le numéro, détecté par le motif déterministe existant,
    # est repris.
    assert document.statut == "a_verifier"
    assert document.telegram_message_id == entrant.message_id
    assert document.deposant_id == deposant.id
    assert document.numero == NUMERO_BL_INVENTE
    assert document.photo_compressee is True

    fichiers = list(tmp_path.glob("*.jpg"))
    assert len(fichiers) == 1
    assert not list(tmp_path.glob("*.tmp"))
    assert fichiers[0].read_bytes() == _CONTENU_TELECHARGE_DEFAUT
    assert document.fichier_path == str(fichiers[0])

    # L2-D9 : numéro interne dans le texte, deux boutons de confirmation.
    assert messagerie.reponses == [
        (
            entrant.chat_id,
            entrant.message_id,
            f"Reçu — document n° {document.numero_interne}",
            _boutons_confirmation(document.numero_interne),
        )
    ]

    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    match = _parse_ligne_supervision(texte)
    assert match["numero_interne"] == str(document.numero_interne)
    assert match["bl"] == NUMERO_BL_INVENTE
    assert match["deposant"] == "Agent Testeur"
    assert match["statut"] == "a_verifier"


async def test_traiter_fichier_photo_compressee_false_pour_un_document_envoye(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9011)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = FichierEntrant(
        update_id=16,
        chat_id=116,
        message_id=216,
        expediteur_id=9011,
        fichier_id="fichier-invente",
        mime_type="application/pdf",
        nom_fichier="bl-invente.pdf",
        compresse=False,
    )

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_avec_numero_bl,
        deposant,
        CHAT_SUPERVISION_INVENTE,
    )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.photo_compressee is False


async def test_depot_conserve_la_legende(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """La légende Telegram (`message.caption`, avenant du 27/09/2026) est
    conservée sur le document déposé, telle que déjà nettoyée par
    `lire_update` (`FichierEntrant.legende`) -- `traiter_fichier` la reprend
    sans la retoucher."""
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9012)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=32, legende="Villa Test")

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_avec_numero_bl,
        deposant,
        CHAT_SUPERVISION_INVENTE,
    )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.legende == "Villa Test"


async def test_traiter_fichier_signature_non_conforme_signale_echec_sans_ecrire(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cas négatif (T9, constat CRITIQUE) : un contenu reçu sous
    l'extension `jpg` (déduite du type MIME *déclaré* par le client
    Telegram, jamais confronté au contenu réel avant ce correctif) mais qui
    n'a pas la signature JPEG est refusé avant toute écriture disque et
    avant tout appel OCR -- même chemin d'échec qu'un échec de
    téléchargement (journalisation sans donnée client, supervision, réponse
    d'échec à l'agent)."""
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9020)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice(
        contenu_telecharge=b"ceci n'est pas un jpeg, juste du texte invente"
    )
    entrant = _entrant(update_id=30)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant,
            messagerie,
            sessions_test,
            tmp_path,
            _ocr_jamais_appele,
            deposant,
            CHAT_SUPERVISION_INVENTE,
        )

    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []
    assert str(entrant.update_id) in caplog.text
    assert "ceci n'est pas un jpeg" not in caplog.text

    # Même chemin d'échec qu'un échec de téléchargement (R22) : réponse
    # d'échec à l'agent sans détail technique, jamais de boutons.
    assert messagerie.reponses == [
        (
            entrant.chat_id,
            entrant.message_id,
            ingest_depot_telegram._MESSAGE_ECHEC_AGENT,
            None,
        )
    ]
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    assert "signature" in texte
    assert "ceci n'est pas un jpeg" not in texte


async def test_traiter_fichier_signature_conforme_photo_compressee_traitee(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Cas positif (T9) : une vraie photo compressée Telegram (toujours un
    JPEG, signature `FF D8 FF`) passe le contrôle de signature et continue
    d'être traitée normalement (document enregistré, fichier écrit, OCR
    appelé)."""
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9021)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=31)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_avec_numero_bl,
        deposant,
        CHAT_SUPERVISION_INVENTE,
    )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.photo_compressee is True
    assert document.numero == NUMERO_BL_INVENTE
    fichiers = list(tmp_path.glob("*.jpg"))
    assert len(fichiers) == 1
    assert fichiers[0].read_bytes() == _CONTENU_TELECHARGE_DEFAUT


async def test_traiter_fichier_echec_telechargement_signale_supervision_et_agent(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9012)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice(echoue_telechargement=True)
    entrant = _entrant(update_id=13)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant,
            messagerie,
            sessions_test,
            tmp_path,
            _ocr_jamais_appele,
            deposant,
            CHAT_SUPERVISION_INVENTE,
        )

    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []
    assert str(entrant.update_id) in caplog.text
    assert "contenu-invente-du-fichier" not in caplog.text

    # Ruling R22 : réponse d'échec à l'agent, sans détail technique, jamais
    # de boutons (décision du contrôleur L2-T3).
    assert messagerie.reponses == [
        (
            entrant.chat_id,
            entrant.message_id,
            ingest_depot_telegram._MESSAGE_ECHEC_AGENT,
            None,
        )
    ]
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    assert "téléchargement" in texte
    assert "contenu-invente-du-fichier" not in texte


async def test_traiter_fichier_echec_ecriture_signale_supervision_et_agent(
    monkeypatch: pytest.MonkeyPatch,
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    def _ecriture_qui_echoue(*args: object, **kwargs: object) -> None:
        raise OSError("disque plein (factice)")

    monkeypatch.setattr(ingest_depot_telegram, "_ecrire_atomique", _ecriture_qui_echoue)

    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9013)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=15)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_jamais_appele,
        deposant,
        CHAT_SUPERVISION_INVENTE,
    )

    assert list(tmp_path.iterdir()) == []
    assert (await db_session.execute(select(Document))).scalars().all() == []

    # R22 : réponse d'échec, jamais de boutons (décision du contrôleur L2-T3).
    assert messagerie.reponses == [
        (
            entrant.chat_id,
            entrant.message_id,
            ingest_depot_telegram._MESSAGE_ECHEC_AGENT,
            None,
        )
    ]
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    assert "écriture" in texte
    assert "contenu-invente-du-fichier" not in texte


async def test_traiter_fichier_echec_base_supprime_le_fichier_ecrit(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Simule un échec base après téléchargement/écriture réussis (FK vers
    un utilisateur inexistant, `deposant.id` fantôme) : aucun fichier ne
    doit rester, l'agent est prévenu."""
    deposant_fantome = Deposant(id=uuid.uuid4(), nom_affichage="Fantôme")
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=14)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_jamais_appele,
        deposant_fantome,
        CHAT_SUPERVISION_INVENTE,
    )

    assert list(tmp_path.iterdir()) == []
    assert (await db_session.execute(select(Document))).scalars().all() == []

    # R22 : réponse d'échec, jamais de boutons (décision du contrôleur L2-T3).
    assert messagerie.reponses == [
        (
            entrant.chat_id,
            entrant.message_id,
            ingest_depot_telegram._MESSAGE_ECHEC_AGENT,
            None,
        )
    ]
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    assert "insertion" in texte
    assert "contenu-invente-du-fichier" not in texte


async def test_traiter_fichier_echec_envoi_supervision_nempeche_pas_le_traitement(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un échec d'envoi du message de supervision est journalisé seulement
    (décision du contrôleur) : le document reste enregistré et la réponse
    « reçu » part quand même."""
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9014)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice(echoue_envoyer=True)
    entrant = _entrant(update_id=17)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant,
            messagerie,
            sessions_test,
            tmp_path,
            _ocr_avec_numero_bl,
            deposant,
            CHAT_SUPERVISION_INVENTE,
        )

    document = (await db_session.execute(select(Document))).scalar_one()
    # `_ocr_avec_numero_bl` ne renvoie aucune `document_annotation` :
    # `a_verifier` (annotation illisible, L3-D10), comme pour tous les
    # faux OCR de ce fichier qui n'en renvoient pas.
    assert document.statut == "a_verifier"
    assert messagerie.supervisions == []
    assert messagerie.reponses == [
        (
            entrant.chat_id,
            entrant.message_id,
            f"Reçu — document n° {document.numero_interne}",
            _boutons_confirmation(document.numero_interne),
        )
    ]
    assert str(entrant.update_id) in caplog.text


# --------------------------------------------------------------------------
# OCR (T6b) : numéro détecté, non détecté, échec de l'appel OCR lui-même.
# Le dépôt du fichier est déjà acquis avant l'OCR (décision du contrôleur
# T6b) : dans les trois cas, le document existe et la réponse « reçu » part.
# --------------------------------------------------------------------------


async def test_traiter_fichier_numero_bl_detecte_remplit_numero_et_type(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9020)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=20)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_avec_numero_bl,
        deposant,
        CHAT_SUPERVISION_INVENTE,
    )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.numero == NUMERO_BL_INVENTE
    assert document.type == "bl"
    # `_ocr_avec_numero_bl` ne renvoie aucune `document_annotation` :
    # `a_verifier` (annotation illisible, L3-D10).
    assert document.statut == "a_verifier"
    assert document.ocr_brut == {
        "pages": [{"markdown": f"LIVRAISON N°{NUMERO_BL_INVENTE}"}]
    }
    assert messagerie.reponses == [
        (
            entrant.chat_id,
            entrant.message_id,
            f"Reçu — document n° {document.numero_interne}",
            _boutons_confirmation(document.numero_interne),
        )
    ]


async def test_traiter_fichier_numero_bl_non_detecte_statut_a_verifier(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9021)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=21)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_sans_numero_bl,
        deposant,
        CHAT_SUPERVISION_INVENTE,
    )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.numero is None
    assert document.statut == "a_verifier"
    assert document.ocr_brut == {
        "pages": [{"markdown": "texte inventé sans motif de BL"}]
    }
    # Le dépôt reste acquis : la réponse « reçu » part malgré l'absence de
    # numéro détecté.
    assert messagerie.reponses == [
        (
            entrant.chat_id,
            entrant.message_id,
            f"Reçu — document n° {document.numero_interne}",
            _boutons_confirmation(document.numero_interne),
        )
    ]

    assert len(messagerie.supervisions) == 1
    match = _parse_ligne_supervision(messagerie.supervisions[0][1])
    assert match["bl"] == "non détecté"
    assert match["statut"] == "a_verifier"


async def test_traiter_fichier_ocr_en_echec_document_a_verifier_sans_numero(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """L3-D10 : un échec complet de l'appel OCR ne laisse plus le document
    `recu` sans extraction — il part `a_verifier` avec le motif `ocr_echec`
    (`enregistrer_echec_ocr`), la réponse « reçu » part quand même."""
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9022)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=22)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant,
            messagerie,
            sessions_test,
            tmp_path,
            _ocr_en_echec,
            deposant,
            CHAT_SUPERVISION_INVENTE,
        )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.statut == "a_verifier"
    assert document.numero is None
    assert document.ocr_brut is None
    assert document.motifs == [{"code": "ocr_echec", "champ": None, "detail": {}}]
    # Le dépôt est acquis quoi qu'il arrive : la réponse « reçu » part même
    # si l'OCR échoue complètement.
    assert messagerie.reponses == [
        (
            entrant.chat_id,
            entrant.message_id,
            f"Reçu — document n° {document.numero_interne}",
            _boutons_confirmation(document.numero_interne),
        )
    ]
    assert str(entrant.update_id) in caplog.text
    assert "contenu-invente-du-fichier" not in caplog.text

    assert len(messagerie.supervisions) == 1
    match = _parse_ligne_supervision(messagerie.supervisions[0][1])
    assert match["bl"] == "non détecté"
    assert match["statut"] == "a_verifier"


# --------------------------------------------------------------------------
# Correction tour 1/5 : une réponse OCR 200 mal formée ne doit jamais faire
# remonter d'exception jusqu'à `traiter_fichier` (la réponse « reçu » doit
# toujours partir). Les trois formes constatées par le relecteur : liste au
# lieu d'un objet, objet sans `pages`, `pages` présent mais pas une liste.
# L3-D10 : traitée comme un échec d'OCR, le document part `a_verifier` avec
# le motif `ocr_echec` (au lieu de rester `recu` sans extraction).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ocr_factice",
    [_ocr_reponse_liste, _ocr_reponse_sans_pages, _ocr_reponse_pages_non_liste],
    ids=["reponse-liste", "objet-sans-pages", "pages-non-liste"],
)
async def test_traiter_fichier_reponse_ocr_malformee_document_a_verifier(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    ocr_factice: Any,
) -> None:
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9030)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=30)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant,
            messagerie,
            sessions_test,
            tmp_path,
            ocr_factice,
            deposant,
            CHAT_SUPERVISION_INVENTE,
        )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.statut == "a_verifier"
    assert document.numero is None
    assert document.ocr_brut is None
    assert document.motifs == [{"code": "ocr_echec", "champ": None, "detail": {}}]
    # Le dépôt est acquis quoi qu'il arrive, y compris pour une réponse OCR
    # mal formée : la réponse « reçu » part quand même.
    assert messagerie.reponses == [
        (
            entrant.chat_id,
            entrant.message_id,
            f"Reçu — document n° {document.numero_interne}",
            _boutons_confirmation(document.numero_interne),
        )
    ]
    assert str(entrant.update_id) in caplog.text
    assert "contenu-invente-du-fichier" not in caplog.text


async def test_traiter_fichier_extraction_bl_leve_document_a_verifier_ocr_echec(
    monkeypatch: pytest.MonkeyPatch,
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Décision du contrôleur (Ruling R5) : une exception inattendue
    d'`enregistrer_extraction_bl` (donnée OCR corrompue imprévue) ne doit
    jamais laisser le document `recu` sans extraction — `enregistrer_echec_ocr`
    est appelé dans une session neuve, le document part `a_verifier` avec le
    motif `ocr_echec`."""

    async def _extraction_qui_leve(
        session: AsyncSession, document_id: uuid.UUID, reponse: dict[str, Any], **_: Any
    ) -> Any:
        raise RuntimeError("donnée OCR corrompue imprévue (factice)")

    monkeypatch.setattr(
        ingest_depot_telegram, "enregistrer_extraction_bl", _extraction_qui_leve
    )

    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9031)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=31)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_fichier(
            entrant,
            messagerie,
            sessions_test,
            tmp_path,
            _ocr_avec_numero_bl,
            deposant,
            CHAT_SUPERVISION_INVENTE,
        )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.statut == "a_verifier"
    assert document.motifs == [{"code": "ocr_echec", "champ": None, "detail": {}}]
    assert str(entrant.update_id) in caplog.text
    assert "contenu-invente-du-fichier" not in caplog.text


# --------------------------------------------------------------------------
# Fix round 1, finding 2 : ligne de supervision avec fournisseur et chantier
# réellement résolus. Tous les tests ci-dessus utilisent un faux OCR sans
# annotation (`_ocr_avec_numero_bl`/`_ocr_sans_numero_bl`), donc la ligne de
# supervision n'y affiche jamais que les deux placeholders « — » : ils ne
# couvraient pas la moitié utile du format T6.
# --------------------------------------------------------------------------


def test_ligne_supervision_avec_fournisseur_et_chantier_resolus() -> None:
    """Test unitaire direct de `_ligne_supervision` (T6) : fournisseur et
    chantier apparaissent tels quels quand ils sont fournis, sans retomber
    sur les placeholders « — »."""
    texte = ingest_depot_telegram._ligne_supervision(
        42,
        NUMERO_BL_INVENTE,
        "Peintures Exemple",
        "MAISON TEST (9900000001)",
        "recu",
        "Agent Testeur",
    )

    match = re.match(
        r"^Document n° 42 · BL " + re.escape(NUMERO_BL_INVENTE) + r" · "
        r"fournisseur Peintures Exemple · "
        r"chantier MAISON TEST \(9900000001\) · Agent Testeur · "
        r"(?P<heure>\d{2}:\d{2}) · recu$",
        texte,
    )
    assert match is not None, f"ligne de supervision inattendue : {texte!r}"


async def test_traiter_fichier_ligne_supervision_fournisseur_et_chantier_resolus(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Bout en bout (`traiter_fichier`) : fournisseur défini en base
    (« Peintures Exemple », alias « Peintures Exemple SAS ») + annotation
    synthétique complète (`_ocr_avec_annotation_complete`) -> le document
    part `recu` et la ligne de supervision affiche le nom du fournisseur du
    référentiel et le chantier brut lu, jamais les placeholders « — »."""
    db_session.add(
        Fournisseur(nom="Peintures Exemple", aliases=["Peintures Exemple SAS"])
    )
    await db_session.commit()
    utilisateur = await _creer_utilisateur(db_session, telegram_user_id=9041)
    deposant = _deposant_depuis(utilisateur)
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=41)

    await traiter_fichier(
        entrant,
        messagerie,
        sessions_test,
        tmp_path,
        _ocr_avec_annotation_complete,
        deposant,
        CHAT_SUPERVISION_INVENTE,
    )

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.statut == "recu"

    assert len(messagerie.supervisions) == 1
    texte = messagerie.supervisions[0][1]
    assert "fournisseur Peintures Exemple" in texte
    assert "chantier MAISON TEST (9900000001)" in texte
    assert "fournisseur —" not in texte
    assert "chantier —" not in texte


# --------------------------------------------------------------------------
# `traiter_clic` (L2-T3, L2-D10) : clic sur un des deux boutons de
# confirmation. Les documents cliqués sont créés directement en base (pas
# via `traiter_fichier`) : seul `traiter_clic` est sous test ici.
# --------------------------------------------------------------------------


def _clic(
    *,
    update_id: int,
    numero_interne: int,
    expediteur_id: int | None,
    action: str = PREFIXE_QUANTITES_VERIFIEES,
    chat_id: int = 555,
    message_id: int = 20,
    callback_id: str = "callback-invente",
) -> ClicBouton:
    return ClicBouton(
        update_id=update_id,
        callback_id=callback_id,
        chat_id=chat_id,
        message_id=message_id,
        expediteur_id=expediteur_id,
        action=action,
        numero_interne=numero_interne,
    )


async def _creer_document(
    db_session: AsyncSession, *, statut: str = "recu"
) -> Document:
    document = Document(
        type="bl",
        source="telegram",
        statut=statut,
        fichier_path="chemin-invente.jpg",
    )
    db_session.add(document)
    await db_session.commit()
    return document


async def test_traiter_clic_quantites_verifiees_confirme_journalise_accuse_et_edite(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
) -> None:
    confirmateur = await _creer_utilisateur(
        db_session, telegram_user_id=8001, nom="Confirmateur Testeur"
    )
    document = await _creer_document(db_session)
    messagerie = MessagerieFactice()
    clic = _clic(
        update_id=50,
        numero_interne=document.numero_interne,
        action=PREFIXE_QUANTITES_VERIFIEES,
        expediteur_id=8001,
    )

    await traiter_clic(clic, messagerie, sessions_test, CHAT_SUPERVISION_INVENTE)

    await db_session.refresh(document)
    assert document.confirme_le is not None
    assert document.confirme_par == confirmateur.id
    assert document.statut == "recu"

    journal = (await db_session.execute(select(Journal))).scalars().all()
    assert len(journal) == 1
    entree = journal[0]
    assert entree.utilisateur_id == confirmateur.id
    assert entree.action == "quantites_verifiees"
    assert entree.cible_table == "document"
    assert entree.cible_id == str(document.id)
    assert entree.avant == {
        "statut": "recu",
        "confirme_le": None,
        "confirme_par": None,
    }
    apres = entree.apres
    assert apres is not None
    assert apres["statut"] == "recu"
    assert apres["confirme_par"] == str(confirmateur.id)

    assert messagerie.accuses == [
        (clic.callback_id, "Quantités vérifiées enregistrées")
    ]
    assert len(messagerie.editions) == 1
    chat_id, message_id, texte = messagerie.editions[0]
    assert chat_id == clic.chat_id
    assert message_id == clic.message_id
    assert texte.startswith(
        f"Reçu — document n° {document.numero_interne} · "
        "Quantités vérifiées par Confirmateur Testeur à "
    )


async def test_traiter_clic_ecart_constate_passe_a_verifier_et_journalise(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
) -> None:
    confirmateur = await _creer_utilisateur(
        db_session, telegram_user_id=8040, nom="Ecart Testeur"
    )
    document = await _creer_document(db_session, statut="recu")
    messagerie = MessagerieFactice()
    clic = _clic(
        update_id=90,
        numero_interne=document.numero_interne,
        action=PREFIXE_ECART_CONSTATE,
        expediteur_id=8040,
    )

    await traiter_clic(clic, messagerie, sessions_test, CHAT_SUPERVISION_INVENTE)

    await db_session.refresh(document)
    assert document.statut == "a_verifier"
    assert document.confirme_par == confirmateur.id
    assert document.confirme_le is not None

    journal = (await db_session.execute(select(Journal))).scalars().all()
    assert len(journal) == 1
    assert journal[0].action == "ecart_constate"
    apres = journal[0].apres
    assert apres is not None
    assert apres["statut"] == "a_verifier"

    assert messagerie.accuses == [(clic.callback_id, "Écart enregistré")]
    assert len(messagerie.editions) == 1
    texte_edition = messagerie.editions[0][2]
    assert "Écart constaté par Ecart Testeur à" in texte_edition


async def test_traiter_clic_second_clic_deja_enregistre_aucune_ecriture(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
) -> None:
    confirmateur = await _creer_utilisateur(
        db_session, telegram_user_id=8030, nom="Premier Clic"
    )
    await _creer_utilisateur(db_session, telegram_user_id=8031, nom="Second Clic")
    document = await _creer_document(db_session)
    messagerie = MessagerieFactice()
    premier = _clic(
        update_id=80,
        numero_interne=document.numero_interne,
        expediteur_id=8030,
        callback_id="callback-premier",
    )
    second = _clic(
        update_id=81,
        numero_interne=document.numero_interne,
        action=PREFIXE_ECART_CONSTATE,
        expediteur_id=8031,
        callback_id="callback-second",
    )

    await traiter_clic(premier, messagerie, sessions_test, CHAT_SUPERVISION_INVENTE)
    await traiter_clic(second, messagerie, sessions_test, CHAT_SUPERVISION_INVENTE)

    await db_session.refresh(document)
    assert document.confirme_par == confirmateur.id
    # Le second clic ("écart") n'a rien pu modifier : le statut reste celui
    # laissé par le premier clic.
    assert document.statut == "recu"

    assert len(messagerie.accuses) == 2
    assert messagerie.accuses[1] == (second.callback_id, "Déjà enregistré")

    journal = (await db_session.execute(select(Journal))).scalars().all()
    assert len(journal) == 1
    assert len(messagerie.editions) == 1


async def test_traiter_clic_utilisateur_non_rattache_refuse_et_signale_supervision(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
) -> None:
    document = await _creer_document(db_session)
    messagerie = MessagerieFactice()
    clic = _clic(
        update_id=70, numero_interne=document.numero_interne, expediteur_id=999999
    )

    await traiter_clic(clic, messagerie, sessions_test, CHAT_SUPERVISION_INVENTE)

    assert messagerie.accuses == [(clic.callback_id, "Non autorisé")]
    assert messagerie.editions == []
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_INVENTE
    assert "999999" in texte
    assert str(document.numero_interne) in texte

    await db_session.refresh(document)
    assert document.confirme_le is None
    assert (await db_session.execute(select(Journal))).scalars().all() == []


async def test_traiter_clic_numero_interne_inexistant_accuse_document_introuvable(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=8020)
    messagerie = MessagerieFactice()
    clic = _clic(update_id=71, numero_interne=999999, expediteur_id=8020)

    await traiter_clic(clic, messagerie, sessions_test, CHAT_SUPERVISION_INVENTE)

    assert messagerie.accuses == [(clic.callback_id, "Document introuvable")]
    assert messagerie.editions == []
    assert (await db_session.execute(select(Journal))).scalars().all() == []


async def test_traiter_clic_concurrence_une_seule_ecriture_un_seul_journal(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
) -> None:
    """Deux clics simultanés sur le même document (deux utilisateurs
    rattachés distincts) : un seul gagne la mise à jour atomique
    (`confirme_le IS NULL`), l'autre reçoit « Déjà enregistré » — même
    principe que `test_enregistrer_update_concurrent_un_seul_gagne`."""
    confirmateur_1 = await _creer_utilisateur(
        db_session, telegram_user_id=8010, nom="Premier"
    )
    confirmateur_2 = await _creer_utilisateur(
        db_session, telegram_user_id=8011, nom="Second"
    )
    document = await _creer_document(db_session)
    messagerie = MessagerieFactice()
    clic_1 = _clic(
        update_id=60,
        numero_interne=document.numero_interne,
        expediteur_id=8010,
        callback_id="callback-1",
    )
    clic_2 = _clic(
        update_id=61,
        numero_interne=document.numero_interne,
        expediteur_id=8011,
        callback_id="callback-2",
    )

    await asyncio.gather(
        traiter_clic(clic_1, messagerie, sessions_test, CHAT_SUPERVISION_INVENTE),
        traiter_clic(clic_2, messagerie, sessions_test, CHAT_SUPERVISION_INVENTE),
    )

    journal = (await db_session.execute(select(Journal))).scalars().all()
    assert len(journal) == 1

    await db_session.refresh(document)
    assert document.confirme_le is not None
    assert document.confirme_par in {confirmateur_1.id, confirmateur_2.id}

    textes_accuses = sorted(texte for _, texte in messagerie.accuses)
    assert textes_accuses == sorted(
        ["Quantités vérifiées enregistrées", "Déjà enregistré"]
    )
    assert len(messagerie.editions) == 1


# --------------------------------------------------------------------------
# Correction tour 1/5 (revue L2-T3) : document archivé, et exception
# inattendue dans `_decider_clic` qui ne doit jamais empêcher l'accusé.
# --------------------------------------------------------------------------


async def test_traiter_clic_document_archive_quantites_verifiees_refuse(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=8060)
    document = await _creer_document(db_session, statut="archive")
    messagerie = MessagerieFactice()
    clic = _clic(
        update_id=96,
        numero_interne=document.numero_interne,
        action=PREFIXE_QUANTITES_VERIFIEES,
        expediteur_id=8060,
    )

    await traiter_clic(clic, messagerie, sessions_test, CHAT_SUPERVISION_INVENTE)

    assert messagerie.accuses == [(clic.callback_id, "Document archivé")]
    assert messagerie.editions == []

    await db_session.refresh(document)
    assert document.confirme_le is None
    assert document.confirme_par is None
    assert document.statut == "archive"
    assert (await db_session.execute(select(Journal))).scalars().all() == []


async def test_traiter_clic_document_archive_ecart_constate_refuse(
    sessions_test: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=8061)
    document = await _creer_document(db_session, statut="archive")
    messagerie = MessagerieFactice()
    clic = _clic(
        update_id=97,
        numero_interne=document.numero_interne,
        action=PREFIXE_ECART_CONSTATE,
        expediteur_id=8061,
    )

    await traiter_clic(clic, messagerie, sessions_test, CHAT_SUPERVISION_INVENTE)

    assert messagerie.accuses == [(clic.callback_id, "Document archivé")]
    assert messagerie.editions == []

    await db_session.refresh(document)
    assert document.confirme_le is None
    assert document.confirme_par is None
    # Ne doit pas non plus être repassé « à vérifier » par le clic refusé.
    assert document.statut == "archive"
    assert (await db_session.execute(select(Journal))).scalars().all() == []


async def test_traiter_clic_exception_inattendue_dans_decision_accuse_quand_meme(
    sessions_test: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Constat Critical (revue L2-T3, tour 1/5) : sans ce filet, une
    exception inattendue dans `_decider_clic` laisse le bouton Telegram
    bloqué en chargement, sans accusé ni trace exploitable."""

    async def _decider_clic_qui_leve(
        session: AsyncSession, clic: ClicBouton
    ) -> ingest_depot_telegram._DecisionClic:
        raise RuntimeError("échec factice inattendu")

    monkeypatch.setattr(ingest_depot_telegram, "_decider_clic", _decider_clic_qui_leve)

    messagerie = MessagerieFactice()
    clic = _clic(update_id=98, numero_interne=1, expediteur_id=8070)

    with caplog.at_level(logging.ERROR, logger="app.modules.ingest.service"):
        await traiter_clic(clic, messagerie, sessions_test, CHAT_SUPERVISION_INVENTE)

    assert messagerie.accuses == [(clic.callback_id, "Erreur, réessayez")]
    assert messagerie.editions == []
    assert messagerie.supervisions == []
    assert str(clic.update_id) in caplog.text
    assert "échec factice inattendu" not in caplog.text
