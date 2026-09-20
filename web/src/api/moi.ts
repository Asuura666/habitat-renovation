import { appelerApi } from "./client";
import type { components } from "./schema";

export type Moi = components["schemas"]["MoiReponse"];

export const CLE_MOI = ["moi"] as const;
export const DUREE_CACHE_MOI = 5 * 60 * 1000;

export function recupererMoi(): Promise<Moi> {
  return appelerApi<Moi>("/api/moi");
}
