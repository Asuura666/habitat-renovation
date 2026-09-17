"""Tests de `app/cli.py` (T7 et L2-T1b).

Tests transverses (le fichier vit à la racine `app/`, pas dans un module) :
- `bl-non-recus` (T7) :
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
- `utilisateur-creer` / `utilisateur-desactiver` (L2-T1b) : `getpass.getpass`
  est monkeypatchée (jamais de vraie saisie interactive dans les tests) ;
  chaque test qui écrit réellement en base surcharge `DATABASE_URL` par
  `TEST_DATABASE_URL` (fixture `_env_bl_test` ci-dessous, même mécanique que
  le test `bl-non-recus` sur fixture réelle) et nettoie l'utilisateur (et son
  entrée `journal`) qu'il a créé. Le rôle invalide est rejeté par `argparse`
  lui-même (`choices`) : le test correspondant attend un `SystemExit`, pas un
  retour de `cli.main`.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app import cli
from app.core.config import get_settings
from app.core.db import creer_sessionmaker
from app.modules.extract.facture import Facture, FactureIllisible
from app.modules.ingest.mistral import ErreurOCR
from app.modules.ingest.models import Document, Journal, Utilisateur

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


# ---------------------------------------------------------------------------
# `utilisateur-creer` / `utilisateur-desactiver` (L2-T1b)
# ---------------------------------------------------------------------------

_MOT_DE_PASSE_CLI = "mot-de-passe-invente-cli-1234"


@pytest.fixture
def _env_bl_test(
    test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Bascule `DATABASE_URL` sur `bl_test` pour la durée du test, jamais la
    base de dev (même mécanique que le test `bl-non-recus` sur fixture
    réelle ci-dessus) : `get_settings()` est mise en cache par processus, le
    cache est vidé avant et après."""
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _getpass_sequence(monkeypatch: pytest.MonkeyPatch, *valeurs: str) -> None:
    """Remplace `getpass.getpass` par une file de réponses inventées (jamais
    de vraie saisie interactive dans les tests) : la première valeur pour le
    mot de passe, la seconde pour sa confirmation. Monkeypatché sur le module
    `getpass` importé ici (et non `cli.getpass`, que mypy strict refuse en
    accès externe faute de réexport explicite) : c'est le même objet module
    que celui que `app.cli` appelle à l'exécution."""
    iterateur = iter(valeurs)

    def _getpass(prompt: str = "") -> str:
        return next(iterateur)

    monkeypatch.setattr(getpass, "getpass", _getpass)


async def _relire_utilisateur(engine: AsyncEngine, email: str) -> Utilisateur | None:
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        return (
            (
                await session.execute(
                    select(Utilisateur).where(Utilisateur.email == email)
                )
            )
            .scalars()
            .one_or_none()
        )


async def _supprimer_utilisateur(engine: AsyncEngine, email: str) -> None:
    """Nettoie l'utilisateur inventé par un test (et son entrée `journal`,
    qui ne référence jamais `utilisateur_id` — L2-D dans le brief L2-T1b —
    mais cible bien son `id` par `cible_id`)."""
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        utilisateur_id = (
            await session.execute(
                select(Utilisateur.id).where(Utilisateur.email == email)
            )
        ).scalar_one_or_none()
        if utilisateur_id is not None:
            await session.execute(
                delete(Journal).where(Journal.cible_id == str(utilisateur_id))
            )
        await session.execute(delete(Utilisateur).where(Utilisateur.email == email))
        await session.commit()


