"""Tests de `ingest/rangement.py` (Task 9, avenant du 27/09/2026, spec §5) :
lien physique des photos de bon sous `<DOCS_DIR>/bl/<AAAA>/<MM>/...`.

Base de test réelle (`bl_test`), données entièrement inventées (« Villa
Test », « Résidence les Pins »…), jamais `tests/fixtures/` (R17).
`chemin_range` est une fonction pure (aucune base) ; `ranger_document`/
`ranger_tout` ont besoin d'un vrai fichier sur `tmp_path` (`os.link`)."""

from __future__ import annotations

import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest import rangement as ingest_rangement
from app.modules.ingest.models import Chantier, Document, Utilisateur
from app.modules.ingest.rangement import chemin_range, ranger_document, ranger_tout

pytestmark = [pytest.mark.anyio, pytest.mark.db]


def _mode(chemin: Path) -> int:
    return stat.S_IMODE(chemin.stat().st_mode)


async def _utilisateur(db_session: AsyncSession, *, nom: str | None) -> Utilisateur:
    utilisateur = Utilisateur(
        email=f"agent.{uuid.uuid4()}@example.invalid",
        role="agent",
        nom=nom,
        is_active=True,
    )
    db_session.add(utilisateur)
    await db_session.flush()
    return utilisateur


async def _chantier(db_session: AsyncSession, nom: str) -> Chantier:
    chantier = Chantier(nom_canonique=nom)
    db_session.add(chantier)
    await db_session.flush()
    return chantier


async def _bon(
    db_session: AsyncSession,
    docs_dir: Path,
    *,
    deposant_id: uuid.UUID | None = None,
    chantier_id: uuid.UUID | None = None,
    statut: str = "recu",
    type_document: str = "bl",
    extension: str = "jpg",
) -> Document:
    """Un bon, avec un vrai fichier source sous `docs_dir` (comme en
    production, `docs_dir/<uuid4>.<ext>`) -- `os.link` a besoin d'un fichier
    qui existe réellement."""
    source = docs_dir / f"{uuid.uuid4()}.{extension}"
    source.write_bytes(b"contenu-invente-bl")
    document = Document(
        type=type_document,
        source="telegram",
        statut=statut,
        fichier_path=str(source),
        deposant_id=deposant_id,
        chantier_id=chantier_id,
    )
    db_session.add(document)
    await db_session.flush()
    return document


# --------------------------------------------------------------------------
# `chemin_range` -- fonction pure, aucune base.
# --------------------------------------------------------------------------


def test_chemin_range_forme(tmp_path: Path) -> None:
    """Dépôt le 1er octobre 2026 à 23h30 UTC -> 01h30 le 2 en heure de Paris
    (CEST, UTC+2) : dossier `2026/10`, jour `02`."""
    depose_le = datetime(2026, 10, 1, 23, 30, tzinfo=UTC)

    chemin = chemin_range(
        tmp_path,
        depose_le=depose_le,
        deposant="Léa Dupont",
        chantier="Villa Test",
        numero_interne=42,
        extension="jpg",
    )

    assert chemin == (
        tmp_path / "bl" / "2026" / "10" / "02_lea-dupont_villa-test_n42.jpg"
    )


def test_nom_range_assaini(tmp_path: Path) -> None:
    """Chantier « Résidence / Les Pins » et déposant « Léa Dupont » ->
    segments ASCII, minuscules, sans `/` ni accent -- fichier sous
    `docs_dir/bl`."""
    depose_le = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)

    chemin = chemin_range(
        tmp_path,
        depose_le=depose_le,
        deposant="Léa Dupont",
        chantier="Résidence / Les Pins",
        numero_interne=7,
        extension="jpg",
    )

    assert chemin.is_relative_to(tmp_path / "bl")
    assert "/" not in chemin.name
    assert chemin.name == "05_lea-dupont_residence-les-pins_n7.jpg"


# --------------------------------------------------------------------------
# `ranger_document`
# --------------------------------------------------------------------------


