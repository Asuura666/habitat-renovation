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

/**
 * Prix internet de plusieurs anomalies en un coup (T10a/T10b, phase 4 IA,
 * spec §6.4) : la colonne « Internet » de la page « Prix à vérifier »
 * (`pages/Prix.tsx`, lot Prix) lit cette route groupée plutôt que
 * `lireAvisIA` anomalie par anomalie -- une seule requête pour toutes les
 * rangées R22 affichées. Mêmes attributs que la dataclasse
 * `ingest.ia_prix.PrixInternetLot`, à ceci près que les clés de `prix` sont
 * des identifiants texte (voir `app/modules/api/schemas.py`).
 */
export type PrixInternetLot = components["schemas"]["PrixInternetLotReponse"];

/** Clé de requête TanStack Query du lot de prix internet -- un lot par
 * ensemble d'identifiants d'anomalies (même principe que `cleAlertesPrix`,
 * `api/prix.ts`) : un nouveau filtre sur la page Prix change les rangées
 * R22 affichées, donc l'ensemble d'identifiants interrogé. */
export function clePrixInternet(anomalieIds: readonly string[]): readonly [string, string, string] {
  return ["ia", "prix-internet", anomalieIds.join(",")] as const;
}

/** `GET /api/ia/prix-internet?anomalie_id=…` (admin, paramètre répété) : le
 * prix internet des anomalies demandées, au plus `MAX_ANOMALIES_PRIX_
 * INTERNET` (200, `ingest/ia_prix.py`, 422 au-delà) -- `Prix.tsx` ne demande
 * que les rangées R22 (brief T10b), très en-deçà en pratique. Les
 * identifiants qui ne désignent pas une alerte R22 ouverte et non masquée
 * sont simplement absents de `prix`, jamais une erreur. */
export function lirePrixInternet(anomalieIds: string[]): Promise<PrixInternetLot> {
  const parametres = new URLSearchParams();
  for (const id of anomalieIds) {
    parametres.append("anomalie_id", id);
  }
  return appelerApi<PrixInternetLot>("/api/ia/prix-internet", {
    url: `/api/ia/prix-internet?${parametres.toString()}`,
  });
}
