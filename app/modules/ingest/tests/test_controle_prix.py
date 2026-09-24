"""Tests de la désactivation des contrôles de prix (décision d'Ilane du
24/09/2026, `docs/dette.md`) : un seul mois de factures ne fonde aucun
« prix habituel », R07 (« Prix un peu plus cher »), R08 (« Prix plus cher
que d'habitude ») et R09 (« Remise habituelle oubliée ») sont désactivées
côté serveur tant que `CONTROLE_PRIX_ACTIF` n'est pas explicitement à
`true`.

Trois volets, données entièrement inventées (jamais `tests/fixtures/`) :
- `ingest.commun` (pur, sans base) : le drapeau et l'ensemble de règles
  qu'il dérive ;
- le calcul (`ingest.rapprochement.rapprocher_facture`) : R07/R08/R09 ne
  sont pas évaluées quand désactivées, et une anomalie déjà ouverte n'est
  jamais levée par un rejeu (masquée, pas détruite) ;
- le masquage de chaque lecture : « À régler » (`lister_anomalies`), le
  compte (`compter_anomalies_ouvertes`/`compter_problemes_a_regler`), le
  tableau de bord, le bilan (montants et export détaillé) et la
  comparaison d'un BL.

`app/modules/ingest/tests/conftest.py` réenclenche `controle_prix_actif`
par défaut pour tout le paquet (sinon la plupart des tests `ingest`
existants, écrits avant cette décision, verraient leurs anomalies
R07/R08/R09 masquées) : chaque test ci-dessous qui veut le drapeau
désactivé l'écrase localement avec `_regler_controle_prix`.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest import commun
from app.modules.ingest.a_traiter import compter_problemes_a_regler
from app.modules.ingest.anomalies import compter_anomalies_ouvertes, lister_anomalies
from app.modules.ingest.bilan import bilan_detail, bilan_par_chantier
from app.modules.ingest.comparaison_bl import comparer_bl
from app.modules.ingest.export import csv_bilan_detail
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Document,
    Fournisseur,
    Ligne,
    RapprochementLigne,
)
from app.modules.ingest.rapprochement import rapprocher_facture
from app.modules.ingest.tableau_de_bord import tableau_de_bord
from app.modules.rules.engine import REGLES_FACTURE

pytestmark = [pytest.mark.anyio, pytest.mark.db]


def _regler_controle_prix(monkeypatch: pytest.MonkeyPatch, *, actif: bool) -> None:
    """Écrase, pour le test courant, la fixture autouse
    `_controle_prix_actif_par_defaut` (`conftest.py`) -- même idiome (seule
    `ingest.commun.get_settings` est monkeypatchée, jamais une seconde
    lecture de `Settings` ailleurs)."""

    class _SettingsInventee:
        controle_prix_actif = actif

    monkeypatch.setattr(commun, "get_settings", lambda: _SettingsInventee())


# --------------------------------------------------------------------------
# `ingest.commun` (pur, sans base)
# --------------------------------------------------------------------------


def test_regles_desactivees_vide_quand_actif(monkeypatch: pytest.MonkeyPatch) -> None:
    _regler_controle_prix(monkeypatch, actif=True)

    assert commun.controle_prix_actif() is True
    assert commun.regles_desactivees() == frozenset()


def test_regles_desactivees_prix_quand_inactif(monkeypatch: pytest.MonkeyPatch) -> None:
    _regler_controle_prix(monkeypatch, actif=False)

    assert commun.controle_prix_actif() is False
    assert commun.regles_desactivees() == frozenset({"R07", "R08", "R09"})


def test_regles_desactivees_ne_touche_aucune_autre_regle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seules R07/R08/R09 sont concernées -- toute autre règle de
    `REGLES_FACTURE` reste active même drapeau désactivé."""
    _regler_controle_prix(monkeypatch, actif=False)

    assert (REGLES_FACTURE - commun.regles_desactivees()) == REGLES_FACTURE - {
        "R07",
        "R08",
        "R09",
    }


# --------------------------------------------------------------------------
# Aides de construction (données inventées) -- même forme que
# `test_rapprochement.py`/`test_comparaison_bl.py`.
# --------------------------------------------------------------------------


