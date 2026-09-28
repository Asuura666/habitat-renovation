"""Cohérence entre `infra/README.md` et la configuration nginx réelle.

Relevé en relecture de T10 (en-têtes de sécurité et zone `login`) : la
documentation d'ensemble décrivait encore l'ancien état (CSP incomplète,
zone `general` seule) après que `deploy/nginx/habitat.conf` a été complété.
`infra/README.md` est désigné par `CLAUDE.md` comme la documentation
technique d'ensemble faisant foi pour le futur serveur dédié ; ces tests
garantissent que ses §5.4 et §7.2 ne repartent pas en arrière si
`habitat.conf` évolue sans que la doc suive.

Ni base ni réseau : simple lecture de fichiers du dépôt.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "infra" / "README.md"
HABITAT_CONF = REPO_ROOT / "deploy" / "nginx" / "habitat.conf"


def _section(texte: str, titre: str) -> str:
    """Renvoie le contenu d'une section `### titre` jusqu'au prochain `### `."""
    debut = texte.index(titre)
    reste = texte[debut + len(titre) :]
    fin = re.search(r"\n### ", reste)
    return reste[: fin.start()] if fin else reste


def test_habitat_conf_a_bien_la_zone_login_et_les_nouveaux_entetes() -> None:
    """Garde-fou : si ceci échoue, c'est `habitat.conf` qui a régressé,
    pas la documentation — les deux autres tests supposent ces éléments
    présents dans la configuration réelle."""
    conf = HABITAT_CONF.read_text(encoding="utf-8")
    assert "zone=login" in conf
    assert "location = /api/auth/login" in conf
    for directive in ("base-uri 'self'", "form-action 'self'", "object-src 'none'"):
        assert directive in conf
    for entete in (
        "Permissions-Policy",
        "Cross-Origin-Opener-Policy",
        "Cross-Origin-Resource-Policy",
    ):
        assert entete in conf


def test_readme_section_5_4_documente_la_zone_login() -> None:
    section = _section(README.read_text(encoding="utf-8"), "### 5.4")
    assert "login" in section
    assert "/api/auth/login" in section


def test_readme_section_7_2_documente_la_csp_complete_et_les_nouveaux_entetes() -> None:
    section = _section(README.read_text(encoding="utf-8"), "### 7.2")
    for directive in ("base-uri 'self'", "form-action 'self'", "object-src 'none'"):
        assert directive in section
    for entete in (
        "Permissions-Policy",
        "Cross-Origin-Opener-Policy",
        "Cross-Origin-Resource-Policy",
    ):
        assert entete in section
