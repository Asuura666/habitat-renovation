"""Normalisation des données extraites de BL et de factures (module pur).

Résolution fournisseur par SIRET/TVA/nom (`fournisseur.py`, L3-D8),
décomposition du libellé chantier en clé d'alias (`chantier.py`, L3-D6),
normalisation d'unité (`unites.py`) et propositions d'article/ratio
(`article.py`, L3-D9). Comme `extract`, ce paquet n'importe ni FastAPI, ni
Starlette, ni SQLAlchemy, ni httpx, ni asyncpg, et n'importe aucun autre
module de `app.modules` (garde de frontière vérifiée par
`tests/test_frontieres.py`) : entrées et sorties en dataclasses, tests sans
base ni réseau.
"""

from __future__ import annotations
