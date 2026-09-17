import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router";

import { CLE_MOI, recupererMoi } from "../api/moi";

/**
 * Route `/` (décision du contrôleur L2-T7) : après connexion, un admin va
 * sur `/factures`, un agent sur `/bl`. Toujours monté à l'intérieur de
 * `RouteProtegee`, donc `["moi"]` est déjà en cache.
 */
export function RedirectionAccueil(): ReactElement | null {
  const { data: moi } = useQuery({ queryKey: CLE_MOI, queryFn: recupererMoi });

  if (!moi) {
    return null;
  }
  return <Navigate to={moi.role === "admin" ? "/factures" : "/bl"} replace />;
}
