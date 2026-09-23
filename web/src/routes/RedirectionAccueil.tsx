import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router";

import { CLE_MOI, DUREE_CACHE_MOI, recupererMoi } from "../api/moi";
import { EcranEnConstruction } from "../ui/EcranEnConstruction";

/**
 * Route `/` (Task 4, remplace L3-T9 : « Vue d'ensemble », maquette `Main`,
 * spec §3/§4) : désormais la destination de l'admin elle-même (pas une
 * redirection ailleurs) — écran en construction ici, une tâche suivante le
 * remplace. Un agent n'a pas accès à la vue d'ensemble et est renvoyé vers
 * ses dépôts (`/documents`) ; même protection que `GardeAdmin`, qui a déjà
 * écarté l'agent avant que ce composant ne soit monté (voir `App.tsx`) —
 * la revérifier ici coûte peu et évite toute dépendance implicite à l'ordre
 * des gardes. Toujours monté à l'intérieur de `RouteProtegee`, donc
 * `["moi"]` est déjà en cache.
 */
export function RedirectionAccueil(): ReactElement | null {
  const { data: moi } = useQuery({
    queryKey: CLE_MOI,
    queryFn: recupererMoi,
    staleTime: DUREE_CACHE_MOI,
  });

  if (!moi) {
    return null;
  }
  if (moi.role !== "admin") {
    return <Navigate to="/documents" replace />;
  }
  return <EcranEnConstruction titre="Vue d'ensemble" />;
}
