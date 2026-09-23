import type { ReactElement, ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router";

import { CLE_MOI, DUREE_CACHE_MOI, recupererMoi } from "../api/moi";

/**
 * Réserve ses enfants au rôle `admin` (décision du contrôleur L2-T7,
 * chemin mis à jour Task 4 — spec §3) : les écrans admin (Vue d'ensemble,
 * À régler, Chantiers, Fournisseurs, Réglages, Journal) n'existent pas pour
 * un agent, renvoyé vers ses dépôts (`/documents`). Aucune règle métier : le
 * rôle vient de l'API (`/api/moi`), cette redirection n'est qu'une décision
 * de navigation.
 *
 * Toujours monté à l'intérieur de `RouteProtegee` (voir `App.tsx`), donc
 * `["moi"]` est déjà en cache — pas d'appel réseau supplémentaire.
 */
export function GardeAdmin({ children }: { children: ReactNode }): ReactElement | null {
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
  return <>{children}</>;
}
