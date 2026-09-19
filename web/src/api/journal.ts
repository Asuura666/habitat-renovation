import { appelerApi } from "./client";
import type { components } from "./schema";

export type EntreeJournal = components["schemas"]["JournalReponse"];

export const CLE_JOURNAL = ["journal"] as const;

/** Filtres de `GET /api/journal` (décision du contrôleur, L5-D10) : mêmes
 * conventions que `FiltresAnomalies` (`api/anomalies.ts`) — `depuis`/
 * `jusquA` sont de simples dates (`"AAAA-MM-JJ"`, valeur brute d'un
 * `<input type="date">`), converties en bornes d'instants Europe/Paris
 * côté serveur (`api/journal.py`), jamais ici. */
export interface FiltresJournal {
  utilisateurId?: string;
  action?: string;
  cibleTable?: string;
  depuis?: string;
  jusquA?: string;
  /** Plafond de pagination (décision du contrôleur, L5-D10) : réglable côté
   * écran (`pages/Journal.tsx`), toujours borné par l'API (1..500,
   * défaut 100). */
  limite?: number;
}

/** Clé de requête TanStack Query incluant les filtres (même principe que
 * `cleAnomalies`) : un jeu de filtres différent est un cache distinct. */
export function cleJournal(filtres: FiltresJournal): readonly [string, FiltresJournal] {
  return ["journal", filtres] as const;
}

function construireRequete(filtres: FiltresJournal): string {
  const params = new URLSearchParams();
  if (filtres.utilisateurId) {
    params.set("utilisateur_id", filtres.utilisateurId);
  }
  if (filtres.action) {
    params.set("action", filtres.action);
  }
  if (filtres.cibleTable) {
    params.set("cible_table", filtres.cibleTable);
  }
  if (filtres.depuis) {
    params.set("depuis", filtres.depuis);
  }
  if (filtres.jusquA) {
    params.set("jusqu_a", filtres.jusquA);
  }
  if (filtres.limite) {
    params.set("limite", String(filtres.limite));
  }
  const requete = params.toString();
  return requete === "" ? "/api/journal" : `/api/journal?${requete}`;
}

/** `GET /api/journal` (admin, L5-T9) : filtres combinables, plafond de
 * pagination appliqué côté serveur (défaut 100 entrées). */
export function listerJournal(filtres: FiltresJournal = {}): Promise<EntreeJournal[]> {
  return appelerApi<EntreeJournal[]>("/api/journal", { url: construireRequete(filtres) });
}
