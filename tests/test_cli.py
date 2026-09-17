"""Tests de `app/cli.py` (`python -m app.cli bl-non-recus <facture.pdf>`, T7).

Tests transverses (le fichier vit à la racine `app/`, pas dans un module) :
- fichier absent -> code 2, en sous-processus avec un environnement sans
  configuration, pour prouver qu'aucun appel réseau ni base n'est tenté
  (une configuration manquante ferait échouer le processus avant tout appel
  si le code allait plus loin) ;
- fichier non-PDF -> code 2, sans mock ni réseau (rejeté avant l'OCR) ;
- `ErreurOCR` / `FactureIllisible` -> code 2, `lire_facture` monkeypatchée
  (R17 : aucun appel réel à Mistral) ;
- vraie fixture `tests/fixtures/unikalo/facture_2026-08.{pdf,mistral-ocr.json,
  attendu.json}` (`pytest.skip` si absente) -> code 0, une ligne par bloc,
  réception exacte vérifiée sur `bl_test` (tour de correction finale du
  lot 1 : la version précédente interrogeait la base de **dev** via
  `DATABASE_URL` et son assertion « reçus + non reçus = nombre de blocs »
  était tautologique — toujours vraie quel que soit le contenu de la base).
  `DATABASE_URL` est surchargée par `TEST_DATABASE_URL` dans l'environnement
  du test (`get_settings()` étant mise en cache par processus, le cache est
  vidé avant et après) ; des documents `bl` sont semés dans `bl_test` pour un
  sous-ensemble des numéros de BL lus **à l'exécution** dans
  `facture_2026-08.attendu.json` (jamais codés en dur ici), puis la
  correspondance « photo reçue » est vérifiée bloc par bloc — par index de
  ligne, jamais par numéro réel dans une assertion ou un message. L'OCR
  Mistral est remplacé par la fixture rejouée (R17 : aucun appel réel).
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine

from app import cli
from app.core.config import get_settings
from app.core.db import creer_sessionmaker
from app.modules.extract.facture import Facture, FactureIllisible
from app.modules.ingest.mistral import ErreurOCR
from app.modules.ingest.models import Document

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "unikalo"
FACTURE_PDF = FIXTURES_DIR / "facture_2026-08.pdf"
FACTURE_OCR = FIXTURES_DIR / "facture_2026-08.mistral-ocr.json"
FACTURE_ATTENDU = FIXTURES_DIR / "facture_2026-08.attendu.json"

# Préfixe distinctif des `fichier_path` inventés par le test de réception
# ci-dessous, pour ne nettoyer que les documents qu'il a lui-même semés.
_PREFIXE_FICHIER_TEST = "/invente/test-cli-"

_SYNTHESE_RE = re.compile(r"^(\d+) blocs — (\d+) reçus — (\d+) non reçus$")


def test_bl_non_recus_fichier_inexistant_code_2_sans_configuration(
    tmp_path: Path,
) -> None:
    """Sous-processus sans configuration : si le code allait plus loin que
    la vérification d'existence, il échouerait fail-fast (config manquante)
    avant tout appel réseau — le code 2 obtenu ici prouve donc qu'aucun
    appel n'a été tenté."""
    chemin = tmp_path / "facture-inventee.pdf"

    resultat = subprocess.run(  # noqa: S603 -- chemin vient de tmp_path, pas d'entrée utilisateur
        [sys.executable, "-m", "app.cli", "bl-non-recus", str(chemin)],
        cwd=tmp_path,
        env={"PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert resultat.returncode == 2
    assert resultat.stdout == ""


def test_bl_non_recus_fichier_non_pdf_code_2(tmp_path: Path) -> None:
    chemin = tmp_path / "pas-une-facture.pdf"
    chemin.write_bytes(b"contenu invente qui n'est pas un pdf")

    code = cli.main(["bl-non-recus", str(chemin)])

    assert code == 2


def test_bl_non_recus_erreur_ocr_code_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chemin = tmp_path / "facture-inventee.pdf"
    chemin.write_bytes(b"%PDF-1.4 contenu invente")

    async def _lire_facture_en_echec(contenu: bytes, ocr: Any) -> Facture:
        raise ErreurOCR("échec factice de l'OCR")

    monkeypatch.setattr(cli, "lire_facture", _lire_facture_en_echec)

    code = cli.main(["bl-non-recus", str(chemin)])

    assert code == 2


def test_bl_non_recus_facture_illisible_code_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chemin = tmp_path / "facture-inventee.pdf"
    chemin.write_bytes(b"%PDF-1.4 contenu invente")

    async def _lire_facture_illisible(contenu: bytes, ocr: Any) -> Facture:
        raise FactureIllisible("facture illisible factice")

    monkeypatch.setattr(cli, "lire_facture", _lire_facture_illisible)

    code = cli.main(["bl-non-recus", str(chemin)])

    assert code == 2


async def _semer_documents_recus(engine: AsyncEngine, numeros: set[str]) -> None:
    """Insère un `document` `bl`/`recu` par numéro dans `numeros` (base
    pointée par `engine`, jamais la base de dev : voir l'appelant)."""
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        for numero in numeros:
            session.add(
                Document(
                    type="bl",
                    source="upload",
                    statut="recu",
                    fichier_path=f"{_PREFIXE_FICHIER_TEST}{uuid.uuid4()}.jpg",
                    numero=numero,
                )
            )
        await session.commit()


async def _nettoyer_documents_semes(engine: AsyncEngine) -> None:
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        await session.execute(
            delete(Document).where(
                Document.fichier_path.startswith(_PREFIXE_FICHIER_TEST)
            )
        )
        await session.commit()


@pytest.mark.db
def test_bl_non_recus_reception_exacte_sur_bl_test(
    db_engine: AsyncEngine,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Sème des documents `bl` dans `bl_test` (jamais la base de dev, cf.
    docstring du module) pour un sous-ensemble des numéros de BL de la
    facture, puis vérifie exactement quels blocs sont rapportés « reçus » —
    par index de ligne, jamais par numéro réel (données client, cf.
    `execution.md`)."""
    if not (FACTURE_PDF.exists() and FACTURE_OCR.exists() and FACTURE_ATTENDU.exists()):
        pytest.skip(
            "fixtures facture_2026-08 absentes dans tests/fixtures/unikalo/ "
            "(clone neuf ou fixtures non déposées)"
        )

    reponse_ocr: dict[str, Any] = json.loads(FACTURE_OCR.read_text(encoding="utf-8"))
    attendu: dict[str, Any] = json.loads(FACTURE_ATTENDU.read_text(encoding="utf-8"))
    blocs_attendus: list[dict[str, Any]] = attendu["blocs"]
    nombre_blocs_attendu = len(blocs_attendus)

    # Un bloc sur deux (jamais 0 % ni 100 % des numéros) : une requête qui
    # ignorerait le filtre de réception, ou qui matcherait tout/rien, serait
    # démasquée par cette répartition. Indices choisis ici ; les numéros de
    # BL eux-mêmes sont lus dans la fixture au moment du test, jamais codés
    # en dur dans ce fichier.
    indices_semes = set(range(0, nombre_blocs_attendu, 2))
    numeros_semes = {blocs_attendus[i]["numero_bl"] for i in indices_semes}

    async def _ocr_document_fixture(
        http: Any, cle_api: str, contenu: bytes, mime: str
    ) -> dict[str, Any]:
        return reponse_ocr

    asyncio.run(_semer_documents_recus(db_engine, numeros_semes))
    try:
        monkeypatch.setattr(cli, "ocr_document", _ocr_document_fixture)
        monkeypatch.setenv("DATABASE_URL", test_database_url)
        get_settings.cache_clear()

        code = cli.main(["bl-non-recus", str(FACTURE_PDF)])
        sortie = capsys.readouterr().out
    finally:
        get_settings.cache_clear()
        asyncio.run(_nettoyer_documents_semes(db_engine))

    assert code == 0
    lignes = sortie.rstrip("\n").split("\n")
    assert len(lignes) == nombre_blocs_attendu + 2, (
        "nombre de lignes de sortie inattendu (en-tête + un par bloc + synthèse)"
    )
    assert lignes[0].startswith("N° BL")

    lignes_donnees = lignes[1:-1]
    recus_attendus = 0
    for indice, ligne in enumerate(lignes_donnees):
        bloc_recu = blocs_attendus[indice]["numero_bl"] in numeros_semes
        recus_attendus += int(bloc_recu)
        reception_affichee = ligne.rsplit(" | ", 1)[-1].strip()
        assert reception_affichee == ("oui" if bloc_recu else "non"), (
            f"réception inattendue pour le bloc d'index {indice}"
        )

    correspondance = _SYNTHESE_RE.match(lignes[-1])
    assert correspondance is not None, "ligne de synthèse au format inattendu"
    total, recus, non_recus = (int(g) for g in correspondance.groups())
    assert total == nombre_blocs_attendu
    assert recus == recus_attendus
    assert non_recus == nombre_blocs_attendu - recus_attendus