@pytest.mark.db
def test_utilisateur_creer_reussi_hash_argon2id_et_mot_de_passe_jamais_affiche(
    db_engine: AsyncEngine,
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    email = "cli.utilisateur.cree1@example.invalid"
    _getpass_sequence(monkeypatch, _MOT_DE_PASSE_CLI, _MOT_DE_PASSE_CLI)
    try:
        code = cli.main(
            [
                "utilisateur-creer",
                "--email",
                email,
                "--nom",
                "Agent Créé CLI",
                "--role",
                "agent",
                "--agence",
                "Toulouse",
                "--telegram-id",
                "555000111",
            ]
        )
        sortie = capsys.readouterr()

        assert code == 0
        assert _MOT_DE_PASSE_CLI not in sortie.out
        assert _MOT_DE_PASSE_CLI not in sortie.err

        utilisateur = asyncio.run(_relire_utilisateur(db_engine, email))
        assert utilisateur is not None
        assert utilisateur.hashed_password is not None
        assert utilisateur.hashed_password.startswith("$argon2id$")
        assert _MOT_DE_PASSE_CLI not in utilisateur.hashed_password
        assert utilisateur.role == "agent"
        assert utilisateur.agence == "Toulouse"
        assert utilisateur.telegram_user_id == 555000111
        assert utilisateur.is_active is True
    finally:
        asyncio.run(_supprimer_utilisateur(db_engine, email))


@pytest.mark.db
def test_utilisateur_creer_email_deja_pris_code_2_sans_deuxieme_ligne(
    db_engine: AsyncEngine,
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    email = "cli.utilisateur.cree2@example.invalid"
    try:
        _getpass_sequence(monkeypatch, _MOT_DE_PASSE_CLI, _MOT_DE_PASSE_CLI)
        premier = cli.main(
            [
                "utilisateur-creer",
                "--email",
                email,
                "--nom",
                "Premier",
                "--role",
                "agent",
                "--agence",
                "Toulouse",
            ]
        )
        assert premier == 0

        _getpass_sequence(monkeypatch, _MOT_DE_PASSE_CLI, _MOT_DE_PASSE_CLI)
        second = cli.main(
            [
                "utilisateur-creer",
                "--email",
                email,
                "--nom",
                "Second",
                "--role",
                "agent",
                "--agence",
                "Toulouse",
            ]
        )
        sortie = capsys.readouterr()

        assert second == 2
        assert sortie.err.strip() != ""
        assert _MOT_DE_PASSE_CLI not in sortie.out
        assert _MOT_DE_PASSE_CLI not in sortie.err

        utilisateur = asyncio.run(_relire_utilisateur(db_engine, email))
        assert utilisateur is not None
        assert utilisateur.nom == "Premier"
    finally:
        asyncio.run(_supprimer_utilisateur(db_engine, email))


@pytest.mark.db
def test_utilisateur_creer_telegram_id_deja_attribue_code_2(
    db_engine: AsyncEngine,
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    email_1 = "cli.utilisateur.telegram1@example.invalid"
    email_2 = "cli.utilisateur.telegram2@example.invalid"
    try:
        _getpass_sequence(monkeypatch, _MOT_DE_PASSE_CLI, _MOT_DE_PASSE_CLI)
        premier = cli.main(
            [
                "utilisateur-creer",
                "--email",
                email_1,
                "--nom",
                "Premier",
                "--role",
                "agent",
                "--agence",
                "Toulouse",
                "--telegram-id",
                "555000222",
            ]
        )
        assert premier == 0

        _getpass_sequence(monkeypatch, _MOT_DE_PASSE_CLI, _MOT_DE_PASSE_CLI)
        second = cli.main(
            [
                "utilisateur-creer",
                "--email",
                email_2,
                "--nom",
                "Second",
                "--role",
                "agent",
                "--agence",
                "Toulouse",
                "--telegram-id",
                "555000222",
            ]
        )
        sortie = capsys.readouterr()

        assert second == 2
        assert _MOT_DE_PASSE_CLI not in sortie.out
        assert _MOT_DE_PASSE_CLI not in sortie.err
        assert asyncio.run(_relire_utilisateur(db_engine, email_2)) is None
    finally:
        asyncio.run(_supprimer_utilisateur(db_engine, email_1))
        asyncio.run(_supprimer_utilisateur(db_engine, email_2))


def test_utilisateur_creer_role_invalide_rejete_par_argparse_systemexit_2() -> None:
    """`--role` est déclaré avec `choices=["admin", "agent"]` : un rôle hors
    de cette liste ne fait même pas exécuter le corps de la commande —
    `argparse` lève `SystemExit(2)` avant tout accès à la configuration ou à
    la base."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "utilisateur-creer",
                "--email",
                "cli.utilisateur.role.invalide@example.invalid",
                "--nom",
                "Rôle invalide",
                "--role",
                "superadmin",
                "--agence",
                "Toulouse",
            ]
        )

    assert exc_info.value.code == 2


@pytest.mark.db
def test_utilisateur_creer_mots_de_passe_differents_code_2(
    db_engine: AsyncEngine,
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    email = "cli.utilisateur.mdp.differents@example.invalid"
    _getpass_sequence(monkeypatch, _MOT_DE_PASSE_CLI, "un-autre-mot-de-passe-1234")

    code = cli.main(
        [
            "utilisateur-creer",
            "--email",
            email,
            "--nom",
            "Mots de passe différents",
            "--role",
            "agent",
            "--agence",
            "Toulouse",
        ]
    )
    sortie = capsys.readouterr()

    assert code == 2
    assert sortie.err.strip() != ""
    assert _MOT_DE_PASSE_CLI not in sortie.out
    assert _MOT_DE_PASSE_CLI not in sortie.err
    assert asyncio.run(_relire_utilisateur(db_engine, email)) is None


@pytest.mark.db
def test_utilisateur_creer_mot_de_passe_trop_court_code_2(
    db_engine: AsyncEngine,
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mot_de_passe_court = "court12345"  # 10 caractères, < minimum de 12
    email = "cli.utilisateur.mdp.court@example.invalid"
    _getpass_sequence(monkeypatch, mot_de_passe_court, mot_de_passe_court)

    code = cli.main(
        [
            "utilisateur-creer",
            "--email",
            email,
            "--nom",
            "Mot de passe court",
            "--role",
            "agent",
            "--agence",
            "Toulouse",
        ]
    )
    sortie = capsys.readouterr()

    assert code == 2
    assert sortie.err.strip() != ""
    assert mot_de_passe_court not in sortie.out
    assert mot_de_passe_court not in sortie.err
    assert asyncio.run(_relire_utilisateur(db_engine, email)) is None


@pytest.mark.db
def test_utilisateur_desactiver_reussi_bascule_actif(
    db_engine: AsyncEngine,
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = "cli.utilisateur.desactive@example.invalid"
    try:
        _getpass_sequence(monkeypatch, _MOT_DE_PASSE_CLI, _MOT_DE_PASSE_CLI)
        assert (
            cli.main(
                [
                    "utilisateur-creer",
                    "--email",
                    email,
                    "--nom",
                    "À désactiver",
                    "--role",
                    "agent",
                    "--agence",
                    "Toulouse",
                ]
            )
            == 0
        )

        code = cli.main(["utilisateur-desactiver", "--email", email])

        assert code == 0
        utilisateur = asyncio.run(_relire_utilisateur(db_engine, email))
        assert utilisateur is not None
        assert utilisateur.is_active is False
    finally:
        asyncio.run(_supprimer_utilisateur(db_engine, email))


@pytest.mark.db
def test_utilisateur_desactiver_email_inconnu_code_2(
    _env_bl_test: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = cli.main(
        [
            "utilisateur-desactiver",
            "--email",
            "personne.na.jamais.existe.cli@example.invalid",
        ]
    )
    sortie = capsys.readouterr()

    assert code == 2
    assert sortie.err.strip() != ""
