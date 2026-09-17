import { appelerApi, ErreurApi } from "./client";
import type { components } from "./schema";

export type FactureResume = components["schemas"]["FactureResumeReponse"];
export type FactureDetail = components["schemas"]["FactureDetailReponse"];
export type BlocFacture = components["schemas"]["BlocFactureReponse"];
export type LigneFacture = components["schemas"]["LigneFactureReponse"];
export type FactureDeposee = components["schemas"]["FactureDeposeeReponse"];

export const CLE_FACTURES = ["factures"] as const;

export function cleFacture(id: string): readonly [string, string] {
  return ["factures", id] as const;
}

export function listerFactures(): Promise<FactureResume[]> {
  return appelerApi<FactureResume[]>("/api/factures");
}

export function obtenirFacture(id: string): Promise<FactureDetail> {
  // `chemin` reste le modèle littéral du schéma (route garantie exister) ;
  // `url` porte l'identifiant réel (voir `api/client.ts`).
  return appelerApi<FactureDetail>("/api/factures/{facture_id}", {
    url: `/api/factures/${id}`,
  });
}

/** Levée par `deposerFacture` sur un 409 (même fournisseur, même numéro déjà
 * déposé, L2-D11). Le routeur renvoie alors `{detail, original_id}` au même
 * niveau (pas le corps d'une `HTTPException` classique) : `originalId` est
 * extrait ici une bonne fois, pour que la page n'ait jamais à lire le JSON
 * brut de `ErreurApi.corps`. */
export class FactureEnDoubleErreur extends ErreurApi {
  readonly originalId: string;

  constructor(detail: string, originalId: string) {
    super(409, detail);
    this.name = "FactureEnDoubleErreur";
    this.originalId = originalId;
  }
}

function estCorpsDoublon(corps: unknown): corps is { original_id: string } {
  return (
    typeof corps === "object" &&
    corps !== null &&
    "original_id" in corps &&
    typeof (corps as { original_id: unknown }).original_id === "string"
  );
}

export async function deposerFacture(fichier: File): Promise<FactureDeposee> {
  const corps = new FormData();
  corps.append("fichier", fichier);
  try {
    return await appelerApi<FactureDeposee>("/api/factures", {
      method: "POST",
      body: corps,
    });
  } catch (erreur) {
    if (erreur instanceof ErreurApi && erreur.status === 409 && estCorpsDoublon(erreur.corps)) {
      throw new FactureEnDoubleErreur(erreur.detail, erreur.corps.original_id);
    }
    throw erreur;
  }
}
