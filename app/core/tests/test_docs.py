"""`API_DOCS_ACTIVES` (constat sécurité du 24/09/2026, `docs/dette.md`) :
`/docs`, `/redoc` et `/openapi.json` exposent en clair le schéma complet de
l'API (routes, formes de requêtes/réponses) sans aucune authentification --
désactivées par défaut, activables explicitement.

Chaque scénario tourne dans un sous-processus isolé, même principe que
`test_demarrage.py` : `app.main.app` est un singleton construit une seule
fois à l'import du module, avec `docs_url`/`redoc_url`/`openapi_url` figés
au moment de cet import d'après `Settings.api_docs_actives` -- impossible de
tester les deux états dans le même process pytest (un second `import
app.main` ne reconstruit rien, Python garde le module déjà chargé). Le
sous-processus tourne dans un répertoire vide (`tmp_path`) avec un
environnement entièrement recomposé, comme `test_demarrage.py` : le `.env`
réel du dépôt ne doit jamais être lu et fausser le résultat.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_TOKEN_INVENTE = "000000:token-invente-pour-les-tests"
_SECRET_INVENTE = "secret-webhook-invente-pour-les-tests"
_CLE_MISTRAL_INVENTEE = "cle-mistral-invente-pour-les-tests"


def _environnement(tmp_path: Path, *, api_docs_actives: str | None) -> dict[str, str]:
    """Environnement minimal mais complet pour que `Settings` se construise
    (voir `test_config.py::_regler_environnement_complet`) -- `api_docs_
    actives` omise (`None`) reproduit l'absence de la variable en
    production, pour vérifier le défaut plutôt qu'une valeur explicite.
    `DOCS_DIR` pointe dans `tmp_path` (jamais un chemin `/tmp` en dur --
    S108) : ce dossier n'a besoin d'exister pour aucun de ces tests."""
    env = {
        "PYTHONPATH": str(REPO_ROOT),
        "DATABASE_URL": "postgresql+asyncpg://bl:x@localhost:5432/bl",
        "DOCS_DIR": str(tmp_path / "docs-inventes"),
        "TELEGRAM_BOT_TOKEN": _TOKEN_INVENTE,
        "TELEGRAM_WEBHOOK_SECRET": _SECRET_INVENTE,
        "TELEGRAM_CHAT_BL_ID": "-1000000000001",
        "TELEGRAM_CHAT_SUPERVISION_ID": "-1000000000002",
        "MISTRAL_API_KEY": _CLE_MISTRAL_INVENTEE,
        "COOKIE_SECURE": "true",
    }
    if api_docs_actives is not None:
        env["API_DOCS_ACTIVES"] = api_docs_actives
    return env


def _statuts_docs(tmp_path: Path, *, api_docs_actives: str | None) -> dict[str, int]:
    # Commande à arguments littéraux (aucune entrée utilisateur/réseau) :
    # même construction que `test_demarrage.py`, `subprocess.run` reste le
    # bon outil (pas de `shell=True`).
    resultat = subprocess.run(
        [
            sys.executable,
            "-c",
            "import asyncio, json\n"
            "import httpx\n"
            "from httpx import ASGITransport\n"
            "from app.main import app\n"
            "async def main():\n"
            "    transport = ASGITransport(app=app)\n"
            "    async with httpx.AsyncClient(\n"
            '        transport=transport, base_url="http://test"\n'
            "    ) as client:\n"
            "        statuts = {}\n"
            '        for chemin in ("/docs", "/redoc", "/openapi.json"):\n'
            "            reponse = await client.get(chemin)\n"
            "            statuts[chemin] = reponse.status_code\n"
            "    print(json.dumps(statuts))\n"
            "asyncio.run(main())\n",
        ],
        cwd=tmp_path,
        env=_environnement(tmp_path, api_docs_actives=api_docs_actives),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert resultat.returncode == 0, resultat.stderr
    statuts: dict[str, int] = json.loads(resultat.stdout)
    return statuts


def test_docs_absente_renvoie_404_par_defaut(tmp_path: Path) -> None:
    """Ni la variable `API_DOCS_ACTIVES` ni le fichier `.env` (répertoire
    vide) : `Settings.api_docs_actives` vaut son défaut `False`, les trois
    routes doivent donc être absentes (404), jamais servies en clair."""
    statuts = _statuts_docs(tmp_path, api_docs_actives=None)

    assert statuts == {"/docs": 404, "/redoc": 404, "/openapi.json": 404}


def test_docs_explicitement_fausse_renvoie_404(tmp_path: Path) -> None:
    statuts = _statuts_docs(tmp_path, api_docs_actives="false")

    assert statuts == {"/docs": 404, "/redoc": 404, "/openapi.json": 404}


def test_docs_activee_renvoie_200(tmp_path: Path) -> None:
    """`API_DOCS_ACTIVES=true` : les trois routes redeviennent servies --
    geste explicite d'administrateur, jamais le comportement par défaut."""
    statuts = _statuts_docs(tmp_path, api_docs_actives="true")

    assert statuts == {"/docs": 200, "/redoc": 200, "/openapi.json": 200}
