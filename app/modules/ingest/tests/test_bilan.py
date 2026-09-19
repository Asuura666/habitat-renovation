"""Tests de `ingest/bilan.py` : agrégats du bilan par chantier (L5-T1), par
fournisseur et par BL, plus la vue inverse (L5-T2).

Base de test réelle (`bl_test`), données entièrement inventées (R17).
`db_session` (fixture locale, `app/modules/ingest/tests/conftest.py`) vide
toutes les tables après chaque test : aucun nettoyage manuel nécessaire ici.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.bilan import (
    LigneBilanBl,
    LigneBilanChantier,
    LigneBilanFournisseur,
    bilan_chantiers_du_fournisseur,
    bilan_par_bl,
    bilan_par_chantier,
    bilan_par_fournisseur,
    bilan_par_fournisseur_global,
)
from app.modules.ingest.models import (
    Anomalie,
    Article,
    BlocFacture,
    Chantier,
    Document,
    Fournisseur,
    Ligne,
)
from app.modules.ingest.rapprochement import rapprocher_facture

pytestmark = [pytest.mark.anyio, pytest.mark.db]


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
    db_session: AsyncSession,
    *,
    nom: str = "Chantier Testeur",
    agence: str | None = None,
) -> Chantier:
    chantier = Chantier(nom_canonique=nom, agence=agence)
    db_session.add(chantier)
    await db_session.commit()
    await db_session.refresh(chantier)
    return chantier


async def _creer_facture(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    numero: str = "F0001",
    statut: str = "recu",
    date_doc: date | None = date(2026, 8, 15),
    created_at: datetime | None = None,
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero=numero,
        fournisseur_id=fournisseur.id,
        date_doc=date_doc,
        **({"created_at": created_at} if created_at is not None else {}),
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
    chantier_id: uuid.UUID | None = None,
    statut_rapprochement: str | None = "recu",
    bl_document_id: uuid.UUID | None = None,
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=ordre,
        numero_bl=numero_bl,
        chantier_id=chantier_id,
        statut_rapprochement=statut_rapprochement,
        bl_document_id=bl_document_id,
    )
    db_session.add(bloc)
    await db_session.commit()
    await db_session.refresh(bloc)
    return bloc


async def _creer_document_bl(
    db_session: AsyncSession,
    *,
    chantier_id: uuid.UUID | None = None,
    fournisseur_id: uuid.UUID | None = None,
    date_doc: date | None = None,
    statut: str = "recu",
) -> Document:
    """Un document BL minimal (données inventées), utilisé uniquement pour
    fournir un `bl_document_id` valide à un bloc de facture (niveau BL,
    L5-T2) -- son contenu réel n'importe pas à ces tests."""
    document = Document(
        type="bl",
        source="telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        chantier_id=chantier_id,
        fournisseur_id=fournisseur_id,
        date_doc=date_doc,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_facture_sans_fournisseur(
    db_session: AsyncSession, *, numero: str = "F-SANS-FOURN"
) -> Document:
    """Une facture sans fournisseur résolu (`fournisseur_id=None`) :
    `_creer_facture` exige un `Fournisseur`, ce cas a besoin d'en construire
    une directement (données inventées, comme le reste du module)."""
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero=numero,
        fournisseur_id=None,
        date_doc=date(2026, 8, 15),
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_ligne(
    db_session: AsyncSession,
    *,
    document: Document,
    bloc: BlocFacture | None = None,
    montant_ht: Decimal = Decimal("100.00"),
    type_ligne: str = "article",
    ordre: int = 0,
    article: Article | None = None,
    code_brut: str | None = None,
    pu_ht: Decimal | None = None,
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        bloc_id=bloc.id if bloc is not None else None,
        montant_ht=montant_ht,
        type_ligne=type_ligne,
        ordre=ordre,
        article_id=article.id if article is not None else None,
        code_brut=code_brut,
        pu_ht=pu_ht,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _creer_article(
    db_session: AsyncSession, *, fournisseur: Fournisseur, code: str = "ART1"
) -> Article:
    article = Article(fournisseur_id=fournisseur.id, code=code, valide=True)
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)
    return article


async def _creer_anomalie(
    db_session: AsyncSession,
    *,
    regle: str = "R03",
    statut: str = "ouverte",
    bloc_id: uuid.UUID | None = None,
    ligne_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    article_id: uuid.UUID | None = None,
    chantier_id: uuid.UUID | None = None,
    gravite: str = "haute",
    created_at: datetime | None = None,
) -> Anomalie:
    anomalie = Anomalie(
        regle=regle,
        gravite=gravite,
        statut=statut,
        bloc_id=bloc_id,
        ligne_id=ligne_id,
        document_id=document_id,
        article_id=article_id,
        chantier_id=chantier_id,
        detail={"cle": "valeur"},
        traitee_le=datetime.now(UTC) if statut != "ouverte" else None,
        commentaire="Traitée (test)." if statut != "ouverte" else None,
        **({"created_at": created_at} if created_at is not None else {}),
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)
    return anomalie


def _ligne_du_chantier(
    lignes: list[LigneBilanChantier], chantier_id: uuid.UUID | None
) -> LigneBilanChantier | None:
    """La ligne de bilan portant `chantier_id`, `None` si absente."""
    for ligne in lignes:
        if ligne.chantier_id == chantier_id:
            return ligne
    return None


def _ligne_du_fournisseur(
    lignes: list[LigneBilanFournisseur], fournisseur_id: uuid.UUID | None
) -> LigneBilanFournisseur | None:
    """La ligne de bilan portant `fournisseur_id`, `None` si absente."""
    for ligne in lignes:
        if ligne.fournisseur_id == fournisseur_id:
            return ligne
    return None


def _ligne_du_bl(lignes: list[LigneBilanBl], bloc_id: uuid.UUID) -> LigneBilanBl | None:
    """La ligne de bilan portant `bloc_id`, `None` si absente."""
    for ligne in lignes:
        if ligne.bloc_id == bloc_id:
            return ligne
    return None


def _somme_montants(montants: list[Any]) -> dict[str, Decimal | int]:
    """Somme composant par composant d'une liste de `MontantsBilan` --
    utilitaire des tests d'invariant (§ »cohérence entre niveaux« ci-dessous,
    décision du contrôleur) : la somme des fournisseurs d'un chantier doit
    égaler ce chantier, et la somme des BL d'un fournisseur doit égaler ce
    fournisseur."""
    return {
        "facture_ht": sum((m.facture_ht for m in montants), Decimal("0")),
        "rapproche": sum((m.rapproche for m in montants), Decimal("0")),
        "en_ecart": sum((m.en_ecart for m in montants), Decimal("0")),
        "non_justifie": sum((m.non_justifie for m in montants), Decimal("0")),
        "nb_anomalies_ouvertes": sum(m.nb_anomalies_ouvertes for m in montants),
    }


def _montants_dict(montants: Any) -> dict[str, Decimal | int]:
    """Un `MontantsBilan` sous la même forme que `_somme_montants`, pour les
    comparer directement."""
    return {
        "facture_ht": montants.facture_ht,
        "rapproche": montants.rapproche,
        "en_ecart": montants.en_ecart,
        "non_justifie": montants.non_justifie,
        "nb_anomalies_ouvertes": montants.nb_anomalies_ouvertes,
    }


async def _construire_jeu_non_trivial(
    db_session: AsyncSession,
) -> tuple[Chantier, Fournisseur, Fournisseur, BlocFacture, BlocFacture, BlocFacture]:
    """Jeu de données non trivial (décision du contrôleur : plusieurs
    fournisseurs, plusieurs blocs, au moins une anomalie ouverte), réutilisé
    par les tests de cohérence entre niveaux et de vue inverse : un
    chantier, deux fournisseurs, trois blocs (un reçu, un non reçu, un reçu
    portant une anomalie de quantité ouverte)."""
    chantier = await _creer_chantier(db_session, nom="Chantier Multi")
    fournisseur_1 = await _creer_fournisseur(db_session, nom="Fournisseur Un")
    fournisseur_2 = await _creer_fournisseur(db_session, nom="Fournisseur Deux")

    facture_1a = await _creer_facture(
        db_session, fournisseur=fournisseur_1, numero="F1A"
    )
    bloc_1a = await _creer_bloc(
        db_session,
        facture=facture_1a,
        chantier_id=chantier.id,
        numero_bl="BL-1A",
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session, document=facture_1a, bloc=bloc_1a, montant_ht=Decimal("100.00")
    )

    facture_1b = await _creer_facture(
        db_session, fournisseur=fournisseur_1, numero="F1B"
    )
    bloc_1b = await _creer_bloc(
        db_session,
        facture=facture_1b,
        chantier_id=chantier.id,
        numero_bl="BL-1B",
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture_1b, bloc=bloc_1b, montant_ht=Decimal("50.00")
    )

    facture_2a = await _creer_facture(
        db_session, fournisseur=fournisseur_2, numero="F2A"
    )
    bloc_2a = await _creer_bloc(
        db_session,
        facture=facture_2a,
        chantier_id=chantier.id,
        numero_bl="BL-2A",
        statut_rapprochement="recu",
    )
    ligne_2a = await _creer_ligne(
        db_session, document=facture_2a, bloc=bloc_2a, montant_ht=Decimal("70.00")
    )
    await _creer_anomalie(
        db_session,
        regle="R04",
        statut="ouverte",
        bloc_id=bloc_2a.id,
        ligne_id=ligne_2a.id,
    )

    return chantier, fournisseur_1, fournisseur_2, bloc_1a, bloc_1b, bloc_2a


# --------------------------------------------------------------------------
# 1. bloc reçu sans anomalie
# --------------------------------------------------------------------------


async def test_bilan_bloc_recu_sans_anomalie_compte_en_facture_et_en_rapproche(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Un")
    facture = await _creer_facture(db_session, fournisseur=fournisseur, numero="F1")
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("100.00")
    )

    lignes = await bilan_par_chantier(db_session, mois=None, agence=None)

    ligne = _ligne_du_chantier(lignes, chantier.id)
    ok = (
        ligne is not None
        and ligne.montants.facture_ht == Decimal("100.00")
        and ligne.montants.rapproche == Decimal("100.00")
        and ligne.montants.en_ecart == Decimal("0")
        and ligne.montants.non_justifie == Decimal("0")
        and ligne.montants.nb_anomalies_ouvertes == 0
    )
    assert ok, (
        "un bloc reçu sans anomalie doit compter dans facture_ht et rapproche, "
        "jamais dans en_ecart ni non_justifie"
    )


# --------------------------------------------------------------------------
# 2. bloc non reçu
# --------------------------------------------------------------------------


async def test_bilan_bloc_non_recu_compte_en_non_justifie(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Deux")
    facture = await _creer_facture(db_session, fournisseur=fournisseur, numero="F1")
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("80.00")
    )

    lignes = await bilan_par_chantier(db_session, mois=None, agence=None)

    ligne = _ligne_du_chantier(lignes, chantier.id)
    ok = (
        ligne is not None
        and ligne.montants.facture_ht == Decimal("80.00")
        and ligne.montants.rapproche == Decimal("0")
        and ligne.montants.non_justifie == Decimal("80.00")
    )
    assert ok, (
        "un bloc non reçu doit compter dans facture_ht et non_justifie, "
        "jamais dans rapproche"
    )


# --------------------------------------------------------------------------
# 3. bloc reçu + anomalie de quantité ouverte : compté deux fois (L5-D3)
# --------------------------------------------------------------------------


async def test_bilan_bloc_recu_avec_anomalie_ouverte_compte_dans_rapproche_et_en_ecart(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Trois")
    facture = await _creer_facture(db_session, fournisseur=fournisseur, numero="F1")
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        statut_rapprochement="recu",
    )
    ligne = await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("60.00")
    )
    await _creer_anomalie(
        db_session, regle="R03", statut="ouverte", bloc_id=bloc.id, ligne_id=ligne.id
    )

    lignes = await bilan_par_chantier(db_session, mois=None, agence=None)

    ligne_bilan = _ligne_du_chantier(lignes, chantier.id)
    ok = (
        ligne_bilan is not None
        and ligne_bilan.montants.rapproche == Decimal("60.00")
        and ligne_bilan.montants.en_ecart == Decimal("60.00")
        and ligne_bilan.montants.nb_anomalies_ouvertes == 1
    )
    assert ok, (
        "L5-D3 : un bloc reçu portant une anomalie de quantité ouverte compte à la "
        "fois dans rapproche et dans en_ecart -- les quatre montants ne forment "
        "pas une partition"
    )


