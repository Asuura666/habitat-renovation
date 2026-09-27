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
from app.modules.ingest.models import Chantier, Fournisseur, Journal, Utilisateur

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


# --------------------------------------------------------------------------
# Task 12 (spec §4.1) : noms au lieu des identifiants
# --------------------------------------------------------------------------


async def test_journal_resout_confirme_par_en_nom(
    db_session: AsyncSession,
) -> None:
    """`apres.confirme_par` (`depot_telegram.py::_enregistrer_confirmation`)
    est un UUID brut d'utilisateur -- `noms` doit porter son nom résolu
    (`coalesce(nom, email)`, même mécanique que `auteur`)."""
    lea = await _creer_utilisateur(db_session, nom="Léa Test")
    await _creer_entree(
        db_session,
        action="quantites_verifiees",
        cible_table="document",
        avant={"statut": "a_verifier", "confirme_le": None, "confirme_par": None},
        apres={
            "statut": "recu",
            "confirme_le": "2026-08-01T12:00:00+00:00",
            "confirme_par": str(lea.id),
        },
    )

    resultat = await lister_journal(db_session, action="quantites_verifiees")

    ok = len(resultat) == 1 and resultat[0].noms[str(lea.id)] == "Léa Test"
    assert ok


async def test_journal_resout_chantier_et_fournisseur(
    db_session: AsyncSession,
) -> None:
    """`chantier_id`/`fournisseur_id` portés par `avant`/`apres`
    (`extraction_bl.py`) résolus vers `nom_canonique`/`nom`."""
    chantier = Chantier(nom_canonique="Villa Test", agence=None, client=None)
    fournisseur = Fournisseur(nom="Unikalo Test")
    db_session.add_all([chantier, fournisseur])
    await db_session.commit()
    await db_session.refresh(chantier)
    await db_session.refresh(fournisseur)

    await _creer_entree(
        db_session,
        action="extraction_bl",
        cible_table="document",
        avant=None,
        apres={
            "statut": "recu",
            "fournisseur_id": str(fournisseur.id),
            "chantier_id": str(chantier.id),
        },
    )

    resultat = await lister_journal(db_session, action="extraction_bl")

    ok = (
        len(resultat) == 1
        and resultat[0].noms[str(chantier.id)] == "Villa Test"
        and resultat[0].noms[str(fournisseur.id)] == "Unikalo Test"
    )
    assert ok


async def test_journal_resout_cible_id_chantier_seulement_si_cible_table_chantier(
    db_session: AsyncSession,
) -> None:
    """`cible_id` d'`avant`/`apres` (distinct de `Journal.cible_id`) n'est
    résolu comme chantier que si `cible_table == "chantier"`
    (`fusion_chantier.py::fusionner_chantiers`) -- une autre table ne doit
    jamais être interprétée comme un identifiant de chantier."""
    cible = Chantier(nom_canonique="Résidence des Tilleuls", agence=None, client=None)
    db_session.add(cible)
    await db_session.commit()
    await db_session.refresh(cible)

    await _creer_entree(
        db_session,
        action="chantier_fusionne",
        cible_table="chantier",
        avant={"chantier_id": str(uuid.uuid4()), "nom": "Ancien nom"},
        apres={"cible_id": str(cible.id), "cible_nom": cible.nom_canonique},
    )
    # Même clé `cible_id`, mais une autre table cible : ne doit jamais être
    # confondue avec un identifiant de chantier.
    await _creer_entree(
        db_session,
        action="parametre_modifie",
        cible_table="parametre",
        avant=None,
        apres={"cible_id": str(cible.id)},
    )

    resultat_fusion = await lister_journal(db_session, action="chantier_fusionne")
    resultat_parametre = await lister_journal(db_session, action="parametre_modifie")

    ok = (
        len(resultat_fusion) == 1
        and resultat_fusion[0].noms[str(cible.id)] == "Résidence des Tilleuls"
        and len(resultat_parametre) == 1
        and resultat_parametre[0].noms == {}
    )
    assert ok


async def test_journal_identifiant_non_uuid_ou_introuvable_absent_de_noms(
    db_session: AsyncSession,
) -> None:
    """Une valeur non-UUID (`cible_id` d'un réglage) ou un identifiant
    inconnu en base reste simplement absent de `noms` -- jamais une clé à
    valeur `None`."""
    fournisseur_disparu = str(uuid.uuid4())
    await _creer_entree(
        db_session,
        action="extraction_bl",
        cible_table="document",
        avant=None,
        apres={
            "fournisseur_id": fournisseur_disparu,
            "chantier_libelle": "pas un uuid",
        },
    )

    resultat = await lister_journal(db_session, action="extraction_bl")

    ok = len(resultat) == 1 and resultat[0].noms == {}
    assert ok


async def test_journal_noms_en_requetes_groupees(
    db_session: AsyncSession,
) -> None:
    """Compter les requêtes n'est pas nécessaire (décision du contrôleur,
    brief Task 12) : il suffit de vérifier que trois entrées distinctes,
    référençant chacune un identifiant différent, sont toutes correctement
    résolues par un seul appel à `lister_journal` (résolution groupée par
    table, jamais une requête par entrée)."""
    admin = await _creer_utilisateur(db_session, nom="Bob Admin")
    chantier = Chantier(nom_canonique="Chantier Groupé", agence=None, client=None)
    fournisseur = Fournisseur(nom="Fournisseur Groupé")
    db_session.add_all([chantier, fournisseur])
    await db_session.commit()
    await db_session.refresh(chantier)
    await db_session.refresh(fournisseur)

    await _creer_entree(
        db_session,
        action="document_valide",
        cible_table="document",
        avant={"statut": "a_verifier", "confirme_le": None, "confirme_par": None},
        apres={"statut": "recu", "confirme_le": "x", "confirme_par": str(admin.id)},
        horodatage=_instant(0),
    )
    await _creer_entree(
        db_session,
        action="extraction_bl",
        cible_table="document",
        avant=None,
        apres={"chantier_id": str(chantier.id)},
        horodatage=_instant(1),
    )
    await _creer_entree(
        db_session,
        action="facture_deposee",
        cible_table="document",
        avant=None,
        apres={"fournisseur_id": str(fournisseur.id)},
        horodatage=_instant(2),
    )

    resultat = await lister_journal(db_session, cible_table="document", limite=10)

    par_action = {entree.action: entree for entree in resultat}
    ok = (
        len(resultat) == 3
        and par_action["document_valide"].noms[str(admin.id)] == "Bob Admin"
        and par_action["extraction_bl"].noms[str(chantier.id)] == "Chantier Groupé"
        and par_action["facture_deposee"].noms[str(fournisseur.id)]
        == "Fournisseur Groupé"
    )
    assert ok
