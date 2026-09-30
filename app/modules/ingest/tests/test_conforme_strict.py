"""« Conforme » strict, une seule définition calculée par le serveur
(décision d'Ilane du 29/09/2026, audit B-02/B-03/D-01) et mention « dont X €
sur des factures à vérifier » (B-09).

Une livraison (bloc de facture) est « conforme » seulement si son bon est
validé, si le rapprochement l'a trouvé (`statut_rapprochement = 'recu'`), si
sa facture n'est pas « à vérifier » et si aucun problème n'est ouvert sur ce
bloc ni sur ce bon (R10-R13, R17, quantité, prix...). Sinon elle est « à
vérifier » (ou « sans bon » quand le bon n'est jamais venu).

Base de test réelle, données inventées ; mêmes aides que `test_bilan.py`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.bilan import (
    bilan_par_bl,
    bilan_par_chantier,
    categories_des_blocs,
    lister_livraisons,
)
from app.modules.ingest.comparaison_bl import comparer_bl
from app.modules.ingest.models import BlocFacture, Chantier, Document
from app.modules.ingest.tableau_de_bord import tableau_de_bord
from app.modules.ingest.tests.test_bilan import (
    _creer_anomalie,
    _creer_bloc,
    _creer_chantier,
    _creer_document_bl,
    _creer_facture,
    _creer_fournisseur,
    _creer_ligne,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_MOIS = date(2026, 8, 1)


async def _livraison(
    db_session: AsyncSession,
    *,
    numero: str,
    montant: str = "100.00",
    statut_bl: str | None = "recu",
    statut_rapprochement: str | None = "recu",
    chantier: Chantier | None = None,
    statut_facture: str = "recu",
) -> tuple[BlocFacture, Document | None]:
    """Une facture d'un bloc, avec (ou sans) son bon, rapprochée."""
    fournisseur = await _creer_fournisseur(db_session, nom=f"Four {numero}")
    if chantier is None:
        chantier = await _creer_chantier(db_session, nom=f"Chantier {numero}")
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero=f"F-{numero}", statut=statut_facture
    )
    bl = (
        await _creer_document_bl(
            db_session,
            chantier_id=chantier.id,
            fournisseur_id=fournisseur.id,
            statut=statut_bl,
        )
        if statut_bl is not None
        else None
    )
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        numero_bl=f"BL-{numero}",
        statut_rapprochement=statut_rapprochement,
        bl_document_id=bl.id if bl is not None else None,
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal(montant)
    )
    return bloc, bl


async def _liste(db_session: AsyncSession) -> list:  # type: ignore[type-arg]
    return await lister_livraisons(
        db_session, mois=_MOIS, agence=None, chantier_id=None, fournisseur_id=None
    )


async def test_livraison_propre_avec_bon_valide_est_conforme(
    db_session: AsyncSession,
) -> None:
    bloc, _bl = await _livraison(db_session, numero="A")

    lignes = await _liste(db_session)
    assert [ligne.categorie for ligne in lignes] == ["conforme"]
    assert lignes[0].montants.conforme == Decimal("100.00")
    assert lignes[0].montants.a_verifier == Decimal("0")
    assert (await categories_des_blocs(db_session, [bloc.id])) == {bloc.id: "conforme"}


async def test_bon_a_verifier_n_est_pas_conforme(db_session: AsyncSession) -> None:
    """B-02 : un bloc « reçu » dont le bon est encore « à vérifier »."""
    await _livraison(db_session, numero="B", statut_bl="a_verifier")

    lignes = await _liste(db_session)
    assert lignes[0].categorie == "a_verifier"
    assert lignes[0].montants.conforme == Decimal("0")
    assert lignes[0].montants.a_verifier == Decimal("100.00")


