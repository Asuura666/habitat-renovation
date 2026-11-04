"""Lot 2, B2 (31/10/2026) : « Dans l'onglet chantier tu rajoutes dans les
filtres le fait de chercher un chantier par son nom ». Le dépôt n'a pas
vitest : la fonction pure `web/src/lib/recherche.ts` est exécutée par Node
(qui lit le TypeScript sans compilation) ; l'écran est vérifié par ses
chaînes, comme les autres `test_web_*.py`."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).parents[1]
WEB = RACINE / "web" / "src"

_SCRIPT = """
import { correspondRecherche } from "%s";
const cas = JSON.parse(process.argv[1]);
const sortie = cas.map(([r, champs]) => correspondRecherche(r, ...champs));
console.log(JSON.stringify(sortie));
"""


def _executer(cas: list[tuple[str, list[str | None]]]) -> list[bool]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node absent")
    script = _SCRIPT % (WEB / "lib" / "recherche.ts").as_posix()
    sortie = subprocess.run(  # noqa: S603
        [node, "--input-type=module", "-e", script, json.dumps(cas)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    resultat: list[bool] = json.loads(sortie.stdout)
    return resultat


def test_recherche_insensible_a_la_casse_et_aux_accents() -> None:
    assert _executer(
        [
            ("aguirre", ["AGUIRRE", None]),
            ("ÉLYSÉE", ["Residence Elysee", None]),
            ("residence elysee", ["Résidence Élysée", None]),
            ("saint-georges", ["Saint Georges", None]),
            ("mariano", ["Saint Georges", None]),
        ]
    ) == [True, True, True, True, False]


def test_recherche_porte_sur_le_nom_et_le_client() -> None:
    assert _executer(
        [
            ("dupont", ["Chantier Nord", "M. Dupont"]),
            ("dupont", ["Chantier Nord", None]),
            ("nord", ["Chantier Nord", "M. Dupont"]),
        ]
    ) == [True, False, True]


def test_recherche_vide_ou_blanche_garde_tout() -> None:
    assert _executer([("", ["A", None]), ("   ", ["A", None])]) == [True, True]


def test_recherche_plusieurs_mots_tous_requis() -> None:
    assert _executer(
        [
            ("saint georges", ["Rue Saint Georges", None]),
            ("georges saint", ["Rue Saint Georges", None]),
            ("saint paul", ["Rue Saint Georges", None]),
        ]
    ) == [True, True, False]


def test_ecran_chantiers_a_son_champ_de_recherche() -> None:
    page = (WEB / "pages" / "ChantiersListe.tsx").read_text()

    for chaine in (
        "Rechercher un chantier",
        "correspondRecherche",
        'id="filtre-recherche"',
        'type="search"',
    ):
        assert chaine in page, chaine
