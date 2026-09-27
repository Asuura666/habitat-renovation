"""Tests des cinq tables de l'IA (migration 0014, tâche T1 de
`docs/superpowers/specs/2026-09-27-phase-4-ia-design.md`) : contraintes de
base uniquement (unicité, cascades, `CHECK`) -- aucun service n'existe
encore pour ces tables (tâches suivantes du plan). Base de test réelle
(`bl_test`), données entièrement inventées.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import (
    Anomalie,
    AppelIA,
    ExplicationAlerte,
    Fournisseur,
    PrixInternet,
    SyntheseAction,
    SyntheseCommentaires,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


async def _creer_anomalie(db_session: AsyncSession, *, regle: str = "R99") -> Anomalie:
    anomalie = Anomalie(
        regle=regle,
        gravite="basse",
        detail={"ecart": "1"},
        statut="ouverte",
    )
    db_session.add(anomalie)
    await db_session.flush()
    return anomalie


async def _creer_synthese(
    db_session: AsyncSession, *, semaine_debut: date = date(2026, 9, 21)
) -> SyntheseCommentaires:
    synthese = SyntheseCommentaires(
        semaine_debut=semaine_debut,
        semaine_fin=semaine_debut + timedelta(days=6),
        statut="ok",
        resume="Résumé inventé de la semaine.",
        nb_commentaires=2,
    )
    db_session.add(synthese)
    await db_session.flush()
    return synthese


# --------------------------------------------------------------------------
# synthese_commentaires -- unicité de semaine_debut
# --------------------------------------------------------------------------


async def test_semaine_debut_unique(db_session: AsyncSession) -> None:
    await _creer_synthese(db_session, semaine_debut=date(2026, 9, 21))
    await db_session.commit()

    db_session.add(
        SyntheseCommentaires(
            semaine_debut=date(2026, 9, 21),
            semaine_fin=date(2026, 9, 27),
            statut="vide",
            resume="Autre résumé inventé.",
            nb_commentaires=0,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_periode_invalide_refusee(db_session: AsyncSession) -> None:
    """`semaine_fin` avant `semaine_debut` : refusé par le `CHECK`."""
    db_session.add(
        SyntheseCommentaires(
            semaine_debut=date(2026, 9, 21),
            semaine_fin=date(2026, 9, 20),
            statut="ok",
            resume="Résumé inventé.",
            nb_commentaires=1,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# --------------------------------------------------------------------------
# synthese_commentaires -> synthese_action : cascade
# --------------------------------------------------------------------------


async def test_suppression_synthese_supprime_ses_actions(
    db_session: AsyncSession,
) -> None:
    synthese = await _creer_synthese(db_session)
    action = SyntheseAction(
        synthese_id=synthese.id,
        ordre=0,
        texte="Rappeler le fournisseur inventé.",
        commentaire_ids=[str(uuid.uuid4())],
        document_ids=[str(uuid.uuid4())],
    )
    db_session.add(action)
    await db_session.commit()
    action_id = action.id

    await db_session.delete(synthese)
    await db_session.commit()

    # `select` (round-trip base) et non `session.get` : la ligne est encore
    # dans l'identity map de la session, qui la renverrait sans requêter la
    # base -- même précaution que `test_commentaires.py`.
    resultat = await db_session.execute(
        select(SyntheseAction).where(SyntheseAction.id == action_id)
    )
    assert resultat.scalar_one_or_none() is None


async def test_action_texte_vide_refuse(db_session: AsyncSession) -> None:
    synthese = await _creer_synthese(db_session)
    db_session.add(
        SyntheseAction(
            synthese_id=synthese.id,
            ordre=0,
            texte="",
            commentaire_ids=[],
            document_ids=[],
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# --------------------------------------------------------------------------
# anomalie -> explication_alerte : cascade et unicité
# --------------------------------------------------------------------------


async def test_suppression_anomalie_supprime_son_explication(
    db_session: AsyncSession,
) -> None:
    anomalie = await _creer_anomalie(db_session)
    explication = ExplicationAlerte(
        anomalie_id=anomalie.id,
        empreinte_detail="empreinte-inventee",
        statut="ok",
        texte="Explication inventée.",
    )
    db_session.add(explication)
    await db_session.commit()
    explication_id = explication.id

    await db_session.delete(anomalie)
    await db_session.commit()

    resultat = await db_session.execute(
        select(ExplicationAlerte).where(ExplicationAlerte.id == explication_id)
    )
    assert resultat.scalar_one_or_none() is None


async def test_explication_anomalie_unique(db_session: AsyncSession) -> None:
    anomalie = await _creer_anomalie(db_session)
    db_session.add(
        ExplicationAlerte(
            anomalie_id=anomalie.id,
            empreinte_detail="empreinte-inventee",
            statut="ok",
            texte="Explication inventée.",
        )
    )
    await db_session.commit()

    db_session.add(
        ExplicationAlerte(
            anomalie_id=anomalie.id,
            empreinte_detail="autre-empreinte",
            statut="ok",
            texte="Autre explication inventée.",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_explication_ok_sans_texte_refusee(db_session: AsyncSession) -> None:
    anomalie = await _creer_anomalie(db_session)
    db_session.add(
        ExplicationAlerte(
            anomalie_id=anomalie.id,
            empreinte_detail="empreinte-inventee",
            statut="ok",
            texte=None,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# --------------------------------------------------------------------------
# prix_internet -- statut 'trouve' sans prix ni source
# --------------------------------------------------------------------------


async def test_prix_internet_trouve_sans_prix_refuse(db_session: AsyncSession) -> None:
    fournisseur = Fournisseur(nom="Fournisseur inventé prix internet")
    db_session.add(fournisseur)
    await db_session.flush()

    db_session.add(
        PrixInternet(
            fournisseur_id=fournisseur.id,
            cle="fournisseur-inventé|produit-invente",
            designation="Produit inventé",
            statut="trouve",
            prix=None,
            source_url=None,
            consulte_le=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_prix_internet_trouve_avec_prix_et_source_accepte(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        PrixInternet(
            fournisseur_id=None,
            cle="produit-invente",
            designation="Produit inventé",
            statut="trouve",
            prix=Decimal("12.34"),
            devise="EUR",
            taxes="TTC",
            source_url="https://exemple.invalid/produit",
            confiance="moyenne",
            consulte_le=datetime.now(UTC),
        )
    )
    await db_session.commit()


async def test_prix_internet_prix_negatif_refuse(db_session: AsyncSession) -> None:
    db_session.add(
        PrixInternet(
            cle="produit-invente-negatif",
            designation="Produit inventé",
            statut="non_verifiable",
            prix=Decimal("-1"),
            raison="prix inventé négatif",
            consulte_le=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# --------------------------------------------------------------------------
# appel_ia -- usage inconnu
# --------------------------------------------------------------------------


async def test_appel_ia_usage_inconnu_refuse(db_session: AsyncSession) -> None:
    db_session.add(AppelIA(usage="inconnu", statut="ok", duree_ms=10))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_appel_ia_statut_inconnu_refuse(db_session: AsyncSession) -> None:
    db_session.add(AppelIA(usage="synthese", statut="inconnu", duree_ms=10))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_appel_ia_valide_accepte(db_session: AsyncSession) -> None:
    appel = AppelIA(
        usage="prix", statut="erreur", erreur="delai_depasse", duree_ms=5000
    )
    db_session.add(appel)
    await db_session.commit()

    relu = (
        await db_session.execute(select(AppelIA).where(AppelIA.id == appel.id))
    ).scalar_one()
    assert relu.usage == "prix"
    assert relu.statut == "erreur"
