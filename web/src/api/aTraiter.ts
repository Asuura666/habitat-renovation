import { appelerApi } from "./client";
import type { components } from "./schema";

export type ATraiter = components["schemas"]["ATraiterReponse"];
export type DocumentATraiter = components["schemas"]["DocumentATraiterReponse"];
export type AliasEnAttente = components["schemas"]["AliasEnAttenteReponse"];
export type ArticleAValider = components["schemas"]["ArticleAValiderReponse"];

export const CLE_A_TRAITER = ["a-traiter"] as const;

/** `GET /api/a-traiter` (admin, L3-D18) : documents « à vérifier », alias
 * chantier en attente de validation et articles à valider. Rafraîchi toutes
 * les 30 s par la page (décision du contrôleur), voir `pages/ATraiter.tsx`. */
export function obtenirATraiter(): Promise<ATraiter> {
  return appelerApi<ATraiter>("/api/a-traiter");
}
