"""Tests de `ingest/bilan.py::bilan_detail` (export détaillé du bilan,
décision d'Ilane du 23/09/2026, réponse à Q3 du lot 5) : une ligne par ligne
de facture, sur tout le périmètre filtré.

Base de test réelle (`bl_test`, ici `bl_test_export`), données entièrement
inventées (R17). `db_session` (fixture locale, `app/modules/ingest/tests
/conftest.py`) vide toutes les tables après chaque test.

Copie réduite des aides de construction de `test_bilan.py` (même raison que
`app/modules/api/tests/test_bilan_csv.py` : pas d'import d'un paquet
`tests` frère), plus deux aides propres à ce fichier
(`_creer_document_bl`/`_creer_rapprochement`) pour la quantité BL appariée.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.bilan import LigneBilanDetail, bilan_detail
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Chantier,
    Document,
    Fournisseur,
    Ligne,
    RapprochementLigne,
)

pytestmark = [pytest.mark.anyio, pytest.mark.db]


# --------------------------------------------------------------------------
# Aides de construction (données inventées)
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur Detail"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_chantier(
    db_session: AsyncSession,
    *,
    nom: str = "Chantier Detail",
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
    date_doc: date | None = date(2026, 8, 15),
    created_at: datetime | None = None,
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
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


async def _creer_document_bl(
    db_session: AsyncSession, *, fournisseur: Fournisseur | None = None
) -> Document:
    """Document BL minimal (données inventées), seulement pour porter une
    ligne de BL à apparier -- son contenu réel n'importe pas à ces tests."""
    document = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
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
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=ordre,
        numero_bl=numero_bl,
        chantier_id=chantier_id,
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
    montant_ht: Decimal | None = Decimal("100.00"),
    type_ligne: str = "article",
    ordre: int = 0,
    code_brut: str | None = "ART1",
    article_brut: str | None = "Article inventé",
    qte_totale: Decimal | None = Decimal("10"),
    unite_brut: str | None = "U",
    pu_ht: Decimal | None = Decimal("10.00"),
    remise_pct: Decimal | None = None,
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        bloc_id=bloc.id if bloc is not None else None,
        montant_ht=montant_ht,
        type_ligne=type_ligne,
        ordre=ordre,
        code_brut=code_brut,
        article_brut=article_brut,
        qte_totale=qte_totale,
        unite_brut=unite_brut,
        pu_ht=pu_ht,
        remise_pct=remise_pct,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _creer_rapprochement(
    db_session: AsyncSession,
    *,
    ligne_facture: Ligne,
    ligne_bl: Ligne,
    methode: str = "code",
) -> RapprochementLigne:
    rapprochement = RapprochementLigne(
        ligne_facture_id=ligne_facture.id, ligne_bl_id=ligne_bl.id, methode=methode
    )
    db_session.add(rapprochement)
    await db_session.commit()
    return rapprochement


async def _creer_anomalie(
    db_session: AsyncSession,
    *,
    regle: str = "R03",
    statut: str = "ouverte",
    bloc_id: uuid.UUID | None = None,
    ligne_id: uuid.UUID | None = None,
    gravite: str = "haute",
) -> Anomalie:
    anomalie = Anomalie(
        regle=regle,
        gravite=gravite,
        statut=statut,
        bloc_id=bloc_id,
        ligne_id=ligne_id,
        detail={"cle": "valeur"},
        traitee_le=datetime.now(UTC) if statut != "ouverte" else None,
        commentaire="Traitée (test)." if statut != "ouverte" else None,
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)
    return anomalie


def _ligne_de(
    lignes: list[LigneBilanDetail], ligne_id: uuid.UUID
) -> LigneBilanDetail | None:
    for ligne in lignes:
        if ligne.ligne_id == ligne_id:
            return ligne
    return None


# --------------------------------------------------------------------------
# Cas nominal
# --------------------------------------------------------------------------


