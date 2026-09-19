import { appelerApi } from "./client";
import type { components } from "./schema";

export type LigneBilanChantier = components["schemas"]["LigneBilanChantierReponse"];

export interface FiltresBilan {
  mois?: string;
  agence?: string;
}

export const CLE_BILAN_CHANTIERS = ["bilan", "chantiers"] as const;

export function cleBilanChantiers(
  filtres: FiltresBilan,
): readonly [string, string, FiltresBilan] {
  return ["bilan", "chantiers", filtres] as const;
}

function ajouterFiltres(chemin: string, filtres: FiltresBilan): string {
  const params = new URLSearchParams();
  if (filtres.mois) {
    params.set("mois", filtres.mois);
  }
  if (filtres.agence) {
    params.set("agence", filtres.agence);
  }
  const requete = params.toString();
  return requete === "" ? chemin : `${chemin}?${requete}`;
}

export function listerBilanChantiers(
  filtres: FiltresBilan = {},
): Promise<LigneBilanChantier[]> {
  return appelerApi<LigneBilanChantier[]>("/api/bilan/chantiers", {
    url: ajouterFiltres("/api/bilan/chantiers", filtres),
  });
}

export function urlExportBilanChantiers(filtres: FiltresBilan = {}): string {
  return ajouterFiltres("/api/bilan/chantiers.csv", filtres);
}
