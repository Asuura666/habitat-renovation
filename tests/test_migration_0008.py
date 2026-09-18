"""Migration 0008 (`migrations/versions/0008_anomalie_bloc_origine.py`,
Ruling L5-R6, tour de correction 2 de L5-T1) : migration de données pure qui
répare `bloc_id` sur les anomalies R07/R08/R09/R13/R17 enregistrées avant le
Ruling L5-R3 (tour de correction 1, `ingest/rapprochement.py`) — voir le
docstring de la migration pour le constat complet.

Tourne sur la base de migrations dédiée (même mécanisme que
`tests/test_migrations.py` : `command.downgrade`/`command.upgrade`
déplacent l'état des migrations, ce que `bl_test`, censée toujours rester à
`head` pour le reste de la suite, ne doit jamais subir). Le schéma de
`anomalie`/`ligne`/`bloc_facture`/`document`/`fournisseur` est identique
entre la révision `0007` et `head` (migration 0008 : « aucune modification
de schéma ») : les modèles ORM peuvent donc être utilisés tels quels pour
préparer une base ramenée à `0007`, comme le ferait l'application elle-même.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db import creer_sessionmaker
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Document,
    Fournisseur,
    Ligne,
)
from tests.conftest import ALEMBIC_INI, preparer_base, url_base_migrations

pytestmark = pytest.mark.db


def _config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["sqlalchemy_url"] = url
    return config


async def _inserer_anomalie_pre_migration(url: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Reproduit l'état laissé en base par un rapprochement antérieur au
    Ruling L5-R3 : une anomalie de prix (R07) `traitee` par un humain, dont
    `bloc_id` est encore vide alors que sa ligne porte, elle, un bloc.
    Renvoie `(anomalie_id, bloc_id_attendu)`."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        sessionmaker = creer_sessionmaker(engine)
        async with sessionmaker() as session:
            fournisseur = Fournisseur(nom="Fournisseur Migration 0008")
            session.add(fournisseur)
            await session.flush()

            facture = Document(
                type="facture",
                source="upload",
                statut="recu",
                fichier_path="chemin-invente-migration-0008.pdf",
                fournisseur_id=fournisseur.id,
            )
            session.add(facture)
            await session.flush()

            bloc = BlocFacture(facture_id=facture.id, ordre=0)
            session.add(bloc)
            await session.flush()

            ligne = Ligne(
                document_id=facture.id,
                bloc_id=bloc.id,
                type_ligne="article",
                ordre=0,
                montant_ht=Decimal("12.00"),
            )
            session.add(ligne)
            await session.flush()

            anomalie = Anomalie(
                regle="R07",
                gravite="moyenne",
                statut="traitee",
                ligne_id=ligne.id,
                bloc_id=None,
                detail={"cle": "valeur"},
                traitee_le=datetime.now(UTC),
                commentaire="Traitée avant le Ruling L5-R3 (test migration 0008).",
            )
            session.add(anomalie)
            await session.commit()
            return anomalie.id, bloc.id
    finally:
        await engine.dispose()


async def _lire_anomalie(url: str, anomalie_id: uuid.UUID) -> Anomalie:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        sessionmaker = creer_sessionmaker(engine)
        async with sessionmaker() as session:
            anomalie = await session.get(Anomalie, anomalie_id)
            if anomalie is None:
                pytest.fail(f"anomalie {anomalie_id} introuvable après migration")
            return anomalie
    finally:
        await engine.dispose()


def test_migration_0008_repare_bloc_id_meme_si_anomalie_traitee(
    test_database_url: str,
) -> None:
    """Point 1 de la fiche de correction : la migration répare `bloc_id`,
    y compris quand l'anomalie est déjà `traitee` (c'est justement ces
    lignes-là qu'il faut sauver, L4-D12)."""
    url = url_base_migrations(test_database_url)
    preparer_base(url)
    command.downgrade(_config(url), "0007")
    try:
        anomalie_id, bloc_id_attendu = asyncio.run(_inserer_anomalie_pre_migration(url))

        avant = asyncio.run(_lire_anomalie(url, anomalie_id))
        assert avant.bloc_id is None, (
            "l'anomalie doit démarrer sans bloc_id (état pré-Ruling L5-R3)"
        )

        command.upgrade(_config(url), "0008")

        apres = asyncio.run(_lire_anomalie(url, anomalie_id))
        ok = apres.bloc_id == bloc_id_attendu and apres.statut == "traitee"
        assert ok, (
            "la migration doit renseigner bloc_id même sur une anomalie déjà "
            "traitee, sans changer son statut"
        )
    finally:
        command.upgrade(_config(url), "head")


def test_migration_0008_downgrade_puis_upgrade_laisse_bloc_id_dans_letat_attendu(
    test_database_url: str,
) -> None:
    """Point 4 de la fiche de correction : un aller-retour downgrade/upgrade
    laisse `bloc_id` dans l'état attendu à chaque étape (vide avant 0008,
    réparé après, remis à vide par `downgrade`, réparé de nouveau par un
    nouvel `upgrade`)."""
    url = url_base_migrations(test_database_url)
    preparer_base(url)
    command.downgrade(_config(url), "0007")
    try:
        anomalie_id, bloc_id_attendu = asyncio.run(_inserer_anomalie_pre_migration(url))

        command.upgrade(_config(url), "0008")
        repare = asyncio.run(_lire_anomalie(url, anomalie_id))
        assert repare.bloc_id == bloc_id_attendu, "upgrade doit renseigner bloc_id"

        command.downgrade(_config(url), "0007")
        redescendu = asyncio.run(_lire_anomalie(url, anomalie_id))
        assert redescendu.bloc_id is None, "downgrade doit remettre bloc_id à NULL"

        command.upgrade(_config(url), "0008")
        rerepare = asyncio.run(_lire_anomalie(url, anomalie_id))
        ok = rerepare.bloc_id == bloc_id_attendu
        assert ok, "un nouvel upgrade doit réparer bloc_id à l'identique"
    finally:
        command.upgrade(_config(url), "head")
