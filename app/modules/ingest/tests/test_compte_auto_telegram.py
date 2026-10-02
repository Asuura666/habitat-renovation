"""Compte créé automatiquement au premier envoi Telegram d'un employé
(décision d'Ilane du 02/10/2026) : `rattacher_ou_creer_deposant` et
`refuser_compte_desactive` (`ingest/depot_telegram.py`)."""

from __future__ import annotations

import asyncio
import dataclasses

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ingest.depot_telegram import (
    MESSAGE_COMPTE_DESACTIVE,
    email_compte_telegram,
    rattacher_ou_creer_deposant,
    refuser_compte_desactive,
)
from app.modules.ingest.models import Journal, Utilisateur
from app.modules.ingest.tests.test_service import (
    MessagerieFactice,
    _creer_utilisateur,
    _entrant,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

CHAT_SUPERVISION = -1009999


async def _comptes_du_telegram(
    session: AsyncSession, telegram_user_id: int
) -> list[Utilisateur]:
    resultat = await session.execute(
        select(Utilisateur).where(Utilisateur.telegram_user_id == telegram_user_id)
    )
    return list(resultat.scalars().all())


async def test_premier_envoi_cree_un_compte_employe(db_session: AsyncSession) -> None:
    entrant = dataclasses.replace(
        _entrant(expediteur_id=7101, expediteur_nom="pseudo-invente"),
        expediteur_nom_complet="Prénom Inventé",
    )

    deposant = await rattacher_ou_creer_deposant(db_session, entrant)

    assert deposant is not None
    comptes = await _comptes_du_telegram(db_session, 7101)
    assert len(comptes) == 1
    compte = comptes[0]
    assert compte.id == deposant.id
    assert compte.nom == "Prénom Inventé"
    assert deposant.nom_affichage == "Prénom Inventé"
    assert compte.role == "agent"
    assert compte.is_active is True
    assert compte.hashed_password is None
    assert compte.email == email_compte_telegram(7101)

    journal = (
        (
            await db_session.execute(
                select(Journal).where(
                    Journal.action == "compte_cree",
                    Journal.cible_id == str(compte.id),
                )
            )
        )
        .scalars()
        .one()
    )
    assert journal.utilisateur_id is None
    assert journal.apres is not None
    assert journal.apres["origine"] == "Premier envoi Telegram"
    assert journal.apres["telegram_user_id"] == 7101


async def test_nom_de_repli_sans_nom_complet(db_session: AsyncSession) -> None:
    sans_nom = await rattacher_ou_creer_deposant(
        db_session, _entrant(expediteur_id=7102)
    )
    pseudo_seul = await rattacher_ou_creer_deposant(
        db_session, _entrant(expediteur_id=7103, expediteur_nom="pseudo-invente")
    )

    assert sans_nom is not None and sans_nom.nom_affichage == "Employé Telegram 7102"
    assert pseudo_seul is not None and pseudo_seul.nom_affichage == "pseudo-invente"


async def test_deuxieme_envoi_reutilise_le_compte(db_session: AsyncSession) -> None:
    premier = await rattacher_ou_creer_deposant(
        db_session, _entrant(update_id=1, expediteur_id=7104)
    )
    second = await rattacher_ou_creer_deposant(
        db_session, _entrant(update_id=2, expediteur_id=7104)
    )

    assert premier is not None and second is not None
    assert premier.id == second.id
    assert len(await _comptes_du_telegram(db_session, 7104)) == 1


async def test_compte_actif_existant_inchange(db_session: AsyncSession) -> None:
    existant = await _creer_utilisateur(db_session, telegram_user_id=7105)

    deposant = await rattacher_ou_creer_deposant(
        db_session, _entrant(expediteur_id=7105, expediteur_nom="autre-nom")
    )

    assert deposant is not None
    assert deposant.id == existant.id
    assert deposant.nom_affichage == "Agent Testeur"
    assert len(await _comptes_du_telegram(db_session, 7105)) == 1


async def test_compte_desactive_refuse_sans_creation(db_session: AsyncSession) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=7106, actif=False)

    deposant = await rattacher_ou_creer_deposant(
        db_session, _entrant(expediteur_id=7106)
    )

    assert deposant is None
    comptes = await _comptes_du_telegram(db_session, 7106)
    assert len(comptes) == 1
    assert comptes[0].is_active is False


async def test_sans_identifiant_telegram_rien_n_est_cree(
    db_session: AsyncSession,
) -> None:
    avant = (
        await db_session.execute(select(func.count()).select_from(Utilisateur))
    ).scalar_one()

    deposant = await rattacher_ou_creer_deposant(
        db_session, _entrant(expediteur_id=None)
    )

    apres = (
        await db_session.execute(select(func.count()).select_from(Utilisateur))
    ).scalar_one()
    assert deposant is None
    assert apres == avant


async def test_deux_envois_simultanes_un_seul_compte(
    sessions_test: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    async def un_envoi(update_id: int) -> object:
        async with sessions_test() as session:
            return await rattacher_ou_creer_deposant(
                session, _entrant(update_id=update_id, expediteur_id=7107)
            )

    premier, second = await asyncio.gather(un_envoi(1), un_envoi(2))

    assert premier is not None and second is not None
    assert len(await _comptes_du_telegram(db_session, 7107)) == 1


async def test_refuser_compte_desactive_repond_et_supervise() -> None:
    messagerie = MessagerieFactice()
    entrant = _entrant(update_id=5, expediteur_id=7108, expediteur_nom="pseudo")

    await refuser_compte_desactive(entrant, messagerie, CHAT_SUPERVISION)

    assert messagerie.reponses == [
        (entrant.chat_id, entrant.message_id, MESSAGE_COMPTE_DESACTIVE, None)
    ]
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION
    assert "7108" in texte
    assert "désactivé" in texte


async def test_refuser_compte_desactive_echecs_d_envoi_ne_levent_pas() -> None:
    messagerie = MessagerieFactice(echoue_envoyer=True, echoue_repondre=True)

    await refuser_compte_desactive(
        _entrant(expediteur_id=7109), messagerie, CHAT_SUPERVISION
    )

    assert messagerie.reponses == []
    assert messagerie.supervisions == []