# --------------------------------------------------------------------------
# 4. anomalie traitée : ne compte pas dans en_ecart
# --------------------------------------------------------------------------


async def test_bilan_anomalie_traitee_ne_compte_pas_dans_en_ecart(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Quatre")
    facture = await _creer_facture(db_session, fournisseur=fournisseur, numero="F1")
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        statut_rapprochement="recu",
    )
    ligne = await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("60.00")
    )
    await _creer_anomalie(
        db_session, regle="R03", statut="traitee", bloc_id=bloc.id, ligne_id=ligne.id
    )

    lignes = await bilan_par_chantier(db_session, mois=None, agence=None)

    ligne_bilan = _ligne_du_chantier(lignes, chantier.id)
    ok = (
        ligne_bilan is not None
        and ligne_bilan.montants.en_ecart == Decimal("0")
        and ligne_bilan.montants.nb_anomalies_ouvertes == 0
        and ligne_bilan.montants.rapproche == Decimal("60.00")
    )
    assert ok, "une anomalie traitee (non ouverte) ne doit jamais compter dans en_ecart"


# --------------------------------------------------------------------------
# 5. filtre par mois : un bloc du mois voisin est exclu
# --------------------------------------------------------------------------


async def test_bilan_filtre_mois_exclut_le_bloc_du_mois_voisin(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Cinq")
    facture_aout = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-AOUT", date_doc=date(2026, 8, 20)
    )
    bloc_aout = await _creer_bloc(
        db_session, facture=facture_aout, chantier_id=chantier.id, numero_bl="L1"
    )
    await _creer_ligne(
        db_session, document=facture_aout, bloc=bloc_aout, montant_ht=Decimal("100.00")
    )

    facture_septembre = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F-SEPT",
        date_doc=date(2026, 9, 5),
    )
    bloc_septembre = await _creer_bloc(
        db_session,
        facture=facture_septembre,
        chantier_id=chantier.id,
        numero_bl="L2",
    )
    await _creer_ligne(
        db_session,
        document=facture_septembre,
        bloc=bloc_septembre,
        montant_ht=Decimal("50.00"),
    )

    lignes = await bilan_par_chantier(db_session, mois=date(2026, 8, 1), agence=None)

    ligne_bilan = _ligne_du_chantier(lignes, chantier.id)
    ok = ligne_bilan is not None and ligne_bilan.montants.facture_ht == Decimal(
        "100.00"
    )
    assert ok, "le filtre mois=août ne doit retenir que le bloc de la facture d'août"


