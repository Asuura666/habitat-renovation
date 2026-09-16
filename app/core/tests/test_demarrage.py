"""`app/main.py` appelle `get_settings()` à l'import : sans configuration,
même `python -c "import app.main"` échoue, avant qu'uvicorn ne démarre.

Le sous-processus tourne dans un répertoire vide (`tmp_path`), avec un
environnement entièrement recomposé (seul `PYTHONPATH` est fourni) : le
`.env` réel du dépôt ne peut donc jamais être trouvé et fausser le test.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def test_import_app_main_sans_configuration_echoue(tmp_path: Path) -> None:
    resultat = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,
        env={"PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert resultat.returncode != 0
    assert "database_url" in resultat.stderr
    assert "docs_dir" in resultat.stderr
