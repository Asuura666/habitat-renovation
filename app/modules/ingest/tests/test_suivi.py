"""Tests de `ingest/suivi.py` (L4-T11) : contrôles différés (R06, R14, R15,
R16), construction du `ContexteSuivi` depuis la base et synchronisation
idempotente de leurs anomalies via `ingest.anomalies.synchroniser_anomalies`.

Base de test réelle (`bl_test`), données entièrement inventées (R17).
`db_session` (fixture locale, `app/modules/ingest/tests/conftest.py`) vide
toutes les tables après chaque test : aucun nettoyage manuel nécessaire ici.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    RapprochementLigne,
)
from app.modules.ingest.suivi import controles_differes

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_MAINTENANT = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Aides de construction (données inventées)
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur Testeur"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_chantier(
    db_session: AsyncSession, *, nom: str = "Chantier Testeur", actif: bool = True
) -> Chantier:
    chantier = Chantier(nom_canonique=nom, actif=actif)
    db_session.add(chantier)
    await db_session.commit()
    await db_session.refresh(chantier)
    return chantier


async def _creer_alias(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    libelle: str = "ALIAS INVENTE",
    chantier_id: uuid.UUID | None = None,
    created_at: datetime = _MAINTENANT,
) -> ChantierAlias:
    alias = ChantierAlias(
        fournisseur_id=fournisseur.id,
        libelle_brut=libelle,
        chantier_id=chantier_id,
        created_at=created_at,
    )
    db_session.add(alias)
    await db_session.commit()
    await db_session.refresh(alias)
    return alias


async def _creer_document(
    db_session: AsyncSession,
    *,
    type_: str,
    statut: str = "recu",
    fournisseur: Fournisseur | None = None,
    numero: str | None = None,
    date_doc: date | None = None,
    chantier_id: uuid.UUID | None = None,
    confirme_le: datetime | None = None,
    created_at: datetime = _MAINTENANT,
) -> Document:
    document = Document(
        type=type_,
        source="upload" if type_ == "facture" else "telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero=numero,
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
        date_doc=date_doc,
        chantier_id=chantier_id,
        confirme_le=confirme_le,
        created_at=created_at,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_bloc(
    db_session: AsyncSession,
    *,
    facture: Document,
    ordre: int = 0,
    numero_bl: str | None = "L0001",
    date_bl: date | None = None,
    chantier_id: uuid.UUID | None = None,
    bl_document_id: uuid.UUID | None = None,
    statut_rapprochement: str | None = None,
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=ordre,
        numero_bl=numero_bl,
        date_bl=date_bl,
        chantier_id=chantier_id,
        bl_document_id=bl_document_id,
        statut_rapprochement=statut_rapprochement,
    )
    db_session.add(bloc)
    await db_session.commit()
    await db_session.refresh(bloc)
    return bloc


async def _creer_ligne(
    db_session: AsyncSession,
    *,
    document: Document,
    bloc: BlocFacture | None = None,
    ordre: int = 0,
    type_ligne: str = "article",
    code_brut: str | None = "ART1",
    qte_totale: Decimal | None = Decimal("10"),
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        bloc_id=bloc.id if bloc is not None else None,
        type_ligne=type_ligne,
        code_brut=code_brut,
        qte_totale=qte_totale,
        ordre=ordre,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


# --------------------------------------------------------------------------
# R06 — ligne BL non facturée après le délai
# --------------------------------------------------------------------------


async def test_controles_differes_r06_declenche_apres_le_delai(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(
        db_session, type_="facture", fournisseur=fournisseur
    )
    bl = await _creer_document(db_session, type_="bl", fournisseur=fournisseur)
    date_bl = _MAINTENANT.date() - timedelta(days=46)
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        date_bl=date_bl,
        bl_document_id=bl.id,
        statut_rapprochement="recu",
    )
    ligne_bl_non_facturee = await _creer_ligne(db_session, document=bl, bloc=None)

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    anomalie = (
        await db_session.execute(select(Anomalie).where(Anomalie.regle == "R06"))
    ).scalar_one()
    ok = (
        anomalie.bloc_id == bloc.id
        and anomalie.ligne_id == ligne_bl_non_facturee.id
        and nb == 1
    )
    assert ok, "R06 doit se déclencher sur la ligne BL non facturée après le délai"


async def test_controles_differes_r06_ne_se_declenche_pas_avant_le_delai(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(
        db_session, type_="facture", fournisseur=fournisseur
    )
    bl = await _creer_document(db_session, type_="bl", fournisseur=fournisseur)
    date_bl = _MAINTENANT.date() - timedelta(days=10)
    await _creer_bloc(
        db_session,
        facture=facture,
        date_bl=date_bl,
        bl_document_id=bl.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(db_session, document=bl, bloc=None)

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert lignes == [] and nb == 0


async def test_controles_differes_r06_ignore_une_ligne_deja_appariee(
    db_session: AsyncSession,
) -> None:
    """Une ligne de BL déjà appariée (`rapprochement_ligne`) n'est jamais
    « non facturée », quel que soit le délai écoulé."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(
        db_session, type_="facture", fournisseur=fournisseur
    )
    bl = await _creer_document(db_session, type_="bl", fournisseur=fournisseur)
    date_bl = _MAINTENANT.date() - timedelta(days=46)
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        date_bl=date_bl,
        bl_document_id=bl.id,
        statut_rapprochement="recu",
    )
    ligne_facture = await _creer_ligne(db_session, document=facture, bloc=bloc)
    ligne_bl = await _creer_ligne(db_session, document=bl, bloc=None)
    db_session.add(
        RapprochementLigne(
            ligne_facture_id=ligne_facture.id,
            ligne_bl_id=ligne_bl.id,
            methode="code",
        )
    )
    await db_session.commit()

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert lignes == [] and nb == 0


