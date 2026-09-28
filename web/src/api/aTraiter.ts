import { appelerApi } from "./client";
import type { components } from "./schema";

export type ATraiter = components["schemas"]["ATraiterReponse"];
export type DocumentATraiter = components["schemas"]["DocumentATraiterReponse"];
export type AliasEnAttente = components["schemas"]["AliasEnAttenteReponse"];
export type ArticleAValider = components["schemas"]["ArticleAValiderReponse"];
export type ChantierACompleter = components["schemas"]["ChantierACompleterReponse"];
export type CompteARegler = components["schemas"]["CompteProblemesReponse"];

export const CLE_A_TRAITER = ["a-traiter"] as const;

/** Sous la clé `CLE_A_TRAITER` : invalider `CLE_A_TRAITER` (document
 * validé, chantier rattaché, article validé…) invalide aussi ce compte. */
export const CLE_COMPTE_A_REGLER = ["a-traiter", "compte"] as const;

/** `GET /api/a-traiter` (admin, L3-D18) : documents « à vérifier », alias
 * chantier en attente de validation et articles à valider. Rafraîchi toutes
 * les 30 s par l'écran « À régler ». */
export function obtenirATraiter(): Promise<ATraiter> {
  return appelerApi<ATraiter>("/api/a-traiter");
}

/** `GET /api/a-regler/compte` (admin, revue finale de la refonte du front)
 * : **le** nombre de problèmes « à régler », tous mois confondus — chaque
 * élément de la liste de l'écran « À régler » compté une fois, calculé par
 * le serveur (`ingest.a_traiter.compter_problemes_a_regler`). Seule source
 * de la pastille de navigation, du « … en tout » de la vue d'ensemble et de
 * l'en-tête de l'écran « À régler » : ces trois chiffres ne peuvent plus se
 * contredire. */
export function obtenirCompteARegler(): Promise<CompteARegler> {
  return appelerApi<CompteARegler>("/api/a-regler/compte");
}

/** « 1 problème », « 10 problèmes » — accord du nom seulement, aucun
 * calcul. */
export function problemes(nombre: number): string {
  return `${nombre} problème${nombre > 1 ? "s" : ""}`;
}
