"""Test générique sur la vraie grille Cedeo du client (spec §12, plan P3).

`tests/fixtures/grilles/GRILLE_BOUCHUT_1.xlsx` est un document réel (jamais
commité, voir `tests/fixtures/README.md` et `CLAUDE.md` § Données) : ce test
saute (`pytest.skip`) s'il est absent, comme les tests équivalents sur les
autres fixtures réelles (`app/modules/extract/tests/test_unikalo.py`).

N'affirme que des **propriétés** de la lecture (zéro erreur, nombre de
lignes cohérent, aucune désignation vide) : jamais une valeur du fichier
(désignation, référence, prix) n'est comparée, affichée ou journalisée ici.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.extract.grille_excel import lire_grille_excel

_FICHIER_CEDEO = (
    Path(__file__).resolve().parent / "fixtures" / "grilles" / "GRILLE_BOUCHUT_1.xlsx"
)


def test_grille_cedeo_reelle_est_lue_sans_erreur() -> None:
    if not _FICHIER_CEDEO.is_file():
        pytest.skip(
            "aucune fixture tests/fixtures/grilles/GRILLE_BOUCHUT_1.xlsx "
            "(clone neuf ou fixtures non déposées)"
        )

    grille = lire_grille_excel(_FICHIER_CEDEO.read_bytes())

    assert grille.erreurs == ()
    assert len(grille.lignes) > 100
    assert all(ligne.designation.strip() for ligne in grille.lignes)
