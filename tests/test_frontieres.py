"""Garde-fous d'architecture (règles de frontière du monolithe modulaire).

Deux règles, valables pour toute la durée du projet :

1. Les modules purs (`extract`, `normalize`, `rules`) n'importent aucune
   dépendance d'infrastructure (FastAPI, Starlette, SQLAlchemy, httpx,
   asyncpg). Ils ne manipulent que des dataclasses, sans base ni réseau.
2. Aucun module métier sous `app/modules/` n'importe un autre module métier,
   sauf `ingest` qui est le seul orchestrateur autorisé.

Les vérifications sont faites via `ast` (analyse statique des imports, pas
d'exécution du code inspecté). Chaque import est résolu en un nom de module
pointé absolu : les imports relatifs (`from . import x`, `from ..pkg import
y`) sont recalculés à partir du paquet du fichier et de `node.level`, et
`from paquet import nom` est aussi lu comme un import potentiel du
sous-module `paquet.nom` (cas `from app.modules import extract`). Chaque
garde a un test positif (sur le vrai arbre `app/`, vide pour l'instant) et
des tests négatifs (sources synthétiques fautives, dans un répertoire
temporaire, jamais commitées) couvrant les formes d'import réalistes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"
MODULES_DIR = APP_DIR / "modules"

PURE_MODULES = ("extract", "normalize", "rules")
FORBIDDEN_IMPORTS_IN_PURE_MODULES = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "httpx",
    "asyncpg",
)
ORCHESTRATEUR_AUTORISE = "ingest"


def _iter_python_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(directory.rglob("*.py"))


def _module_dotted_name(root: Path, path: Path) -> str:
    """Nom de module pointé absolu d'un fichier, relatif à `root`."""
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_dotted_name(root: Path, path: Path) -> str:
    """Paquet contenant le fichier (base de résolution des imports relatifs)."""
    if path.name == "__init__.py":
        return _module_dotted_name(root, path)
    parts = _module_dotted_name(root, path).split(".")
    return ".".join(parts[:-1])


def _resolve_relative_import_base(package: str, level: int, module: str | None) -> str:
    """Base absolue d'un `from ... import ...` (`level` = nombre de points)."""
    if level == 0:
        return module or ""
    parts = package.split(".") if package else []
    truncate = level - 1
    base_parts = parts[: len(parts) - truncate] if truncate < len(parts) else []
    base = ".".join(base_parts)
    if module:
        return f"{base}.{module}" if base else module
    return base


