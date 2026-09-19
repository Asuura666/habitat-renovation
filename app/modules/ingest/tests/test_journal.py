"""Tests de `ingest/journal.py` (L5-T9) : lecture filtrée et paginée du
journal de traçabilité.

Base de test réelle (`bl_test`/`bl_test_wt`), données entièrement inventées
(R7 du lot 3). `db_session` (fixture locale, `app/modules/ingest/tests
/conftest.py`) vide toutes les tables après chaque test : aucun nettoyage
manuel nécessaire ici.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.journal import JournalLue, lister_journal
from app.modules.ingest.models import Journal, Utilisateur

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_BASE_TEMPS = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _instant(decalage_s: int) -> datetime:
    """Horodatage déterministe, distinct par appel (voir
    `ingest.tests.test_anomalies`/`test_lecture`) : nécessaire pour tester le
    tri, `func.now()` étant identique pour toutes les lignes d'une même
    transaction."""
    return _BASE_TEMPS + timedelta(seconds=decalage_s)


async def _creer_utilisateur(
    db_session: AsyncSession,
    *,
    role: str = "admin",
    nom: str | None = "Nom Testeur",
    email: str | None = None,
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=email or f"{role}.{uuid.uuid4()}@example.invalid",
        role=role,
        nom=nom,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _creer_entree(
    db_session: AsyncSession,
    *,
    utilisateur_id: uuid.UUID | None = None,
    action: str = "document_valide",
    cible_table: str | None = "document",
    cible_id: str | None = None,
    avant: dict[str, object] | None = None,
    apres: dict[str, object] | None = None,
    horodatage: datetime | None = None,
) -> Journal:
    entree = Journal(
        utilisateur_id=utilisateur_id,
        action=action,
        cible_table=cible_table,
        cible_id=cible_id or str(uuid.uuid4()),
        avant=avant,
        apres=apres,
    )
    if horodatage is not None:
        entree.horodatage = horodatage
    db_session.add(entree)
    await db_session.commit()
    await db_session.refresh(entree)
    return entree


@pytest.fixture
async def jeu_journal(db_session: AsyncSession) -> dict[str, object]:
    """Trois entrées bien distinctes (auteur, action, table cible, période) :
    de quoi tester chaque filtre séparément, en combinaison, et une entrée
    à auteur nul (décision automatique, convention du projet depuis le
    lot 1)."""
    admin = await _creer_utilisateur(db_session, role="admin", nom="Alice Admin")
    agent_sans_nom = await _creer_utilisateur(
        db_session, role="agent", nom=None, email="agent.sansnom@example.invalid"
    )

    entree_admin = await _creer_entree(
        db_session,
        utilisateur_id=admin.id,
        action="document_valide",
        cible_table="document",
        avant={"statut": "a_verifier"},
        apres={"statut": "recu"},
        horodatage=_instant(0),
    )
    entree_agent = await _creer_entree(
        db_session,
        utilisateur_id=agent_sans_nom.id,
        action="facture_deposee",
        cible_table="document",
        avant=None,
        apres={"numero": "F-INVENTE-1"},
        horodatage=_instant(10),
    )
    entree_automatique = await _creer_entree(
        db_session,
        utilisateur_id=None,
        action="anomalie_levee",
        cible_table="anomalie",
        avant={"regle": "R10"},
        apres=None,
        horodatage=_instant(20),
    )

    return {
        "admin": admin,
        "agent_sans_nom": agent_sans_nom,
        "entree_admin": entree_admin,
        "entree_agent": entree_agent,
        "entree_automatique": entree_automatique,
    }


# --------------------------------------------------------------------------
# Filtres, séparément
# --------------------------------------------------------------------------


async def test_lister_journal_filtre_utilisateur_id(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    admin = jeu_journal["admin"]
    assert isinstance(admin, Utilisateur)

    resultat = await lister_journal(db_session, utilisateur_id=admin.id)

    ok = len(resultat) == 1 and resultat[0].action == "document_valide"
    assert ok


async def test_lister_journal_filtre_action(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    resultat = await lister_journal(db_session, action="facture_deposee")

    ok = len(resultat) == 1 and resultat[0].action == "facture_deposee"
    assert ok


async def test_lister_journal_filtre_cible_table(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    resultat = await lister_journal(db_session, cible_table="anomalie")

    ok = len(resultat) == 1 and resultat[0].action == "anomalie_levee"
    assert ok


async def test_lister_journal_filtre_depuis(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    resultat = await lister_journal(db_session, depuis=_instant(15))

    ok = len(resultat) == 1 and resultat[0].action == "anomalie_levee"
    assert ok


async def test_lister_journal_filtre_jusqu_a(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    resultat = await lister_journal(db_session, jusqu_a=_instant(5))

    ok = len(resultat) == 1 and resultat[0].action == "document_valide"
    assert ok


# --------------------------------------------------------------------------
# Filtres combinés
# --------------------------------------------------------------------------


async def test_lister_journal_filtres_combines(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    agent_sans_nom = jeu_journal["agent_sans_nom"]
    assert isinstance(agent_sans_nom, Utilisateur)

    resultat = await lister_journal(
        db_session,
        utilisateur_id=agent_sans_nom.id,
        cible_table="document",
        depuis=_instant(5),
        jusqu_a=_instant(15),
    )

    ok = len(resultat) == 1 and resultat[0].action == "facture_deposee"
    assert ok


async def test_lister_journal_filtres_combines_aucun_resultat(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    admin = jeu_journal["admin"]
    assert isinstance(admin, Utilisateur)

    # L'auteur existe, mais pas avec cette action : l'intersection est vide.
    resultat = await lister_journal(
        db_session, utilisateur_id=admin.id, action="facture_deposee"
    )

    assert resultat == []


# --------------------------------------------------------------------------
# Plafond de pagination
# --------------------------------------------------------------------------


async def test_lister_journal_limite(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    resultat = await lister_journal(db_session, limite=2)

    assert len(resultat) == 2


# --------------------------------------------------------------------------
# Ordre : le plus récent d'abord, `id` en clé de départage
# --------------------------------------------------------------------------


async def test_lister_journal_tri_horodatage_decroissant(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    resultat = await lister_journal(db_session)

    ok = [entree.action for entree in resultat] == [
        "anomalie_levee",
        "facture_deposee",
        "document_valide",
    ]
    assert ok, "le plus récent (horodatage le plus grand) doit venir en premier"


async def test_lister_journal_tri_stable_a_horodatage_egal(
    db_session: AsyncSession,
) -> None:
    """Deux entrées au même `horodatage` (même transaction applicative,
    ex. les trois écritures `extraction_bl` d'un même document) : `id` en
    clé de départage pour un ordre stable et reproductible d'un appel à
    l'autre (décision du contrôleur), pas un ordre indéfini du moteur."""
    meme_instant = _instant(0)
    entree_1 = await _creer_entree(
        db_session, action="extraction_bl", horodatage=meme_instant
    )
    entree_2 = await _creer_entree(
        db_session, action="extraction_bl", horodatage=meme_instant
    )

    resultat = await lister_journal(db_session)

    ordre_attendu = sorted([entree_1.id, entree_2.id], reverse=True)
    ok = [entree.id for entree in resultat] == ordre_attendu
    assert ok, "à horodatage égal, l'ordre doit être celui de `id` décroissant"


# --------------------------------------------------------------------------
# Auteur nul (décision automatique) et résolution du nom
# --------------------------------------------------------------------------


async def test_lister_journal_entree_automatique_auteur_nul(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    """Convention du projet depuis le lot 1 : une décision automatique a
    `utilisateur_id = NULL` — ce service la renvoie telle quelle
    (`auteur is None`), sans la traduire en un libellé (`Journal.tsx`,
    décision du contrôleur)."""
    resultat = await lister_journal(db_session, action="anomalie_levee")

    ok = (
        len(resultat) == 1
        and resultat[0].utilisateur_id is None
        and resultat[0].auteur is None
    )
    assert ok


async def test_lister_journal_resout_le_nom_de_l_auteur(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    resultat = await lister_journal(db_session, action="document_valide")

    ok = len(resultat) == 1 and resultat[0].auteur == "Alice Admin"
    assert ok


async def test_lister_journal_resout_l_email_a_defaut_de_nom(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    """`coalesce(nom, email)`, même mécanique qu'`AnomalieLue.traitee_par` :
    un utilisateur sans `nom` renseigné est identifié par son e-mail."""
    resultat = await lister_journal(db_session, action="facture_deposee")

    ok = len(resultat) == 1 and resultat[0].auteur == "agent.sansnom@example.invalid"
    assert ok


# --------------------------------------------------------------------------
# `avant`/`apres` exposés tels quels
# --------------------------------------------------------------------------


async def test_lister_journal_expose_avant_apres_tels_quels(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    resultat = await lister_journal(db_session, action="document_valide")

    lue = resultat[0]
    ok = (
        isinstance(lue, JournalLue)
        and lue.avant == {"statut": "a_verifier"}
        and lue.apres == {"statut": "recu"}
    )
    assert ok


async def test_lister_journal_expose_apres_nul(
    db_session: AsyncSession, jeu_journal: dict[str, object]
) -> None:
    """Une entrée sans `apres` (ex. `anomalie_levee`) garde `apres is None` —
    jamais un dictionnaire vide qui laisserait croire à une valeur
    calculée."""
    resultat = await lister_journal(db_session, action="anomalie_levee")

    ok = len(resultat) == 1 and resultat[0].apres is None
    assert ok