async def test_bilan_filtre_mois_exclut_anomalie_du_bloc_du_mois_voisin(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Mois Anomalie")
    facture_aout = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="ANOM-AOUT",
        date_doc=date(2026, 8, 20),
    )
    bloc_aout = await _creer_bloc(
        db_session,
        facture=facture_aout,
        chantier_id=chantier.id,
        numero_bl="ANOM-BL-AOUT",
    )
    await _creer_ligne(db_session, document=facture_aout, bloc=bloc_aout)

    facture_septembre = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="ANOM-SEPT",
        date_doc=date(2026, 9, 5),
    )
    bloc_septembre = await _creer_bloc(
        db_session,
        facture=facture_septembre,
        chantier_id=chantier.id,
        numero_bl="ANOM-BL-SEPT",
    )
    ligne_septembre = await _creer_ligne(
        db_session, document=facture_septembre, bloc=bloc_septembre
    )
    await _creer_anomalie(
        db_session,
        regle="R03",
        bloc_id=bloc_septembre.id,
        ligne_id=ligne_septembre.id,
    )

    lignes = await bilan_par_chantier(db_session, mois=date(2026, 8, 1), agence=None)

    ligne = _ligne_du_chantier(lignes, chantier.id)
    assert ligne is not None
    assert ligne.montants.nb_anomalies_ouvertes == 0
    assert ligne.montants.en_ecart == Decimal("0")


# --------------------------------------------------------------------------
# 6. facture archivée : exclue de tous les montants
# --------------------------------------------------------------------------


async def test_bilan_bloc_de_facture_archivee_exclu_de_tous_les_montants(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Six")
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F1", statut="archive"
    )
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        statut_rapprochement="recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("100.00")
    )

    lignes = await bilan_par_chantier(db_session, mois=None, agence=None)

    ok = _ligne_du_chantier(lignes, chantier.id) is None
    assert ok, "un bloc d'une facture archivée ne doit produire aucune ligne de bilan"


async def test_bilan_exclut_anomalie_dune_facture_archivee(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Archive Anomalie")
    facture_active = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="ACTIVE"
    )
    bloc_actif = await _creer_bloc(
        db_session, facture=facture_active, chantier_id=chantier.id
    )
    await _creer_ligne(db_session, document=facture_active, bloc=bloc_actif)

    facture_archivee = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="ARCHIVEE", statut="archive"
    )
    bloc_archive = await _creer_bloc(
        db_session, facture=facture_archivee, chantier_id=chantier.id
    )
    ligne_archivee = await _creer_ligne(
        db_session, document=facture_archivee, bloc=bloc_archive
    )
    await _creer_anomalie(
        db_session,
        regle="R03",
        bloc_id=bloc_archive.id,
        ligne_id=ligne_archivee.id,
    )

    lignes_chantier = await bilan_par_chantier(db_session, mois=None, agence=None)
    lignes_fournisseur = await bilan_par_fournisseur(
        db_session, chantier_id=chantier.id, mois=None, agence=None
    )

    ligne_chantier = _ligne_du_chantier(lignes_chantier, chantier.id)
    ligne_fournisseur = _ligne_du_fournisseur(lignes_fournisseur, fournisseur.id)
    assert ligne_chantier is not None
    assert ligne_fournisseur is not None
    assert ligne_chantier.montants.nb_anomalies_ouvertes == 0
    assert ligne_fournisseur.montants.nb_anomalies_ouvertes == 0


# --------------------------------------------------------------------------
# 7. blocs sans chantier résolu : regroupés sous chantier_id=None
# --------------------------------------------------------------------------


async def test_bilan_blocs_sans_chantier_resolu_regroupes_sous_ligne_nulle(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur, numero="F1")
    bloc = await _creer_bloc(
        db_session, facture=facture, chantier_id=None, statut_rapprochement="recu"
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("42.00")
    )

    lignes = await bilan_par_chantier(db_session, mois=None, agence=None)

    ligne_bilan = _ligne_du_chantier(lignes, None)
    ok = (
        ligne_bilan is not None
        and ligne_bilan.nom_canonique is None
        and ligne_bilan.agence is None
        and ligne_bilan.montants.facture_ht == Decimal("42.00")
    )
    assert ok, (
        "un bloc sans chantier résolu doit apparaître sous une ligne "
        "chantier_id=None, jamais disparaître du bilan"
    )


# --------------------------------------------------------------------------
# 8. filtre par agence
# --------------------------------------------------------------------------


