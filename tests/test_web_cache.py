from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).parents[1] / "web" / "src"


def test_cache_long_est_limite_a_la_requete_utilisateur() -> None:
    """`DUREE_CACHE_MOI` (5 min, `api/moi.ts`) ne doit jamais devenir le
    `staleTime` par défaut de `QueryClient` : seules les requêtes `["moi"]`
    l'utilisent explicitement (Gabarit, GardeAdmin, RedirectionAccueil,
    RouteProtegee) — sinon *toute* requête du front hériterait de 5 min de
    fraîcheur au lieu des 30 s par défaut (tâche T7, audit rapidité)."""
    main = (WEB / "main.tsx").read_text()
    moi = (WEB / "api" / "moi.ts").read_text()

    assert "staleTime: DUREE_CACHE_MOI" not in main
    assert "DUREE_CACHE_MOI" in moi
    for chemin in (
        WEB / "components" / "Gabarit.tsx",
        WEB / "routes" / "GardeAdmin.tsx",
        WEB / "routes" / "RedirectionAccueil.tsx",
        WEB / "routes" / "RouteProtegee.tsx",
    ):
        assert "staleTime: DUREE_CACHE_MOI" in chemin.read_text()


def test_fraicheur_par_defaut_30_secondes() -> None:
    """Tâche T7 (audit rapidité) : `defaultOptions.queries.staleTime` vaut
    30 s pour tout le front (défaut TanStack sinon `0`) — un remontage
    d'écran ou un retour de focus dans les 30 s qui suivent le dernier
    chargement ne relance plus la requête pour rien ; les invalidations
    après écriture (`api/invalidations.ts`, etc.) restent le mécanisme de
    fraîcheur après une mutation, indépendant de ce délai."""
    main = (WEB / "main.tsx").read_text()
    assert "staleTime: 30_000" in main