async def test_controles_differes_r06_ignore_un_bloc_dont_la_facture_est_archivee(
    db_session: AsyncSession,
) -> None:
    """Ruling R25 (revue finale du lot 4, constat 3) : une ligne de BL
    appariée à un bloc dont la facture porteuse est archivée n'est jamais
    « non facturée », même après le délai — sans quoi une facture archivée
    (ex. doublon corrigé par l'admin) laisserait invisible un vrai trou de
    facturation sur les BL qu'elle référençait."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_document(
        db_session, type_="facture", statut="archive", fournisseur=fournisseur
    )
    bl = await _creer_document(db_session, type_="bl", fournisseur=fournisseur)
    date_bl = _MAINTENANT.date() - timedelta(days=46)
    await _creer_bloc(
        db_session,
        facture=facture,
        date_bl=date_bl,
        bl_document_id=bl.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(db_session, document=bl, bloc=None)

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert lignes == [] and nb == 0


# --------------------------------------------------------------------------
# R14 — alias en attente après le délai
# --------------------------------------------------------------------------


async def test_controles_differes_r14_declenche_apres_le_delai(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    alias = await _creer_alias(
        db_session,
        fournisseur=fournisseur,
        created_at=_MAINTENANT - timedelta(hours=49),
    )

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    anomalie = (
        await db_session.execute(select(Anomalie).where(Anomalie.regle == "R14"))
    ).scalar_one()
    assert anomalie.alias_id == alias.id and nb == 1


async def test_controles_differes_r14_ne_se_declenche_pas_avant_le_delai(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_alias(
        db_session,
        fournisseur=fournisseur,
        created_at=_MAINTENANT - timedelta(hours=10),
    )

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert lignes == [] and nb == 0


async def test_controles_differes_r14_ignore_un_alias_deja_valide(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session)
    await _creer_alias(
        db_session,
        fournisseur=fournisseur,
        chantier_id=chantier.id,
        created_at=_MAINTENANT - timedelta(hours=100),
    )

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert lignes == [] and nb == 0


# --------------------------------------------------------------------------
# R15 — BL sans confirmation après le délai
# --------------------------------------------------------------------------


async def test_controles_differes_r15_n_est_plus_produite(
    db_session: AsyncSession,
) -> None:
    """Décision d'Ilane du 31/10/2026 : un BL jamais confirmé depuis plus du
    délai ne produit plus de R15."""
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_document(
        db_session,
        type_="bl",
        fournisseur=fournisseur,
        created_at=_MAINTENANT - timedelta(hours=25),
    )

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert lignes == [] and nb == 0


async def test_controles_differes_r15_ne_se_declenche_pas_si_confirme(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_document(
        db_session,
        type_="bl",
        fournisseur=fournisseur,
        created_at=_MAINTENANT - timedelta(hours=25),
        confirme_le=_MAINTENANT - timedelta(hours=24),
    )

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert lignes == [] and nb == 0


async def test_controles_differes_r15_ignore_un_document_archive(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_document(
        db_session,
        type_="bl",
        statut="archive",
        fournisseur=fournisseur,
        created_at=_MAINTENANT - timedelta(hours=25),
    )

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert lignes == [] and nb == 0


# --------------------------------------------------------------------------
# R16 — chantier silencieux avec factures postérieures
# --------------------------------------------------------------------------


async def test_controles_differes_r16_declenche_avec_facture_posterieure(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session)
    # `confirme_le` renseigné : ce BL ne doit pas aussi déclencher R15 dans
    # ce test, qui ne porte que sur R16 (isolation des scénarios).
    await _creer_document(
        db_session,
        type_="bl",
        fournisseur=fournisseur,
        chantier_id=chantier.id,
        created_at=_MAINTENANT - timedelta(days=10),
        confirme_le=_MAINTENANT - timedelta(days=10),
    )
    facture = await _creer_document(
        db_session, type_="facture", fournisseur=fournisseur
    )
    await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        date_bl=_MAINTENANT.date() - timedelta(days=3),
    )

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    ok = (
        len(lignes) == 1
        and lignes[0].regle == "R16"
        and lignes[0].chantier_id == chantier.id
    )
    assert ok, "R16 doit se déclencher seul, sur le chantier silencieux avec facture"
    assert nb == 1


async def test_controles_differes_r16_ne_se_declenche_pas_sans_facture_posterieure(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session)
    await _creer_document(
        db_session,
        type_="bl",
        fournisseur=fournisseur,
        chantier_id=chantier.id,
        created_at=_MAINTENANT - timedelta(days=10),
        confirme_le=_MAINTENANT - timedelta(days=10),
    )

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert lignes == [] and nb == 0


async def test_controles_differes_r16_ignore_un_chantier_inactif(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, actif=False)
    await _creer_document(
        db_session,
        type_="bl",
        fournisseur=fournisseur,
        chantier_id=chantier.id,
        created_at=_MAINTENANT - timedelta(days=10),
        confirme_le=_MAINTENANT - timedelta(days=10),
    )
    facture = await _creer_document(
        db_session, type_="facture", fournisseur=fournisseur
    )
    await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        date_bl=_MAINTENANT.date() - timedelta(days=3),
    )

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert lignes == [] and nb == 0


# --------------------------------------------------------------------------
# Rejeu sans doublon, anomalie levée, valeur de retour
# --------------------------------------------------------------------------


async def test_controles_differes_rejeu_sans_doublon(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_alias(
        db_session,
        fournisseur=fournisseur,
        created_at=_MAINTENANT - timedelta(hours=49),
    )

    premier = await controles_differes(db_session, maintenant=_MAINTENANT)
    second = await controles_differes(
        db_session, maintenant=_MAINTENANT + timedelta(hours=1)
    )

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    ok = len(lignes) == 1 and premier == 1 and second == 1
    assert ok, (
        "un rejeu identique met à jour la même anomalie, n'en crée jamais une seconde"
    )


async def test_controles_differes_leve_une_anomalie_disparue(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    alias = await _creer_alias(
        db_session,
        fournisseur=fournisseur,
        created_at=_MAINTENANT - timedelta(hours=49),
    )

    await controles_differes(db_session, maintenant=_MAINTENANT)
    anomalie_avant = (
        await db_session.execute(select(Anomalie).where(Anomalie.regle == "R14"))
    ).scalar_one()

    # L'admin valide l'alias entre-temps : il ne fait plus partie des alias
    # en attente, l'anomalie doit disparaître au rejeu (L4-D12).
    chantier = await _creer_chantier(db_session)
    alias.chantier_id = chantier.id
    await db_session.commit()

    nb = await controles_differes(
        db_session, maintenant=_MAINTENANT + timedelta(hours=1)
    )

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    journal_leve = (
        await db_session.execute(
            select(Journal).where(
                Journal.action == "anomalie_levee",
                Journal.cible_id == str(anomalie_avant.id),
            )
        )
    ).scalar_one_or_none()
    ok = lignes == [] and journal_leve is not None and nb == 0
    assert ok, (
        "l'anomalie doit être levée (supprimée + journalisée) une fois sa cause résolue"
    )


async def test_controles_differes_compte_toutes_les_regles_de_suivi_ouvertes(
    db_session: AsyncSession,
) -> None:
    """Valeur de retour : nombre d'anomalies de suivi ouvertes après
    synchronisation, toutes règles confondues (R06, R14, R16 ; R15 est retirée
    depuis le 31/10/2026 : le BL non confirmé ci-dessous ne compte pas)."""
    fournisseur = await _creer_fournisseur(db_session)
    await _creer_alias(
        db_session,
        fournisseur=fournisseur,
        created_at=_MAINTENANT - timedelta(hours=49),
    )
    await _creer_document(
        db_session,
        type_="bl",
        fournisseur=fournisseur,
        created_at=_MAINTENANT - timedelta(hours=25),
    )

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    assert nb == 1