def _resolved_imports(root: Path, path: Path) -> list[str]:
    """Noms de modules pointés absolus réellement visés par les imports d'un fichier.

    Pour `import a.b`, renvoie `"a.b"`. Pour `from a.b import c`, renvoie
    `"a.b.c"` (que `c` soit un sous-module ou un attribut, on ne peut pas le
    distingure statiquement, donc on garde la forme la plus précise). Pour
    `from . import c` / `from ..a import c`, la base relative est résolue via
    le paquet du fichier avant d'être combinée avec `c`.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    package = _package_dotted_name(root, path)
    resolved: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            resolved.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative_import_base(package, node.level, node.module)
            for alias in node.names:
                if alias.name == "*":
                    if base:
                        resolved.append(base)
                    continue
                resolved.append(f"{base}.{alias.name}" if base else alias.name)
    return resolved


def find_forbidden_imports(
    root: Path, directory: Path, forbidden: tuple[str, ...]
) -> list[str]:
    """Liste `"fichier:import"` pour chaque import interdit sous `directory`."""
    violations: list[str] = []
    for path in _iter_python_files(directory):
        for imported in _resolved_imports(root, path):
            root_package = imported.split(".")[0]
            if root_package in forbidden:
                violations.append(f"{path}:{imported}")
    return violations


def find_cross_module_imports(
    root: Path, modules_dir: Path, allowed_orchestrator: str
) -> list[str]:
    """Liste `"fichier:import"` pour tout import d'un autre module métier.

    L'orchestrateur `allowed_orchestrator` (ingest) est exempté : c'est le
    seul module autorisé à importer les autres modules métier. Un import
    relatif vers le même module (ex. `from .pdf import x` dans `extract`)
    n'est pas une violation.
    """
    violations: list[str] = []
    if not modules_dir.is_dir():
        return violations
    module_names = sorted(p.name for p in modules_dir.iterdir() if p.is_dir())
    for module_name in module_names:
        if module_name == allowed_orchestrator:
            continue
        for path in _iter_python_files(modules_dir / module_name):
            for imported in _resolved_imports(root, path):
                parts = imported.split(".")
                if len(parts) >= 3 and parts[0] == "app" and parts[1] == "modules":
                    other_module = parts[2]
                    if other_module != module_name:
                        violations.append(f"{path}:{imported}")
    return violations


def test_modules_purs_sans_dependance_infrastructure() -> None:
    violations: list[str] = []
    for module_name in PURE_MODULES:
        violations.extend(
            find_forbidden_imports(
                REPO_ROOT,
                MODULES_DIR / module_name,
                FORBIDDEN_IMPORTS_IN_PURE_MODULES,
            )
        )
    assert not violations, f"imports interdits détectés : {violations}"


def test_aucun_module_metier_nimporte_un_autre_sauf_ingest() -> None:
    violations = find_cross_module_imports(
        REPO_ROOT, MODULES_DIR, ORCHESTRATEUR_AUTORISE
    )
    assert not violations, f"imports croisés interdits détectés : {violations}"


@pytest.mark.parametrize(
    ("import_statement", "attendu"),
    [
        pytest.param("import fastapi", "fastapi", id="import-fastapi"),
        pytest.param(
            "from sqlalchemy.orm import Session",
            "sqlalchemy.orm.Session",
            id="from-sqlalchemy-orm-import-session",
        ),
        pytest.param("import httpx", "httpx", id="import-httpx"),
    ],
)
def test_garde_detecte_bibliotheque_interdite_dans_module_pur(
    tmp_path: Path, import_statement: str, attendu: str
) -> None:
    """Cas négatifs : une dépendance d'infrastructure dans un module pur
    est détectée."""
    faux_module_extract = tmp_path / "app" / "modules" / "extract"
    faux_module_extract.mkdir(parents=True)
    fichier_fautif = faux_module_extract / "faux.py"
    fichier_fautif.write_text(f"{import_statement}\n", encoding="utf-8")

    violations = find_forbidden_imports(
        tmp_path, faux_module_extract, FORBIDDEN_IMPORTS_IN_PURE_MODULES
    )

    assert violations == [f"{fichier_fautif}:{attendu}"]


@pytest.mark.parametrize(
    ("import_statement", "attendu"),
    [
        pytest.param(
            "from app.modules.extract import pdf",
            "app.modules.extract.pdf",
            id="from-module-point-attribut",
        ),
        pytest.param(
            "from app.modules import extract",
            "app.modules.extract",
            id="from-paquet-sous-module",
        ),
        pytest.param(
            "import app.modules.extract.pdf",
            "app.modules.extract.pdf",
            id="import-absolu-complet",
        ),
        pytest.param(
            "from ..extract import pdf",
            "app.modules.extract.pdf",
            id="relatif-module-point-attribut",
        ),
        pytest.param(
            "from .. import extract",
            "app.modules.extract",
            id="relatif-paquet-sous-module",
        ),
    ],
)
def test_garde_detecte_import_croise_sous_toutes_ses_formes(
    tmp_path: Path, import_statement: str, attendu: str
) -> None:
    """Cas négatifs : chaque style d'import inter-modules (absolu, via un nom
    de sous-module, ou relatif) doit être détecté, depuis un module qui n'est
    pas `ingest`."""
    modules_dir = tmp_path / "app" / "modules"
    (modules_dir / "extract").mkdir(parents=True)
    (modules_dir / "normalize").mkdir(parents=True)
    fichier_fautif = modules_dir / "normalize" / "service.py"
    fichier_fautif.write_text(f"{import_statement}\n", encoding="utf-8")

    violations = find_cross_module_imports(
        tmp_path, modules_dir, ORCHESTRATEUR_AUTORISE
    )

    assert violations == [f"{fichier_fautif}:{attendu}"]


def test_garde_autorise_import_relatif_intra_module(tmp_path: Path) -> None:
    """Cas positif : un import relatif vers son propre module n'est pas
    une violation."""
    modules_dir = tmp_path / "app" / "modules"
    (modules_dir / "extract").mkdir(parents=True)
    fichier = modules_dir / "extract" / "pdf.py"
    fichier.write_text(
        "from . import ocr\nfrom .ocr import Something\n", encoding="utf-8"
    )

    violations = find_cross_module_imports(
        tmp_path, modules_dir, ORCHESTRATEUR_AUTORISE
    )

    assert violations == []


def test_garde_autorise_ingest_a_importer_un_autre_module(tmp_path: Path) -> None:
    """Cas positif : `ingest` est le seul orchestrateur autorisé à importer
    un autre module métier."""
    modules_dir = tmp_path / "app" / "modules"
    (modules_dir / "extract").mkdir(parents=True)
    (modules_dir / "ingest").mkdir(parents=True)
    fichier = modules_dir / "ingest" / "service.py"
    fichier.write_text("from app.modules.extract import pdf\n", encoding="utf-8")

    violations = find_cross_module_imports(
        tmp_path, modules_dir, ORCHESTRATEUR_AUTORISE
    )

    assert violations == []
