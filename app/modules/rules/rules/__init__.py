"""Une règle par module (`R01.py` … `R17.py`, L4-D2).

Chaque fichier expose une unique fonction `Rxx(...) -> Anomalie | None` (ou
`tuple[Anomalie, ...]` pour une règle qui balaie une collection), pure et
nommée d'après son code CDC §5. `rules.engine` les enchaîne dans l'ordre du
catalogue.
"""

from __future__ import annotations
