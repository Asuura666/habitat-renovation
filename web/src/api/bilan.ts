import { appelerApi } from "./client";
import type { components } from "./schema";

export type LigneBilanChantier = components["schemas"]["LigneBilanChantierReponse"];
export type LigneBilanFournisseur = components["schemas"]["LigneBilanFournisseurReponse"];
export type LigneBilanBl = components["schemas"]["LigneBilanBlReponse"];

export interface FiltresBilan {
  mois?: string;
  agence?: string;
}

export const CLE_BILAN_CHANTIERS = ["bilan", "chantiers"] as const;
export const CLE_BILAN_FOURNISSEURS = ["bilan", "fournisseurs"] as const;
export const CLE_BILAN_BL = ["bilan", "bl"] as const;

export function cleBilanChantiers(
  filtres: FiltresBilan,
): readonly [string, string, FiltresBilan] {
  return ["bilan", "chantiers", filtres] as const;
}

export function cleBilanFournisseurs(
  chantierId: string | null,
  filtres: FiltresBilan,
): readonly [string, string, string | null, FiltresBilan] {
  return ["bilan", "fournisseurs", chantierId, filtres] as const;
}

export function cleBilanBl(
  chantierId: string,
  fournisseurId: string,
  filtres: FiltresBilan,
): readonly [string, string, string, string, FiltresBilan] {
  return ["bilan", "bl", chantierId, fournisseurId, filtres] as const;
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

export function listerBilanFournisseurs(
  chantierId: string,
  filtres: FiltresBilan = {},
): Promise<LigneBilanFournisseur[]> {
  const chemin = `/api/bilan/chantiers/${chantierId}/fournisseurs`;
  return appelerApi<LigneBilanFournisseur[]>(
    "/api/bilan/chantiers/{chantier_id}/fournisseurs",
    { url: ajouterFiltres(chemin, filtres) },
  );
}

export function listerBilanBl(
  chantierId: string,
  fournisseurId: string,
  filtres: FiltresBilan = {},
): Promise<LigneBilanBl[]> {
  const chemin = `/api/bilan/chantiers/${chantierId}/fournisseurs/${fournisseurId}/bl`;
  return appelerApi<LigneBilanBl[]>(
    "/api/bilan/chantiers/{chantier_id}/fournisseurs/{fournisseur_id}/bl",
    { url: ajouterFiltres(chemin, { mois: filtres.mois }) },
  );
}

export function listerBilanFournisseursGlobal(
  filtres: FiltresBilan = {},
): Promise<LigneBilanFournisseur[]> {
  return appelerApi<LigneBilanFournisseur[]>("/api/bilan/fournisseurs", {
    url: ajouterFiltres("/api/bilan/fournisseurs", filtres),
  });
}

export function listerBilanChantiersFournisseur(
  fournisseurId: string,
  filtres: FiltresBilan = {},
): Promise<LigneBilanChantier[]> {
  const chemin = `/api/bilan/fournisseurs/${fournisseurId}/chantiers`;
  return appelerApi<LigneBilanChantier[]>(
    "/api/bilan/fournisseurs/{fournisseur_id}/chantiers",
    { url: ajouterFiltres(chemin, filtres) },
  );
}

export function urlExportBilanChantiers(filtres: FiltresBilan = {}): string {
  return ajouterFiltres("/api/bilan/chantiers.csv", filtres);
}

/** Export détaillé (décision d'Ilane du 23/09/2026, réponse à Q3 du lot 5) :
 * une ligne par ligne de facture, sans niveau (pas de route JSON équivalente,
 * ce fichier n'a pas d'écran) -- mêmes filtres `mois`/`agence` que les
 * exports par niveau ci-dessus. */
export function urlExportBilanDetail(filtres: FiltresBilan = {}): string {
  return ajouterFiltres("/api/bilan/detail.csv", filtres);
}

export function urlExportBilanFournisseurs(
  chantierId: string | null,
  filtres: FiltresBilan = {},
): string {
  const chemin = chantierId === null
    ? "/api/bilan/fournisseurs.csv"
    : `/api/bilan/chantiers/${chantierId}/fournisseurs.csv`;
  return ajouterFiltres(chemin, filtres);
}

export function urlExportBilanBl(
  chantierId: string,
  fournisseurId: string,
  filtres: FiltresBilan = {},
): string {
  return ajouterFiltres(
    `/api/bilan/chantiers/${chantierId}/fournisseurs/${fournisseurId}/bl.csv`,
    { mois: filtres.mois },
  );
}

export function urlExportBilanChantiersFournisseur(
  fournisseurId: string,
  filtres: FiltresBilan = {},
): string {
  return ajouterFiltres(
    `/api/bilan/fournisseurs/${fournisseurId}/chantiers.csv`,
    filtres,
  );
}
