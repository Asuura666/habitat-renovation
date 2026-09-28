"""Segment de nom de fichier stable, ASCII, sans espace ni caractère réservé.

Déplacé depuis `app.modules.jobs.drive` (Task 9, avenant du 27/09/2026,
spec §5) : `ingest.rangement` (rangement des photos de bon sur le serveur,
`<DOCS_DIR>/bl/...`) en a besoin, mais `ingest` ne doit jamais importer
`jobs` (l'import inverse existe déjà : `jobs/drive_sync.py` importe
`ingest.models`, un cycle réel si `ingest` importait `jobs`). Fonction pure
partagée par les deux appelants -- `app.core` est la seule couche que
`ingest` et `jobs` importent tous les deux sans restriction (`app` et
`app.modules.ingest`, décision L2-D3 vérifiée par `tests/test_frontieres
.py`). `jobs.drive` réexporte ce symbole (import puis réutilisation directe)
pour ne rien casser côté `jobs.drive_sync`/tests existants.
"""

from __future__ import annotations

import re
import unicodedata

_CARACTERES_INTERDITS = re.compile(r"[^A-Za-z0-9._-]+")
_SEPARATEURS = re.compile(r"[-_.]{2,}")
_LONGUEUR_MAX = 100


def normaliser_segment(valeur: str) -> str:
    """Produit un segment stable, ASCII, sans espace ni caractère réservé."""

    sans_accents = (
        unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode("ascii")
    )
    nettoye = _CARACTERES_INTERDITS.sub("-", sans_accents.strip())
    nettoye = _SEPARATEURS.sub("-", nettoye).strip("-._")
    return nettoye[:_LONGUEUR_MAX] or "sans-nom"