async def _creer_fournisseur(
    db_session: AsyncSession, *, nom: str = "Fournisseur Testeur Prix"
) -> Fournisseur:
    fournisseur = Fournisseur(nom=nom)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _creer_facture(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    numero: str = "F-PRIX-0001",
    date_doc: date = date(2026, 8, 15),
) -> Document:
    document = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero=numero,
        fournisseur_id=fournisseur.id,
        date_doc=date_doc,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_bl(
    db_session: AsyncSession,
    *,
    fournisseur: Fournisseur,
    numero: str = "L-PRIX-0001",
    date_doc: date = date(2026, 8, 1),
) -> Document:
    document = Document(
        type="bl",
        source="telegram",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        numero=numero,
        fournisseur_id=fournisseur.id,
        date_doc=date_doc,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_bloc(
    db_session: AsyncSession,
    *,
    facture: Document,
    bl: Document | None,
    numero_bl: str = "L-PRIX-0001",
) -> BlocFacture:
    bloc = BlocFacture(
        facture_id=facture.id,
        ordre=0,
        numero_bl=numero_bl,
        bl_document_id=bl.id if bl is not None else None,
        statut_rapprochement="recu" if bl is not None else "non_recu",
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
    pu_ht: Decimal | None = None,
    montant_ht: Decimal | None = None,
    qte_totale: Decimal | None = None,
) -> Ligne:
    ligne = Ligne(
        document_id=document.id,
        bloc_id=bloc.id if bloc is not None else None,
        code_brut="ART-PRIX",
        article_brut="Article inventé",
        type_ligne="article",
        ordre=ordre,
        pu_ht=pu_ht,
        montant_ht=montant_ht,
        qte_totale=qte_totale,
    )
    db_session.add(ligne)
    await db_session.commit()
    await db_session.refresh(ligne)
    return ligne


async def _creer_anomalie_r08(
    db_session: AsyncSession,
    *,
    document: Document,
    bloc: BlocFacture,
    ligne: Ligne,
) -> Anomalie:
    """Une anomalie R08 « déjà ouverte » -- posée directement en base
    (jamais via `evaluer_facture`) : les tests de masquage n'ont besoin que
    de sa présence, pas d'un historique de prix réel."""
    anomalie = Anomalie(
        regle="R08",
        gravite="haute",
        statut="ouverte",
        document_id=document.id,
        bloc_id=bloc.id,
        ligne_id=ligne.id,
        detail={
            "article": "Article inventé",
            "code": "ART-PRIX",
            "pu_facture": "130.00",
            "mediane": "100.00",
            "ecart_pct": "30",
            "occurrences": "3",
        },
    )
    db_session.add(anomalie)
    await db_session.commit()
    await db_session.refresh(anomalie)
    return anomalie


@pytest.fixture
async def scenario_r08(
    db_session: AsyncSession,
) -> tuple[Document, BlocFacture, Ligne, Anomalie]:
    """Une facture reçue avec un bloc reçu (BL rapproché), une ligne
    article et une anomalie R08 ouverte dessus -- scénario partagé par les
    tests de masquage de lecture ci-dessous."""
    fournisseur = await _creer_fournisseur(db_session)
    bl = await _creer_bl(db_session, fournisseur=fournisseur)
    facture = await _creer_facture(db_session, fournisseur=fournisseur)
    bloc = await _creer_bloc(db_session, facture=facture, bl=bl)
    ligne = await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        pu_ht=Decimal("130.00"),
        montant_ht=Decimal("130.00"),
        qte_totale=Decimal("1"),
    )
    ligne_bl = await _creer_ligne(
        db_session, document=bl, bloc=None, qte_totale=Decimal("1")
    )
    db_session.add(
        RapprochementLigne(
            ligne_facture_id=ligne.id, ligne_bl_id=ligne_bl.id, methode="code"
        )
    )
    await db_session.commit()
    anomalie = await _creer_anomalie_r08(
        db_session, document=facture, bloc=bloc, ligne=ligne
    )
    return facture, bloc, ligne, anomalie


# --------------------------------------------------------------------------
# Masquage de chaque lecture (requirement 3 de la tâche)
# --------------------------------------------------------------------------