async def test_bilan_filtre_agence_ne_retient_que_les_chantiers_de_cette_agence(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier_a = await _creer_chantier(db_session, nom="Chantier A", agence="Nord")
    chantier_b = await _creer_chantier(db_session, nom="Chantier B", agence="Sud")

    facture_a = await _creer_facture(db_session, fournisseur=fournisseur, numero="F-A")
    bloc_a = await _creer_bloc(
        db_session, facture=facture_a, chantier_id=chantier_a.id, numero_bl="LA"
    )
    await _creer_ligne(
        db_session, document=facture_a, bloc=bloc_a, montant_ht=Decimal("10.00")
    )

    facture_b = await _creer_facture(db_session, fournisseur=fournisseur, numero="F-B")
    bloc_b = await _creer_bloc(
        db_session, facture=facture_b, chantier_id=chantier_b.id, numero_bl="LB"
    )
    await _creer_ligne(
        db_session, document=facture_b, bloc=bloc_b, montant_ht=Decimal("20.00")
    )

    lignes = await bilan_par_chantier(db_session, mois=None, agence="Nord")

    ok = (
        len(lignes) == 1
        and lignes[0].chantier_id == chantier_a.id
        and lignes[0].agence == "Nord"
    )
    assert ok, "le filtre agence ne doit retenir que les chantiers de cette agence"


# --------------------------------------------------------------------------
# Ruling L5-R4 (tour de correction 1, L5-T1) : nb_anomalies_ouvertes compte
# toutes les anomalies ouvertes, pas seulement quantité/prix
# --------------------------------------------------------------------------


async def test_bilan_anomalie_r01_seule_compte_mais_ne_met_rien_en_ecart(
    db_session: AsyncSession,
) -> None:
    """Un chantier dont le bloc n'a jamais reçu de BL porte une anomalie R01
    (gravité haute) ouverte : `nb_anomalies_ouvertes` doit la compter même
    si R01 n'est pas une règle de quantité/prix -- `en_ecart` reste à zéro,
    ce n'est pas le même signal (Ruling L5-R4, docstring de
    `MontantsBilan`)."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier R01")
    facture = await _creer_facture(db_session, fournisseur=fournisseur, numero="F1")
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("30.00")
    )
    await _creer_anomalie(db_session, regle="R01", statut="ouverte", bloc_id=bloc.id)

    lignes = await bilan_par_chantier(db_session, mois=None, agence=None)

    ligne_bilan = _ligne_du_chantier(lignes, chantier.id)
    ok = (
        ligne_bilan is not None
        and ligne_bilan.montants.nb_anomalies_ouvertes == 1
        and ligne_bilan.montants.en_ecart == Decimal("0")
    )
    assert ok, (
        "une anomalie R01 seule doit compter dans nb_anomalies_ouvertes, "
        "jamais dans en_ecart"
    )


async def test_bilan_chantier_compte_r16_sans_bloc_sans_modifier_en_ecart(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier R16")
    autre_chantier = await _creer_chantier(db_session, nom="Autre chantier R16")
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("45.00")
    )
    await _creer_anomalie(db_session, regle="R16", chantier_id=chantier.id)
    await _creer_anomalie(db_session, regle="R16", chantier_id=autre_chantier.id)

    lignes = await bilan_par_chantier(db_session, mois=None, agence=None)
    lignes_fournisseur = await bilan_par_fournisseur(
        db_session, chantier_id=chantier.id, mois=None, agence=None
    )

    ligne = _ligne_du_chantier(lignes, chantier.id)
    ligne_fournisseur = _ligne_du_fournisseur(lignes_fournisseur, fournisseur.id)
    assert ligne is not None
    assert ligne_fournisseur is not None
    assert ligne.montants.nb_anomalies_ouvertes == 1
    assert ligne.montants.en_ecart == Decimal("0")
    assert ligne_fournisseur.montants.nb_anomalies_ouvertes == 0


async def test_bilan_filtre_mois_anomalie_sans_document_par_date_de_creation(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier R16 Mois")
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(db_session, document=facture, bloc=bloc)
    await _creer_anomalie(
        db_session,
        regle="R16",
        chantier_id=chantier.id,
        created_at=datetime(2026, 8, 20, 12, tzinfo=FUSEAU_PARIS),
    )
    await _creer_anomalie(
        db_session,
        regle="R14",
        chantier_id=chantier.id,
        created_at=datetime(2026, 9, 2, 12, tzinfo=FUSEAU_PARIS),
    )

    lignes = await bilan_par_chantier(db_session, mois=date(2026, 8, 1), agence=None)

    ligne = _ligne_du_chantier(lignes, chantier.id)
    assert ligne is not None
    assert ligne.montants.nb_anomalies_ouvertes == 1


async def test_bilan_compte_anomalie_document_sans_bloc_aux_niveaux_attribuables(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier document")
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(db_session, document=facture, bloc=bloc)
    document_bl = await _creer_document_bl(
        db_session, chantier_id=chantier.id, fournisseur_id=fournisseur.id
    )
    await _creer_anomalie(
        db_session, regle="R11", document_id=document_bl.id, bloc_id=None
    )

    lignes_chantier = await bilan_par_chantier(db_session, mois=None, agence=None)
    lignes_fournisseur = await bilan_par_fournisseur(
        db_session, chantier_id=chantier.id, mois=None, agence=None
    )
    lignes_bl = await bilan_par_bl(
        db_session, chantier_id=chantier.id, fournisseur_id=fournisseur.id, mois=None
    )

    ligne_chantier = _ligne_du_chantier(lignes_chantier, chantier.id)
    ligne_fournisseur = _ligne_du_fournisseur(lignes_fournisseur, fournisseur.id)
    ligne_bl = _ligne_du_bl(lignes_bl, bloc.id)
    assert ligne_chantier is not None
    assert ligne_fournisseur is not None
    assert ligne_bl is not None
    assert ligne_chantier.montants.nb_anomalies_ouvertes == 1
    assert ligne_fournisseur.montants.nb_anomalies_ouvertes == 1
    assert ligne_bl.montants.nb_anomalies_ouvertes == 0


async def test_bilan_filtre_mois_anomalies_documentaires_selon_le_document(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Document Mois")
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(db_session, document=facture, bloc=bloc)
    document_aout = await _creer_document_bl(
        db_session,
        chantier_id=chantier.id,
        fournisseur_id=fournisseur.id,
        date_doc=date(2026, 8, 18),
    )
    document_septembre = await _creer_document_bl(
        db_session,
        chantier_id=chantier.id,
        fournisseur_id=fournisseur.id,
        date_doc=date(2026, 9, 3),
    )
    await _creer_anomalie(db_session, regle="R11", document_id=document_aout.id)
    await _creer_anomalie(db_session, regle="R15", document_id=document_septembre.id)

    lignes_chantier = await bilan_par_chantier(
        db_session, mois=date(2026, 8, 1), agence=None
    )
    lignes_fournisseur = await bilan_par_fournisseur(
        db_session,
        chantier_id=chantier.id,
        mois=date(2026, 8, 1),
        agence=None,
    )
    lignes_bl = await bilan_par_bl(
        db_session,
        chantier_id=chantier.id,
        fournisseur_id=fournisseur.id,
        mois=date(2026, 8, 1),
    )

    ligne_chantier = _ligne_du_chantier(lignes_chantier, chantier.id)
    ligne_fournisseur = _ligne_du_fournisseur(lignes_fournisseur, fournisseur.id)
    ligne_bl = _ligne_du_bl(lignes_bl, bloc.id)
    assert ligne_chantier is not None
    assert ligne_fournisseur is not None
    assert ligne_bl is not None
    assert ligne_chantier.montants.nb_anomalies_ouvertes == 1
    assert ligne_fournisseur.montants.nb_anomalies_ouvertes == 1
    assert ligne_bl.montants.nb_anomalies_ouvertes == 0


# --------------------------------------------------------------------------
# Cas limite du filtre mois : repli sur created_at, heure de Paris
# --------------------------------------------------------------------------


async def test_bilan_filtre_mois_facture_creee_le_1er_a_paris_avant_minuit_utc(
    db_session: AsyncSession,
) -> None:
    """Cas limite du repli `created_at` (L5-D4) : une facture sans
    `date_doc`, créée le 1er du mois à 00h30 heure de Paris -- donc encore
    la veille en UTC (heure d'été, UTC+2) -- doit tomber dans le mois
    parisien demandé, pas dans le mois calendaire UTC."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Minuit Paris")
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="F1",
        date_doc=None,
        created_at=datetime(2026, 8, 1, 0, 30, tzinfo=FUSEAU_PARIS),
    )
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("15.00")
    )

    lignes = await bilan_par_chantier(db_session, mois=date(2026, 8, 1), agence=None)

    ligne_bilan = _ligne_du_chantier(lignes, chantier.id)
    ok = ligne_bilan is not None and ligne_bilan.montants.facture_ht == Decimal("15.00")
    assert ok, (
        "une facture créée le 1er du mois à 00h30 heure de Paris doit "
        "tomber dans ce mois parisien, même si c'est encore la veille en UTC"
    )


