"""Tests de `ingest/referentiels_vue.py` (L5-T7) : dépôts par agent sur une
fenêtre glissante, chantiers sans dépôt depuis plus que le seuil configuré,
agences connues.

Base de test réelle (`bl_test_wt`, arbre de travail), données entièrement
inventées (R17). `db_session` (fixture locale, `app/modules/ingest/tests
/conftest.py`) vide toutes les tables après chaque test.

Les seuils temporels ne sont pas injectés (la fiche ne donne aucun
paramètre `maintenant` aux fonctions testées, à la différence de
`ingest.suivi.controles_differes`) : comme `ingest.anomalies
.synchroniser_anomalies` (règle des 90 jours, `test_anomalies.py`), les
horodatages de test sont construits relativement à `datetime.now(UTC)`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.models import Chantier, Document, Parametre, Utilisateur
from app.modules.ingest.referentiels_vue import (
    DEPOTS_PAR_AGENT_JOURS_DEFAUT,
    ChantierSilencieux,
    DepotAgent,
    agences_connues,
    chantiers_sans_depot,
    depots_par_agent,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _creer_utilisateur(
    db_session: AsyncSession, *, role: str = "agent", nom: str | None = "Agent Testeur"
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=f"{role}.{uuid.uuid4()}@example.invalid",
        role=role,
        nom=nom,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    await db_session.refresh(utilisateur)
    return utilisateur


async def _creer_chantier(
    db_session: AsyncSession,
    *,
    nom: str = "Chantier Testeur",
    agence: str | None = None,
    actif: bool = True,
    ferme_le: date | None = None,
) -> Chantier:
    chantier = Chantier(
        nom_canonique=nom, agence=agence, actif=actif, ferme_le=ferme_le
    )
    db_session.add(chantier)
    await db_session.commit()
    await db_session.refresh(chantier)
    return chantier


async def _creer_document(
    db_session: AsyncSession,
    *,
    type_: str = "bl",
    statut: str = "recu",
    deposant: Utilisateur | None = None,
    chantier_id: uuid.UUID | None = None,
    created_at: datetime,
) -> Document:
    document = Document(
        type=type_,
        source="telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        deposant_id=deposant.id if deposant is not None else None,
        chantier_id=chantier_id,
        created_at=created_at,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


def _il_y_a(jours: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=jours)


# ---------------------------------------------------------------------------
# depots_par_agent
# ---------------------------------------------------------------------------


async def test_depots_par_agent_agent_sans_depot_apparait_avec_zero(
    db_session: AsyncSession,
) -> None:
    agent = await _creer_utilisateur(db_session, nom="Agent Sans Dépôt")

    resultat = await depots_par_agent(db_session)

    assert resultat == [
        DepotAgent(
            agent_id=agent.id,
            nom="Agent Sans Dépôt",
            email=agent.email,
            nombre_depots=0,
        )
    ]


async def test_depots_par_agent_depot_hors_fenetre_non_compte(
    db_session: AsyncSession,
) -> None:
    agent = await _creer_utilisateur(db_session)
    await _creer_document(db_session, deposant=agent, created_at=_il_y_a(5))
    await _creer_document(db_session, deposant=agent, created_at=_il_y_a(40))

    resultat = await depots_par_agent(db_session, jours=30)

    assert resultat == [
        DepotAgent(agent_id=agent.id, nom=agent.nom, email=agent.email, nombre_depots=1)
    ]


async def test_depots_par_agent_compte_quel_que_soit_le_statut(
    db_session: AsyncSession,
) -> None:
    agent = await _creer_utilisateur(db_session)
    await _creer_document(
        db_session, deposant=agent, statut="archive", created_at=_il_y_a(1)
    )

    resultat = await depots_par_agent(db_session, jours=30)

    assert resultat == [
        DepotAgent(agent_id=agent.id, nom=agent.nom, email=agent.email, nombre_depots=1)
    ]


async def test_depots_par_agent_administrateur_sans_depot_est_absent(
    db_session: AsyncSession,
) -> None:
    """Le rôle sert à composer la liste de référence (tout agent), jamais à
    filtrer les dépôts eux-mêmes (Ruling L5-R7, tour de correction 1) : un
    administrateur qui n'a rien déposé n'a pas sa place ici pour autant —
    il n'est pas un agent de terrain suivi par ce tableau."""
    await _creer_utilisateur(db_session, role="admin", nom="Admin Testeur")

    resultat = await depots_par_agent(db_session)

    assert resultat == []


