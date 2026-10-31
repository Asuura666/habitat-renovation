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
