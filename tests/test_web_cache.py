from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).parents[1] / "web" / "src"


def test_cache_long_est_limite_a_la_requete_utilisateur() -> None:
    main = (WEB / "main.tsx").read_text()
    moi = (WEB / "api" / "moi.ts").read_text()

    assert "staleTime" not in main
    assert "DUREE_CACHE_MOI" in moi
    for chemin in (
        WEB / "components" / "Gabarit.tsx",
        WEB / "routes" / "GardeAdmin.tsx",
        WEB / "routes" / "RedirectionAccueil.tsx",
        WEB / "routes" / "RouteProtegee.tsx",
    ):
        assert "staleTime: DUREE_CACHE_MOI" in chemin.read_text()
