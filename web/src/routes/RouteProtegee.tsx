import type { ReactElement, ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { CLE_MOI, DUREE_CACHE_MOI, recupererMoi } from "../api/moi";

/**
 * Protège ses enfants derrière `GET /api/moi` : tant que la requête est en
 * cours, affiche un état de chargement ; en cas d'échec (401 notamment),
 * ne rend rien — la redirection vers `/connexion` est déjà déclenchée par
 * `appelerApi` via `EcouteAuthentification` (le routeur, jamais
 * `window.location`). Politique de réessai définie une seule fois, au
 * niveau du `QueryClient` (`main.tsx`) — jamais divergente par hook, alors
 * que `Gabarit` observe la même clé `["moi"]`.
 */
export function RouteProtegee({ children }: { children: ReactNode }): ReactElement | null {
  const { data, isPending, isError } = useQuery({
    queryKey: CLE_MOI,
    queryFn: recupererMoi,
    staleTime: DUREE_CACHE_MOI,
  });

  if (isPending) {
    return (
      <p className="p-6 text-center text-sm text-slate-500" role="status">
        Chargement…
      </p>
    );
  }

  if (isError || !data) {
    return null;
  }

  return <>{children}</>;
}
