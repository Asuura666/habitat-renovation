"""Tests de la désactivation de R06 « Livré mais pas facturé » (décision
d'Ilane du 24/09/2026, `docs/dette.md`, seconde demande du jour) : aucune
preuve encore constatée que ce cas se produise, R06 est désactivée côté
serveur tant que `CONTROLE_LIVRE_NON_FACTURE_ACTIF` n'est pas explicitement
à `true` -- même mécanisme que les contrôles de prix
(`test_controle_prix.py`), jamais un second point de décision.

Trois volets, données entièrement inventées (jamais `tests/fixtures/`) :
- `ingest.commun` (pur, sans base) : le drapeau et l'ensemble de règles
  qu'il dérive, indépendant du drapeau de prix ;
- `ingest.suivi.controles_differes` : R06 n'est pas évaluée quand
  désactivée (même scénario que `test_suivi.py`, qui déclencherait R06
  drapeau actif), une anomalie R06 déjà ouverte n'est jamais levée par un
  passage des contrôles différés (masquée, pas détruite), et les trois
  autres règles de suivi (R14/R15/R16) restent inchangées ;
- le masquage de chaque lecture (`lister_anomalies`,
  `compter_anomalies_ouvertes`) -- même mécanisme unique
  (`ingest.anomalies.condition_regles_actives`) que pour le prix, pas
  reconstruit ici.

`app/modules/ingest/tests/conftest.py` réenclenche les deux drapeaux par
défaut pour tout le paquet : chaque test ci-dessous qui veut R06 désactivée
l'écrase localement avec `_regler_controle_livre_non_facture`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest import commun
from app.modules.ingest.anomalies import compter_anomalies_ouvertes, lister_anomalies
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Document,
    Fournisseur,
    Ligne,
)
from app.modules.ingest.suivi import controles_differes
from app.modules.rules.engine import REGLES_SUIVI

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_MAINTENANT = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)


def _regler_controle_livre_non_facture(
    monkeypatch: pytest.MonkeyPatch, *, actif: bool
) -> None:
    """Même idiome que `test_controle_prix._regler_controle_prix` : seule
    `ingest.commun.get_settings` est monkeypatchée. `controle_prix_actif`
    reste à `True` (hors périmètre de ce fichier)."""

    class _SettingsInventee:
        controle_prix_actif = True
        controle_livre_non_facture_actif = actif

    monkeypatch.setattr(commun, "get_settings", lambda: _SettingsInventee())


# --------------------------------------------------------------------------
# `ingest.commun` (pur, sans base)
# --------------------------------------------------------------------------


def test_regles_desactivees_vide_quand_actif(monkeypatch: pytest.MonkeyPatch) -> None:
    _regler_controle_livre_non_facture(monkeypatch, actif=True)

    assert commun.controle_livre_non_facture_actif() is True
    # R15 est retirée en permanence (31/10/2026) : jamais vide.
    assert commun.regles_desactivees() == frozenset({"R15"})


def test_regles_desactivees_r06_quand_inactif(monkeypatch: pytest.MonkeyPatch) -> None:
    _regler_controle_livre_non_facture(monkeypatch, actif=False)

    assert commun.controle_livre_non_facture_actif() is False
    assert commun.regles_desactivees() == frozenset({"R06", "R15"})


def test_regles_desactivees_ne_touche_aucune_autre_regle_de_suivi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seule R06 est concernée par ce drapeau -- R14/R16 restent actives
    même drapeau désactivé (R15 est retirée à part, 31/10/2026)."""
    _regler_controle_livre_non_facture(monkeypatch, actif=False)

    assert (REGLES_SUIVI - commun.regles_desactivees()) == REGLES_SUIVI - {"R06", "R15"}


def test_r15_est_retiree_en_permanence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Décision d'Ilane du 31/10/2026 : la confirmation des quantités est
    retirée, R15 n'est plus produite quels que soient les drapeaux."""
    _regler_controle_livre_non_facture(monkeypatch, actif=True)

    assert frozenset({"R15"}) == commun.REGLES_RETIREES
    assert "R15" in commun.regles_desactivees()
    assert "R15" not in REGLES_SUIVI - commun.regles_desactivees()


