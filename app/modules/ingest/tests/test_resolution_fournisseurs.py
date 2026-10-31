"""Tests de `ingest/resolution_fournisseurs.py` (décision d'Ilane du
31/10/2026) : rattacher aux fournisseurs créés après coup les bons déjà reçus,
**sans rappeler l'OCR**, à partir de `document.ocr_brut`.

Base de test réelle, données entièrement inventées (la réponse OCR
synthétique de `extract/tests/donnees`, fournisseur « PEINTURES EXEMPLE SAS »,
SIRET « 000 000 000 00000 », TVA « FR00000000000 »).
"""

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
from app.modules.ingest.models import Document, Fournisseur, Journal
from app.modules.ingest.resolution_fournisseurs import resoudre_fournisseurs_des_bons

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
    """Aucun appel OCR n'est permis : l'OCR factice échoue s'il est appelé."""

    async def _echoue(*args: object, **kwargs: object) -> dict[str, Any]:
        raise AssertionError("l'OCR ne doit jamais être appelé")

    monkeypatch.setattr(mistral, "ocr_document", _echoue)


def _reponse() -> dict[str, Any]:
    return copy.deepcopy(_REPONSE_BASE)


async def _creer_bon(
    db_session: AsyncSession,
    *,
    type_: str = "bl",
    statut: str = "a_verifier",
    avec_ocr: bool = True,
    fournisseur: Fournisseur | None = None,
) -> Document:
    document = Document(
        type=type_,
        source="telegram",
        statut=statut,
        fichier_path=f"chemin-invente-{uuid.uuid4()}.jpg",
        fournisseur_id=fournisseur.id if fournisseur is not None else None,
        ocr_brut=_reponse() if avec_ocr else None,
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _creer_fournisseur(db_session: AsyncSession, **champs: Any) -> Fournisseur:
    fournisseur = Fournisseur(**champs)
    db_session.add(fournisseur)
    await db_session.commit()
    await db_session.refresh(fournisseur)
    return fournisseur


async def _journaux(
    db_session: AsyncSession, document_id: uuid.UUID, action: str
) -> Any:
    return (
        (
            await db_session.execute(
                select(Journal).where(
                    Journal.cible_id == str(document_id), Journal.action == action
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.parametrize(
    "champs",
    [
        {"nom": "Peintures Exemple", "tva": "FR00000000000"},
        {"nom": "Peintures Exemple", "aliases": ["Peintures Exemple SAS"]},
        {"nom": "Négoce Exemple", "siret": "000 000 000 12345"},
    ],
    ids=["par TVA", "par nom/alias", "par SIREN"],
)
async def test_bon_sans_fournisseur_rattache_apres_creation_du_fournisseur(
    db_session: AsyncSession, tmp_path: Path, champs: dict[str, Any]
) -> None:
    bon = await _creer_bon(db_session)
    fournisseur = await _creer_fournisseur(db_session, **champs)

    bilan = await resoudre_fournisseurs_des_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.fournisseur_id == fournisseur.id
    assert (bilan.relus, bilan.rattaches, bilan.inconnus, bilan.ignores) == (
        1,
        1,
        0,
        0,
    )
    journaux = await _journaux(db_session, bon.id, "extraction_relancee")
    assert len(journaux) == 1
    assert journaux[0].utilisateur_id is None
    assert journaux[0].apres == {"origine": "Sans nouvel OCR (lecture déjà gardée)"}


async def test_un_enlevement_est_traite_aussi(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    bon = await _creer_bon(db_session, type_="enlevement")
    fournisseur = await _creer_fournisseur(
        db_session, nom="Peintures Exemple", tva="FR00000000000"
    )

    await resoudre_fournisseurs_des_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.fournisseur_id == fournisseur.id


async def test_fournisseur_toujours_inconnu_est_compte_et_non_rattache(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    bon = await _creer_bon(db_session)
    await _creer_fournisseur(db_session, nom="Autre Société", tva="FR99999999999")

    bilan = await resoudre_fournisseurs_des_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.fournisseur_id is None
    assert (bilan.relus, bilan.rattaches, bilan.inconnus, bilan.ignores) == (
        1,
        0,
        1,
        0,
    )


@pytest.mark.parametrize(
    "action", ["document_corrige", "lignes_corrigees", "document_valide"]
)
async def test_bon_corrige_ou_valide_a_la_main_est_ignore(
    db_session: AsyncSession, tmp_path: Path, action: str
) -> None:
    bon = await _creer_bon(db_session)
    await _creer_fournisseur(db_session, nom="Peintures Exemple", tva="FR00000000000")
    db_session.add(
        Journal(
            utilisateur_id=None,
            action=action,
            cible_table="document",
            cible_id=str(bon.id),
            avant=None,
            apres=None,
        )
    )
    await db_session.commit()

    bilan = await resoudre_fournisseurs_des_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.fournisseur_id is None
    assert (bilan.relus, bilan.rattaches, bilan.inconnus, bilan.ignores) == (
        0,
        0,
        0,
        1,
    )
    assert await _journaux(db_session, bon.id, "extraction_relancee") == []


async def test_bon_archive_est_ignore_sans_etre_compte(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    bon = await _creer_bon(db_session, statut="archive")
    await _creer_fournisseur(db_session, nom="Peintures Exemple", tva="FR00000000000")

    bilan = await resoudre_fournisseurs_des_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.fournisseur_id is None
    assert (bilan.relus, bilan.rattaches, bilan.inconnus, bilan.ignores) == (
        0,
        0,
        0,
        0,
    )


async def test_bon_deja_rattache_ou_sans_lecture_gardee_est_ignore(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    fournisseur = await _creer_fournisseur(
        db_session, nom="Peintures Exemple", tva="FR00000000000"
    )
    deja = await _creer_bon(db_session, fournisseur=fournisseur)
    sans_lecture = await _creer_bon(db_session, avec_ocr=False)
    facture = await _creer_bon(db_session, type_="facture")

    bilan = await resoudre_fournisseurs_des_bons(db_session, tmp_path)

    for document in (deja, sans_lecture, facture):
        await db_session.refresh(document)
    assert sans_lecture.fournisseur_id is None
    assert facture.fournisseur_id is None
    assert (bilan.relus, bilan.rattaches, bilan.inconnus, bilan.ignores) == (
        0,
        0,
        0,
        0,
    )
    assert await _journaux(db_session, deja.id, "extraction_relancee") == []


async def test_simulation_n_ecrit_rien_et_nomme_le_fournisseur_trouve(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    bon = await _creer_bon(db_session)
    autre = await _creer_bon(db_session)
    await _creer_fournisseur(db_session, nom="Peintures Exemple", tva="FR00000000000")
    # Le second bon aurait une lecture sans fournisseur connu.
    reponse = _reponse()
    annotation = json.loads(reponse["document_annotation"])
    annotation.update(
        fournisseur="INCONNU SARL", siret=None, tva_intracommunautaire=None
    )
    reponse["document_annotation"] = json.dumps(annotation)
    autre.ocr_brut = reponse
    await db_session.commit()
    avant = (
        await db_session.execute(select(Document.id, Document.fournisseur_id))
    ).all()
    nb_journal = len((await db_session.execute(select(Journal))).scalars().all())

    bilan = await resoudre_fournisseurs_des_bons(db_session, tmp_path, simulation=True)

    assert (
        await db_session.execute(select(Document.id, Document.fournisseur_id))
    ).all() == avant
    assert (
        len((await db_session.execute(select(Journal))).scalars().all()) == nb_journal
    )
    assert (bilan.relus, bilan.rattaches, bilan.inconnus, bilan.ignores) == (2, 1, 1, 0)
    trouves = {ligne.numero_interne: ligne.fournisseur for ligne in bilan.lignes}
    assert trouves == {
        bon.numero_interne: "Peintures Exemple",
        autre.numero_interne: None,
    }


async def _bon_lu_sans_fournisseur(
    db_session: AsyncSession, reponse: dict[str, Any]
) -> Document:
    """Un bon réellement lu une première fois (fournisseur absent du
    référentiel), comme à la réception."""
    from app.modules.ingest.extraction_bl import enregistrer_extraction_bl

    bon = await _creer_bon(db_session, avec_ocr=False)
    await enregistrer_extraction_bl(db_session, bon.id, reponse)
    await db_session.refresh(bon)
    return bon


def _codes(bon: Document) -> list[str]:
    return sorted(m["code"] for m in (bon.motifs or []))


async def test_bon_dont_le_seul_motif_etait_le_fournisseur_passe_a_recu(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    bon = await _bon_lu_sans_fournisseur(db_session, _reponse())
    assert bon.statut == "a_verifier"
    assert _codes(bon) == ["fournisseur_inconnu"]
    await _creer_fournisseur(db_session, nom="Peintures Exemple", tva="FR00000000000")

    bilan = await resoudre_fournisseurs_des_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bilan.rattaches == 1
    assert bon.fournisseur_id is not None
    assert bon.statut == "recu"
    assert not bon.motifs


async def test_bon_qui_garde_un_autre_motif_reste_a_verifier(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    reponse = _reponse()
    annotation = json.loads(reponse["document_annotation"])
    annotation["total_ht"] = "999,00"
    reponse["document_annotation"] = json.dumps(annotation)
    bon = await _bon_lu_sans_fournisseur(db_session, reponse)
    assert "somme_incoherente" in _codes(bon)
    await _creer_fournisseur(db_session, nom="Peintures Exemple", tva="FR00000000000")

    await resoudre_fournisseurs_des_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.fournisseur_id is not None
    assert bon.statut == "a_verifier"
    assert "somme_incoherente" in _codes(bon)
    assert "fournisseur_inconnu" not in _codes(bon)


async def test_bon_deja_recu_sans_fournisseur_est_ignore_pas_inconnu(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    bon = await _creer_bon(db_session, statut="recu")
    await _creer_fournisseur(db_session, nom="Peintures Exemple", tva="FR00000000000")

    bilan = await resoudre_fournisseurs_des_bons(db_session, tmp_path)

    await db_session.refresh(bon)
    assert bon.fournisseur_id is None
    assert (bilan.inconnus, bilan.ignores) == (0, 1)