async def test_bloc_recu_sans_bon_rattache_n_est_pas_conforme(
    db_session: AsyncSession,
) -> None:
    await _livraison(db_session, numero="C", statut_bl=None)

    lignes = await _liste(db_session)
    assert lignes[0].categorie == "a_verifier"
    assert lignes[0].montants.conforme == Decimal("0")


@pytest.mark.parametrize("regle", ["R10", "R11", "R12", "R13", "R17", "R03", "R05"])
async def test_probleme_ouvert_sur_le_bloc_retire_du_conforme(
    db_session: AsyncSession, regle: str
) -> None:
    """B-03 : quelle que soit la règle (doublon R12, avoir R13, R17...)."""
    bloc, _bl = await _livraison(db_session, numero="D")
    await _creer_anomalie(db_session, regle=regle, bloc_id=bloc.id)

    lignes = await _liste(db_session)
    assert lignes[0].categorie == "a_verifier"
    assert lignes[0].montants.conforme == Decimal("0")
    assert lignes[0].montants.a_verifier == Decimal("100.00")
    par_bl = await bilan_par_bl(
        db_session,
        chantier_id=lignes[0].chantier_id,
        fournisseur_id=lignes[0].fournisseur_id,
        mois=_MOIS,
    )
    assert par_bl[0].categorie == "a_verifier"
    assert par_bl[0].montants.conforme == Decimal("0")


async def test_probleme_traite_ne_bloque_plus_le_conforme(
    db_session: AsyncSession,
) -> None:
    bloc, _bl = await _livraison(db_session, numero="E")
    await _creer_anomalie(db_session, regle="R12", bloc_id=bloc.id, statut="traitee")

    assert (await _liste(db_session))[0].categorie == "conforme"


async def test_probleme_ouvert_sur_le_bon_retire_du_conforme(
    db_session: AsyncSession,
) -> None:
    """Un problème porté par le bon lui-même (R11) rend aussi le bloc « à
    vérifier »."""
    _bloc, bl = await _livraison(db_session, numero="F")
    assert bl is not None
    await _creer_anomalie(db_session, regle="R11", document_id=bl.id)

    lignes = await _liste(db_session)
    assert lignes[0].categorie == "a_verifier"
    assert lignes[0].montants.conforme == Decimal("0")


async def test_doublon_de_facturation_retire_aussi_le_bloc_d_origine(
    db_session: AsyncSession,
) -> None:
    """Le même bon facturé deux fois (R12 sur le 2e bloc) : les deux blocs
    citent ce bon, aucun n'est conforme."""
    fournisseur = await _creer_fournisseur(db_session, nom="Four doublon")
    chantier = await _creer_chantier(db_session, nom="Chantier doublon")
    bl = await _creer_document_bl(
        db_session, chantier_id=chantier.id, fournisseur_id=fournisseur.id
    )
    blocs = []
    for numero in ("F-1", "F-2"):
        facture = await _creer_facture(
            db_session, fournisseur=fournisseur, numero=numero
        )
        bloc = await _creer_bloc(
            db_session,
            facture=facture,
            chantier_id=chantier.id,
            numero_bl="BL-D",
            bl_document_id=bl.id,
        )
        await _creer_ligne(db_session, document=facture, bloc=bloc)
        blocs.append(bloc)
    await _creer_anomalie(db_session, regle="R12", bloc_id=blocs[1].id)

    categories = await categories_des_blocs(db_session, [b.id for b in blocs])
    assert set(categories.values()) == {"a_verifier"}


async def test_bloc_sans_bon_reste_sans_bon(db_session: AsyncSession) -> None:
    await _livraison(
        db_session, numero="G", statut_bl=None, statut_rapprochement="non_recu"
    )
    lignes = await _liste(db_session)
    assert lignes[0].categorie == "sans_bon"
    assert lignes[0].montants.conforme == Decimal("0")