def test_les_deux_drapeaux_se_combinent_sans_se_recouvrir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Les deux décisions du 24/09/2026 sont indépendantes : les deux
    ensembles de règles désactivées s'additionnent, sans jamais se
    recouvrir (`REGLES_PRIX` et `REGLES_LIVRE_NON_FACTURE` sont
    disjoints)."""

    class _AucunControleActif:
        controle_prix_actif = False
        controle_livre_non_facture_actif = False

    monkeypatch.setattr(commun, "get_settings", lambda: _AucunControleActif())

    assert commun.regles_desactivees() == frozenset({"R07", "R08", "R09", "R06", "R15"})


# --------------------------------------------------------------------------
# Aides de construction (données inventées) -- mêmes formes que
# `test_suivi.py`, dupliquées ici pour ne dépendre que de ce fichier.
# --------------------------------------------------------------------------


async def _creer_fournisseur(db_session: AsyncSession) -> Fournisseur:
    fournisseur = Fournisseur(nom="Fournisseur Testeur R06 Désactivé")
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _scenario_r06_declencherait(
    db_session: AsyncSession,
) -> tuple[BlocFacture, Ligne]:
    """Bloc reçu, BL rapproché reçu, une ligne de BL jamais facturée,
    déposée bien avant le délai de R06 -- drapeau actif, ce scénario
    déclenche R06 (voir `test_suivi.py::test_controles_differes_r06_
    declenche_apres_le_delai`, même construction)."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path="chemin-invente-facture.pdf",
        fournisseur_id=fournisseur.id,
    )
    bl = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path="chemin-invente-bl.jpg",
        fournisseur_id=fournisseur.id,
    )
    db_session.add_all([facture, bl])
    await db_session.commit()
    await db_session.refresh(facture)
    await db_session.refresh(bl)

    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=0,
        numero_bl="L0001",
        date_bl=_MAINTENANT.date() - timedelta(days=46),
        bl_document_id=bl.id,
        statut_rapprochement="recu",
    )
    db_session.add(bloc)
    await db_session.commit()
    await db_session.refresh(bloc)

    ligne_bl_non_facturee = Ligne(
        document_id=bl.id,
        type_ligne="article",
        code_brut="ART1",
        ordre=0,
    )
    db_session.add(ligne_bl_non_facturee)
    await db_session.commit()
    await db_session.refresh(ligne_bl_non_facturee)

    return bloc, ligne_bl_non_facturee


# --------------------------------------------------------------------------
# Calcul (`ingest.suivi.controles_differes`)
# --------------------------------------------------------------------------


