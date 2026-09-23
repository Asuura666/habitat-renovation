"""Tests des garde-fous non destructifs de ``deploy/restore.sh``."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESTORE_SCRIPT = REPO_ROOT / "deploy" / "restore.sh"


def _environnement_restore(tmp_path: Path) -> tuple[dict[str, str], Path]:
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

    appels_docker = tmp_path / "appels-docker.txt"
    faux_bin = tmp_path / "bin"
    faux_bin.mkdir()
    faux_docker = faux_bin / "docker"
    faux_docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$APPELS_DOCKER"\n',
        encoding="utf-8",
    )
    faux_docker.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "APPELS_DOCKER": str(appels_docker),
            "COMPOSE_PROJECT_NAME": "habitat_reno_test",
            "HABITAT_RENO_ENV_FILE": str(env_file),
            "PATH": f"{faux_bin}:{env['PATH']}",
        }
    )
    return env, appels_docker


def _executer_restore(
    snapshot: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- script du dépôt, arguments de test fixes
        [str(RESTORE_SCRIPT), snapshot, "--confirmer"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_restore_refuse_latest_sans_appeler_docker(tmp_path: Path) -> None:
    env, appels_docker = _environnement_restore(tmp_path)

    resultat = _executer_restore("latest", env)

    assert resultat.returncode == 1
    assert "identifiant de snapshot précis obligatoire" in resultat.stderr
    assert "latest" in resultat.stderr
    assert not appels_docker.exists()


def test_restore_refuse_un_conteneur_api_absent_avant_tout_effet(
    tmp_path: Path,
) -> None:
    env, appels_docker = _environnement_restore(tmp_path)

    resultat = _executer_restore("abcd1234", env)

    assert resultat.returncode == 1
    assert "conteneur api introuvable" in resultat.stderr
    appels = appels_docker.read_text(encoding="utf-8").splitlines()
    assert len(appels) == 1
    assert appels[0].startswith("compose ")
    assert appels[0].endswith(" ps -q api")
    assert all(" run " not in appel and " stop api" not in appel for appel in appels)