async def test_tuile_conforme_et_liste_ouverte_coincident(
    db_session: AsyncSession,
) -> None:
    """D-01 : le montant « Conforme » de l'accueil est exactement la somme
    des livraisons « conformes » de la liste (jeu mêlant tous les cas)."""
    await _livraison(db_session, numero="H1", montant="10.00")
    bloc_doublon, _ = await _livraison(db_session, numero="H2", montant="20.00")
    await _creer_anomalie(db_session, regle="R12", bloc_id=bloc_doublon.id)
    await _livraison(db_session, numero="H3", montant="40.00", statut_bl="a_verifier")
    await _livraison(
        db_session,
        numero="H4",
        montant="80.00",
        statut_bl=None,
        statut_rapprochement="non_recu",
    )
    await _livraison(db_session, numero="H5", montant="160.00")

    lignes = await _liste(db_session)
    conforme_liste = sum(
        (
            ligne.montants.facture_ht
            for ligne in lignes
            if ligne.categorie == "conforme"
        ),
        Decimal("0"),
    )
    tableau = await tableau_de_bord(db_session, mois=_MOIS)
    lignes_bilan = await bilan_par_chantier(db_session, mois=_MOIS, agence=None)

    assert conforme_liste == Decimal("170.00")
    assert tableau.totaux.conforme == conforme_liste
    assert sum((ligne.montants.conforme for ligne in lignes_bilan), Decimal("0")) == (
        conforme_liste
    )


async def test_comparaison_du_bon_donne_la_meme_categorie(
    db_session: AsyncSession,
) -> None:
    _bloc, bl_propre = await _livraison(db_session, numero="I1")
    _bloc, bl_a_verifier = await _livraison(
        db_session, numero="I2", statut_bl="a_verifier"
    )
    bloc_doublon, bl_doublon = await _livraison(db_session, numero="I3")
    await _creer_anomalie(db_session, regle="R12", bloc_id=bloc_doublon.id)
    assert bl_propre and bl_a_verifier and bl_doublon

    assert (await comparer_bl(db_session, bl_propre.id)).categorie == "conforme"
    assert (await comparer_bl(db_session, bl_a_verifier.id)).categorie == "a_verifier"
    assert (await comparer_bl(db_session, bl_doublon.id)).categorie == "a_verifier"


async def test_bon_jamais_facture_n_est_ni_conforme_ni_a_verifier(
    db_session: AsyncSession,
) -> None:
    bl = await _creer_document_bl(db_session)
    assert (await comparer_bl(db_session, bl.id)).categorie == "pas_encore_facture"


# --------------------------------------------------------------------------
# B-09 : facture à somme incohérente, comptée dans « Facturé », mention
# « dont X € sur des factures à vérifier ».
# --------------------------------------------------------------------------


async def test_facture_a_verifier_reste_dans_facture_avec_mention(
    db_session: AsyncSession,
) -> None:
    await _livraison(db_session, numero="J1", montant="100.00")
    await _livraison(
        db_session,
        numero="J2",
        montant="50.00",
        statut_bl=None,
        statut_rapprochement=None,
        statut_facture="a_verifier",
    )

    tableau = await tableau_de_bord(db_session, mois=_MOIS)
    lignes_bilan = await bilan_par_chantier(db_session, mois=_MOIS, agence=None)

    assert tableau.totaux.facture_ht == Decimal("150.00")
    assert tableau.totaux.facture_a_verifier == Decimal("50.00")
    assert sum(
        (ligne.montants.facture_a_verifier for ligne in lignes_bilan), Decimal("0")
    ) == Decimal("50.00")
    assert tableau.totaux.conforme == Decimal("100.00")


async def test_facture_a_verifier_jamais_conforme_meme_avec_bon_valide(
    db_session: AsyncSession,
) -> None:
    await _livraison(
        db_session, numero="K", statut_rapprochement="recu", statut_facture="a_verifier"
    )
    lignes = await _liste(db_session)
    assert lignes[0].categorie == "a_verifier"
    assert lignes[0].montants.conforme == Decimal("0")


