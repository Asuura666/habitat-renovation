"""Garde-fou sur le contrat de période entre le front et l'API.

`GET /api/anomalies` accepte `depuis` et `jusqu_a` en **dates**
(`app/modules/api/anomalies.py`, Ruling R21) : le serveur les convertit
lui-même en bornes du jour en Europe/Paris. Le front doit donc transmettre
la valeur brute du champ `<input type="date">`, sans y ajouter d'heure.

Ce test existe parce que ce contrat s'est déjà cassé une fois : le serveur
est passé de `datetime` à `date` sans que `construireRequete` change, et le
front a continué d'envoyer `"AAAA-MM-JJT23:59:59"`. Pydantic refuse un
horodatage à heure non nulle là où il attend une date, donc la liste
d'anomalies renvoyait 422 dès que l'administrateur renseignait la borne
haute. Ni le typage TypeScript, ni la construction du bundle, ni aucun test
de l'API ne pouvaient le voir : le premier ne type pas le contenu d'une
chaîne de requête, les seconds ne passent jamais par le code du front.

C'est un palliatif, pas une vraie couverture : le projet n'a pas de suite de
tests front (dette du lot 2, aucune dépendance npm supplémentaire n'est
autorisée). Le jour où il en aura une, ce test sera remplacé par une
vérification directe de `construireRequete`."""

from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SOURCE_FRONT = RACINE / "web" / "src" / "api" / "anomalies.ts"

# `params.set("depuis", <expression>)` et son équivalent pour `jusqu_a`.
_APPEL_PARAM = re.compile(
    r"""params\.set\(\s*["'](depuis|jusqu_a)["']\s*,\s*([^)]+?)\s*\)""",
    re.MULTILINE,
)


def test_le_front_transmet_les_dates_de_periode_sans_heure() -> None:
    """Les deux bornes sont transmises telles quelles, sans horodatage
    fabriqué côté client."""
    source = SOURCE_FRONT.read_text(encoding="utf-8")
    appels = dict(_APPEL_PARAM.findall(source))

    assert set(appels) == {"depuis", "jusqu_a"}, (
        "les deux bornes de période doivent être posées par `params.set` "
        f"dans {SOURCE_FRONT.name} ; trouvé : {sorted(appels)}"
    )

    for parametre, valeur in appels.items():
        assert "T" not in valeur and ":" not in valeur, (
            f"le paramètre `{parametre}` est construit à partir de "
            f"`{valeur}` : l'API attend une date brute (AAAA-MM-JJ) et "
            "refuse un horodatage à heure non nulle. La conversion en "
            "bornes de journée se fait côté serveur, en Europe/Paris."
        )
