import type { ReactElement, ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router";

import { CLE_MOI, recupererMoi } from "../api/moi";

/**
 * Réserve ses enfants au rôle `admin` (décision du contrôleur L2-T7) :
 * l'onglet « Factures » n'existe pas pour un agent, et `/factures*` le
 * redirige vers `/bl`. Aucune règle métier : le rôle vient de l'API
 * (`/api/moi`), cette redirection n'est qu'une décision de navigation.
 *
 * Toujours monté à l'intérieur de `RouteProtegee` (voir `App.tsx`), donc
 * `["moi"]` est déjà en cache — pas d'appel réseau supplémentaire.
 */
export function GardeAdmin({ children }: { children: ReactNode }): ReactElement | null {
  const { data: moi } = useQuery({ queryKey: CLE_MOI, queryFn: recupererMoi });

  if (!moi) {
    return null;
  }
  if (moi.role !== "admin") {
    return <Navigate to="/bl" replace />;
  }
  return <>{children}</>;
}
