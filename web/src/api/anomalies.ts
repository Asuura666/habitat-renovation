import { appelerApi } from "./client";
import type { components } from "./schema";

export type Anomalie = components["schemas"]["AnomalieReponse"];
export type StatutAnomalie = "ouverte" | "traitee" | "ignoree" | "toutes";
export type GraviteAnomalie = "haute" | "moyenne" | "basse";

export const CLE_ANOMALIES = ["anomalies"] as const;

/** Filtres de `GET /api/anomalies` (décision du contrôleur, L4-T10, revue
 * par le Ruling R21) : `depuis`/`jusquA` sont de simples dates
 * (`"AAAA-MM-JJ"`, valeur brute d'un `<input type="date">`) — c'est
 * `construireRequete` ci-dessous qui les transmet telles quelles à l'API,
 * sans y ajouter d'heure. La conversion en bornes d'instants (début/fin de
 * journée en Europe/Paris) se fait côté serveur (`api/anomalies.py`) :
 * fabriquer ici un horodatage naïf (`"...T00:00:00"`) aurait été lu comme
 * tel par Pydantic, avec un décalage silencieux face à une session Postgres
 * en UTC alors que tout l'affichage est en Europe/Paris. */
export interface FiltresAnomalies {
  regle?: string;
  gravite?: GraviteAnomalie;
  statut?: StatutAnomalie;
  chantierId?: string;
  fournisseurId?: string;
  depuis?: string;
  jusquA?: string;
}

/** Clé de requête TanStack Query incluant les filtres (même principe que
 * `cleDocument`/`cleFacture`) : un jeu de filtres différent est un cache
 * distinct. */
export function cleAnomalies(filtres: FiltresAnomalies): readonly [string, FiltresAnomalies] {
  return ["anomalies", filtres] as const;
}

function construireRequete(filtres: FiltresAnomalies): string {
  const params = new URLSearchParams();
  if (filtres.regle) {
    params.set("regle", filtres.regle);
  }
  if (filtres.gravite) {
    params.set("gravite", filtres.gravite);
  }
  if (filtres.statut) {
    params.set("statut", filtres.statut);
  }
  if (filtres.chantierId) {
    params.set("chantier_id", filtres.chantierId);
  }
  if (filtres.fournisseurId) {
    params.set("fournisseur_id", filtres.fournisseurId);
  }
  if (filtres.depuis) {
    params.set("depuis", `${filtres.depuis}T00:00:00`);
  }
  if (filtres.jusquA) {
    params.set("jusqu_a", `${filtres.jusquA}T23:59:59`);
  }
  const requete = params.toString();
  return requete === "" ? "/api/anomalies" : `/api/anomalies?${requete}`;
}

/** `GET /api/anomalies` (admin, L4-T9/T10) : filtres combinables, défaut
 * `statut=ouverte` côté API si `filtres.statut` est absent. */
export function listerAnomalies(filtres: FiltresAnomalies = {}): Promise<Anomalie[]> {
  return appelerApi<Anomalie[]>("/api/anomalies", { url: construireRequete(filtres) });
}

export interface TraitementAnomalie {
  statut: "traitee" | "ignoree";
  commentaire: string;
}

/** `POST /api/anomalies/{id}/traitement` (L4-D15) : commentaire obligatoire
 * côté API (1 à 500 caractères, 422 sinon), transition refusée avec 409 si
 * l'anomalie n'est plus `ouverte` — messages traduits par `pages/Anomalies
 * .tsx`. */
export function traiterAnomalie(
  id: string,
  traitement: TraitementAnomalie,
): Promise<Anomalie> {
  return appelerApi<Anomalie>("/api/anomalies/{anomalie_id}/traitement", {
    url: `/api/anomalies/${id}/traitement`,
    method: "POST",
    json: traitement,
  });
}