async def test_depots_par_agent_administrateur_ayant_depose_apparait(
    db_session: AsyncSession,
) -> None:
    """Ruling L5-R7 (tour de correction 1) : un bon de livraison peut être
    déposé par un compte administrateur (le rattachement Telegram ne
    regarde pas le rôle). Ce dépôt ne doit jamais disparaître silencieusement
    d'une vue — l'administrateur apparaît donc ici, avec son compte réel de
    dépôts, alors qu'il n'est pas un agent."""
    admin = await _creer_utilisateur(db_session, role="admin", nom="Admin Déposant")
    await _creer_document(db_session, deposant=admin, created_at=_il_y_a(1))

    resultat = await depots_par_agent(db_session)

    assert resultat == [
        DepotAgent(agent_id=admin.id, nom=admin.nom, email=admin.email, nombre_depots=1)
    ]


async def test_depots_par_agent_serre_la_limite_du_jour_parisien(
    db_session: AsyncSession,
) -> None:
    """Tour de correction 1, point 3 : les marges précédentes (5 jours
    contre une fenêtre de 30) ne détecteraient pas une régression vers une
    soustraction naïve en UTC. Un dépôt une minute avant minuit
    (Europe/Paris) du premier jour de la fenêtre n'est pas compté ; un
    dépôt une minute après l'est — alors que les deux instants tombent le
    même jour civil en UTC (Europe/Paris est toujours en avance sur UTC
    d'au moins une heure, hiver comme été) : une régression qui calculerait
    cette borne à partir du minuit **UTC** du même jour civil, au lieu du
    minuit **parisien**, ferait échouer ce test."""
    agent = await _creer_utilisateur(db_session)
    jours = DEPOTS_PAR_AGENT_JOURS_DEFAUT
    premier_jour_fenetre = datetime.now(FUSEAU_PARIS).date() - timedelta(days=jours)
    minuit_paris = datetime.combine(premier_jour_fenetre, time.min, tzinfo=FUSEAU_PARIS)

    await _creer_document(
        db_session, deposant=agent, created_at=minuit_paris - timedelta(minutes=1)
    )
    await _creer_document(
        db_session, deposant=agent, created_at=minuit_paris + timedelta(minutes=1)
    )

    resultat = await depots_par_agent(db_session, jours=jours)

    assert resultat == [
        DepotAgent(agent_id=agent.id, nom=agent.nom, email=agent.email, nombre_depots=1)
    ]


# ---------------------------------------------------------------------------
# chantiers_sans_depot
# ---------------------------------------------------------------------------


