import type { ReactElement } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router";

import { appelerApi } from "../api/client";
import { CLE_MOI, recupererMoi } from "../api/moi";

const LIBELLES_ROLE: Record<string, string> = {
  admin: "Administrateur",
  agent: "Agent",
};

function classesOnglet({ isActive }: { isActive: boolean }): string {
  const base = "inline-block border-b-2 px-1 py-3 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-blue-600";
  return isActive
    ? `${base} border-blue-600 text-blue-700`
    : `${base} border-transparent text-slate-600 hover:border-slate-300 hover:text-slate-900`;
}

/** Gabarit de l'application : en-tête (nom, rôle, déconnexion), onglets de
 * navigation (décision du contrôleur : « À traiter », « Anomalies » (L4-D17,
 * juste après « À traiter ») et « Factures » réservés à l'admin, L3-D18 ;
 * « BL déposés » ouvert aux deux rôles) et
 * contenu de la route active (`<Outlet />`). N'est monté qu'à l'intérieur de
 * `RouteProtegee`, donc `["moi"]` est déjà en cache (même clé de requête) :
 * pas d'appel réseau supplémentaire tant que les données ne sont pas jugées
 * périmées. */
export function Gabarit(): ReactElement {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: moi } = useQuery({ queryKey: CLE_MOI, queryFn: recupererMoi });

  const deconnexion = useMutation({
    mutationFn: () => appelerApi("/api/auth/logout", { method: "POST" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: CLE_MOI });
      navigate("/connexion", { replace: true });
    },
  });

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
        <div>
          <p className="text-sm font-semibold text-slate-900">
            {moi?.nom ?? moi?.email ?? "…"}
          </p>
          {moi && (
            <p className="text-xs text-slate-500">
              {LIBELLES_ROLE[moi.role] ?? moi.role}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => deconnexion.mutate()}
          disabled={deconnexion.isPending}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 outline-none hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Se déconnecter
        </button>
      </header>

      {moi && (
        <nav aria-label="Navigation principale" className="border-b border-slate-200 bg-white px-4 sm:px-6">
          <ul className="flex gap-6">
            {moi.role === "admin" && (
              <>
                <li>
                  <NavLink to="/a-traiter" className={classesOnglet}>
                    À traiter
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/anomalies" className={classesOnglet}>
                    Anomalies
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/factures" className={classesOnglet}>
                    Factures
                  </NavLink>
                </li>
              </>
            )}
            <li>
              <NavLink to="/bl" className={classesOnglet}>
                BL déposés
              </NavLink>
            </li>
          </ul>
        </nav>
      )}

      <main className="px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}
