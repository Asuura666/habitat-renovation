"""Tests de `ingest/recalcul_bons.py` (lot 2 du 31/10/2026, A5) : appliquer
aux bons déjà reçus les règles de lecture (fournisseur confirmé, chantier
reconnu ou lu dans la référence de commande), **sans rappeler l'OCR**, depuis
`document.ocr_brut`. Base de test réelle, données entièrement inventées."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest import mistral
from app.modules.ingest.models import Chantier, Document, Fournisseur, Journal
from app.modules.ingest.recalcul_bons import recalculer_bons

pytestmark = [pytest.mark.anyio, pytest.mark.db]

_DONNEES = (
    Path(__file__).resolve().parent.parent.parent
    / "extract"
    / "tests"
    / "donnees"
    / "bl_synthetique.mistral-ocr.json"
)
with _DONNEES.open(encoding="utf-8") as _fichier:
    _REPONSE_BASE: dict[str, Any] = json.load(_fichier)


@pytest.fixture(autouse=True)
def _ocr_interdit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _echoue(*args: object, **kwargs: object) -> dict[str, Any]:
        raise AssertionError("l'OCR ne doit jamais être appelé")

    monkeypatch.setattr(mistral, "ocr_document", _echoue)


def _reponse(
    *, nom_incertain: bool = False, reference: str | None = None, chantier: bool = True
) -> dict[str, Any]:
    reponse = copy.deepcopy(_REPONSE_BASE)
    if nom_incertain:
        for mot in reponse["pages"][0]["confidence_scores"]["word_confidence_scores"]:
            if mot["text"] == " PEINTURES":
                mot["confidence"] = 0.10
    annotation = json.loads(reponse["document_annotation"])
    if not chantier:
        annotation["chantier_brut"] = None
    if reference is not None:
        annotation["numero_commande"] = reference
    reponse["document_annotation"] = json.dumps(annotation)
    return reponse


async def _creer_bon(
    db_session: AsyncSession,
    reponse: dict[str, Any] | None,
    *,
    statut: str = "a_verifier",
    type_: str = "bl",
    codes: tuple[tuple[str, str], ...] = (),
) -> Document:
    document = Document(
        motifs=[{"code": c, "champ": champ, "detail": {}} for c, champ in codes],
        type=type_,
        source="telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        ocr_brut=reponse,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _referentiel(db_session: AsyncSession, *, tva: bool = True) -> None:
    db_session.add(
        Fournisseur(nom="Négoce Exemple", tva="FR00000000000" if tva else None)
    )
    await db_session.commit()


async def test_fournisseur_confirme_le_bon_passe_a_recu(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await _referentiel(db_session)
    db_session.add(Chantier(nom_canonique="Maison Test", a_completer=False))
    await db_session.commit()
    bon = await _creer_bon(
        db_session,
        _reponse(nom_incertain=True),
        codes=(
            ("fournisseur_inconnu", "fournisseur"),
            ("confiance_faible", "fournisseur"),
        ),
    )

    bilan = await recalculer_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.statut == "recu"
    assert bon.motifs == []
    assert bilan.examines == 1
    assert bilan.passes_a_recu == 1
    assert bilan.motifs_leves == {"fournisseur_inconnu": 1, "confiance_faible": 1}
    assert bilan.echecs == 0


async def test_chantier_lu_dans_la_reference_est_compte(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await _referentiel(db_session)
    kayre = Chantier(nom_canonique="Kayre", a_completer=False)
    db_session.add(kayre)
    await db_session.commit()
    bon = await _creer_bon(
        db_session,
        _reponse(chantier=False, reference="KAYRE"),
        codes=(
            ("champ_absent", "chantier_brut"),
            ("fournisseur_inconnu", "fournisseur"),
        ),
    )

    bilan = await recalculer_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.chantier_id == kayre.id
    assert bon.statut == "recu"
    assert bilan.chantiers_par_reference == 1
    assert bilan.passes_a_recu == 1
    assert bilan.motifs_leves == {"champ_absent": 1, "fournisseur_inconnu": 1}


async def test_un_bon_corrige_a_la_main_n_est_pas_touche(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await _referentiel(db_session)
    bon = await _creer_bon(db_session, _reponse(nom_incertain=True))
    bon.numero = "A-MAIN"
    db_session.add(
        Journal(
            utilisateur_id=None,
            action="document_corrige",
            cible_table="document",
            cible_id=str(bon.id),
            avant={},
            apres={},
        )
    )
    await db_session.commit()

    bilan = await recalculer_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.numero == "A-MAIN"
    assert bon.fournisseur_id is None
    assert (bilan.examines, bilan.ignores) == (0, 1)


async def test_seuls_les_bons_a_verifier_avec_lecture_sont_examines(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await _referentiel(db_session)
    await _creer_bon(db_session, _reponse(), statut="recu")
    await _creer_bon(db_session, _reponse(), statut="archive")
    await _creer_bon(db_session, None)
    await _creer_bon(db_session, _reponse(), type_="facture")
    enlevement = await _creer_bon(db_session, _reponse(), type_="enlevement")

    bilan = await recalculer_bons(db_session, tmp_path)

    assert bilan.examines == 1
    await db_session.refresh(enlevement)
    assert enlevement.fournisseur_id is not None


async def test_simulation_n_ecrit_rien(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await _referentiel(db_session)
    bon = await _creer_bon(db_session, _reponse(nom_incertain=True))

    bilan = await recalculer_bons(db_session, tmp_path, simulation=True)

    await db_session.refresh(bon)
    assert bilan.examines == 1
    assert bon.fournisseur_id is None
    assert bon.statut == "a_verifier"
    journaux = (
        (
            await db_session.execute(
                select(Journal).where(Journal.cible_id == str(bon.id))
            )
        )
        .scalars()
        .all()
    )
    assert journaux == []


# --------------------------------------------------------------------------
# Un chantier choisi à la main (`chantier_choisi`) n'est jamais écrasé par la
# relecture ; il lève les motifs de lecture du chantier (correction 1).
# --------------------------------------------------------------------------


async def _bon_avec_chantier_choisi(
    db_session: AsyncSession, *, avec_correction_apres: bool = False
) -> tuple[Document, Chantier]:
    choisi = Chantier(nom_canonique="Choisi Main", a_completer=True)
    db_session.add(choisi)
    await db_session.commit()
    bon = await _creer_bon(
        db_session,
        _reponse(nom_incertain=True),
        codes=(("confiance_faible", "chantier_brut"),),
    )
    bon.chantier_id = choisi.id
    db_session.add(
        Journal(
            utilisateur_id=None,
            action="chantier_choisi",
            cible_table="document",
            cible_id=str(bon.id),
            avant={"chantier_id": None},
            apres={"chantier_id": str(choisi.id)},
        )
    )
    await db_session.commit()
    if avec_correction_apres:
        # Hors `corriges_a_la_main` pour ce test : on appelle le rattachement.
        db_session.add(
            Journal(
                utilisateur_id=None,
                action="document_corrige",
                cible_table="document",
                cible_id=str(bon.id),
                avant={},
                apres={},
            )
        )
        await db_session.commit()
    return bon, choisi


async def test_recalcul_garde_le_chantier_choisi_et_leve_le_motif(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await _referentiel(db_session)
    bon, choisi = await _bon_avec_chantier_choisi(db_session)
    # La lecture donne « MAISON TEST » : sans protection, elle écraserait.
    reponse = _reponse(nom_incertain=False)
    for mot in reponse["pages"][0]["confidence_scores"]["word_confidence_scores"]:
        if mot["text"] == " MAISON":
            mot["confidence"] = 0.10
    bon.ocr_brut = reponse
    await db_session.commit()

    bilan = await recalculer_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.chantier_id == choisi.id
    assert bilan.motifs_leves.get("confiance_faible") == 1
    assert all(
        not (m["code"] == "confiance_faible" and m["champ"] == "chantier_brut")
        for m in bon.motifs or []
    )
    assert bon.statut == "recu"


async def test_resolution_fournisseurs_garde_le_chantier_choisi(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    from app.modules.ingest.resolution_fournisseurs import (
        resoudre_fournisseurs_des_bons,
    )

    await _referentiel(db_session)
    bon, choisi = await _bon_avec_chantier_choisi(db_session)

    await resoudre_fournisseurs_des_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.fournisseur_id is not None
    assert bon.chantier_id == choisi.id


async def test_correction_plus_recente_que_le_choix_re_resout_normalement(
    db_session: AsyncSession,
) -> None:
    from app.modules.ingest.rattachement_chantier import (
        rattacher_chantier_document,
    )

    db_session.add(Chantier(nom_canonique="Maison Test", a_completer=False))
    await db_session.commit()
    bon, choisi = await _bon_avec_chantier_choisi(
        db_session, avec_correction_apres=True
    )
    bon.chantier_brut = "MAISON TEST"
    await db_session.flush()

    resultat = await rattacher_chantier_document(db_session, bon)

    assert resultat.methode == "ressemblance"
    assert bon.chantier_id != choisi.id


async def test_r18_traitee_est_toujours_conservee_et_leve_le_motif() -> None:
    import uuid as _uuid

    from app.modules.extract.verification import CodeMotif, Motif
    from app.modules.ingest.ajustement_motifs import ajuster_motifs
    from app.modules.ingest.rattachement_chantier import ResultatRattachement

    motifs = [
        Motif(CodeMotif.CONFIANCE_FAIBLE, "chantier_brut", {}),
        Motif(CodeMotif.CHAMP_ABSENT, "chantier_brut", {}),
        Motif(CodeMotif.CONFIANCE_FAIBLE, "numero", {}),
    ]
    resultat = ResultatRattachement(
        chantier_id=_uuid.uuid4(),
        methode="décision humaine conservée",
        score=None,
        cree=False,
        alerte=False,
        chantier_nom="Choisi",
        chantier_a_completer=True,
    )

    ajuste = ajuster_motifs(motifs, methode_fournisseur=None, chantier=resultat)

    assert [m.champ for m in ajuste.motifs] == ["numero"]
    assert ajuste.leves == (
        {"champ": "chantier_brut", "raison": "Chantier choisi à la main : Choisi"},
    )