# --------------------------------------------------------------------------
# État d'un chantier à l'accueil décidé sur les blocs (I2)
# --------------------------------------------------------------------------


async def _etat_du_chantier(db_session: AsyncSession, chantier: Chantier) -> str:
    tableau = await tableau_de_bord(db_session, mois=_MOIS)
    return next(c.etat for c in tableau.chantiers if c.chantier_id == chantier.id)


async def test_etat_chantier_tous_blocs_conformes_est_conforme(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Chantier propre")
    await _livraison(db_session, numero="E1", chantier=chantier)
    await _livraison(db_session, numero="E2", chantier=chantier)

    assert await _etat_du_chantier(db_session, chantier) == "conforme"


async def test_etat_chantier_bloc_a_verifier_a_zero_euro_n_est_pas_conforme(
    db_session: AsyncSession,
) -> None:
    """Un bloc « à vérifier » (bon non validé) à 0 € ne pèse rien dans
    `a_verifier` : l'état se décide sur les blocs, pas sur le montant."""
    chantier = await _creer_chantier(db_session, nom="Chantier zéro")
    await _livraison(
        db_session,
        numero="E3",
        montant="0.00",
        statut_bl="a_verifier",
        chantier=chantier,
    )

    assert await _etat_du_chantier(db_session, chantier) == "a_voir"


async def test_etat_chantier_avoir_qui_annule_une_facture_n_est_pas_conforme(
    db_session: AsyncSession,
) -> None:
    """Facture à vérifier de 100 € annulée par un avoir de -100 € : la somme
    « à vérifier » est nulle, le chantier n'est pourtant pas conforme."""
    chantier = await _creer_chantier(db_session, nom="Chantier avoir")
    await _livraison(
        db_session,
        numero="E4",
        montant="100.00",
        statut_bl="a_verifier",
        chantier=chantier,
    )
    await _livraison(
        db_session,
        numero="E5",
        montant="-100.00",
        statut_bl="a_verifier",
        chantier=chantier,
    )

    assert await _etat_du_chantier(db_session, chantier) == "a_voir"


async def test_etat_chantier_blocs_sans_bon_sans_anomalie_ouverte_pas_conforme(
    db_session: AsyncSession,
) -> None:
    """Un bloc « sans bon » dont le problème a été traité (aucune anomalie
    ouverte) ne rend pas le chantier conforme."""
    chantier = await _creer_chantier(db_session, nom="Chantier sans bon")
    bloc, _ = await _livraison(
        db_session,
        numero="E6",
        statut_bl=None,
        statut_rapprochement="non_recu",
        chantier=chantier,
    )
    await _creer_anomalie(db_session, regle="R01", bloc_id=bloc.id, statut="ignoree")

    assert await _etat_du_chantier(db_session, chantier) == "a_voir"


async def test_page_du_bon_dit_pourquoi_a_verifier_sans_probleme(
    db_session: AsyncSession,
) -> None:
    """Constat final 6 : pastille « À vérifier » avec 0 problème, la raison
    (« bon à valider » / « facture à vérifier ») vient du serveur."""
    _bloc, bl = await _livraison(db_session, numero="R1", statut_bl="a_verifier")
    assert bl is not None
    comparaison = await comparer_bl(db_session, bl.id)
    assert comparaison.categorie == "a_verifier"
    assert comparaison.nb_problemes == 0
    assert comparaison.raison_a_verifier == "bon à valider"

    _bloc, bl = await _livraison(db_session, numero="R2", statut_facture="a_verifier")
    assert bl is not None
    comparaison = await comparer_bl(db_session, bl.id)
    assert comparaison.categorie == "a_verifier"
    assert comparaison.raison_a_verifier == "facture à vérifier"

    _bloc, bl = await _livraison(db_session, numero="R3")
    assert bl is not None
    assert (await comparer_bl(db_session, bl.id)).raison_a_verifier is None
