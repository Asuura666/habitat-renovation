"""Migration 0008 (`migrations/versions/0008_anomalie_bloc_origine.py`,
Ruling L5-R6, tour de correction 2 de L5-T1) : migration de données pure qui
répare `bloc_id` sur les anomalies R07/R08/R09/R13/R17 enregistrées avant le
Ruling L5-R3 (tour de correction 1, `ingest/rapprochement.py`) — voir le
docstring de la migration pour le constat complet.

Tourne sur la base de migrations dédiée (même mécanisme que
`tests/test_migrations.py` : `command.downgrade`/`command.upgrade`
déplacent l'état des migrations, ce que `bl_test`, censée toujours rester à
`head` pour le reste de la suite, ne doit jamais subir). Depuis L5-T11, le
modèle ORM `Document` porte des colonnes absentes aux révisions 0007/0008 :
les fixtures historiques utilisent donc du SQL explicite limité aux colonnes
de l'époque, afin de réellement tester l'ancien schéma.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import ALEMBIC_INI, preparer_base, url_base_migrations

pytestmark = pytest.mark.db


def _config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["sqlalchemy_url"] = url
    return config


async def _inserer_scenario_pre_migration(
    url: str, *, regle: str, avec_collision: bool = False
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]:
    """Insère une anomalie historique sans bloc et, facultativement, la ligne
    déjà corrigée qui entrerait en collision avec elle pendant l'upgrade."""
    fournisseur_id = uuid.uuid4()
    facture_id = uuid.uuid4()
    bloc_id = uuid.uuid4()
    ligne_id = uuid.uuid4()
    anomalie_id = uuid.uuid4()
    collision_id = uuid.uuid4() if avec_collision else None
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connexion:
            await connexion.execute(
                text("INSERT INTO fournisseur (id, nom) VALUES (:id, :nom)"),
                {
                    "id": fournisseur_id,
                    "nom": f"Fournisseur Migration 0008 {uuid.uuid4()}",
                },
            )
            await connexion.execute(
                text(
                    "INSERT INTO document "
                    "(id, type, source, statut, fichier_path, fournisseur_id) "
                    "VALUES (:id, 'facture', 'upload', 'recu', :chemin, :fournisseur)"
                ),
                {
                    "id": facture_id,
                    "chemin": f"chemin-invente-migration-0008-{uuid.uuid4()}.pdf",
                    "fournisseur": fournisseur_id,
                },
            )
            await connexion.execute(
                text(
                    "INSERT INTO bloc_facture (id, facture_id, ordre) "
                    "VALUES (:id, :facture, 0)"
                ),
                {"id": bloc_id, "facture": facture_id},
            )
            await connexion.execute(
                text(
                    "INSERT INTO ligne "
                    "(id, document_id, bloc_id, type_ligne, ordre, montant_ht) "
                    "VALUES (:id, :document, :bloc, 'article', 0, 12.00)"
                ),
                {"id": ligne_id, "document": facture_id, "bloc": bloc_id},
            )
            await connexion.execute(
                text(
                    "INSERT INTO anomalie "
                    "(id, regle, gravite, statut, ligne_id, bloc_id, detail, "
                    "traitee_le, commentaire) VALUES "
                    "(:id, :regle, 'moyenne', 'traitee', :ligne, NULL, "
                    "CAST(:detail AS jsonb), :traitee_le, :commentaire)"
                ),
                {
                    "id": anomalie_id,
                    "regle": regle,
                    "ligne": ligne_id,
                    "detail": json.dumps({"cle": "valeur historique"}),
                    "traitee_le": datetime.now(UTC),
                    "commentaire": (
                        "Traitée avant le Ruling L5-R3 (test migration 0008)."
                    ),
                },
            )
            if collision_id is not None:
                await connexion.execute(
                    text(
                        "INSERT INTO anomalie "
                        "(id, regle, gravite, statut, ligne_id, bloc_id, detail) "
                        "VALUES (:id, :regle, 'moyenne', 'ouverte', :ligne, "
                        ":bloc, CAST(:detail AS jsonb))"
                    ),
                    {
                        "id": collision_id,
                        "regle": regle,
                        "ligne": ligne_id,
                        "bloc": bloc_id,
                        "detail": json.dumps({"cle": "valeur déjà corrigée"}),
                    },
                )
        return anomalie_id, bloc_id, collision_id
    finally:
        await engine.dispose()


async def _inserer_anomalie_pre_migration(url: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Reproduit une anomalie R07 historique traitée sans `bloc_id`."""
    anomalie_id, bloc_id, _ = await _inserer_scenario_pre_migration(url, regle="R07")
    return anomalie_id, bloc_id


@dataclass(frozen=True)
class _AnomalieLue:
    bloc_id: uuid.UUID | None
    statut: str


async def _lire_anomalie(url: str, anomalie_id: uuid.UUID) -> _AnomalieLue:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connexion:
            ligne = (
                await connexion.execute(
                    text(
                        "SELECT bloc_id, statut FROM anomalie WHERE id = :identifiant"
                    ),
                    {"identifiant": anomalie_id},
                )
            ).one_or_none()
            if ligne is None:
                pytest.fail(f"anomalie {anomalie_id} introuvable après migration")
            return _AnomalieLue(bloc_id=ligne.bloc_id, statut=ligne.statut)
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


def test_migration_0008_upgrade_ne_touche_pas_une_autre_regle(
    test_database_url: str,
) -> None:
    """L'upgrade est limité aux cinq règles réparées par la migration."""
    url = url_base_migrations(test_database_url)
    preparer_base(url)
    command.downgrade(_config(url), "0007")
    try:
        anomalie_id, _bloc_id, _ = asyncio.run(
            _inserer_scenario_pre_migration(url, regle="R03")
        )

        command.upgrade(_config(url), "0008")

        anomalie = asyncio.run(_lire_anomalie(url, anomalie_id))
        assert anomalie.bloc_id is None
        assert anomalie.statut == "traitee"
    finally:
        command.upgrade(_config(url), "head")


def test_migration_0008_collision_est_non_destructive(
    test_database_url: str,
) -> None:
    """Une ligne déjà corrigée ne doit ni faire échouer ni détruire l'historique."""
    url = url_base_migrations(test_database_url)
    preparer_base(url)
    command.downgrade(_config(url), "0007")
    try:
        historique_id, bloc_id, collision_id = asyncio.run(
            _inserer_scenario_pre_migration(url, regle="R07", avec_collision=True)
        )
        assert collision_id is not None

        command.upgrade(_config(url), "0008")

        historique = asyncio.run(_lire_anomalie(url, historique_id))
        deja_corrigee = asyncio.run(_lire_anomalie(url, collision_id))
        assert historique.bloc_id is None
        assert historique.statut == "traitee"
        assert deja_corrigee.bloc_id == bloc_id
        assert deja_corrigee.statut == "ouverte"
    finally:
        command.upgrade(_config(url), "head")
