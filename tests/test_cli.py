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
- `fournisseur-definir` (L3-T5) : même mécanique `_env_bl_test` sur `bl_test`,
  nettoyage du fournisseur (et de ses agences) créé par le test. Une
  création vérifie le SIRET/TVA stockés et le nombre d'alias/agences
  annoncé ; une mise à jour (nom en casse différente, alias déjà présent
  renvoyé, nouvelle agence) vérifie le remplacement du TVA, l'absence de
  doublon d'alias et l'agence ajoutée.
- `rapport-ocr` (L3-T11) : sans base (l'outil ne touche jamais la base) —
  dossier vide/inexistant -> code 2, rien écrit dans `--sortie` ; dossier
  avec une photo, son `.attendu.json` et son cache `.mistral-ocr.json` ->
  code 0, rapport Markdown écrit ; `--appeler-ocr` construit l'OCR de
  production avec les mêmes options/délai que `ingest/router.py::get_ocr`
  (`ocr_document` monkeypatché, R17 : jamais de vrai appel Mistral).
- `rapprocher`/`controles-differes` (L4-T11) : la logique métier
  (rapprochement, contrôles différés) est déjà testée en profondeur côté
  `ingest` (`test_rapprochement.py`, `test_suivi.py`) — les tests ici ne
  vérifient que le câblage CLI (arguments, codes de sortie, sortie sans
  donnée client) avec des données minimales sur `bl_test`
  (mécanique `_env_bl_test`) : `--facture` sur une facture introuvable (code
  2) ou existante (code 0, compteurs affichés) ; `--tout` sur plusieurs
  factures `recu` (une ligne par facture, code 0) et sur un échec simulé
  (`rapprocher_facture_sans_echec` monkeypatché pour renvoyer `None`, code
  1) ; erreurs d'arguments (`--facture`/`--tout` absents ou combinés, UUID
  invalide) rejetées par `argparse` lui-même (`SystemExit(2)`, sans jamais
  toucher la base) ; `controles-differes` sur un BL non confirmé (code 0,
  compte affiché) et rejeu sans doublon.
- `synthese-commentaires` (T4, phase 4 IA) : la logique métier (période,
  plafond, appel à l'IA, écriture) est déjà testée en profondeur côté
  `ingest` (`test_ia_synthese.py`) — les tests ici ne vérifient que le
  câblage CLI (`generer_synthese` monkeypatchée, jamais de vrai appel IA ni
  de vraie base touchée par le service) : une ligne par statut
  (`ResultatSynthese.statut`), code 1 seulement sur `"echec"` ; sans
  `--semaine`, `derniere_semaine_complete` monkeypatchée pour vérifier la
  date transmise sans dépendre de la date du jour ; `--semaine` illisible ou
  qui n'est pas un lundi rejeté par `argparse` lui-même (`SystemExit(2)`,
  sans jamais toucher la base ni la configuration).