# --------------------------------------------------------------------------
# Tri : chantier_id comme départage ultime
# --------------------------------------------------------------------------


async def test_bilan_tri_ordonne_par_chantier_id_dans_la_requete_sql(
    db_session: AsyncSession,
) -> None:
    """Le tri est porté par la requête elle-même, pas par un tri Python sur
    une liste déjà construite (tour de correction 1) : `chantier_id` doit
    apparaître comme dernière clé de l'`ORDER BY` généré, pour que deux
    chantiers de même nom et de même montant facturé ne s'échangent jamais
    d'un appel à l'autre.

    Vérifié sur le texte SQL compilé, pas sur l'ordre observé : avec deux
    lignes seulement, Postgres peut renvoyer un ordre déjà croissant même
    sans départage explicite (vérifié empiriquement en retirant la clé
    pendant la préparation de ce correctif -- l'ordre observé ne changeait
    pas), ce qui rendrait un test purement comportemental peu fiable ici."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier SQL")
    facture = await _creer_facture(db_session, fournisseur=fournisseur, numero="F1")
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(db_session, document=facture, bloc=bloc)

    instructions: list[str] = []

    def _capturer(
        conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any
    ) -> None:
        instructions.append(statement)

    moteur_sync = db_session.get_bind()
    event.listen(moteur_sync, "before_cursor_execute", _capturer)
    try:
        await bilan_par_chantier(db_session, mois=None, agence=None)
    finally:
        event.remove(moteur_sync, "before_cursor_execute", _capturer)

    requetes_avec_tri = [sql for sql in instructions if "ORDER BY" in sql]
    ok = (
        len(requetes_avec_tri) == 1
        and "chantier.id" in requetes_avec_tri[0].split("ORDER BY", 1)[1]
    )
    assert ok, "chantier_id doit être une clé de l'ORDER BY généré par la requête"


# --------------------------------------------------------------------------
# Test d'équivalence (tour de correction 2) : le chemin bloc_id renseigné à
# la source (Ruling L5-R3) donne le même résultat que l'ancien contournement
# COALESCE retiré au tour de correction 1
# --------------------------------------------------------------------------


async def test_bilan_rattache_une_anomalie_de_prix_reelle_au_bon_chantier(
    db_session: AsyncSession,
) -> None:
    """Test de bout en bout (tour de correction 2) : un vrai rapprochement
    qui produit une anomalie de prix (R07/R08/R09) doit se retrouver dans
    `bilan_par_chantier`, rattachée au bon chantier. Preuve que le chemin
    aujourd'hui pris par `bilan_par_chantier` (`Anomalie.bloc_id` lu
    directement, renseigné à la source par `rapprocher_facture`, Ruling
    L5-R3) donne le même résultat que l'ancien contournement `COALESCE`
    retiré au tour de correction 1 -- sans ce test, plus rien ne protège ce
    chemin (constat de la re-revue)."""
    fournisseur = await _creer_fournisseur(db_session)
    chantier = await _creer_chantier(db_session, nom="Chantier Equivalence")
    article = await _creer_article(db_session, fournisseur=fournisseur, code="ART-EQ")

    for mois, numero in ((5, "H-EQ-1"), (6, "H-EQ-2"), (7, "H-EQ-3")):
        historique = await _creer_facture(
            db_session,
            fournisseur=fournisseur,
            numero=numero,
            date_doc=date(2026, mois, 1),
        )
        await _creer_ligne(
            db_session,
            document=historique,
            article=article,
            code_brut="ART-EQ",
            pu_ht=Decimal("10.00"),
            montant_ht=Decimal("10.00"),
        )

    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-EQ", date_doc=date(2026, 8, 20)
    )
    bloc = await _creer_bloc(
        db_session, facture=facture, chantier_id=chantier.id, numero_bl="L-EQ"
    )
    await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        article=article,
        code_brut="ART-EQ",
        pu_ht=Decimal("12.00"),
        montant_ht=Decimal("12.00"),
    )

    await rapprocher_facture(db_session, facture.id)

    lignes = await bilan_par_chantier(db_session, mois=None, agence=None)

    ligne_bilan = _ligne_du_chantier(lignes, chantier.id)
    ok = (
        ligne_bilan is not None
        and ligne_bilan.montants.en_ecart == Decimal("12.00")
        and ligne_bilan.montants.nb_anomalies_ouvertes >= 1
    )
    assert ok, (
        "une anomalie de prix produite par un rapprochement réel doit "
        "rattacher son bloc au bon chantier dans le bilan"
    )


# ==========================================================================
# L5-T2 : niveaux fournisseur et BL, vue inverse
# ==========================================================================


# --------------------------------------------------------------------------
# Cohérence entre niveaux (décision du contrôleur) : la somme des
# fournisseurs d'un chantier égale ce chantier, la somme des BL d'un
# fournisseur égale ce fournisseur
# --------------------------------------------------------------------------


async def test_bilan_somme_des_fournisseurs_dun_chantier_egale_le_chantier(
    db_session: AsyncSession,
) -> None:
    chantier, _f1, _f2, *_ = await _construire_jeu_non_trivial(db_session)

    lignes_chantier = await bilan_par_chantier(db_session, mois=None, agence=None)
    lignes_fournisseur = await bilan_par_fournisseur(
        db_session, chantier_id=chantier.id, mois=None, agence=None
    )

    ligne_chantier = _ligne_du_chantier(lignes_chantier, chantier.id)
    ok = (
        ligne_chantier is not None
        and len(lignes_fournisseur) == 2
        and _somme_montants([ligne.montants for ligne in lignes_fournisseur])
        == _montants_dict(ligne_chantier.montants)
    )
    assert ok, (
        "la somme des montants des fournisseurs d'un chantier doit égaler "
        "les montants de ce chantier"
    )


async def test_bilan_somme_des_bl_dun_fournisseur_egale_le_fournisseur(
    db_session: AsyncSession,
) -> None:
    (
        chantier,
        fournisseur_1,
        _f2,
        bloc_1a,
        bloc_1b,
        _b2a,
    ) = await _construire_jeu_non_trivial(db_session)

    lignes_fournisseur = await bilan_par_fournisseur(
        db_session, chantier_id=chantier.id, mois=None, agence=None
    )
    lignes_bl = await bilan_par_bl(
        db_session, chantier_id=chantier.id, fournisseur_id=fournisseur_1.id, mois=None
    )

    ligne_fournisseur_1 = _ligne_du_fournisseur(lignes_fournisseur, fournisseur_1.id)
    ids_bl = {ligne.bloc_id for ligne in lignes_bl}
    ok = (
        ligne_fournisseur_1 is not None
        and ids_bl == {bloc_1a.id, bloc_1b.id}
        and _somme_montants([ligne.montants for ligne in lignes_bl])
        == _montants_dict(ligne_fournisseur_1.montants)
    )
    assert ok, (
        "la somme des montants des BL d'un fournisseur (dans un chantier) doit "
        "égaler les montants de ce fournisseur"
    )


# --------------------------------------------------------------------------
# Blocs sans chantier ou sans fournisseur résolu : jamais ignorés
# --------------------------------------------------------------------------


async def test_bilan_par_fournisseur_retrouve_les_blocs_du_chantier_non_resolu(
    db_session: AsyncSession,
) -> None:
    """`chantier_id=None` sélectionne le côté « chantier non résolu » du
    périmètre (décision du contrôleur) -- le fournisseur, lui, reste résolu
    normalement."""
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Sans Chantier")
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-SANS-CHANT"
    )
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=None)
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("77.00")
    )

    lignes = await bilan_par_fournisseur(
        db_session, chantier_id=None, mois=None, agence=None
    )

    ligne = _ligne_du_fournisseur(lignes, fournisseur.id)
    ok = ligne is not None and ligne.montants.facture_ht == Decimal("77.00")
    assert ok, (
        "bilan_par_fournisseur(chantier_id=None) doit retrouver les blocs du "
        "chantier non résolu, jamais renvoyer une liste vide"
    )


async def test_bilan_par_fournisseur_bloc_sans_fournisseur_resolu_ligne_nulle(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Chantier Fournisseur Nul")
    facture = await _creer_facture_sans_fournisseur(db_session, numero="F-SANS-FOURN")
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("33.00")
    )

    lignes = await bilan_par_fournisseur(
        db_session, chantier_id=chantier.id, mois=None, agence=None
    )

    ligne = _ligne_du_fournisseur(lignes, None)
    ok = (
        ligne is not None
        and ligne.nom is None
        and ligne.montants.facture_ht == Decimal("33.00")
    )
    assert ok, (
        "un bloc sans fournisseur résolu doit apparaître sous une ligne "
        "fournisseur_id=None, jamais disparaître du bilan"
    )


async def test_bilan_par_bl_bloc_sans_chantier_ni_fournisseur_resolu(
    db_session: AsyncSession,
) -> None:
    facture = await _creer_facture_sans_fournisseur(db_session, numero="F-BL-SANS-RIEN")
    bloc = await _creer_bloc(
        db_session, facture=facture, chantier_id=None, numero_bl="BL-SANS-RIEN"
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("21.00")
    )

    lignes = await bilan_par_bl(
        db_session, chantier_id=None, fournisseur_id=None, mois=None
    )

    ligne = _ligne_du_bl(lignes, bloc.id)
    ok = ligne is not None and ligne.montants.facture_ht == Decimal("21.00")
    assert ok, (
        "un bloc sans chantier ni fournisseur résolu doit apparaître au niveau "
        "BL sous chantier_id=None/fournisseur_id=None, jamais disparaître"
    )


async def test_bilan_ne_compte_pas_anomalie_sans_origine_sur_lignes_non_resolues(
    db_session: AsyncSession,
) -> None:
    facture = await _creer_facture_sans_fournisseur(
        db_session, numero="F-ORIGINE-NULLE"
    )
    bloc = await _creer_bloc(
        db_session, facture=facture, chantier_id=None, numero_bl="BL-ORIGINE-NULLE"
    )
    await _creer_ligne(db_session, document=facture, bloc=bloc)
    await _creer_anomalie(db_session, regle="R16")

    lignes_chantier = await bilan_par_chantier(db_session, mois=None, agence=None)
    lignes_fournisseur = await bilan_par_fournisseur(
        db_session, chantier_id=None, mois=None, agence=None
    )

    ligne_chantier = _ligne_du_chantier(lignes_chantier, None)
    ligne_fournisseur = _ligne_du_fournisseur(lignes_fournisseur, None)
    assert ligne_chantier is not None
    assert ligne_fournisseur is not None
    assert ligne_chantier.montants.nb_anomalies_ouvertes == 0
    assert ligne_fournisseur.montants.nb_anomalies_ouvertes == 0


# --------------------------------------------------------------------------
# Vue inverse : mêmes montants que la vue directe
# --------------------------------------------------------------------------


async def test_bilan_vue_inverse_retrouve_les_memes_montants_que_la_vue_directe(
    db_session: AsyncSession,
) -> None:
    chantier_a = await _creer_chantier(db_session, nom="Chantier Inverse A")
    chantier_b = await _creer_chantier(db_session, nom="Chantier Inverse B")
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Inverse")

    facture_a = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="INV-A"
    )
    bloc_a = await _creer_bloc(
        db_session, facture=facture_a, chantier_id=chantier_a.id, numero_bl="INV-BL-A"
    )
    await _creer_ligne(
        db_session, document=facture_a, bloc=bloc_a, montant_ht=Decimal("40.00")
    )

    facture_b = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="INV-B"
    )
    bloc_b = await _creer_bloc(
        db_session,
        facture=facture_b,
        chantier_id=chantier_b.id,
        numero_bl="INV-BL-B",
        statut_rapprochement="non_recu",
    )
    await _creer_ligne(
        db_session, document=facture_b, bloc=bloc_b, montant_ht=Decimal("25.00")
    )

    lignes_globales = await bilan_par_fournisseur_global(
        db_session, mois=None, agence=None
    )
    lignes_chantiers_du_fournisseur = await bilan_chantiers_du_fournisseur(
        db_session, fournisseur_id=fournisseur.id, mois=None, agence=None
    )
    lignes_fournisseur_a = await bilan_par_fournisseur(
        db_session, chantier_id=chantier_a.id, mois=None, agence=None
    )

    ligne_globale = _ligne_du_fournisseur(lignes_globales, fournisseur.id)
    ligne_directe_a = _ligne_du_fournisseur(lignes_fournisseur_a, fournisseur.id)
    ligne_inverse_a = _ligne_du_chantier(lignes_chantiers_du_fournisseur, chantier_a.id)
    ok = (
        ligne_globale is not None
        and ligne_directe_a is not None
        and ligne_inverse_a is not None
        and len(lignes_chantiers_du_fournisseur) == 2
        and _somme_montants(
            [ligne.montants for ligne in lignes_chantiers_du_fournisseur]
        )
        == _montants_dict(ligne_globale.montants)
        and _montants_dict(ligne_directe_a.montants)
        == _montants_dict(ligne_inverse_a.montants)
    )
    assert ok, (
        "la vue inverse (bilan_par_fournisseur_global / "
        "bilan_chantiers_du_fournisseur) doit retrouver les mêmes montants "
        "que la vue directe"
    )


# --------------------------------------------------------------------------
# Filtres mois et agence : s'appliquent aux niveaux fournisseur et à la vue
# inverse (le niveau BL n'a pas de paramètre agence, décision du
# contrôleur -- le chantier y est déjà fixé par chantier_id)
# --------------------------------------------------------------------------


async def test_bilan_filtre_agence_sapplique_au_niveau_fournisseur_et_a_la_vue_inverse(
    db_session: AsyncSession,
) -> None:
    chantier_nord = await _creer_chantier(
        db_session, nom="Chantier Agence Nord", agence="Nord"
    )
    chantier_sud = await _creer_chantier(
        db_session, nom="Chantier Agence Sud", agence="Sud"
    )
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Agences")

    facture_nord = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="AG-NORD"
    )
    bloc_nord = await _creer_bloc(
        db_session,
        facture=facture_nord,
        chantier_id=chantier_nord.id,
        numero_bl="AG-BL-N",
    )
    await _creer_ligne(
        db_session, document=facture_nord, bloc=bloc_nord, montant_ht=Decimal("11.00")
    )

    facture_sud = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="AG-SUD"
    )
    bloc_sud = await _creer_bloc(
        db_session,
        facture=facture_sud,
        chantier_id=chantier_sud.id,
        numero_bl="AG-BL-S",
    )
    await _creer_ligne(
        db_session, document=facture_sud, bloc=bloc_sud, montant_ht=Decimal("22.00")
    )

    lignes_fournisseur_nord = await bilan_par_fournisseur(
        db_session, chantier_id=chantier_nord.id, mois=None, agence="Nord"
    )
    lignes_fournisseur_sud_filtre_nord = await bilan_par_fournisseur(
        db_session, chantier_id=chantier_sud.id, mois=None, agence="Nord"
    )
    lignes_globales_nord = await bilan_par_fournisseur_global(
        db_session, mois=None, agence="Nord"
    )
    lignes_chantiers_nord = await bilan_chantiers_du_fournisseur(
        db_session, fournisseur_id=fournisseur.id, mois=None, agence="Nord"
    )

    ok = (
        len(lignes_fournisseur_nord) == 1
        and lignes_fournisseur_nord[0].montants.facture_ht == Decimal("11.00")
        and len(lignes_fournisseur_sud_filtre_nord) == 0
        and len(lignes_globales_nord) == 1
        and lignes_globales_nord[0].montants.facture_ht == Decimal("11.00")
        and len(lignes_chantiers_nord) == 1
        and lignes_chantiers_nord[0].chantier_id == chantier_nord.id
    )
    assert ok, (
        "le filtre agence doit s'appliquer au niveau fournisseur (direct et "
        "restreint à un chantier d'une autre agence) et à la vue inverse"
    )


async def test_bilan_fournisseur_global_exclut_anomalies_des_autres_agences(
    db_session: AsyncSession,
) -> None:
    chantier_nord = await _creer_chantier(
        db_session, nom="Chantier Compte Nord", agence="Nord"
    )
    chantier_sud = await _creer_chantier(
        db_session, nom="Chantier Compte Sud", agence="Sud"
    )
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Compte Agence")

    for chantier, suffixe in ((chantier_nord, "N"), (chantier_sud, "S")):
        facture = await _creer_facture(
            db_session, fournisseur=fournisseur, numero=f"COMPTE-{suffixe}"
        )
        bloc = await _creer_bloc(
            db_session,
            facture=facture,
            chantier_id=chantier.id,
            numero_bl=f"COMPTE-BL-{suffixe}",
        )
        ligne_facture = await _creer_ligne(db_session, document=facture, bloc=bloc)
        await _creer_anomalie(
            db_session,
            regle="R03",
            bloc_id=bloc.id,
            ligne_id=ligne_facture.id,
        )

    lignes = await bilan_par_fournisseur_global(db_session, mois=None, agence="Nord")

    ligne_bilan = _ligne_du_fournisseur(lignes, fournisseur.id)
    assert ligne_bilan is not None
    assert ligne_bilan.montants.nb_anomalies_ouvertes == 1


async def test_bilan_filtre_mois_sapplique_au_niveau_fournisseur_et_bl(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Chantier Mois F")
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Mois F")

    facture_aout = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="MOIS-AOUT",
        date_doc=date(2026, 8, 12),
    )
    bloc_aout = await _creer_bloc(
        db_session,
        facture=facture_aout,
        chantier_id=chantier.id,
        numero_bl="MOIS-BL-AOUT",
    )
    await _creer_ligne(
        db_session, document=facture_aout, bloc=bloc_aout, montant_ht=Decimal("15.00")
    )

    facture_sept = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        numero="MOIS-SEPT",
        date_doc=date(2026, 9, 3),
    )
    bloc_sept = await _creer_bloc(
        db_session,
        facture=facture_sept,
        chantier_id=chantier.id,
        numero_bl="MOIS-BL-SEPT",
    )
    await _creer_ligne(
        db_session, document=facture_sept, bloc=bloc_sept, montant_ht=Decimal("9.00")
    )

    lignes_fournisseur_aout = await bilan_par_fournisseur(
        db_session, chantier_id=chantier.id, mois=date(2026, 8, 1), agence=None
    )
    lignes_bl_aout = await bilan_par_bl(
        db_session,
        chantier_id=chantier.id,
        fournisseur_id=fournisseur.id,
        mois=date(2026, 8, 1),
    )

    ok = (
        len(lignes_fournisseur_aout) == 1
        and lignes_fournisseur_aout[0].montants.facture_ht == Decimal("15.00")
        and len(lignes_bl_aout) == 1
        and lignes_bl_aout[0].bloc_id == bloc_aout.id
    )
    assert ok, "le filtre mois doit s'appliquer au niveau fournisseur et au niveau BL"


# --------------------------------------------------------------------------
# Facture archivée : exclue à tous les niveaux
# --------------------------------------------------------------------------


async def test_bilan_bloc_facture_archivee_exclu_au_niveau_fournisseur_et_bl(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Chantier Archive F")
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Archive F")
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="ARCH-F", statut="archive"
    )
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("60.00")
    )

    lignes_fournisseur = await bilan_par_fournisseur(
        db_session, chantier_id=chantier.id, mois=None, agence=None
    )
    lignes_bl = await bilan_par_bl(
        db_session, chantier_id=chantier.id, fournisseur_id=fournisseur.id, mois=None
    )
    lignes_globales = await bilan_par_fournisseur_global(
        db_session, mois=None, agence=None
    )

    ok = (
        len(lignes_fournisseur) == 0
        and len(lignes_bl) == 0
        and _ligne_du_fournisseur(lignes_globales, fournisseur.id) is None
    )
    assert ok, (
        "un bloc de facture archivée ne doit produire aucune ligne de bilan, "
        "à aucun niveau"
    )


# --------------------------------------------------------------------------
# Niveau BL : bl_document_id renseigné ou vide
# --------------------------------------------------------------------------


async def test_bilan_par_bl_rend_bl_document_id_quand_la_photo_existe(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Chantier BL Photo")
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur BL Photo")
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="BL-PHOTO-F"
    )
    bl_photo = await _creer_document_bl(db_session)
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        numero_bl="BL-PHOTO",
        bl_document_id=bl_photo.id,
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("18.00")
    )

    lignes = await bilan_par_bl(
        db_session, chantier_id=chantier.id, fournisseur_id=fournisseur.id, mois=None
    )

    ligne = _ligne_du_bl(lignes, bloc.id)
    ok = (
        ligne is not None
        and ligne.bl_document_id == bl_photo.id
        and ligne.facture_id == facture.id
    )
    assert ok, (
        "bilan_par_bl doit renvoyer bl_document_id quand la photo du BL a été "
        "retrouvée par le rapprochement"
    )


async def test_bilan_par_bl_rend_bl_document_id_vide_quand_absent(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Chantier BL Sans Photo")
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur BL Sans Photo")
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="BL-SANS-F"
    )
    bloc = await _creer_bloc(
        db_session, facture=facture, chantier_id=chantier.id, numero_bl="BL-SANS"
    )
    await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("9.00")
    )

    lignes = await bilan_par_bl(
        db_session, chantier_id=chantier.id, fournisseur_id=fournisseur.id, mois=None
    )

    ligne = _ligne_du_bl(lignes, bloc.id)
    ok = ligne is not None and ligne.bl_document_id is None
    assert ok, (
        "bilan_par_bl doit renvoyer bl_document_id=None quand la photo du BL "
        "n'a pas été retrouvée"
    )


# --------------------------------------------------------------------------
# Tri : dernière clé de départage, comme à L5-T1 -- vérifié sur un niveau
# supplémentaire (fournisseur), le mécanisme étant partagé
# (`_bilan_par_fournisseur_interne`)
# --------------------------------------------------------------------------


async def test_bilan_par_fournisseur_tri_ordonne_par_fournisseur_id_dans_la_requete_sql(
    db_session: AsyncSession,
) -> None:
    chantier = await _creer_chantier(db_session, nom="Chantier Tri Fournisseur")
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Tri")
    facture = await _creer_facture(db_session, fournisseur=fournisseur, numero="TRI-F")
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=chantier.id)
    await _creer_ligne(db_session, document=facture, bloc=bloc)

    instructions: list[str] = []

    def _capturer(
        conn: Any, cursor: Any, statement: str, *args: Any, **kwargs: Any
    ) -> None:
        instructions.append(statement)

    moteur_sync = db_session.get_bind()
    event.listen(moteur_sync, "before_cursor_execute", _capturer)
    try:
        await bilan_par_fournisseur(
            db_session, chantier_id=chantier.id, mois=None, agence=None
        )
    finally:
        event.remove(moteur_sync, "before_cursor_execute", _capturer)

    requetes_avec_tri = [sql for sql in instructions if "ORDER BY" in sql]
    ok = (
        len(requetes_avec_tri) == 1
        and "fournisseur.id" in requetes_avec_tri[0].split("ORDER BY", 1)[1]
    )
    assert ok, "fournisseur_id doit être une clé de l'ORDER BY généré par la requête"
