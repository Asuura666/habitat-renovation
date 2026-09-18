"""Verrou anti-désynchronisation entre le filtre `regle` de `GET
/api/anomalies` (Ruling R22, revue finale du lot 4) et le catalogue de
règles réellement produites par le moteur.

`app.modules.api.anomalies.RegleAnomalie` (l'énumération qui valide le
paramètre `regle`) ne peut pas être définie en important
`app.modules.rules.engine.REGLES_FACTURE`/`REGLES_SUIVI` : `api` n'a pas le
droit d'importer `rules` (garde vérifiée par `tests/test_frontieres.py`,
qui s'applique aussi aux fichiers sous `app/modules/api/tests/`). Ce test
vit donc ici, sous le `tests/` racine, hors de `app/modules/`, seul endroit
autorisé à importer les deux pour comparer leur contenu — sans lui,
l'énumération se désynchroniserait en silence à la première règle ajoutée
au moteur (200 + liste vide sur une règle pourtant réelle, au lieu du
filtre attendu)."""

from __future__ import annotations

from typing import get_args

from app.modules.api.anomalies import RegleAnomalie
from app.modules.rules.engine import REGLES_FACTURE, REGLES_SUIVI


def test_regle_anomalie_couvre_exactement_les_regles_du_moteur() -> None:
    assert set(get_args(RegleAnomalie)) == REGLES_FACTURE | REGLES_SUIVI