"""

from __future__ import annotations

import asyncio
import csv
import getpass
import io
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app import cli
from app.core.config import get_settings
from app.core.db import creer_sessionmaker
from app.modules.extract.bl import OPTIONS_OCR_BL
from app.modules.extract.facture import Facture, FactureIllisible
from app.modules.extract.reponses_ia import PrixInternetLu
from app.modules.extract.verification import SEUIL_CONFIANCE_DEFAUT
from app.modules.ingest.ia_prix import BilanIA, LigneEssai, ProduitEssai
from app.modules.ingest.ia_synthese import ResultatSynthese
from app.modules.ingest.mistral import ErreurOCR
from app.modules.ingest.models import (
    AgenceFournisseur,
    Anomalie,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Utilisateur,
)
from app.modules.ingest.router import DELAI_OCR_BL

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


def test_drive_sync_dispatch_avec_limite(monkeypatch: pytest.MonkeyPatch) -> None:
    recu: list[int] = []

    async def _drive_sync_factice(*, limite: int) -> int:
        recu.append(limite)
        return 0

    monkeypatch.setattr(cli, "_drive_sync", _drive_sync_factice, raising=False)

    assert cli.main(["drive-sync", "--limite", "7"]) == 0
    assert recu == [7]


def test_drive_sync_refuse_configuration_google_absente(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            google_drive_service_account_json=None,
            google_drive_folder_id=None,
        ),
    )

    code = asyncio.run(cli._drive_sync(limite=10))

    assert code == 2
    assert "configuration Google Drive absente" in capsys.readouterr().err


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


# ---------------------------------------------------------------------------
# `fournisseur-definir` (L3-T5)
# ---------------------------------------------------------------------------


async def _relire_fournisseur(engine: AsyncEngine, nom: str) -> Fournisseur | None:
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        return (
            (
                await session.execute(
                    select(Fournisseur).where(
                        func.lower(Fournisseur.nom) == nom.lower()
                    )
                )
            )
            .scalars()
            .one_or_none()
        )


async def _compter_agences(engine: AsyncEngine, fournisseur_id: uuid.UUID) -> int:
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(AgenceFournisseur)
                .where(AgenceFournisseur.fournisseur_id == fournisseur_id)
            )
        ).scalar_one()


async def _supprimer_fournisseur(engine: AsyncEngine, nom: str) -> None:
    """Nettoie le fournisseur inventé par un test, et ses agences (aucune
    contrainte en cascade, `ingest/models.py`)."""
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        fournisseur_id = (
            await session.execute(
                select(Fournisseur.id).where(func.lower(Fournisseur.nom) == nom.lower())
            )
        ).scalar_one_or_none()
        if fournisseur_id is not None:
            await session.execute(
                delete(AgenceFournisseur).where(
                    AgenceFournisseur.fournisseur_id == fournisseur_id
                )
            )
        await session.execute(
            delete(Fournisseur).where(func.lower(Fournisseur.nom) == nom.lower())
        )
        await session.commit()


@pytest.mark.db
def test_fournisseur_definir_creation_avec_siret_tva_alias_et_agence(
    db_engine: AsyncEngine,
    _env_bl_test: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    nom = "CLI Fournisseur Test Création"
    try:
        code = cli.main(
            [
                "fournisseur-definir",
                "--nom",
                nom,
                "--siret",
                "123 456 789 00012",
                "--tva",
                "FR12345678901",
                "--alias",
                "Alias Un",
                "--alias",
                "Alias Deux",
                "--agence",
                "Agence Nord",
            ]
        )
        sortie = capsys.readouterr().out

        assert code == 0
        assert sortie.strip() == "Fournisseur créé (2 alias, 1 agences)"

        fournisseur = asyncio.run(_relire_fournisseur(db_engine, nom))
        assert fournisseur is not None
        assert fournisseur.siret == "123 456 789 00012"
        assert fournisseur.tva == "FR12345678901"
        assert fournisseur.aliases is not None
        assert set(fournisseur.aliases) == {"Alias Un", "Alias Deux"}
        assert asyncio.run(_compter_agences(db_engine, fournisseur.id)) == 1
    finally:
        asyncio.run(_supprimer_fournisseur(db_engine, nom))


@pytest.mark.db
def test_fournisseur_definir_mise_a_jour_alias_double_ignore_agence_ajoutee(
    db_engine: AsyncEngine,
    _env_bl_test: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    nom = "CLI Fournisseur Test Mise À Jour"
    try:
        premier = cli.main(
            [
                "fournisseur-definir",
                "--nom",
                nom,
                "--alias",
                "Alias Un",
                "--agence",
                "Agence Nord",
            ]
        )
        assert premier == 0
        capsys.readouterr()

        # Nom en casse différente (comparaison sans casse) ; alias déjà
        # présent (comparaison `normaliser_libelle`, casse ignorée) ignoré ;
        # TVA fourni (remplacé) ; une nouvelle agence.
        second = cli.main(
            [
                "fournisseur-definir",
                "--nom",
                nom.upper(),
                "--tva",
                "FR99999999999",
                "--alias",
                "alias un",
                "--agence",
                "Agence Sud",
            ]
        )
        sortie = capsys.readouterr().out

        assert second == 0
        assert sortie.strip() == "Fournisseur mis à jour (1 alias, 2 agences)"

        fournisseur = asyncio.run(_relire_fournisseur(db_engine, nom))
        assert fournisseur is not None
        assert fournisseur.tva == "FR99999999999"
        assert fournisseur.aliases == ["Alias Un"]
        assert asyncio.run(_compter_agences(db_engine, fournisseur.id)) == 2
    finally:
        asyncio.run(_supprimer_fournisseur(db_engine, nom))


# ---------------------------------------------------------------------------
# `rapport-ocr` (L3-T11) — sans base, données inventées dans `tmp_path`
# ---------------------------------------------------------------------------


def _attendu_invente(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "numero": "BL0001",
        "fournisseur": "Fournisseur Invente",
        "date_doc": "2026-01-15",
        "chantier_brut": "Chantier Invente",
        "degradee": False,
        "lignes": [],
    }
    base.update(overrides)
    return base


def test_rapport_ocr_dossier_vide_code_2_rien_ecrit(tmp_path: Path) -> None:
    sortie = tmp_path / "rapport.md"

    code = cli.main(["rapport-ocr", str(tmp_path), "--sortie", str(sortie)])

    assert code == 2
    assert not sortie.exists()


def test_rapport_ocr_dossier_inexistant_code_2(tmp_path: Path) -> None:
    dossier = tmp_path / "n-existe-pas"
    sortie = tmp_path / "rapport.md"

    code = cli.main(["rapport-ocr", str(dossier), "--sortie", str(sortie)])

    assert code == 2
    assert not sortie.exists()


def test_rapport_ocr_rapport_ecrit_sans_appeler_ocr(tmp_path: Path) -> None:
    """Sans `--appeler-ocr` : utilise uniquement le cache
    `<nom>.mistral-ocr.json`, aucun appel réseau (R17)."""
    dossier = tmp_path / "photos"
    dossier.mkdir()
    nom = "photo-cli"
    (dossier / f"{nom}.jpg").write_bytes(b"contenu invente")
    (dossier / f"{nom}.attendu.json").write_text(
        json.dumps(_attendu_invente()), encoding="utf-8"
    )
    (dossier / f"{nom}.mistral-ocr.json").write_text(
        json.dumps({"document_annotation": {"lignes": []}}), encoding="utf-8"
    )
    sortie = tmp_path / "rapport.md"

    code = cli.main(["rapport-ocr", str(dossier), "--sortie", str(sortie)])

    assert code == 0
    assert sortie.is_file()
    contenu = sortie.read_text(encoding="utf-8")
    assert "Rapport" in contenu
    assert nom in contenu


def test_rapport_ocr_sortie_ecrite_en_0640(tmp_path: Path) -> None:
    """Correction (relecture tâche T3) : le rapport Markdown peut contenir
    des valeurs attendues et lues d'un document client réel (docstring de
    `ingest.rapport_ocr`) -- avant cette correction, `_rapport_ocr`
    (`app/cli.py`) écrivait `sortie` via `Path.write_text`, sans passer par
    `ecrire_rapport`/`_ecrire_fichier_prive` : sous l'umask 0022 du
    conteneur (fixée ici pour un résultat déterministe), le fichier
    ressortait en 0644, lisible par tout autre compte Unix du VPS partagé."""
    dossier = tmp_path / "photos"
    dossier.mkdir()
    nom = "photo-permissions"
    (dossier / f"{nom}.jpg").write_bytes(b"contenu invente")
    (dossier / f"{nom}.attendu.json").write_text(
        json.dumps(_attendu_invente()), encoding="utf-8"
    )
    (dossier / f"{nom}.mistral-ocr.json").write_text(
        json.dumps({"document_annotation": {"lignes": []}}), encoding="utf-8"
    )
    sortie = tmp_path / "rapport.md"

    umask_avant = os.umask(0o022)
    try:
        code = cli.main(["rapport-ocr", str(dossier), "--sortie", str(sortie)])
    finally:
        os.umask(umask_avant)

    assert code == 0
    assert sortie.is_file()
    assert stat.S_IMODE(sortie.stat().st_mode) == 0o640


def test_rapport_ocr_appeler_ocr_construit_ocr_meme_options_et_delai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--appeler-ocr` construit l'OCR de production avec les mêmes options
    et le même délai que `ingest/router.py::get_ocr` (décision du
    contrôleur) — `ocr_document` monkeypatché (R17 : jamais de vrai appel
    Mistral)."""
    dossier = tmp_path / "photos"
    dossier.mkdir()
    nom = "photo-appel-ocr"
    (dossier / f"{nom}.jpg").write_bytes(b"contenu invente")
    (dossier / f"{nom}.attendu.json").write_text(
        json.dumps(_attendu_invente()), encoding="utf-8"
    )
    sortie = tmp_path / "rapport.md"

    appels: list[dict[str, Any]] = []

    async def _ocr_document_factice(
        http: Any,
        cle_api: str,
        contenu: bytes,
        mime: str,
        *,
        delai: Any = None,
        options: Any = None,
    ) -> dict[str, Any]:
        appels.append(
            {"contenu": contenu, "mime": mime, "delai": delai, "options": options}
        )
        return {"document_annotation": {"lignes": []}}

    monkeypatch.setattr(cli, "ocr_document", _ocr_document_factice)

    code = cli.main(
        ["rapport-ocr", str(dossier), "--sortie", str(sortie), "--appeler-ocr"]
    )

    assert code == 0
    assert sortie.is_file()
    assert len(appels) == 1
    assert appels[0]["contenu"] == b"contenu invente"
    assert appels[0]["mime"] == "image/jpeg"
    assert appels[0]["delai"] == DELAI_OCR_BL
    assert appels[0]["options"] == OPTIONS_OCR_BL


