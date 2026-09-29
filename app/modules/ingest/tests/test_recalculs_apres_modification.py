"""Corrections d'audit, groupe 1 (C-01, B-01, B-04, B-07) : une correction,
une relecture, une suppression de ligne ou un archivage d'un document qui
participe à un rapprochement rejoue le rapprochement des factures
concernées (mêmes fonctions que le dépôt et la validation), sans violation
de clé étrangère sur `rapprochement_ligne`.

Base de test réelle, données entièrement inventées.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extract.verification import CodeMotif
from app.modules.ingest import rapprochement as ingest_rapprochement
from app.modules.ingest.anomalies import compter_anomalies_ouvertes, lister_anomalies
from app.modules.ingest.corrections import (
    CorrectionEntete,
    LigneSaisie,
    archiver_document,
    corriger_entete,
    corriger_lignes,
    valider_document,
)
from app.modules.ingest.extraction_bl import enregistrer_extraction_bl
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    RapprochementLigne,
    Utilisateur,
)
from app.modules.ingest.rapprochement import rapprocher_facture
from app.modules.ingest.tests.test_rapprochement import (
    _creer_bl,
    _creer_bloc,
    _creer_facture,
    _creer_fournisseur,
    _creer_ligne,
    _rafraichir,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


_MOTIF_SOMME = [
    {
        "code": CodeMotif.SOMME_INCOHERENTE.value,
        "champ": "total_ht",
        "detail": {"somme": "10.00", "total": "50.00", "ecart": "40.00"},
    }
]


async def _admin(db_session: AsyncSession) -> Utilisateur:
    admin = Utilisateur(
        email=f"admin.{uuid.uuid4()}@example.invalid", role="admin", is_active=True
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


def _saisie(ligne: Ligne, **surcharge: Any) -> LigneSaisie:
    valeurs: dict[str, Any] = {
        "id": ligne.id,
        "code_brut": ligne.code_brut,
        "article_brut": ligne.article_brut,
        "qte_livree": ligne.qte_livree,
        "qte_totale": ligne.qte_totale,
        "unite_brut": ligne.unite_brut,
        "pu_ht": ligne.pu_ht,
        "montant_ht": ligne.montant_ht,
    }
    valeurs.update(surcharge)
    return LigneSaisie(**valeurs)


async def _facture_et_bl_rapproches(
    db_session: AsyncSession,
    *,
    qte_facture: str = "12",
    qte_bl: str = "10",
    numero_bl: str = "L0001",
) -> tuple[Fournisseur, Document, BlocFacture, Document, Ligne]:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl=numero_bl)
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        qte_livree=Decimal(qte_facture),
        qte_totale=Decimal(qte_facture),
        montant_ht=Decimal("10.00"),
    )
    bl = await _creer_bl(
        db_session,
        fournisseur=fournisseur,
        numero=numero_bl,
        chantier_brut="Chantier inventé",
        total_ht=Decimal("10.00"),
    )
    ligne_bl = await _creer_ligne(
        db_session,
        document=bl,
        qte_livree=Decimal(qte_bl),
        qte_totale=Decimal(qte_bl),
        montant_ht=Decimal("10.00"),
    )
    await rapprocher_facture(db_session, facture.id)
    await _rafraichir(db_session, bloc)
    assert bloc.statut_rapprochement == "recu"
    return fournisseur, facture, bloc, bl, ligne_bl


async def _regles_ouvertes(db_session: AsyncSession, facture: Document) -> list[str]:
    blocs = select(BlocFacture.id).where(BlocFacture.facture_id == facture.id)
    lignes = select(Ligne.id).where(Ligne.document_id == facture.id)
    resultat = await db_session.execute(
        select(Anomalie.regle).where(
            Anomalie.statut == "ouverte",
            (Anomalie.document_id == facture.id)
            | Anomalie.bloc_id.in_(blocs)
            | Anomalie.ligne_id.in_(lignes),
        )
    )
    return sorted(resultat.scalars().all())


async def _liens(db_session: AsyncSession) -> int:
    return len((await db_session.execute(select(RapprochementLigne))).scalars().all())


# --------------------------------------------------------------------------
# C-01 : supprimer / relire des lignes de BL déjà rapprochées
# --------------------------------------------------------------------------


async def test_c01_supprimer_toutes_les_lignes_du_bl_rapproche_sans_erreur(
    db_session: AsyncSession,
) -> None:
    _f, _facture, _bloc, bl, _ligne_bl = await _facture_et_bl_rapproches(db_session)
    admin = await _admin(db_session)
    assert await _liens(db_session) == 1

    await corriger_lignes(db_session, bl.id, [], auteur_id=admin.id)

    assert await _liens(db_session) == 0


async def test_c01_supprimer_une_ligne_du_bl_garde_le_lien_de_l_autre(
    db_session: AsyncSession,
) -> None:
    _f, facture, bloc, bl, ligne_bl = await _facture_et_bl_rapproches(db_session)
    admin = await _admin(db_session)
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        ordre=1,
        code_brut="ART2",
        article_brut="Autre article",
        qte_livree=Decimal("1"),
        qte_totale=Decimal("1"),
        montant_ht=Decimal("1.00"),
    )
    autre = await _creer_ligne(
        db_session,
        document=bl,
        ordre=1,
        code_brut="ART2",
        article_brut="Autre article",
        qte_livree=Decimal("1"),
        qte_totale=Decimal("1"),
        montant_ht=Decimal("1.00"),
    )
    await rapprocher_facture(db_session, facture.id)
    assert await _liens(db_session) == 2

    await corriger_lignes(db_session, bl.id, [_saisie(ligne_bl)], auteur_id=admin.id)

    ids = (
        (await db_session.execute(select(RapprochementLigne.ligne_bl_id)))
        .scalars()
        .all()
    )
    assert ids == [ligne_bl.id]
    assert autre.id not in ids


async def test_c01_relancer_la_lecture_d_un_bl_rapproche_sans_erreur(
    db_session: AsyncSession,
) -> None:
    _f, _facture, bloc, bl, _ligne_bl = await _facture_et_bl_rapproches(db_session)
    reponse = {
        "pages": [
            {
                "index": 0,
                "markdown": "LIVRAISON N°L0001",
                "images": [],
                "dimensions": {"dpi": 200, "height": 100, "width": 100},
            }
        ],
        "model": "test",
        "document_annotation": "N/A",
        "usage_info": {"pages_processed": 1, "doc_size_bytes": 1},
    }

    await enregistrer_extraction_bl(db_session, bl.id, reponse, relance=True)

    assert await _liens(db_session) == 0
    await _rafraichir(db_session, bloc)
    assert bloc.bl_document_id == bl.id  # le rejeu a bien eu lieu


# --------------------------------------------------------------------------
# B-01 : R11 levée après correction du BL
# --------------------------------------------------------------------------


async def test_b01_r11_levee_quand_le_bl_est_valide(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    await _creer_bloc(db_session, facture=facture, numero_bl="L0011")
    bl = await _creer_bl(
        db_session,
        fournisseur=fournisseur,
        numero="L0011",
        statut="a_verifier",
        chantier_brut="Chantier inventé",
        total_ht=Decimal("50.00"),
    )
    bl.motifs = _MOTIF_SOMME
    await _creer_ligne(db_session, document=bl, montant_ht=Decimal("10.00"))
    await db_session.commit()
    await rapprocher_facture(db_session, facture.id)
    assert (await compter_anomalies_ouvertes(db_session))[0] == 1  # R11

    admin = await _admin(db_session)
    bl.total_ht = Decimal("10.00")
    await db_session.commit()
    await valider_document(db_session, bl.id, auteur_id=admin.id)

    r11 = (
        (await db_session.execute(select(Anomalie).where(Anomalie.regle == "R11")))
        .scalars()
        .all()
    )
    assert [a.statut for a in r11] != ["ouverte"]
    assert (await compter_anomalies_ouvertes(db_session))[0] == 0


# --------------------------------------------------------------------------
# B-04 : corriger un BL déjà reçu rejoue le rapprochement
# --------------------------------------------------------------------------


async def test_b04_corriger_les_lignes_leve_l_ecart_de_quantite(
    db_session: AsyncSession,
) -> None:
    _f, facture, _bloc, bl, ligne_bl = await _facture_et_bl_rapproches(db_session)
    admin = await _admin(db_session)
    assert "R03" in await _regles_ouvertes(db_session, facture)

    await corriger_lignes(
        db_session,
        bl.id,
        [_saisie(ligne_bl, qte_livree=Decimal("12"), qte_totale=Decimal("12"))],
        auteur_id=admin.id,
    )

    assert "R03" not in await _regles_ouvertes(db_session, facture)


async def test_b04_corriger_les_lignes_cree_l_ecart_de_quantite(
    db_session: AsyncSession,
) -> None:
    _f, facture, _bloc, bl, ligne_bl = await _facture_et_bl_rapproches(
        db_session, qte_facture="10", qte_bl="10"
    )
    admin = await _admin(db_session)
    assert "R03" not in await _regles_ouvertes(db_session, facture)

    await corriger_lignes(
        db_session,
        bl.id,
        [_saisie(ligne_bl, qte_livree=Decimal("8"), qte_totale=Decimal("8"))],
        auteur_id=admin.id,
    )

    assert "R03" in await _regles_ouvertes(db_session, facture)


async def test_b04_corriger_le_numero_deplace_le_lien_du_bloc(
    db_session: AsyncSession,
) -> None:
    _f, facture, bloc, bl, _ligne_bl = await _facture_et_bl_rapproches(
        db_session, numero_bl="L0002"
    )
    autre_bloc = await _creer_bloc(
        db_session, facture=facture, ordre=1, numero_bl="L0009"
    )
    await rapprocher_facture(db_session, facture.id)
    admin = await _admin(db_session)

    await corriger_entete(
        db_session,
        bl.id,
        CorrectionEntete(valeurs={"numero": "L0009"}),
        auteur_id=admin.id,
    )

    await _rafraichir(db_session, bloc)
    await _rafraichir(db_session, autre_bloc)
    assert bloc.statut_rapprochement == "non_recu"
    assert bloc.bl_document_id is None
    assert autre_bloc.statut_rapprochement == "recu"
    assert autre_bloc.bl_document_id == bl.id


# --------------------------------------------------------------------------
# B-07 : archiver rejoue ce qui en dépend
# --------------------------------------------------------------------------


async def test_b07_archiver_un_bl_remet_le_bloc_non_recu_et_leve_r11(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0021")
    bl = await _creer_bl(
        db_session,
        fournisseur=fournisseur,
        numero="L0021",
        statut="a_verifier",
        total_ht=Decimal("50.00"),
    )
    bl.motifs = _MOTIF_SOMME
    await _creer_ligne(db_session, document=bl, montant_ht=Decimal("10.00"))
    await db_session.commit()
    await rapprocher_facture(db_session, facture.id)
    await _rafraichir(db_session, bloc)
    assert bloc.statut_rapprochement == "recu"
    assert (await compter_anomalies_ouvertes(db_session))[0] == 1  # R11
    admin = await _admin(db_session)

    await archiver_document(
        db_session, bl.id, commentaire="doublon", auteur_id=admin.id
    )

    await _rafraichir(db_session, bloc)
    assert bloc.statut_rapprochement == "non_recu"
    assert bloc.bl_document_id is None
    regles = await _regles_ouvertes(db_session, facture)
    assert "R11" not in regles
    assert "R01" in regles
    assert await _liens(db_session) == 0


async def test_b07_archiver_une_facture_leve_r12_de_l_autre(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    a = await _creer_facture(db_session, fournisseur=fournisseur, numero="FA")
    await _creer_bloc(db_session, facture=a, numero_bl="L0031")
    b = await _creer_facture(db_session, fournisseur=fournisseur, numero="FB")
    await _creer_bloc(db_session, facture=b, numero_bl="L0031")
    await rapprocher_facture(db_session, a.id)
    await rapprocher_facture(db_session, b.id)
    # R12 est portée par la facture la plus récente (contre la plus ancienne)
    assert "R12" in await _regles_ouvertes(db_session, b)
    admin = await _admin(db_session)

    await archiver_document(db_session, a.id, commentaire="erreur", auteur_id=admin.id)

    assert "R12" not in await _regles_ouvertes(db_session, b)


# --------------------------------------------------------------------------
# Correction 1, important 1 : un BL `a_verifier` lié est rejoué aussi
# --------------------------------------------------------------------------


async def test_bl_a_verifier_lie_corriger_le_numero_deplace_le_lien_du_bloc(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0041")
    autre_bloc = await _creer_bloc(
        db_session, facture=facture, ordre=1, numero_bl="L0049"
    )
    bl = await _creer_bl(
        db_session, fournisseur=fournisseur, numero="L0041", statut="a_verifier"
    )
    await _creer_ligne(db_session, document=bl, montant_ht=Decimal("10.00"))
    await rapprocher_facture(db_session, facture.id)
    await _rafraichir(db_session, bloc)
    assert bloc.bl_document_id == bl.id  # un BL a_verifier est candidat
    admin = await _admin(db_session)

    await corriger_entete(
        db_session,
        bl.id,
        CorrectionEntete(valeurs={"numero": "L0049"}),
        auteur_id=admin.id,
    )

    await _rafraichir(db_session, bloc)
    await _rafraichir(db_session, autre_bloc)
    assert bloc.bl_document_id is None
    assert autre_bloc.bl_document_id == bl.id


async def test_bl_a_verifier_lie_corriger_les_lignes_rejoue_les_liens(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, numero_bl="L0042")
    await _creer_ligne(db_session, document=facture, bloc=bloc, code_brut="ART1")
    bl = await _creer_bl(
        db_session, fournisseur=fournisseur, numero="L0042", statut="a_verifier"
    )
    ligne_bl = await _creer_ligne(db_session, document=bl, code_brut="ART1")
    await rapprocher_facture(db_session, facture.id)
    assert await _liens(db_session) == 1
    admin = await _admin(db_session)

    await corriger_lignes(
        db_session,
        bl.id,
        [_saisie(ligne_bl, id=None, qte_livree=Decimal("3"))],
        auteur_id=admin.id,
    )

    # les liens supprimés avant les lignes sont recréés par le rejeu
    assert await _liens(db_session) == 1


# --------------------------------------------------------------------------
# Correction 1, important 2 : tout ou rien si le rejeu échoue
# --------------------------------------------------------------------------


async def _rejeu_en_echec(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("rejeu simulé en échec")

    monkeypatch.setattr(ingest_rapprochement, "rapprocher_facture", _boom)


async def test_rejeu_en_echec_corriger_lignes_annule_tout(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _f, _facture, bloc, bl, ligne_bl = await _facture_et_bl_rapproches(db_session)
    admin = await _admin(db_session)
    bl_id, ligne_bl_id = bl.id, ligne_bl.id
    await _rejeu_en_echec(monkeypatch)

    with pytest.raises(RuntimeError):
        await corriger_lignes(db_session, bl_id, [], auteur_id=admin.id)

    assert await _liens(db_session) == 1
    lignes = (
        (await db_session.execute(select(Ligne.id).where(Ligne.document_id == bl_id)))
        .scalars()
        .all()
    )
    assert lignes == [ligne_bl_id]
    journal = (
        (
            await db_session.execute(
                select(Journal).where(Journal.action == "lignes_corrigees")
            )
        )
        .scalars()
        .all()
    )
    assert journal == []
    await _rafraichir(db_session, bloc)
    assert bloc.statut_rapprochement == "recu"


async def test_rejeu_en_echec_corriger_entete_annule_tout(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _f, _facture, _bloc, bl, _ligne_bl = await _facture_et_bl_rapproches(db_session)
    admin = await _admin(db_session)
    await _rejeu_en_echec(monkeypatch)

    with pytest.raises(RuntimeError):
        await corriger_entete(
            db_session,
            bl.id,
            CorrectionEntete(valeurs={"numero": "L0999"}),
            auteur_id=admin.id,
        )

    await _rafraichir(db_session, bl)
    assert bl.numero == "L0001"


async def test_rejeu_en_echec_archiver_annule_tout(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _f, _facture, bloc, bl, _ligne_bl = await _facture_et_bl_rapproches(db_session)
    admin = await _admin(db_session)
    await _rejeu_en_echec(monkeypatch)

    with pytest.raises(RuntimeError):
        await archiver_document(
            db_session, bl.id, commentaire="doublon", auteur_id=admin.id
        )

    await _rafraichir(db_session, bl)
    assert bl.statut == "recu"
    await _rafraichir(db_session, bloc)
    assert bloc.statut_rapprochement == "recu"


# --------------------------------------------------------------------------
# Correction 1, mineur : compteur et liste excluent les documents archivés
# --------------------------------------------------------------------------


async def test_compteur_exclut_les_anomalies_d_un_bl_archive(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    bl = await _creer_bl(db_session, fournisseur=fournisseur)
    db_session.add(
        Anomalie(
            regle="R11",
            gravite="moyenne",
            document_id=bl.id,
            detail={"somme": "1"},
            statut="ouverte",
        )
    )
    await db_session.commit()
    assert (await compter_anomalies_ouvertes(db_session))[0] == 1
    assert len(await lister_anomalies(db_session, statut="ouverte")) == 1

    bl.statut = "archive"
    await db_session.commit()

    assert (await compter_anomalies_ouvertes(db_session))[0] == 0
    assert await lister_anomalies(db_session, statut="ouverte") == []
