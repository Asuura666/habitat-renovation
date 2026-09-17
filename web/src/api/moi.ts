import { appelerApi } from "./client";
import type { components } from "./schema";

export type Moi = components["schemas"]["MoiReponse"];

export const CLE_MOI = ["moi"] as const;

export function recupererMoi(): Promise<Moi> {
  return appelerApi<Moi>("/api/moi");
}