async def test_r08_masquee_de_lister_anomalies_quand_desactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    """« À régler » (`GET /api/anomalies`)."""
    _regler_controle_prix(monkeypatch, actif=False)

    anomalies = await lister_anomalies(db_session, statut="ouverte")

    assert not any(a.regle == "R08" for a in anomalies)


async def test_r08_reapparait_dans_lister_anomalies_quand_reactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    _regler_controle_prix(monkeypatch, actif=True)

    anomalies = await lister_anomalies(db_session, statut="ouverte")

    assert any(a.regle == "R08" for a in anomalies)


async def test_r08_masquee_du_compte_quand_desactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    """Pastille de navigation / en-tête « À régler » (`compter_anomalies_
    ouvertes`, repris par `compter_problemes_a_regler`)."""
    _regler_controle_prix(monkeypatch, actif=False)

    nb_ouvertes, nb_hautes = await compter_anomalies_ouvertes(db_session)
    compte = await compter_problemes_a_regler(db_session)

    assert nb_ouvertes == 0
    assert nb_hautes == 0
    assert compte.nb_problemes == 0
    assert compte.nb_urgents == 0
    assert compte.controle_prix_actif is False


async def test_r08_compte_quand_reactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    _regler_controle_prix(monkeypatch, actif=True)

    nb_ouvertes, nb_hautes = await compter_anomalies_ouvertes(db_session)
    compte = await compter_problemes_a_regler(db_session)

    assert nb_ouvertes == 1
    assert nb_hautes == 1
    assert compte.nb_problemes == 1
    assert compte.controle_prix_actif is True


async def test_r08_masquee_du_tableau_de_bord_quand_desactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    _regler_controle_prix(monkeypatch, actif=False)

    donnees = await tableau_de_bord(db_session, mois=date(2026, 8, 1))

    assert donnees.nb_problemes_ouverts == 0
    assert donnees.nb_problemes_urgents == 0
    assert donnees.priorites == []
    # Aucun chantier ne peut être marqué « prix » (catégorie R08) alors que
    # la seule anomalie du périmètre est masquée.
    assert all(c.etat != "prix" for c in donnees.chantiers)


async def test_r08_visible_du_tableau_de_bord_quand_reactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    _regler_controle_prix(monkeypatch, actif=True)

    donnees = await tableau_de_bord(db_session, mois=date(2026, 8, 1))

    assert donnees.nb_problemes_ouverts == 1
    assert donnees.nb_problemes_urgents == 1


async def test_r08_masquee_du_bilan_quand_desactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    """`en_ecart`, `conforme` et `nb_anomalies_ouvertes` (tuiles/colonnes du
    bilan) -- une seule ligne (`chantier_id=None`, aucun chantier résolu)."""
    _regler_controle_prix(monkeypatch, actif=False)

    lignes = await bilan_par_chantier(db_session, mois=None, agence=None)

    assert len(lignes) == 1
    montants = lignes[0].montants
    assert montants.en_ecart == Decimal("0")
    assert montants.nb_anomalies_ouvertes == 0
    assert montants.conforme == Decimal("130.00")


async def test_r08_visible_du_bilan_quand_reactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    _regler_controle_prix(monkeypatch, actif=True)

    lignes = await bilan_par_chantier(db_session, mois=None, agence=None)

    assert len(lignes) == 1
    montants = lignes[0].montants
    assert montants.en_ecart == Decimal("130.00")
    assert montants.nb_anomalies_ouvertes == 1
    assert montants.conforme == Decimal("0")


async def test_r08_masquee_de_la_comparaison_bl_quand_desactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    """Page BL, contrôle par ligne et `nb_problemes`."""
    _regler_controle_prix(monkeypatch, actif=False)
    _facture, bloc, _ligne, _anomalie = scenario_r08
    bl_document_id = bloc.bl_document_id
    assert bl_document_id is not None

    comparaison = await comparer_bl(db_session, bl_document_id)

    assert comparaison.nb_problemes == 0
    assert all(ligne.regles_ouvertes == [] for ligne in comparaison.lignes)