async def test_ranger_document_cree_un_lien(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    utilisateur = await _utilisateur(db_session, nom="Léa Dupont")
    document = await _bon(db_session, tmp_path, deposant_id=utilisateur.id)

    cible = await ranger_document(db_session, tmp_path, document.id)

    assert cible is not None
    assert cible.is_file()
    # Même inode que l'original (lien physique, jamais une copie).
    assert cible.stat().st_ino == Path(document.fichier_path).stat().st_ino
    assert f"_n{document.numero_interne}." in cible.name
    assert "lea-dupont" in cible.name
    assert cible.parent.parent.parent == tmp_path / "bl"
    # Dossiers créés en 0750 (spec §5), à chaque niveau -- `Path.mkdir
    # (parents=True)` n'appliquerait le mode qu'au dernier niveau créé.
    assert _mode(cible.parent) == 0o750
    assert _mode(cible.parent.parent) == 0o750
    assert _mode(cible.parent.parent.parent) == 0o750


async def test_bon_sans_chantier_sans_chantier_dans_le_nom(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    document = await _bon(db_session, tmp_path)

    cible = await ranger_document(db_session, tmp_path, document.id)

    assert cible is not None
    assert "sans-chantier" in cible.name
    assert "inconnu" in cible.name  # aucun déposant non plus.


async def test_ranger_document_renomme_quand_le_chantier_change(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    chantier_1 = await _chantier(db_session, "Villa Un")
    chantier_2 = await _chantier(db_session, "Villa Deux")
    document = await _bon(db_session, tmp_path, chantier_id=chantier_1.id)

    premier = await ranger_document(db_session, tmp_path, document.id)
    assert premier is not None
    assert premier.exists()
    assert "villa-un" in premier.name

    document.chantier_id = chantier_2.id
    await db_session.flush()

    second = await ranger_document(db_session, tmp_path, document.id)

    assert second is not None
    assert "villa-deux" in second.name
    assert second != premier
    assert not premier.exists()  # ancien lien retiré : jamais deux à la fois.
    assert second.exists()
    assert second.stat().st_ino == Path(document.fichier_path).stat().st_ino


async def test_ranger_document_document_absent_type_ou_statut_hors_perimetre(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    facture = await _bon(db_session, tmp_path, type_document="facture")
    archive = await _bon(db_session, tmp_path, statut="archive")

    assert await ranger_document(db_session, tmp_path, uuid.uuid4()) is None
    assert await ranger_document(db_session, tmp_path, facture.id) is None
    assert await ranger_document(db_session, tmp_path, archive.id) is None
    assert list(tmp_path.glob("bl/*/*/*")) == []


async def test_echec_de_rangement_ne_leve_pas(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, tmp_path: Path
) -> None:
    """Un disque plein/des droits insuffisants (`OSError`) sont journalisés
    et jamais levés -- simulé en monkeypatchant la partie synchrone (même
    idiome que `test_traiter_fichier_echec_ecriture_signale_supervision_et
    _agent`, indépendant des droits root du bac de test)."""

    def _echoue(*args: object, **kwargs: object) -> None:
        raise OSError("disque plein (factice)")

    monkeypatch.setattr(ingest_rangement, "_poser_lien", _echoue)
    document = await _bon(db_session, tmp_path)

    resultat = await ranger_document(db_session, tmp_path, document.id)

    assert resultat is None


# --------------------------------------------------------------------------
# `ranger_tout`
# --------------------------------------------------------------------------


async def test_ranger_tout_range_chaque_bon_non_archive(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    premier = await _bon(db_session, tmp_path)
    second = await _bon(db_session, tmp_path)
    archive = await _bon(db_session, tmp_path, statut="archive")

    nb_ranges = await ranger_tout(db_session, tmp_path)

    assert nb_ranges == 2
    liens = list(tmp_path.glob("bl/*/*/*"))
    assert len(liens) == 2
    noms = {lien.name for lien in liens}
    assert any(f"_n{premier.numero_interne}." in nom for nom in noms)
    assert any(f"_n{second.numero_interne}." in nom for nom in noms)
    assert not any(f"_n{archive.numero_interne}." in nom for nom in noms)


async def test_ranger_tout_idempotent(db_session: AsyncSession, tmp_path: Path) -> None:
    await _bon(db_session, tmp_path)
    await _bon(db_session, tmp_path)

    premier_appel = await ranger_tout(db_session, tmp_path)
    second_appel = await ranger_tout(db_session, tmp_path)

    assert premier_appel == 2
    assert second_appel == 2
    assert len(list(tmp_path.glob("bl/*/*/*"))) == 2
