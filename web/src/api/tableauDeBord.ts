import { appelerApi } from "./client";
import type { components } from "./schema";

export type TableauDeBord = components["schemas"]["TableauDeBordReponse"];

export const CLE_TABLEAU_DE_BORD = ["tableau-de-bord"] as const;

export function cleTableauDeBord(mois: string): readonly [string, string] {
  return ["tableau-de-bord", mois] as const;
}

export function obtenirTableauDeBord(mois: string): Promise<TableauDeBord> {
  return appelerApi<TableauDeBord>("/api/tableau-de-bord", {
    url: `/api/tableau-de-bord?mois=${mois}`,
  });
}