async def test_bilan_detail_cas_nominal(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Nominal")
    chantier = await _creer_chantier(
        db_session, nom="Chantier Nominal", agence="Agence Un"
    )
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-NOM", date_doc=date(2026, 8, 15)
    )
    bloc = await _creer_bloc(
        db_session,
        facture=facture,
        chantier_id=chantier.id,
        numero_bl="BL-NOM",
        statut_rapprochement="recu",
    )
    ligne = await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        montant_ht=Decimal("95.00"),
        qte_totale=Decimal("10"),
        unite_brut="U",
        pu_ht=Decimal("10.00"),
        remise_pct=Decimal("5.00"),
    )

    lignes = await bilan_detail(db_session, mois=None, agence=None)

    resultat = _ligne_de(lignes, ligne.id)
    assert resultat is not None
    assert resultat.bloc_id == bloc.id
    assert resultat.facture_id == facture.id
    assert resultat.mois == date(2026, 8, 1)
    assert resultat.fournisseur_id == fournisseur.id
    assert resultat.fournisseur_nom == "Fournisseur Nominal"
    assert resultat.numero_facture == "F-NOM"
    assert resultat.date_facture == date(2026, 8, 15)
    assert resultat.chantier_id == chantier.id
    assert resultat.nom_chantier == "Chantier Nominal"
    assert resultat.agence == "Agence Un"
    assert resultat.numero_bl == "BL-NOM"
    assert resultat.statut_rapprochement == "recu"
    assert resultat.type_ligne == "article"
    assert resultat.code_article == "ART1"
    assert resultat.designation == "Article inventé"
    assert resultat.qte_facturee == Decimal("10")
    assert resultat.unite == "U"
    assert resultat.pu_ht == Decimal("10.00")
    assert resultat.remise_pct == Decimal("5.00")
    assert resultat.montant_ht == Decimal("95.00")
    assert resultat.qte_bl_appariee is None
    assert resultat.nb_anomalies_ouvertes == 0
    assert resultat.codes_regles == ()


async def test_bilan_detail_ligne_commentaire_incluse_sans_montant(
    db_session: AsyncSession,
) -> None:
    """Une ligne "commentaire" (jamais de montant) est incluse au même titre
    qu'une ligne "article" -- rien n'est tu au client (CDC : « le client
    ouvrira ce fichier dans Excel pour tout vérifier »)."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture)
    ligne = await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        type_ligne="commentaire",
        montant_ht=None,
        qte_totale=None,
        unite_brut=None,
        pu_ht=None,
        remise_pct=None,
        code_brut=None,
        article_brut="Livraison le matin uniquement",
    )

    lignes = await bilan_detail(db_session, mois=None, agence=None)

    resultat = _ligne_de(lignes, ligne.id)
    assert resultat is not None
    assert resultat.type_ligne == "commentaire"
    assert resultat.montant_ht is None
    assert resultat.qte_facturee is None
    assert resultat.designation == "Livraison le matin uniquement"


# --------------------------------------------------------------------------
# Chantier non résolu conservé
# --------------------------------------------------------------------------


async def test_bilan_detail_chantier_non_resolu_conserve(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, chantier_id=None)
    ligne = await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("42.00")
    )

    lignes = await bilan_detail(db_session, mois=None, agence=None)

    resultat = _ligne_de(lignes, ligne.id)
    assert resultat is not None
    assert resultat.chantier_id is None
    assert resultat.nom_chantier is None
    assert resultat.agence is None
    assert resultat.montant_ht == Decimal("42.00")


# --------------------------------------------------------------------------
# Filtre mois, frontière Europe/Paris
# --------------------------------------------------------------------------


async def test_bilan_detail_filtre_mois_facture_creee_le_1er_a_paris_avant_minuit_utc(
    db_session: AsyncSession,
) -> None:
    """Même cas limite que `test_bilan.py` (L5-D4, tour de correction 1) :
    une facture sans `date_doc`, créée le 1er du mois à 00h30 heure de
    Paris -- donc encore la veille en UTC (heure d'été) -- doit tomber dans
    le mois parisien demandé, avec `mois` posé sur ce même 1er."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(
        db_session,
        fournisseur=fournisseur,
        date_doc=None,
        created_at=datetime(2026, 8, 1, 0, 30, tzinfo=FUSEAU_PARIS),
    )
    bloc = await _creer_bloc(db_session, facture=facture)
    ligne = await _creer_ligne(
        db_session, document=facture, bloc=bloc, montant_ht=Decimal("15.00")
    )

    lignes_aout = await bilan_detail(db_session, mois=date(2026, 8, 1), agence=None)
    lignes_juillet = await bilan_detail(db_session, mois=date(2026, 7, 1), agence=None)

    resultat = _ligne_de(lignes_aout, ligne.id)
    assert resultat is not None
    assert resultat.mois == date(2026, 8, 1)
    assert _ligne_de(lignes_juillet, ligne.id) is None