async def test_controles_differes_nevalue_pas_r06_quand_desactive(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _regler_controle_livre_non_facture(monkeypatch, actif=False)
    await _scenario_r06_declencherait(db_session)

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    lignes = (await db_session.execute(select(Anomalie))).scalars().all()
    assert lignes == []
    assert nb == 0


async def test_controles_differes_evalue_r06_quand_active(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _regler_controle_livre_non_facture(monkeypatch, actif=True)
    await _scenario_r06_declencherait(db_session)

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    anomalie = (
        await db_session.execute(select(Anomalie).where(Anomalie.regle == "R06"))
    ).scalar_one()
    assert anomalie is not None
    assert nb == 1


async def test_controles_differes_ne_supprime_pas_une_r06_existante_quand_desactive(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement de la tâche : la portée de `synchroniser_anomalies` ne
    doit jamais considérer R06 comme « recalculée » quand elle est
    désactivée -- une anomalie R06 déjà ouverte (posée ici comme si elle
    datait d'un passage où le drapeau était actif) doit survivre à un
    nouveau passage des contrôles différés fait drapeau désactivé, sans
    être levée."""
    bloc, ligne_bl = await _scenario_r06_declencherait(db_session)
    anomalie = Anomalie(
        regle="R06",
        gravite="moyenne",
        statut="ouverte",
        bloc_id=bloc.id,
        ligne_id=ligne_bl.id,
        detail={"article": "Article inventé", "qte": "10", "jours": "46"},
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)

    _regler_controle_livre_non_facture(monkeypatch, actif=False)
    await controles_differes(db_session, maintenant=_MAINTENANT)

    encore_presente = await db_session.get(Anomalie, anomalie.id)
    assert encore_presente is not None
    assert encore_presente.statut == "ouverte"


async def test_controles_differes_r14_continue_de_se_declencher_quand_r06_desactivee(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contre-épreuve : la portée réduite ne bloque le balayage que pour
    R06 -- une R14 (alias en attente hors délai) se déclenche et se lève
    normalement, drapeau R06 désactivé ou non."""
    from app.modules.ingest.models import ChantierAlias

    _regler_controle_livre_non_facture(monkeypatch, actif=False)
    fournisseur = await _creer_fournisseur(db_session)
    alias = ChantierAlias(
        fournisseur_id=fournisseur.id,
        libelle_brut="ALIAS INVENTE",
        created_at=_MAINTENANT - timedelta(hours=49),
    )
    db_session.add(alias)
    await db_session.commit()
    await db_session.refresh(alias)

    nb = await controles_differes(db_session, maintenant=_MAINTENANT)

    r14 = (
        await db_session.execute(select(Anomalie).where(Anomalie.regle == "R14"))
    ).scalar_one()
    assert r14.alias_id == alias.id
    assert nb == 1


# --------------------------------------------------------------------------
# Masquage de chaque lecture -- même mécanisme unique que le prix
# (`ingest.anomalies.condition_regles_actives`), pas reconstruit ici.
# --------------------------------------------------------------------------


async def test_r06_masquee_de_lister_anomalies_quand_desactive(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _regler_controle_livre_non_facture(monkeypatch, actif=True)
    await _scenario_r06_declencherait(db_session)
    await controles_differes(db_session, maintenant=_MAINTENANT)

    _regler_controle_livre_non_facture(monkeypatch, actif=False)
    anomalies = await lister_anomalies(db_session, statut="ouverte")

    assert not any(a.regle == "R06" for a in anomalies)


async def test_r06_reapparait_dans_lister_anomalies_quand_reactive(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cycle complet, pas seulement la moitié « active » : désactivée,
    l'anomalie R06 est bien absente de `lister_anomalies` (masquée) ; sans
    autre passage des contrôles différés ni retouche de la ligne en base,
    réactiver le drapeau suffit à la faire réapparaître -- le masquage est
    purement un filtre de lecture (`ingest.anomalies
    .condition_regles_actives`), jamais une recréation."""
    _regler_controle_livre_non_facture(monkeypatch, actif=True)
    await _scenario_r06_declencherait(db_session)
    await controles_differes(db_session, maintenant=_MAINTENANT)

    _regler_controle_livre_non_facture(monkeypatch, actif=False)
    anomalies_desactivee = await lister_anomalies(db_session, statut="ouverte")
    assert not any(a.regle == "R06" for a in anomalies_desactivee)

    _regler_controle_livre_non_facture(monkeypatch, actif=True)
    anomalies_reactivee = await lister_anomalies(db_session, statut="ouverte")
    assert any(a.regle == "R06" for a in anomalies_reactivee)


async def test_r06_masquee_du_compte_quand_desactive(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _regler_controle_livre_non_facture(monkeypatch, actif=True)
    await _scenario_r06_declencherait(db_session)
    await controles_differes(db_session, maintenant=_MAINTENANT)

    _regler_controle_livre_non_facture(monkeypatch, actif=False)
    nb_ouvertes, nb_hautes = await compter_anomalies_ouvertes(db_session)

    assert nb_ouvertes == 0
    assert nb_hautes == 0
