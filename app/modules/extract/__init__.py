"""Extraction pure des factures fournisseurs (aucune dépendance d'infrastructure).

Ce module n'importe ni FastAPI, ni SQLAlchemy, ni httpx : il ne manipule que
des dataclasses en entrée/sortie et ne journalise rien (garde de frontière
vérifiée par `tests/test_frontieres.py`).
"""

from __future__ import annotations