# --------------------------------------------------------------------------
# Filtre agence
# --------------------------------------------------------------------------


async def test_bilan_detail_filtre_agence(db_session: AsyncSession) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    chantier_nord = await _creer_chantier(
        db_session, nom="Chantier Nord", agence="Nord"
    )
    chantier_sud = await _creer_chantier(db_session, nom="Chantier Sud", agence="Sud")
    facture_nord = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-NORD"
    )
    facture_sud = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-SUD"
    )
    bloc_nord = await _creer_bloc(
        db_session, facture=facture_nord, chantier_id=chantier_nord.id
    )
    bloc_sud = await _creer_bloc(
        db_session, facture=facture_sud, chantier_id=chantier_sud.id
    )
    ligne_nord = await _creer_ligne(db_session, document=facture_nord, bloc=bloc_nord)
    ligne_sud = await _creer_ligne(db_session, document=facture_sud, bloc=bloc_sud)

    lignes_nord = await bilan_detail(db_session, mois=None, agence="Nord")

    assert _ligne_de(lignes_nord, ligne_nord.id) is not None
    assert _ligne_de(lignes_nord, ligne_sud.id) is None


# --------------------------------------------------------------------------
# Quantité BL appariée
# --------------------------------------------------------------------------


async def test_bilan_detail_ligne_sans_appariement_qte_bl_vide(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture)
    ligne = await _creer_ligne(db_session, document=facture, bloc=bloc)

    lignes = await bilan_detail(db_session, mois=None, agence=None)

    resultat = _ligne_de(lignes, ligne.id)
    assert resultat is not None
    assert resultat.qte_bl_appariee is None


async def test_bilan_detail_ligne_appariee_qte_bl_renseignee(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture)
    ligne_facture = await _creer_ligne(
        db_session, document=facture, bloc=bloc, qte_totale=Decimal("12")
    )
    document_bl = await _creer_document_bl(db_session, fournisseur=fournisseur)
    ligne_bl = await _creer_ligne(
        db_session, document=document_bl, bloc=None, qte_totale=Decimal("10")
    )
    await _creer_rapprochement(
        db_session, ligne_facture=ligne_facture, ligne_bl=ligne_bl
    )

    lignes = await bilan_detail(db_session, mois=None, agence=None)

    resultat = _ligne_de(lignes, ligne_facture.id)
    assert resultat is not None
    assert resultat.qte_facturee == Decimal("12")
    assert resultat.qte_bl_appariee == Decimal("10")


# --------------------------------------------------------------------------
# Anomalies : pas de double comptage, comptées une fois par ligne ou bloc
# --------------------------------------------------------------------------