async def test_r08_visible_de_la_comparaison_bl_quand_reactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    _regler_controle_prix(monkeypatch, actif=True)
    _facture, bloc, _ligne, _anomalie = scenario_r08
    bl_document_id = bloc.bl_document_id
    assert bl_document_id is not None

    comparaison = await comparer_bl(db_session, bl_document_id)

    assert comparaison.nb_problemes == 1
    assert any(ligne.regles_ouvertes == ["R08"] for ligne in comparaison.lignes)


async def test_r08_masquee_de_lexport_csv_quand_desactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    """Export détaillé (`bilan_detail`/`csv_bilan_detail`, colonnes
    « Anomalies ouvertes »/« Règles concernées »)."""
    _regler_controle_prix(monkeypatch, actif=False)

    lignes = await bilan_detail(db_session, mois=None, agence=None)

    assert len(lignes) == 1
    assert lignes[0].nb_anomalies_ouvertes == 0
    assert lignes[0].codes_regles == ()
    csv = csv_bilan_detail(lignes)
    assert "R08" not in csv


async def test_r08_visible_de_lexport_csv_quand_reactive(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    scenario_r08: tuple[Document, BlocFacture, Ligne, Anomalie],
) -> None:
    _regler_controle_prix(monkeypatch, actif=True)

    lignes = await bilan_detail(db_session, mois=None, agence=None)

    assert len(lignes) == 1
    assert lignes[0].nb_anomalies_ouvertes == 1
    assert lignes[0].codes_regles == ("R08",)
    csv = csv_bilan_detail(lignes)
    assert "R08" in csv


# --------------------------------------------------------------------------
# Calcul (`rapprochement.rapprocher_facture`) -- requirement 2/5 de la tâche
# --------------------------------------------------------------------------


async def _historique_et_facture_hors_prix(
    db_session: AsyncSession, *, fournisseur: Fournisseur
) -> Document:
    """Trois factures historiques à 10,00 € (occurrences suffisantes,
    L4-D9), puis une facture d'août à 13,00 € (+30 %, hors seuil fort) sur
    le même article -- même scénario que `test_rapprochement.py::test_
    rapprocher_facture_prix_hors_historique_anomalie_r07`, dupliqué ici
    (jamais importé d'un autre module de tests) pour ne dépendre que de ce
    fichier."""
    from app.modules.ingest.models import Article

    article = Article(fournisseur_id=fournisseur.id, code="ART-HISTO")
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    for mois, numero in ((5, "H-PRIX-0001"), (6, "H-PRIX-0002"), (7, "H-PRIX-0003")):
        historique = Document(
            type="facture",
            source="upload",
            statut="recu",
            fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
            numero=numero,
            fournisseur_id=fournisseur.id,
            date_doc=date(2026, mois, 1),
        )
        db_session.add(historique)
        await db_session.commit()
        await db_session.refresh(historique)
        ligne = Ligne(
            document_id=historique.id,
            article_id=article.id,
            code_brut="ART-HISTO",
            type_ligne="article",
            ordre=0,
            pu_ht=Decimal("10.00"),
            montant_ht=Decimal("10.00"),
        )
        db_session.add(ligne)
        await db_session.commit()

    facture = Document(
        type="facture",
        source="upload",
        statut="recu",
        fichier_path=f"chemin-invente-{uuid.uuid4()}.pdf",
        numero="F-PRIX-HISTO",
        fournisseur_id=fournisseur.id,
        date_doc=date(2026, 8, 15),
    )
    db_session.add(facture)
    await db_session.commit()
    await db_session.refresh(facture)
    bloc = BlocFacture(facture_id=facture.id, ordre=0, numero_bl="L-PRIX-HISTO")
    db_session.add(bloc)
    await db_session.commit()
    await db_session.refresh(bloc)
    ligne_facture = Ligne(
        document_id=facture.id,
        bloc_id=bloc.id,
        article_id=article.id,
        code_brut="ART-HISTO",
        type_ligne="article",
        ordre=0,
        pu_ht=Decimal("13.00"),
        montant_ht=Decimal("13.00"),
    )
    db_session.add(ligne_facture)
    await db_session.commit()
    return facture


