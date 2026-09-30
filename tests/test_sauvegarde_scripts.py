"""Tests de ``deploy/backup.sh`` et ``deploy/basculer-documents.sh`` sans Docker.

`docker` est simulé par un script placé en tête du PATH qui consigne chaque
appel ; les `.env` sont inventés. Ce qui exige un vrai Docker (restic,
pg_dump, chown en root) est couvert par `deploy/test-restauration.sh`.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_SCRIPT = REPO_ROOT / "deploy" / "backup.sh"
BASCULE_SCRIPT = REPO_ROOT / "deploy" / "basculer-documents.sh"


def _environnement_backup(
    tmp_path: Path, *, projet: str = "habitat_prod"
) -> tuple[dict[str, str], Path]:
    docs_dir = tmp_path / "documents"
    docs_dir.mkdir()
    restic_repo = tmp_path / "restic-repo"
    restic_repo.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "POSTGRES_USER=utilisateur_fictif",
                "POSTGRES_PASSWORD=mot_de_passe_fictif",
                "POSTGRES_DB=base_fictive",
                f"DOCS_HOST_DIR={docs_dir}",
                f"RESTIC_REPOSITORY={restic_repo}",
                "RESTIC_PASSWORD=secret_restic_fictif",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    appels = tmp_path / "appels-docker.txt"
    faux_bin = tmp_path / "bin"
    faux_bin.mkdir()
    faux_docker = faux_bin / "docker"
    faux_docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$APPELS_DOCKER"\n',
        encoding="utf-8",
    )
    faux_docker.chmod(0o755)
    env = os.environ.copy()
    for nom in (  # une variable héritée du processus masquerait un .env incomplet
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DOCS_HOST_DIR",
        "RESTIC_REPOSITORY",
        "RESTIC_PASSWORD",
    ):
        env.pop(nom, None)
    env.update(
        {
            "APPELS_DOCKER": str(appels),
            "COMPOSE_PROJECT_NAME": projet,
            "HABITAT_RENO_ENV_FILE": str(env_file),
            "PATH": f"{faux_bin}:{env['PATH']}",
        }
    )
    return env, appels


def _lancer_backup(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- script du dépôt, arguments de test fixes
        [str(BACKUP_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_backup_fixe_le_chemin_du_dump_et_l_hote_restic(tmp_path: Path) -> None:
    """F-01 : sans chemin ni hôte stables, chaque instantané forme son propre
    groupe et `forget` ne supprime jamais rien."""
    env, appels_docker = _environnement_backup(tmp_path)

    resultat = _lancer_backup(env)

    assert resultat.returncode == 0, resultat.stderr
    appels = appels_docker.read_text(encoding="utf-8").splitlines()
    sauvegarde = next(a for a in appels if " backup " in a)
    rotation = next(a for a in appels if " forget " in a)
    dump = next(a for a in appels if "pg_dump" in a)
    assert "--host habitat_prod" in sauvegarde
    assert "--host habitat_prod" in rotation
    # Le dump est vu sous /dump dans les deux conteneurs : le chemin
    # sauvegardé ne dépend plus du dossier temporaire de l'hôte.
    assert ":/dump" in dump and "-f /dump/bl.dump" in dump
    assert ":/dump:ro" in sauvegarde
    assert " backup /dump " in sauvegarde
    hote_dump = sauvegarde.split(":/dump:ro")[0].rsplit(" ", 1)[1]
    assert hote_dump not in sauvegarde.split(" backup ", 1)[1]


def test_backup_hote_distinct_par_instance(tmp_path: Path) -> None:
    env, appels_docker = _environnement_backup(tmp_path, projet="habitat_demo")

    assert _lancer_backup(env).returncode == 0

    contenu = appels_docker.read_text(encoding="utf-8")
    assert "--host habitat_demo" in contenu
    assert "habitat_prod" not in contenu


def test_backup_refuse_sans_variable_obligatoire(tmp_path: Path) -> None:
    env, appels_docker = _environnement_backup(tmp_path)
    env_file = Path(env["HABITAT_RENO_ENV_FILE"])
    env_file.write_text(
        "".join(
            ligne + "\n"
            for ligne in env_file.read_text(encoding="utf-8").splitlines()
            if not ligne.startswith("POSTGRES_DB=")
        ),
        encoding="utf-8",
    )

    resultat = _lancer_backup(env)

    assert resultat.returncode != 0
    assert "POSTGRES_DB manquant" in resultat.stderr
    assert not appels_docker.exists()


def test_backup_refuse_un_docs_host_dir_absent(tmp_path: Path) -> None:
    env, appels_docker = _environnement_backup(tmp_path)
    (tmp_path / "documents").rmdir()

    resultat = _lancer_backup(env)

    assert resultat.returncode == 1
    assert "DOCS_HOST_DIR introuvable" in resultat.stderr
    assert not appels_docker.exists()


# --- basculer-documents.sh : copie, droits de l'API, deux renommages ---


def _faux_chown(tmp_path: Path) -> tuple[dict[str, str], Path]:
    journal = tmp_path / "chown.txt"
    faux_bin = tmp_path / "bin-chown"
    faux_bin.mkdir()
    faux = faux_bin / "chown"
    faux.write_text('#!/bin/sh\necho "$*" >> "$JOURNAL_CHOWN"\n', encoding="utf-8")
    faux.chmod(0o755)
    env = os.environ.copy()
    env["JOURNAL_CHOWN"] = str(journal)
    env["PATH"] = f"{faux_bin}:{env['PATH']}"
    return env, journal


def _basculer(
    env: dict[str, str], source: Path, nouveau: Path, cible: Path, ancien: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- script du dépôt, arguments de test fixes
        [
            "/bin/sh",
            str(BASCULE_SCRIPT),
            str(source),
            str(nouveau),
            str(cible),
            str(ancien),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _mode(chemin: Path) -> int:
    return stat.S_IMODE(chemin.stat().st_mode)


def test_bascule_donne_les_droits_de_l_api_et_conserve_l_ancien(
    tmp_path: Path,
) -> None:
    source = tmp_path / "restaure"
    (source / "sous").mkdir(parents=True)
    fichier = source / "sous" / "facture.pdf"
    fichier.write_text("contenu", encoding="utf-8")
    fichier.chmod(0o644)
    source.chmod(0o700)
    (source / "sous").chmod(0o755)
    cible = tmp_path / "documents"
    cible.mkdir()
    (cible / "ancien.txt").write_text("avant", encoding="utf-8")
    nouveau = tmp_path / "documents.restaure-1"
    ancien = tmp_path / "documents.avant-restauration-1"
    env, journal = _faux_chown(tmp_path)

    resultat = _basculer(env, source, nouveau, cible, ancien)

    assert resultat.returncode == 0, resultat.stderr
    assert (ancien / "ancien.txt").read_text(encoding="utf-8") == "avant"
    assert (cible / "sous" / "facture.pdf").read_text(encoding="utf-8") == "contenu"
    assert not nouveau.exists()
    assert _mode(cible) == 0o750
    assert _mode(cible / "sous") == 0o750
    assert _mode(cible / "sous" / "facture.pdf") == 0o640
    lignes = journal.read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 1
    assert lignes[0].startswith("-R 10001:10001 ")
    assert str(nouveau) in lignes[0]


def test_bascule_ne_touche_pas_a_l_existant_si_la_copie_echoue(
    tmp_path: Path,
) -> None:
    cible = tmp_path / "documents"
    cible.mkdir()
    (cible / "ancien.txt").write_text("avant", encoding="utf-8")
    env, _ = _faux_chown(tmp_path)

    resultat = _basculer(
        env,
        tmp_path / "source-absente",
        tmp_path / "documents.restaure-1",
        cible,
        tmp_path / "documents.avant-restauration-1",
    )

    assert resultat.returncode != 0
    assert (cible / "ancien.txt").read_text(encoding="utf-8") == "avant"
    assert not (tmp_path / "documents.avant-restauration-1").exists()


def test_bascule_sans_documents_en_place(tmp_path: Path) -> None:
    source = tmp_path / "restaure"
    source.mkdir()
    (source / "a.pdf").write_text("x", encoding="utf-8")
    env, _ = _faux_chown(tmp_path)

    resultat = _basculer(
        env,
        source,
        tmp_path / "documents.restaure-1",
        tmp_path / "documents",
        tmp_path / "documents.avant-restauration-1",
    )

    assert resultat.returncode == 0, resultat.stderr
    assert (tmp_path / "documents" / "a.pdf").exists()