# ---------------------------------------------------------------------------
# `rapport-ocr --seuil` (fix round 1, finding 2 / ruling R13)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("valeur", ["abc", "1.5", "-0.1", "2", "nan", "inf", "-inf"])
def test_rapport_ocr_seuil_invalide_systemexit_2(valeur: str, tmp_path: Path) -> None:
    """`--seuil` hors de [0, 1], non numérique ou non fini (`nan`/`inf`,
    acceptés par le constructeur `Decimal` mais dont la comparaison lève
    `decimal.InvalidOperation`, vague finale/revue de branche) -> rejeté par
    `argparse` lui-même (même mécanique que `--role` de `utilisateur-creer`),
    avant tout accès au dossier ou à la configuration."""
    sortie = tmp_path / "rapport.md"

    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            ["rapport-ocr", str(tmp_path), "--sortie", str(sortie), "--seuil", valeur]
        )

    assert exc_info.value.code == 2


def test_rapport_ocr_seuil_personnalise_transmis_a_mesurer_dossier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--seuil` transmis tel quel à `mesurer_dossier` (`Decimal`, pas une
    chaîne) — `mesurer_dossier` monkeypatché pour observer les arguments
    reçus sans dépendre d'un scénario de confiance complet."""
    dossier = tmp_path / "photos"
    dossier.mkdir()
    (dossier / "photo.jpg").write_bytes(b"contenu invente")
    (dossier / "photo.attendu.json").write_text(
        json.dumps(_attendu_invente()), encoding="utf-8"
    )
    sortie = tmp_path / "rapport.md"

    appels: list[dict[str, Any]] = []

    async def _mesurer_dossier_factice(
        dossier_recu: Path, *, ocr: Any, seuil: Any, tolerance: Any
    ) -> Any:
        from app.modules.ingest.rapport_ocr import agreger

        appels.append({"seuil": seuil, "tolerance": tolerance})
        rapport = agreger([], ["photo"], seuil=seuil)
        return rapport, []

    monkeypatch.setattr(cli, "mesurer_dossier", _mesurer_dossier_factice)

    code = cli.main(
        ["rapport-ocr", str(dossier), "--sortie", str(sortie), "--seuil", "0.5"]
    )

    assert code == 0
    assert len(appels) == 1
    assert appels[0]["seuil"] == Decimal("0.5")


def test_rapport_ocr_seuil_defaut_est_seuil_confiance_defaut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans `--seuil`, `mesurer_dossier` reçoit `SEUIL_CONFIANCE_DEFAUT`."""
    dossier = tmp_path / "photos"
    dossier.mkdir()
    (dossier / "photo.jpg").write_bytes(b"contenu invente")
    (dossier / "photo.attendu.json").write_text(
        json.dumps(_attendu_invente()), encoding="utf-8"
    )
    sortie = tmp_path / "rapport.md"

    appels: list[dict[str, Any]] = []

    async def _mesurer_dossier_factice(
        dossier_recu: Path, *, ocr: Any, seuil: Any, tolerance: Any
    ) -> Any:
        from app.modules.ingest.rapport_ocr import agreger

        appels.append({"seuil": seuil})
        rapport = agreger([], ["photo"], seuil=seuil)
        return rapport, []

    monkeypatch.setattr(cli, "mesurer_dossier", _mesurer_dossier_factice)

    code = cli.main(["rapport-ocr", str(dossier), "--sortie", str(sortie)])

    assert code == 0
    assert appels[0]["seuil"] == SEUIL_CONFIANCE_DEFAUT


# ---------------------------------------------------------------------------
# `rapport-ocr` — isolation par document (fix round 1, finding 1)
# ---------------------------------------------------------------------------


def test_rapport_ocr_attendu_invalide_isole_stdout_et_rapport(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un `.attendu.json` invalide ne fait plus échouer la commande : elle
    écrit quand même un rapport (le document est listé « non mesuré ») et
    compte l'échec sur stdout (jamais son contenu, seulement un compte)."""
    dossier = tmp_path / "photos"
    dossier.mkdir()
    (dossier / "photo-ko.jpg").write_bytes(b"contenu invente")
    (dossier / "photo-ko.attendu.json").write_text("pas du JSON", encoding="utf-8")
    sortie = tmp_path / "rapport.md"

    code = cli.main(["rapport-ocr", str(dossier), "--sortie", str(sortie)])
    sortie_stdout = capsys.readouterr().out

    assert code == 0
    assert sortie.is_file()
    contenu = sortie.read_text(encoding="utf-8")
    assert "Documents non mesurés" in contenu
    assert "photo-ko" in contenu
    assert "attendus invalides : 1" in sortie_stdout


# ---------------------------------------------------------------------------
# `rapprocher` (L4-T11) — câblage CLI seulement, la logique métier
# (`ingest.rapprochement.rapprocher_facture`) est déjà testée dans
# `app/modules/ingest/tests/test_rapprochement.py`.
# ---------------------------------------------------------------------------

_PREFIXE_FICHIER_RAPPROCHER = "/invente/test-cli-rapprocher-"
_SYNTHESE_RAPPROCHER_TOUT_RE = re.compile(
    r"^(\d+) factures traitées, (\d+) échecs, (\d+) anomalies ouvertes au total$"
)


async def _creer_facture_recue(engine: AsyncEngine) -> tuple[uuid.UUID, int]:
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        document = Document(
            type="facture",
            source="upload",
            statut="recu",
            fichier_path=f"{_PREFIXE_FICHIER_RAPPROCHER}{uuid.uuid4()}.pdf",
        )
        session.add(document)
        await session.commit()
        await session.refresh(document)
        return document.id, document.numero_interne


async def _nettoyer_factures_rapprochees(engine: AsyncEngine) -> None:
    """Nettoie les factures inventées par les tests `rapprocher` ci-dessous,
    et tout ce qu'elles ont pu produire (anomalie, journal) : une facture ne
    peut être supprimée tant qu'une anomalie la référence encore (FK sans
    cascade, `ingest/models.py`)."""
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        document_ids = (
            (
                await session.execute(
                    select(Document.id).where(
                        Document.fichier_path.startswith(_PREFIXE_FICHIER_RAPPROCHER)
                    )
                )
            )
            .scalars()
            .all()
        )
        if document_ids:
            await session.execute(
                delete(Anomalie).where(Anomalie.document_id.in_(document_ids))
            )
            await session.execute(
                delete(Journal).where(
                    Journal.cible_id.in_([str(i) for i in document_ids])
                )
            )
            await session.execute(delete(Document).where(Document.id.in_(document_ids)))
        await session.commit()


@pytest.mark.db
def test_rapprocher_facture_introuvable_code_2(
    _env_bl_test: None, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["rapprocher", "--facture", str(uuid.uuid4())])
    sortie = capsys.readouterr()

    assert code == 2
    assert sortie.err.strip() != ""
    assert sortie.out == ""


@pytest.mark.db
def test_rapprocher_facture_existante_affiche_les_compteurs_code_0(
    db_engine: AsyncEngine, _env_bl_test: None, capsys: pytest.CaptureFixture[str]
) -> None:
    facture_id, _numero_interne = asyncio.run(_creer_facture_recue(db_engine))
    try:
        code = cli.main(["rapprocher", "--facture", str(facture_id)])
        sortie = capsys.readouterr().out

        assert code == 0
        assert sortie.strip() == (
            "0 blocs, 0 reçus, 0 pas de bon, 0 lignes appariées, 0 anomalies ouvertes"
        )
    finally:
        asyncio.run(_nettoyer_factures_rapprochees(db_engine))


@pytest.mark.db
def test_rapprocher_tout_traite_les_factures_recues_une_par_une_code_0(
    db_engine: AsyncEngine, _env_bl_test: None, capsys: pytest.CaptureFixture[str]
) -> None:
    _facture_1_id, numero_1 = asyncio.run(_creer_facture_recue(db_engine))
    _facture_2_id, numero_2 = asyncio.run(_creer_facture_recue(db_engine))
    try:
        code = cli.main(["rapprocher", "--tout"])
        sortie = capsys.readouterr().out
        lignes = sortie.rstrip("\n").split("\n")

        assert code == 0
        ligne_attendue = (
            "0 blocs, 0 reçus, 0 pas de bon, 0 lignes appariées, 0 anomalies ouvertes"
        )
        assert f"facture {numero_1} : {ligne_attendue}" in lignes
        assert f"facture {numero_2} : {ligne_attendue}" in lignes

        correspondance = _SYNTHESE_RAPPROCHER_TOUT_RE.match(lignes[-1])
        assert correspondance is not None, "ligne de synthèse au format inattendu"
        traitees, echecs, _anomalies = (int(g) for g in correspondance.groups())
        assert traitees >= 2
        assert echecs == 0
    finally:
        asyncio.run(_nettoyer_factures_rapprochees(db_engine))


@pytest.mark.db
def test_rapprocher_tout_compte_les_echecs_code_1(
    db_engine: AsyncEngine,
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`rapprocher_facture_sans_echec` monkeypatchée pour échouer
    systématiquement (jamais un vrai échec provoqué en base) : prouve que
    `--tout` compte les échecs et continue au lieu de s'arrêter à la
    première facture en erreur."""
    asyncio.run(_creer_facture_recue(db_engine))

    async def _toujours_en_echec(session: Any, facture_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(cli, "rapprocher_facture_sans_echec", _toujours_en_echec)
    try:
        code = cli.main(["rapprocher", "--tout"])
        sortie = capsys.readouterr()

        assert code == 1
        assert "échec du rapprochement" in sortie.err
        correspondance = _SYNTHESE_RAPPROCHER_TOUT_RE.match(
            sortie.out.rstrip("\n").split("\n")[-1]
        )
        assert correspondance is not None
        assert int(correspondance.group(2)) >= 1
    finally:
        asyncio.run(_nettoyer_factures_rapprochees(db_engine))


def test_rapprocher_sans_argument_rejete_par_argparse_systemexit_2() -> None:
    """`--facture`/`--tout` forment un groupe mutuellement exclusif
    `required=True` : aucun des deux fait échouer l'analyse des arguments
    avant tout accès à la configuration ou à la base."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["rapprocher"])

    assert exc_info.value.code == 2


def test_rapprocher_facture_et_tout_combines_rejete_par_argparse_systemexit_2() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["rapprocher", "--facture", str(uuid.uuid4()), "--tout"])

    assert exc_info.value.code == 2


def test_rapprocher_facture_uuid_invalide_rejete_par_argparse_systemexit_2() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["rapprocher", "--facture", "pas-un-uuid"])

    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# `controles-differes` (L4-T11) — câblage CLI seulement, la logique métier
# (`ingest.suivi.controles_differes`) est déjà testée dans
# `app/modules/ingest/tests/test_suivi.py`.
# ---------------------------------------------------------------------------

_PREFIXE_FICHIER_CONTROLES_DIFFERES = "/invente/test-cli-controles-differes-"


async def _creer_bl_sans_confirmation(engine: AsyncEngine) -> uuid.UUID:
    """Un BL déposé il y a plus de 24h, jamais confirmé : matière de R15
    (`delai_confirmation_bl_h`, défaut 24 — L4-D10), suffisante pour prouver
    que la CLI appelle bien `controles_differes` et en affiche le compte."""
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        document = Document(
            type="bl",
            source="telegram",
            statut="recu",
            fichier_path=f"{_PREFIXE_FICHIER_CONTROLES_DIFFERES}{uuid.uuid4()}.jpg",
            created_at=datetime.now(UTC) - timedelta(hours=25),
        )
        session.add(document)
        await session.commit()
        await session.refresh(document)
        return document.id


async def _nettoyer_bl_controles_differes(engine: AsyncEngine) -> None:
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        document_ids = (
            (
                await session.execute(
                    select(Document.id).where(
                        Document.fichier_path.startswith(
                            _PREFIXE_FICHIER_CONTROLES_DIFFERES
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        if document_ids:
            await session.execute(
                delete(Anomalie).where(Anomalie.document_id.in_(document_ids))
            )
            await session.execute(delete(Document).where(Document.id.in_(document_ids)))
        await session.commit()


@pytest.mark.db
def test_controles_differes_affiche_le_nombre_ouvertes_code_0(
    db_engine: AsyncEngine, _env_bl_test: None, capsys: pytest.CaptureFixture[str]
) -> None:
    asyncio.run(_creer_bl_sans_confirmation(db_engine))
    try:
        code = cli.main(["controles-differes"])
        sortie = capsys.readouterr().out

        assert code == 0
        correspondance = re.match(
            r"^(\d+) anomalies de suivi ouvertes$", sortie.strip()
        )
        assert correspondance is not None, "sortie au format inattendu"
        assert int(correspondance.group(1)) >= 1
    finally:
        asyncio.run(_nettoyer_bl_controles_differes(db_engine))


@pytest.mark.db
def test_controles_differes_rejeu_meme_compte_sans_doublon(
    db_engine: AsyncEngine, _env_bl_test: None, capsys: pytest.CaptureFixture[str]
) -> None:
    asyncio.run(_creer_bl_sans_confirmation(db_engine))
    try:
        premier = cli.main(["controles-differes"])
        sortie_premiere = capsys.readouterr().out
        second = cli.main(["controles-differes"])
        sortie_seconde = capsys.readouterr().out

        assert premier == 0 and second == 0
        assert sortie_premiere == sortie_seconde, (
            "un rejeu identique ne doit jamais faire grossir le compte affiché"
        )
    finally:
        asyncio.run(_nettoyer_bl_controles_differes(db_engine))


# ---------------------------------------------------------------------------
# `rattacher-chantiers` (Task 8, spec §2.8) — câblage CLI seulement, la
# logique métier (`ingest.rattachement_chantier.reprendre_chantiers`) est
# déjà testée en profondeur dans
# `app/modules/ingest/tests/test_rattachement_chantier.py`.
# ---------------------------------------------------------------------------

_BILAN_RATTACHER_CHANTIERS_RE = re.compile(
    r"^Noms rattachés : (\d+) · chantiers créés : (\d+) · "
    r"noms ambigus : (\d+) · bons rattachés : (\d+) · bons en alerte : (\d+)$"
)


async def _preparer_alias_en_attente(
    engine: AsyncEngine,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Sème un fournisseur, un chantier déjà connu et un alias en attente qui
    lui ressemble exactement (`chantier_id IS NULL`, ancien flux) :
    suffisant pour prouver que la CLI appelle bien `reprendre_chantiers` et
    affiche son bilan au format attendu, sans re-tester la logique de
    rattachement elle-même."""
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        fournisseur = Fournisseur(nom=f"Fournisseur CLI {uuid.uuid4()}")
        session.add(fournisseur)
        chantier = Chantier(nom_canonique=f"Villa CLI {uuid.uuid4()}")
        session.add(chantier)
        await session.flush()
        alias = ChantierAlias(
            fournisseur_id=fournisseur.id,
            libelle_brut=chantier.nom_canonique.casefold(),
            code_brut=None,
            chantier_id=None,
        )
        session.add(alias)
        await session.commit()
        return fournisseur.id, chantier.id


async def _nettoyer_alias_en_attente(
    engine: AsyncEngine, fournisseur_id: uuid.UUID, chantier_id: uuid.UUID
) -> None:
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        await session.execute(
            delete(ChantierAlias).where(ChantierAlias.fournisseur_id == fournisseur_id)
        )
        await session.execute(
            delete(Journal).where(Journal.cible_id == str(chantier_id))
        )
        await session.execute(delete(Chantier).where(Chantier.id == chantier_id))
        await session.execute(
            delete(Fournisseur).where(Fournisseur.id == fournisseur_id)
        )
        await session.commit()


@pytest.mark.db
def test_cli_rattacher_chantiers(
    db_engine: AsyncEngine, _env_bl_test: None, capsys: pytest.CaptureFixture[str]
) -> None:
    fournisseur_id, chantier_id = asyncio.run(_preparer_alias_en_attente(db_engine))
    try:
        code = cli.main(["rattacher-chantiers"])
        sortie = capsys.readouterr().out

        assert code == 0
        correspondance = _BILAN_RATTACHER_CHANTIERS_RE.match(sortie.strip())
        assert correspondance is not None, "sortie au format inattendu"
        rattaches, _crees, _ambigus, _bons_rattaches, _bons_alerte = (
            int(g) for g in correspondance.groups()
        )
        assert rattaches >= 1
    finally:
        asyncio.run(_nettoyer_alias_en_attente(db_engine, fournisseur_id, chantier_id))


def test_rattacher_chantiers_sans_argument_supplementaire() -> None:
    """`rattacher-chantiers` ne prend aucun argument : un argument superflu
    est rejeté par `argparse` lui-même, avant tout accès à la base."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["rattacher-chantiers", "--inconnu"])

    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# `ranger-photos` (Task 9, spec §5) — câblage CLI seulement, la logique
# métier (`ingest.rangement.ranger_tout`) est déjà testée en profondeur dans
# `app/modules/ingest/tests/test_rangement.py`.
# ---------------------------------------------------------------------------

_BILAN_RANGER_PHOTOS_RE = re.compile(r"^(\d+) bon\(s\) rangé\(s\)$")


async def _semer_bon_a_ranger(
    engine: AsyncEngine, docs_dir: Path
) -> tuple[uuid.UUID, int, str]:
    """Sème un bon `bl` avec un vrai fichier source sous `docs_dir`
    (`os.link` a besoin d'un fichier qui existe réellement) : suffisant pour
    prouver que la CLI appelle bien `ranger_tout` et pose son lien, sans
    re-tester la logique de rangement elle-même."""
    source = docs_dir / f"{uuid.uuid4()}.jpg"
    source.write_bytes(b"contenu-invente-cli-ranger-photos")
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        document = Document(
            type="bl",
            source="telegram",
            statut="recu",
            fichier_path=str(source),
        )
        session.add(document)
        await session.commit()
        await session.refresh(document)
        return document.id, document.numero_interne, document.fichier_path


async def _nettoyer_bon_range(engine: AsyncEngine, document_id: uuid.UUID) -> None:
    sessionmaker = creer_sessionmaker(engine)
    async with sessionmaker() as session:
        await session.execute(delete(Document).where(Document.id == document_id))
        await session.commit()


@pytest.mark.db
def test_cli_ranger_photos(
    db_engine: AsyncEngine,
    _env_bl_test: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DOCS_DIR", str(tmp_path))
    get_settings.cache_clear()
    document_id, numero_interne, fichier_path = asyncio.run(
        _semer_bon_a_ranger(db_engine, tmp_path)
    )
    try:
        code = cli.main(["ranger-photos"])
        sortie = capsys.readouterr().out

        assert code == 0
        correspondance = _BILAN_RANGER_PHOTOS_RE.match(sortie.strip())
        assert correspondance is not None, "sortie au format inattendu"
        assert int(correspondance.group(1)) >= 1

        liens = list(tmp_path.glob(f"bl/*/*/*_n{numero_interne}.*"))
        assert len(liens) == 1
        # Même inode que l'original (lien physique, jamais une copie).
        assert liens[0].stat().st_ino == Path(fichier_path).stat().st_ino
    finally:
        get_settings.cache_clear()
        asyncio.run(_nettoyer_bon_range(db_engine, document_id))


def test_ranger_photos_sans_argument_supplementaire() -> None:
    """`ranger-photos` ne prend aucun argument : un argument superflu est
    rejeté par `argparse` lui-même, avant tout accès à la base."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["ranger-photos", "--inconnu"])

    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# `synthese-commentaires` (T4, phase 4 IA) — câblage CLI seulement, la
# logique métier (`ingest.ia_synthese.generer_synthese`) est déjà testée dans
# `app/modules/ingest/tests/test_ia_synthese.py`.
# ---------------------------------------------------------------------------


def _generer_synthese_factice(
    resultat: ResultatSynthese, *, semaine_attendue: date | None = None
) -> Callable[..., Any]:
    """Substitut de `generer_synthese` (jamais de vraie base ni de vrai
    appel IA touchés par ces tests) : vérifie, si fourni, la semaine reçue,
    puis renvoie `resultat` tel quel."""

    async def _factice(
        session: Any, http: Any, *, semaine_debut: date
    ) -> ResultatSynthese:
        if semaine_attendue is not None:
            assert semaine_debut == semaine_attendue
        return resultat

    return _factice


def test_synthese_commentaires_creee_code_0(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "generer_synthese",
        _generer_synthese_factice(
            ResultatSynthese(
                statut="creee",
                semaine_debut=date(2026, 9, 21),
                nb_commentaires=12,
                nb_actions=4,
            ),
            semaine_attendue=date(2026, 9, 21),
        ),
    )

    code = cli.main(["synthese-commentaires", "--semaine", "2026-09-21"])
    sortie = capsys.readouterr().out

    assert code == 0
    assert sortie.strip() == (
        "Synthèse du 21/09/2026 au 27/09/2026 créée (12 commentaires, 4 actions)"
    )


def test_synthese_commentaires_deja_faite_code_0(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "generer_synthese",
        _generer_synthese_factice(
            ResultatSynthese(statut="deja_faite", semaine_debut=date(2026, 9, 21))
        ),
    )

    code = cli.main(["synthese-commentaires", "--semaine", "2026-09-21"])
    sortie = capsys.readouterr().out

    assert code == 0
    assert sortie.strip() == "Synthèse du 21/09/2026 au 27/09/2026 déjà faite"


def test_synthese_commentaires_vide_code_0(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "generer_synthese",
        _generer_synthese_factice(
            ResultatSynthese(
                statut="vide", semaine_debut=date(2026, 9, 21), nb_commentaires=0
            )
        ),
    )

    code = cli.main(["synthese-commentaires", "--semaine", "2026-09-21"])
    sortie = capsys.readouterr().out

    assert code == 0
    assert sortie.strip() == "Synthèse du 21/09/2026 au 27/09/2026 : aucun commentaire"


def test_synthese_commentaires_ia_eteinte_code_0(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "generer_synthese",
        _generer_synthese_factice(
            ResultatSynthese(statut="ia_eteinte", semaine_debut=date(2026, 9, 21))
        ),
    )

    code = cli.main(["synthese-commentaires", "--semaine", "2026-09-21"])
    sortie = capsys.readouterr().out

    assert code == 0
    assert sortie.strip() == "IA éteinte : rien à faire"


def test_synthese_commentaires_echec_code_1_stderr(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Code 1 (le timer d'exploitation alerte alors sur Telegram et réessaie
    le lendemain) : la ligne part sur stderr, jamais stdout, comme les autres
    échecs de ce fichier."""
    monkeypatch.setattr(
        cli,
        "generer_synthese",
        _generer_synthese_factice(
            ResultatSynthese(
                statut="echec",
                semaine_debut=date(2026, 9, 21),
                erreur="ProviderAuthError",
            )
        ),
    )

    code = cli.main(["synthese-commentaires", "--semaine", "2026-09-21"])
    sortie = capsys.readouterr()

    assert code == 1
    assert sortie.out == ""
    assert (
        sortie.err.strip() == "Échec de la synthèse du 21/09/2026 : ProviderAuthError"
    )


def test_synthese_commentaires_sans_semaine_utilise_derniere_semaine_complete(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Sans `--semaine`, la CLI passe `derniere_semaine_complete(datetime.now
    (UTC))` -- monkeypatchée ici pour vérifier le câblage sans dépendre de la
    date du jour."""
    monkeypatch.setattr(
        cli, "derniere_semaine_complete", lambda maintenant: date(2026, 9, 14)
    )
    monkeypatch.setattr(
        cli,
        "generer_synthese",
        _generer_synthese_factice(
            ResultatSynthese(
                statut="vide", semaine_debut=date(2026, 9, 14), nb_commentaires=0
            ),
            semaine_attendue=date(2026, 9, 14),
        ),
    )

    code = cli.main(["synthese-commentaires"])
    sortie = capsys.readouterr().out

    assert code == 0
    assert sortie.strip() == "Synthèse du 14/09/2026 au 20/09/2026 : aucun commentaire"


def test_synthese_commentaires_semaine_illisible_systemexit_2() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["synthese-commentaires", "--semaine", "pas-une-date"])

    assert exc_info.value.code == 2


def test_synthese_commentaires_semaine_pas_lundi_systemexit_2() -> None:
    """22/09/2026 est un mardi (inventé pour ce test)."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["synthese-commentaires", "--semaine", "2026-09-22"])

    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# `ia-prix` (T6, phase 4 IA) -- câblage CLI seulement, la logique métier
# (sélection, cache, échecs, plafond) est déjà testée en profondeur côté
# `ingest` (`app/modules/ingest/tests/test_ia_prix.py`) : les tests ici ne
# vérifient que le message affiché et le code de sortie, `expliquer_alertes`/
# `chercher_prix_internet` étant monkeypatchées (jamais de vrai appel IA ni
# de vraie base touchée par le service).
# ---------------------------------------------------------------------------


def _bilan_factice(bilan: BilanIA) -> Callable[..., Any]:
    async def _factice(session: Any, http: Any) -> BilanIA:
        return bilan

    return _factice


async def _jamais_appelee_bilan(session: Any, http: Any) -> BilanIA:
    raise AssertionError("ne doit jamais être appelée")


def test_ia_prix_ia_eteinte_code_0(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "ia_active", lambda: False)
    monkeypatch.setattr(cli, "expliquer_alertes", _jamais_appelee_bilan)
    monkeypatch.setattr(cli, "chercher_prix_internet", _jamais_appelee_bilan)

    code = cli.main(["ia-prix"])
    sortie = capsys.readouterr().out

    assert code == 0
    assert sortie.strip() == "IA éteinte : rien à faire"


def test_ia_prix_nominal_message_et_code_0(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "ia_active", lambda: True)
    monkeypatch.setattr(cli, "expliquer_alertes", _bilan_factice(BilanIA(ok=3)))
    monkeypatch.setattr(
        cli,
        "chercher_prix_internet",
        _bilan_factice(BilanIA(ok=1, non_verifiables=1)),
    )

    code = cli.main(["ia-prix"])
    sortie = capsys.readouterr().out

    assert code == 0
    assert sortie.strip() == "3 explications, 1 prix trouvé, 1 non vérifiable, 0 échec"


def test_ia_prix_arret_plafond_pendant_explications_saute_recherche_prix(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`chercher_prix_internet` ne doit jamais être appelée si les
    explications se sont déjà arrêtées faute d'IA joignable (brief : « puis,
    si pas d'arrêt »)."""
    monkeypatch.setattr(cli, "ia_active", lambda: True)
    monkeypatch.setattr(
        cli, "expliquer_alertes", _bilan_factice(BilanIA(arret="plafond"))
    )
    monkeypatch.setattr(cli, "chercher_prix_internet", _jamais_appelee_bilan)

    code = cli.main(["ia-prix"])
    sortie = capsys.readouterr().out

    assert code == 0
    assert sortie.strip() == (
        "0 explication, 0 prix trouvé, 0 non vérifiable, 0 échec"
        " — plafond du jour atteint"
    )


def test_ia_prix_arret_eteinte_en_cours_de_route_mention_dediee(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fix round 1 : `arret == "eteinte"` (IA coupée pendant que la commande
    tournait) porte sa propre mention, distincte de « plafond du jour
    atteint »."""
    monkeypatch.setattr(cli, "ia_active", lambda: True)
    monkeypatch.setattr(
        cli, "expliquer_alertes", _bilan_factice(BilanIA(arret="eteinte"))
    )
    monkeypatch.setattr(cli, "chercher_prix_internet", _jamais_appelee_bilan)

    code = cli.main(["ia-prix"])
    sortie = capsys.readouterr().out

    assert code == 0
    assert sortie.strip() == (
        "0 explication, 0 prix trouvé, 0 non vérifiable, 0 échec"
        " — IA éteinte en cours de route"
    )


def test_ia_prix_toutes_tentatives_injoignables_code_1(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "ia_active", lambda: True)
    monkeypatch.setattr(
        cli,
        "expliquer_alertes",
        _bilan_factice(BilanIA(echecs=2, echecs_injoignable=2)),
    )
    monkeypatch.setattr(
        cli,
        "chercher_prix_internet",
        _bilan_factice(BilanIA(echecs=1, echecs_injoignable=1)),
    )

    code = cli.main(["ia-prix"])
    sortie = capsys.readouterr().out

    assert code == 1
    assert sortie.strip() == "0 explication, 0 prix trouvé, 0 non vérifiable, 3 échecs"


def test_ia_prix_melange_succes_et_echec_injoignable_reste_code_0(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un échec « injoignable » mêlé à un succès reste code 0 -- seul le cas
    « toutes les tentatives ont échoué faute d'IA joignable » déclenche
    l'alerte (code 1)."""
    monkeypatch.setattr(cli, "ia_active", lambda: True)
    monkeypatch.setattr(cli, "expliquer_alertes", _bilan_factice(BilanIA(ok=1)))
    monkeypatch.setattr(
        cli,
        "chercher_prix_internet",
        _bilan_factice(BilanIA(echecs=1, echecs_injoignable=1)),
    )

    code = cli.main(["ia-prix"])

    assert code == 0


def test_ia_prix_sans_argument_supplementaire() -> None:
    """`ia-prix` ne prend aucun argument : un argument superflu est rejeté
    par `argparse` lui-même, avant tout accès à la configuration ou à la
    base."""
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["ia-prix", "--inconnu"])

    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# `essai-prix-internet` (T6, phase 4 IA, document d'Ilane §16) -- lecture du
# CSV testée en propre (pure, sans base) ; câblage CLI vérifié avec
# `essayer_prix_internet` monkeypatchée.
# ---------------------------------------------------------------------------


def test_lire_produits_essai_entete_reconnue_et_ignoree(tmp_path: Path) -> None:
    chemin = tmp_path / "produits.csv"
    chemin.write_text(
        "fournisseur;designation;code;unite\n"
        "Fournisseur Un;Produit Un;COD1;u\n"
        ";Produit Deux;;\n",
        encoding="utf-8",
    )

    produits = cli._lire_produits_essai(chemin)

    assert produits == [
        ProduitEssai(
            fournisseur="Fournisseur Un",
            designation="Produit Un",
            code="COD1",
            unite="u",
        ),
        ProduitEssai(
            fournisseur=None, designation="Produit Deux", code=None, unite=None
        ),
    ]


def test_lire_produits_essai_entete_insensible_a_la_casse(tmp_path: Path) -> None:
    chemin = tmp_path / "produits.csv"
    chemin.write_text(
        "FOURNISSEUR;designation;code;unite\nFournisseur Un;Produit Un;COD1;u\n",
        encoding="utf-8",
    )

    produits = cli._lire_produits_essai(chemin)

    assert len(produits) == 1
    assert produits[0].designation == "Produit Un"


def test_lire_produits_essai_sans_entete_premiere_ligne_gardee(tmp_path: Path) -> None:
    """Une ligne de données dont le premier champ ne commence pas par
    « fournisseur » (brief T6 : reconnaissance sur ce seul critère) n'est
    jamais prise pour une en-tête, même en premier."""
    chemin = tmp_path / "produits.csv"
    chemin.write_text("Point P Invente;Produit Un;COD1;u\n", encoding="utf-8")

    produits = cli._lire_produits_essai(chemin)

    assert produits == [
        ProduitEssai(
            fournisseur="Point P Invente",
            designation="Produit Un",
            code="COD1",
            unite="u",
        ),
    ]


def test_lire_produits_essai_lignes_vides_ignorees(tmp_path: Path) -> None:
    chemin = tmp_path / "produits.csv"
    chemin.write_text(
        "fournisseur;designation;code;unite\n\nFournisseur Un;Produit Un;COD1;u\n\n",
        encoding="utf-8",
    )

    produits = cli._lire_produits_essai(chemin)

    assert len(produits) == 1


def test_lire_produits_essai_champ_avec_point_virgule_entre_guillemets(
    tmp_path: Path,
) -> None:
    """Fix round 1 : une désignation réelle peut porter un `;` -- entre
    guillemets dans le CSV, elle doit rester un seul champ, jamais découpée
    en deux colonnes par un `split(";")` naïf."""
    chemin = tmp_path / "produits.csv"
    chemin.write_text(
        "fournisseur;designation;code;unite\n"
        'Fournisseur Un;"Plaque 60x60; blanche";COD1;u\n',
        encoding="utf-8",
    )

    produits = cli._lire_produits_essai(chemin)

    assert produits == [
        ProduitEssai(
            fournisseur="Fournisseur Un",
            designation="Plaque 60x60; blanche",
            code="COD1",
            unite="u",
        ),
    ]


def test_lire_produits_essai_bom_excel_accepte(tmp_path: Path) -> None:
    """Fix round 1 : un fichier enregistré depuis Excel porte souvent un BOM
    UTF-8 en tête -- il doit être retiré, jamais gardé dans le premier
    champ (« ﻿ournisseur » ne doit jamais apparaître)."""
    chemin = tmp_path / "produits.csv"
    chemin.write_bytes(
        (
            "﻿fournisseur;designation;code;unite\nFournisseur Un;Produit Un;COD1;u\n"
        ).encode()
    )

    produits = cli._lire_produits_essai(chemin)

    assert produits == [
        ProduitEssai(
            fournisseur="Fournisseur Un",
            designation="Produit Un",
            code="COD1",
            unite="u",
        ),
    ]


def test_essai_prix_internet_champ_ia_echappe_dans_la_sortie(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Fix round 1 : un champ libre venu de l'IA (`raison`) portant un `;`
    et un guillemet doit rester UNE seule colonne dans le CSV de sortie,
    correctement échappée par `csv.writer` -- vérifié en reparsant la sortie
    avec `csv.reader` et en comptant les colonnes (jamais un décalage)."""
    monkeypatch.setattr(cli, "ia_active", lambda: True)
    chemin = tmp_path / "produits.csv"
    chemin.write_text("Fournisseur Un;Produit Un;COD1;u\n", encoding="utf-8")
    produit = ProduitEssai(
        fournisseur="Fournisseur Un",
        designation="Produit Un",
        code="COD1",
        unite="u",
    )
    raison_piegee = 'Prix "spécial" non garanti; à vérifier à la source'
    ligne_essai = LigneEssai(
        produit=produit,
        resultat=PrixInternetLu(
            statut="non_verifiable",
            prix=None,
            devise=None,
            taxes=None,
            unite=None,
            conditionnement=None,
            produit_trouve=None,
            source_url=None,
            confiance="faible",
            raison=raison_piegee,
        ),
        erreur=None,
        duree_s=0.3,
    )

    async def _essayer_prix_internet_factice(
        session: Any, http: Any, produits: Any
    ) -> list[LigneEssai]:
        return [ligne_essai]

    monkeypatch.setattr(cli, "essayer_prix_internet", _essayer_prix_internet_factice)

    code = cli.main(["essai-prix-internet", "--fichier", str(chemin)])
    sortie = capsys.readouterr().out

    assert code == 0
    lignes = list(csv.reader(io.StringIO(sortie), delimiter=";"))
    assert len(lignes) == 2  # en-tête + une ligne de données
    assert len(lignes[0]) == 11
    ligne_donnees = lignes[1]
    assert len(ligne_donnees) == 11  # jamais décalée par le `;`/`"` du champ
    assert ligne_donnees[0] == "Produit Un"
    assert ligne_donnees[1] == "non_verifiable"
    assert ligne_donnees[9] == raison_piegee  # colonne "raison", intacte