async def test_chantiers_sans_depot_signale_le_chantier_ancien(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Chantier Ancien")
    await _creer_document(db_session, chantier_id=chantier.id, created_at=_il_y_a(10))

    # Seuil par défaut (aucune ligne `parametre`) : 7 jours -> 10 jours de
    # silence dépasse le seuil.
    resultat = await chantiers_sans_depot(db_session)

    ids = {c.chantier_id for c in resultat}
    assert chantier.id in ids


async def test_chantiers_sans_depot_recent_non_signale(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Chantier Récent")
    await _creer_document(db_session, chantier_id=chantier.id, created_at=_il_y_a(1))

    resultat = await chantiers_sans_depot(db_session)

    ids = {c.chantier_id for c in resultat}
    assert chantier.id not in ids


async def test_chantiers_sans_depot_jamais_depose_est_signale(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Chantier Jamais Servi")

    resultat = await chantiers_sans_depot(db_session)

    lignes = {c.chantier_id: c for c in resultat}
    assert chantier.id in lignes
    assert lignes[chantier.id] == ChantierSilencieux(
        chantier_id=chantier.id,
        nom_canonique="Chantier Jamais Servi",
        agence=None,
        dernier_depot_le=None,
    )


async def test_chantiers_sans_depot_chantier_ferme_non_signale(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(
        db_session,
        nom="Chantier Fermé",
        ferme_le=datetime.now(FUSEAU_PARIS).date() - timedelta(days=1),
    )
    await _creer_document(db_session, chantier_id=chantier.id, created_at=_il_y_a(365))

    resultat = await chantiers_sans_depot(db_session)

    ids = {c.chantier_id for c in resultat}
    assert chantier.id not in ids


async def test_chantiers_sans_depot_chantier_inactif_non_signale(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Chantier Inactif", actif=False)
    await _creer_document(db_session, chantier_id=chantier.id, created_at=_il_y_a(365))

    resultat = await chantiers_sans_depot(db_session)

    ids = {c.chantier_id for c in resultat}
    assert chantier.id not in ids


async def test_chantiers_sans_depot_seuil_lu_depuis_parametre(
    db_session: AsyncSession,
) -> None:
    """Le seuil est bien lu depuis la table `parametre` : un chantier
    silencieux depuis 10 jours est signalé avec le seuil par défaut (7
    jours), mais ne l'est plus une fois le seuil relevé à 15 jours."""
    chantier = await _creer_chantier(db_session, nom="Chantier Seuil")
    await _creer_document(db_session, chantier_id=chantier.id, created_at=_il_y_a(10))

    avant = {c.chantier_id for c in await chantiers_sans_depot(db_session)}
    assert chantier.id in avant

    db_session.add(Parametre(cle="delai_chantier_silencieux_j", valeur="15"))
    await db_session.commit()

    apres = {c.chantier_id for c in await chantiers_sans_depot(db_session)}
    assert chantier.id not in apres


async def test_chantiers_sans_depot_tri_ordonne_par_chantier_id_dans_la_requete_sql(
    db_session: AsyncSession,
) -> None:
    """Tour de correction 1, point 2 : `nom_canonique` n'est pas garanti
    unique en base, donc `chantier_id` doit apparaître comme dernière clé de
    l'`ORDER BY` généré par la requête (même correctif que `ingest.bilan
    .bilan_par_chantier`, tour de correction 1) — sinon deux chantiers
    silencieux de même nom pourraient s'échanger d'un appel à l'autre.

    Vérifié sur le texte SQL compilé, pas sur l'ordre observé : avec deux
    lignes seulement, Postgres peut renvoyer un ordre déjà croissant même
    sans départage explicite, ce qui rendrait un test purement
    comportemental peu fiable ici (même remarque que
    `test_bilan.py::test_bilan_tri_ordonne_par_chantier_id_dans_la_requete_sql`)."""
    await _creer_chantier(db_session, nom="Chantier Homonyme")

    instructions: list[str] = []

    def _capturer(
        conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any
    ) -> None:
        instructions.append(statement)

    moteur_sync = db_session.get_bind()
    event.listen(moteur_sync, "before_cursor_execute", _capturer)
    try:
        await chantiers_sans_depot(db_session)
    finally:
        event.remove(moteur_sync, "before_cursor_execute", _capturer)

    requetes_avec_tri = [sql for sql in instructions if "ORDER BY" in sql]
    ok = (
        len(requetes_avec_tri) == 1
        and "chantier.id" in requetes_avec_tri[0].split("ORDER BY", 1)[1]
    )
    assert ok, "chantier_id doit être une clé de l'ORDER BY généré par la requête"


# ---------------------------------------------------------------------------
# agences_connues
# ---------------------------------------------------------------------------


async def test_agences_connues_base_sans_agence_renvoie_liste_vide(
    db_session: AsyncSession,
) -> None:
    await _creer_chantier(db_session, nom="Chantier Sans Agence", agence=None)

    resultat = await agences_connues(db_session)

    assert resultat == []


async def test_agences_connues_valeurs_distinctes_triees(
    db_session: AsyncSession,
) -> None:
    await _creer_chantier(db_session, nom="Chantier Nord 1", agence="Agence Nord")
    await _creer_chantier(db_session, nom="Chantier Nord 2", agence="Agence Nord")
    await _creer_chantier(db_session, nom="Chantier Sud", agence="Agence Sud")
    await _creer_chantier(db_session, nom="Chantier Vide", agence="")
    await _creer_chantier(db_session, nom="Chantier Aucune", agence=None)

    resultat = await agences_connues(db_session)

    assert resultat == ["Agence Nord", "Agence Sud"]