async def test_bilan_detail_anomalie_ligne_et_bloc_pas_de_double_comptage(
    db_session: AsyncSession,
) -> None:
    """Un bloc porte une anomalie sans ligne propre (R01, « BL non reçu »),
    une de ses deux lignes porte en plus une anomalie de ligne (R03) :
    - la ligne concernée par les deux doit compter exactement 2 anomalies
      (jamais 3, 4 ou plus -- pas de duplication par un JOIN direct) ;
    - l'autre ligne du même bloc, elle, ne porte que l'anomalie du bloc (1),
      jamais celle de sa voisine."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(
        db_session, facture=facture, statut_rapprochement="non_recu"
    )
    ligne_avec_r03 = await _creer_ligne(
        db_session, document=facture, bloc=bloc, ordre=0, code_brut="ART-A"
    )
    ligne_sans_r03 = await _creer_ligne(
        db_session, document=facture, bloc=bloc, ordre=1, code_brut="ART-B"
    )
    await _creer_anomalie(db_session, regle="R01", bloc_id=bloc.id, ligne_id=None)
    await _creer_anomalie(
        db_session, regle="R03", bloc_id=bloc.id, ligne_id=ligne_avec_r03.id
    )

    lignes = await bilan_detail(db_session, mois=None, agence=None)

    resultat_avec = _ligne_de(lignes, ligne_avec_r03.id)
    resultat_sans = _ligne_de(lignes, ligne_sans_r03.id)
    assert resultat_avec is not None and resultat_sans is not None
    assert resultat_avec.nb_anomalies_ouvertes == 2
    assert resultat_avec.codes_regles == ("R01", "R03")
    assert resultat_sans.nb_anomalies_ouvertes == 1
    assert resultat_sans.codes_regles == ("R01",)
    # Chaque ligne apparaît une seule fois dans le résultat, quel que soit
    # le nombre d'anomalies qui la concernent (piège documenté).
    assert sum(1 for ligne in lignes if ligne.ligne_id == ligne_avec_r03.id) == 1


async def test_bilan_detail_anomalie_fermee_non_comptee(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture)
    ligne = await _creer_ligne(db_session, document=facture, bloc=bloc)
    await _creer_anomalie(
        db_session,
        regle="R03",
        statut="traitee",
        bloc_id=bloc.id,
        ligne_id=ligne.id,
    )

    lignes = await bilan_detail(db_session, mois=None, agence=None)

    resultat = _ligne_de(lignes, ligne.id)
    assert resultat is not None
    assert resultat.nb_anomalies_ouvertes == 0
    assert resultat.codes_regles == ()


async def test_bilan_detail_anomalie_r06_jamais_attribuee_a_une_ligne_de_facture(
    db_session: AsyncSession,
) -> None:
    """Limite documentée (`docs/dette.md`) : R06 porte `ligne_id` sur la
    ligne de BL absente de la facture, jamais sur une ligne de ce périmètre
    -- elle ne doit apparaître dans le compte d'aucune ligne exportée, même
    si son `bloc_id` est dans le périmètre."""
    fournisseur = await _creer_fournisseur(db_session)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture)
    ligne = await _creer_ligne(db_session, document=facture, bloc=bloc)
    document_bl = await _creer_document_bl(db_session, fournisseur=fournisseur)
    ligne_bl_non_facturee = await _creer_ligne(
        db_session, document=document_bl, bloc=None
    )
    await _creer_anomalie(
        db_session, regle="R06", bloc_id=bloc.id, ligne_id=ligne_bl_non_facturee.id
    )

    lignes = await bilan_detail(db_session, mois=None, agence=None)

    resultat = _ligne_de(lignes, ligne.id)
    assert resultat is not None
    assert resultat.nb_anomalies_ouvertes == 0
    assert resultat.codes_regles == ()


# --------------------------------------------------------------------------
# Tri déterministe
# --------------------------------------------------------------------------


async def test_bilan_detail_tri_par_chantier_puis_fournisseur_puis_ligne(
    db_session: AsyncSession,
) -> None:
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Tri")
    chantier_a = await _creer_chantier(db_session, nom="Chantier A")
    chantier_b = await _creer_chantier(db_session, nom="Chantier B")
    facture_b = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-TRI-B"
    )
    facture_a = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-TRI-A"
    )
    bloc_b = await _creer_bloc(
        db_session, facture=facture_b, chantier_id=chantier_b.id, numero_bl="B"
    )
    bloc_a = await _creer_bloc(
        db_session, facture=facture_a, chantier_id=chantier_a.id, numero_bl="A"
    )
    ligne_b = await _creer_ligne(db_session, document=facture_b, bloc=bloc_b)
    ligne_a = await _creer_ligne(db_session, document=facture_a, bloc=bloc_a)

    lignes = await bilan_detail(db_session, mois=None, agence=None)

    position_a = next(
        i for i, ligne in enumerate(lignes) if ligne.ligne_id == ligne_a.id
    )
    position_b = next(
        i for i, ligne in enumerate(lignes) if ligne.ligne_id == ligne_b.id
    )
    assert position_a < position_b
