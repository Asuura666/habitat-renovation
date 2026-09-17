import type { ReactElement } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { appelerApi } from "../api/client";
import { CLE_MOI, recupererMoi } from "../api/moi";

const LIBELLES_ROLE: Record<string, string> = {
  admin: "Administrateur",
  agent: "Agent",
};

/** Gabarit de l'application : en-tête (nom, rôle, déconnexion) + contenu.
 * N'est monté qu'à l'intérieur de `RouteProtegee`, donc `["moi"]` est déjà en
 * cache (même clé de requête) : pas d'appel réseau supplémentaire tant que
 * les données ne sont pas jugées périmées. */
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

      <main className="px-4 py-6 sm:px-6">
        <h1 className="mb-4 text-lg font-semibold text-slate-900">Factures</h1>
        <p className="text-sm text-slate-600">
          Contenu à venir (écran « Factures », tâche L2-T7).
        </p>
      </main>
    </div>
  );
}
