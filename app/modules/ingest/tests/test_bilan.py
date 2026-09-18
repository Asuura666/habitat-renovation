"""Tests de `ingest/bilan.py` (L5-T1) : agrégats du bilan par chantier.

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
from app.modules.ingest.bilan import LigneBilanChantier, bilan_par_chantier
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
    gravite: str = "haute",
) -> Anomalie:
    anomalie = Anomalie(
        regle=regle,
        gravite=gravite,
        statut=statut,
        bloc_id=bloc_id,
        ligne_id=ligne_id,
        document_id=document_id,
        article_id=article_id,
        detail={"cle": "valeur"},
        traitee_le=datetime.now(UTC) if statut != "ouverte" else None,
        commentaire="Traitée (test)." if statut != "ouverte" else None,
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
