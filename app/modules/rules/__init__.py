"""Moteur de règles de rapprochement BL/facture (module PUR, lot 4).

Applique le catalogue déterministe du CDC §5 aux dataclasses de
`modeles.py` : chaque règle (`rules/Rxx.py`) est une fonction pure qui
reçoit ces dataclasses et renvoie `Anomalie | None`, `engine.py` les
enchaîne dans l'ordre du CDC. Comme `extract` et `normalize`, ce paquet
n'importe ni FastAPI, ni Starlette, ni SQLAlchemy, ni httpx, ni asyncpg, et
n'importe **aucun** autre module de `app.modules` — y compris `extract` et
`normalize` (L4-D1) : il redéfinit ses propres dataclasses d'entrée plutôt
que de réutiliser celles de `extract`/`normalize`, pour rester
indépendant de leur évolution. `ingest` (L4-T7/T8) construit ces
dataclasses depuis la base et orchestre l'appel au moteur ; garde de
frontière vérifiée par `tests/test_frontieres.py`.
"""

from __future__ import annotations