async def _anomalies_de(db_session: AsyncSession, facture: Document) -> list[Anomalie]:
    return list(
        (
            await db_session.execute(
                select(Anomalie).where(
                    (Anomalie.document_id == facture.id)
                    | (
                        Anomalie.bloc_id.in_(
                            select(BlocFacture.id).where(
                                BlocFacture.facture_id == facture.id
                            )
                        )
                    )
                    | (
                        Anomalie.ligne_id.in_(
                            select(Ligne.id).where(Ligne.document_id == facture.id)
                        )
                    )
                )
            )
        )
        .scalars()
        .all()
    )


async def test_rapprocher_facture_nevalue_pas_r07_r08_r09_quand_desactive(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _regler_controle_prix(monkeypatch, actif=False)
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Historique")
    facture = await _historique_et_facture_hors_prix(
        db_session, fournisseur=fournisseur
    )

    await rapprocher_facture(db_session, facture.id)

    anomalies = await _anomalies_de(db_session, facture)
    assert not any(a.regle in ("R07", "R08", "R09") for a in anomalies)


async def test_rapprocher_facture_evalue_r07_r08_r09_quand_active(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _regler_controle_prix(monkeypatch, actif=True)
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Historique 2")
    facture = await _historique_et_facture_hors_prix(
        db_session, fournisseur=fournisseur
    )

    await rapprocher_facture(db_session, facture.id)

    anomalies = await _anomalies_de(db_session, facture)
    assert any(a.regle in ("R07", "R08") for a in anomalies)


async def test_rapprocher_facture_ne_supprime_pas_une_r08_existante_quand_desactive(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement de la tâche : la portée de `synchroniser_anomalies` ne
    doit jamais considérer R07/R08/R09 comme « recalculées » quand elles
    sont désactivées -- une anomalie R08 déjà ouverte (posée ici comme si
    elle datait d'un rejeu où le drapeau était actif) doit survivre à un
    nouveau rapprochement fait drapeau désactivé, sans être levée."""
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur Survie R08")
    bl = await _creer_bl(db_session, fournisseur=fournisseur, numero="L-SURVIE")
    facture = await _creer_facture(
        db_session, fournisseur=fournisseur, numero="F-SURVIE"
    )
    bloc = await _creer_bloc(db_session, facture=facture, bl=bl, numero_bl="L-SURVIE")
    ligne = await _creer_ligne(
        db_session,
        document=facture,
        bloc=bloc,
        pu_ht=Decimal("130.00"),
        montant_ht=Decimal("130.00"),
        qte_totale=Decimal("1"),
    )
    await _creer_ligne(
        db_session,
        document=bl,
        bloc=None,
        pu_ht=Decimal("130.00"),
        montant_ht=Decimal("130.00"),
        qte_totale=Decimal("1"),
    )
    anomalie = await _creer_anomalie_r08(
        db_session, document=facture, bloc=bloc, ligne=ligne
    )

    _regler_controle_prix(monkeypatch, actif=False)
    await rapprocher_facture(db_session, facture.id)

    encore_presente = await db_session.get(Anomalie, anomalie.id)
    assert encore_presente is not None
    assert encore_presente.statut == "ouverte"


async def test_rapprocher_facture_leve_bien_une_r01_quand_desactive(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contre-épreuve : la portée réduite ne bloque le balayage que pour
    R07/R08/R09 -- une R01 (BL jamais reçu) devenue obsolète après dépôt du
    bon reste levée normalement, drapeau désactivé ou non."""
    _regler_controle_prix(monkeypatch, actif=False)
    fournisseur = await _creer_fournisseur(db_session, nom="Fournisseur R01 Levee")
    facture = await _creer_facture(db_session, fournisseur=fournisseur, numero="F-R01")
    bloc = await _creer_bloc(db_session, facture=facture, bl=None, numero_bl="L-R01")
    await _creer_ligne(db_session, document=facture, bloc=bloc)

    await rapprocher_facture(db_session, facture.id)
    anomalies_avant = await _anomalies_de(db_session, facture)
    assert any(a.regle == "R01" for a in anomalies_avant)

    await _creer_bl(db_session, fournisseur=fournisseur, numero="L-R01")
    await rapprocher_facture(db_session, facture.id)

    anomalies_apres = await _anomalies_de(db_session, facture)
    assert not any(a.regle == "R01" for a in anomalies_apres)
