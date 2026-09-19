import { appelerApi } from "./client";
import type { components } from "./schema";

export type Parametre = components["schemas"]["ParametreReponse"];

export const CLE_PARAMETRES = ["parametres"] as const;

export function listerParametres(): Promise<Parametre[]> {
  return appelerApi<Parametre[]>("/api/parametres");
}

export function modifierParametre(cle: string, valeur: string): Promise<Parametre> {
  return appelerApi<Parametre>("/api/parametres/{cle}", {
    url: `/api/parametres/${encodeURIComponent(cle)}`,
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ valeur }),
  });
}