def test_essai_prix_internet_ia_eteinte_code_1(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """IA éteinte -> code 1 (contrairement à `ia-prix`) et le fichier n'est
    jamais lu (vérifié en pointant un chemin qui n'existe pas)."""
    monkeypatch.setattr(cli, "ia_active", lambda: False)

    code = cli.main(
        ["essai-prix-internet", "--fichier", str(tmp_path / "inexistant.csv")]
    )
    sortie = capsys.readouterr().out

    assert code == 1
    assert sortie.strip() == "IA éteinte : rien à faire"


def test_essai_prix_internet_fichier_introuvable_code_2(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "ia_active", lambda: True)
    chemin = tmp_path / "inexistant.csv"

    code = cli.main(["essai-prix-internet", "--fichier", str(chemin)])
    sortie = capsys.readouterr()

    assert code == 2
    assert sortie.out == ""
    assert sortie.err.strip() == f"lecture du fichier impossible : {chemin}"


def test_essai_prix_internet_nominal_csv_sortie(
    _env_bl_test: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "ia_active", lambda: True)
    chemin = tmp_path / "produits.csv"
    chemin.write_text(
        "fournisseur;designation;code;unite\n"
        "Fournisseur Un;Produit Un;COD1;u\n"
        ";Produit Deux;;\n",
        encoding="utf-8",
    )
    produits_attendus = [
        ProduitEssai(
            fournisseur="Fournisseur Un",
            designation="Produit Un",
            code="COD1",
            unite="u",
        ),
        ProduitEssai(
            fournisseur=None, designation="Produit Deux", code=None, unite=None
        ),
    ]
    lignes_essai = [
        LigneEssai(
            produit=produits_attendus[0],
            resultat=PrixInternetLu(
                statut="trouve",
                prix=Decimal("12.3400"),
                devise="EUR",
                taxes="HT",
                unite="u",
                conditionnement="boîte",
                produit_trouve="Produit Un Trouvé",
                source_url="https://exemple.invalid/produit-un",
                confiance="elevee",
                raison=None,
            ),
            erreur=None,
            duree_s=1.234,
        ),
        LigneEssai(
            produit=produits_attendus[1],
            resultat=None,
            erreur="ProviderAuthError",
            duree_s=0.5,
        ),
    ]
    produits_captures: list[ProduitEssai] = []

    async def _essayer_prix_internet_factice(
        session: Any, http: Any, produits: Any
    ) -> list[LigneEssai]:
        produits_captures.extend(produits)
        return lignes_essai

    monkeypatch.setattr(cli, "essayer_prix_internet", _essayer_prix_internet_factice)

    code = cli.main(["essai-prix-internet", "--fichier", str(chemin)])
    sortie = capsys.readouterr().out.splitlines()

    assert code == 0
    assert produits_captures == produits_attendus
    assert sortie[0] == (
        "designation;statut;prix;taxes;unite;conditionnement;produit_trouve;"
        "source_url;confiance;raison;duree_s"
    )
    assert sortie[1] == ";".join(
        [
            "Produit Un",
            "trouve",
            "12.3400",
            "HT",
            "u",
            "boîte",
            "Produit Un Trouvé",
            "https://exemple.invalid/produit-un",
            "elevee",
            "",
            "1.2",
        ]
    )
    assert sortie[2] == ";".join(
        [
            "Produit Deux",
            "echec",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "ProviderAuthError",
            "0.5",
        ]
    )


def test_essai_prix_internet_sans_fichier_systemexit_2() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["essai-prix-internet"])

    assert exc_info.value.code == 2
