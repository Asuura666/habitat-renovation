import { appelerApi } from "./client";
import type { components } from "./schema";

/**
 * Synthèse hebdomadaire des commentaires (T4, phase 4 IA, spec §4.6) : un
 * résumé rédigé par l'IA et des actions à cocher, lus par la carte
 * « Commentaires de la semaine » de la Vue d'ensemble
 * (`components/SyntheseCommentaires.tsx`, T5). Mêmes attributs que les
 * dataclasses d'`ingest.ia_synthese` (`BonLie`, `ActionVue`, `SyntheseVue`,
 * `SyntheseAccueil`) — voir `app/modules/api/schemas.py`.
 */
export type BonLie = components["schemas"]["BonLieReponse"];
export type ActionSynthese = components["schemas"]["ActionSyntheseReponse"];
export type Synthese = components["schemas"]["SyntheseReponse"];
export type SyntheseAccueil = components["schemas"]["SyntheseAccueilReponse"];

export const cleSyntheseIA = ["ia", "synthese"] as const;

/** `GET /api/ia/synthese` (admin) : la dernière synthèse (résumé, actions de
 * la semaine) et les actions non faites des semaines précédentes
 * (`encore_a_faire`) — `ia_active` distingue « l'IA n'a encore rien produit »
 * de « l'IA est éteinte », deux messages différents côté écran. */
export function lireSyntheseIA(): Promise<SyntheseAccueil> {
  return appelerApi<SyntheseAccueil>("/api/ia/synthese");
}

/** `POST /api/ia/synthese/actions/{action_id}/faite` (`faite: true`) ou
 * `.../a-faire` (`faite: false`) : coche ou décoche une action de synthèse
 * (admin), idempotent côté serveur (`ingest.ia_synthese.marquer_action`) —
 * 404 si l'action est inconnue. Deux routes distinctes du schéma OpenAPI
 * (pas un seul gabarit avec un segment variable) : `chemin` reste le
 * littéral exact de chaque branche, comme l'exige `CheminApi`. */
export function marquerActionSynthese(id: string, faite: boolean): Promise<ActionSynthese> {
  if (faite) {
    return appelerApi<ActionSynthese>("/api/ia/synthese/actions/{action_id}/faite", {
      url: `/api/ia/synthese/actions/${id}/faite`,
      method: "POST",
    });
  }
  return appelerApi<ActionSynthese>("/api/ia/synthese/actions/{action_id}/a-faire", {
    url: `/api/ia/synthese/actions/${id}/a-faire`,
    method: "POST",
  });
}

/**
 * Avis de l'IA sur une anomalie de prix (T6/T7, phase 4 IA, spec §6.4) :
 * explication de l'alerte et dernier prix trouvé sur internet, lus par
 * l'encart `components/AvisIA.tsx` (T7) du détail d'un problème de
 * catégorie « prix » (`pages/ProblemeDetail.tsx`). Mêmes attributs que les
 * dataclasses d'`ingest.ia_prix` (`ExplicationVue`, `PrixInternetVue`,
 * `AvisIA`) — voir `app/modules/api/schemas.py`.
 */
export type ExplicationAlerte = components["schemas"]["ExplicationAlerteReponse"];
export type PrixInternet = components["schemas"]["PrixInternetReponse"];
export type AvisIA = components["schemas"]["AvisIAReponse"];

/** Clé de requête TanStack Query propre à chaque anomalie (même principe
 * que `cleAnomalies`) : un avis par anomalie, jamais partagé entre deux
 * problèmes différents. */
export function cleAvisIA(anomalieId: string): readonly [string, string, string] {
  return ["ia", "anomalie", anomalieId] as const;
}

/** `GET /api/ia/anomalies/{anomalie_id}` (admin) : 404 si l'anomalie est
 * inconnue ou masquée (`ingest.ia_prix.avis_ia_anomalie`) — `ProblemeDetail
 * .tsx` n'appelle cette route que pour une anomalie déjà chargée par `GET
 * /api/anomalies`, ce 404 ne devrait donc jamais se produire en usage
 * normal ; `AvisIA.tsx` le traite comme n'importe quelle erreur (rien à
 * l'écran, l'avis est un bonus, jamais un blocage). */
export function lireAvisIA(anomalieId: string): Promise<AvisIA> {
  return appelerApi<AvisIA>("/api/ia/anomalies/{anomalie_id}", {
    url: `/api/ia/anomalies/${anomalieId}`,
  });
}
