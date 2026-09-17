"""Service du front React (L2-T6, décision du contrôleur qui prévaut sur
L2-D16 en cas de conflit) : `StaticFiles` sur `/assets` et renvoi
d'`index.html` pour toute route `GET` du front, React Router décidant côté
client de la page à afficher.

`monter_front` n'est appelée par `app/main.py` que si `web/dist` existe (le
build front n'est pas requis pour lancer la suite de tests) : les tests de ce
module construisent leur propre `FastAPI` isolé avec un faux dossier de
build (`tmp_path`), jamais `app.main.app`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

_logger = logging.getLogger(__name__)

# Préfixes jamais remplacés par `index.html`, même si aucune route ne les
# gère explicitement : ils tombent alors sur le 404 JSON par défaut de
# FastAPI/Starlette, jamais sur l'app React.
_PREFIXES_RESERVES = (
    "/api",
    "/tg",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/assets",
)


def _chemin_reserve(chemin: str) -> bool:
    return any(
        chemin == prefixe or chemin.startswith(f"{prefixe}/")
        for prefixe in _PREFIXES_RESERVES
    )


def monter_front(app: FastAPI, dossier: Path) -> None:
    """Monte le build front (`dossier` = `web/dist`) sur `app`.

    - `dossier/assets` (fichiers hashés par Vite) est servi tel quel sur
      `/assets` s'il existe.
    - Toute autre route `GET` renvoie `dossier/index.html`, sauf les
      préfixes réservés à l'API et aux outils (`_PREFIXES_RESERVES`).

    Appelée après le montage des routeurs de `app/main.py` : une route
    déjà enregistrée (`/health`, `/api/...`, `/tg/...`, `/docs`, `/redoc`,
    `/openapi.json`) est toujours prioritaire sur ce montage, ajouté en
    dernier dans la table de routage.

    Si `dossier/index.html` est absent (build incomplet ou mauvais dossier),
    rien n'est monté (ni `/assets`, ni le renvoi d'index) plutôt que de
    laisser `FileResponse` échouer en 500 au premier appel : un avertissement
    est journalisé une fois, au démarrage.
    """
    index_html = dossier / "index.html"
    if not index_html.is_file():
        _logger.warning(
            "Front introuvable : %s absent, aucune route front montée "
            "(l'API reste servie normalement).",
            index_html,
        )
        return

    assets_dir = dossier / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{chemin_complet:path}", include_in_schema=False)
    async def _servir_index(chemin_complet: str) -> Response:
        if _chemin_reserve(f"/{chemin_complet}"):
            raise HTTPException(status_code=404)
        # Point 3 (vague finale du lot 2) : `index.html` référence les
        # fichiers hachés de `assets/` par leur nom (donc leur contenu) —
        # un navigateur qui le mettrait en cache verrait une page qui pointe
        # vers un bundle déjà remplacé après un déploiement. Les fichiers
        # sous `assets/` (servis par `StaticFiles` ci-dessus, noms hachés)
        # restent, eux, cachables sans limite : seul `index.html` porte
        # `Cache-Control: no-cache` (revalidation à chaque chargement,
        # jamais servi périmé depuis le cache local).
        return FileResponse(index_html, headers={"Cache-Control": "no-cache"})
