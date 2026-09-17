import { appelerApi, ErreurApi } from "./client";
import type { components } from "./schema";

export type Chantier = components["schemas"]["ChantierReponse"];
export type Fournisseur = components["schemas"]["FournisseurReponse"];
export type ValidationAliasReponse = components["schemas"]["ValidationAliasReponse"];

export const CLE_CHANTIERS = ["chantiers"] as const;
export const CLE_FOURNISSEURS = ["fournisseurs"] as const;

export function listerChantiers(): Promise<Chantier[]> {
  return appelerApi<Chantier[]>("/api/chantiers");
}

/** Référentiel fournisseur complet — consommé par le formulaire de
 * correction d'un document (L3-T10, `fournisseur en liste déroulante`,
 * `docs/plan-lot-3.md`) ; exposé dès maintenant car l'endpoint existe déjà
 * (L3-T8b) et partage ce fichier avec les autres référentiels admin. */
export function listerFournisseurs(): Promise<Fournisseur[]> {
  return appelerApi<Fournisseur[]>("/api/fournisseurs");
}

/** Levée par `creerChantier` sur un 409 (nom déjà porté par un chantier
 * existant, `ChantierEnDouble` côté service) : l'API ne renvoie que
 * `original_id`, jamais le nom de l'existant (voir `api/referentiels.py
 * ::creer_chantier_endpoint`) — la page le retrouve dans les chantiers déjà
 * chargés (décision du contrôleur : « message avec le nom du chantier
 * existant si l'API le renvoie, sinon message générique »). */
export class ChantierEnDoubleErreur extends ErreurApi {
  readonly originalId: string;

  constructor(detail: string, originalId: string) {
    super(409, detail);
    this.name = "ChantierEnDoubleErreur";
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

/** `POST /api/chantiers` : `agence` vide -> `null` (décision du
 * contrôleur, même règle que le service qui la débarrasse des espaces de
 * bord). */
export async function creerChantier(
  nomCanonique: string,
  agence: string | null,
): Promise<Chantier> {
  try {
    return await appelerApi<Chantier>("/api/chantiers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nom_canonique: nomCanonique, agence }),
    });
  } catch (erreur) {
    if (erreur instanceof ErreurApi && erreur.status === 409 && estCorpsDoublon(erreur.corps)) {
      throw new ChantierEnDoubleErreur(erreur.detail, erreur.corps.original_id);
    }
    throw erreur;
  }
}

/** `POST /api/alias-chantier/{id}/validation` : rattache un alias en
 * attente à un chantier existant (`chemin` reste le modèle littéral du
 * schéma, `url` porte l'identifiant réel — voir `api/client.ts`). */
export function validerAlias(
  aliasId: string,
  chantierId: string,
): Promise<ValidationAliasReponse> {
  return appelerApi<ValidationAliasReponse>("/api/alias-chantier/{alias_id}/validation", {
    url: `/api/alias-chantier/${aliasId}/validation`,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chantier_id: chantierId }),
  });
}

export interface ValidationArticleParams {
  uniteCdt: string | null;
  uniteFact: string | null;
  /** Chaîne décimale (virgule déjà remplacée par un point par l'appelant,
   * voir `pages/ATraiter.tsx`) ou `null` (ratio non modifié). */
  ratio: string | null;
}

/** `POST /api/articles/{id}/validation` : fige unités et ratio (204, aucun
 * corps de réponse). */
export function validerArticle(
  articleId: string,
  params: ValidationArticleParams,
): Promise<void> {
  return appelerApi<void>("/api/articles/{article_id}/validation", {
    url: `/api/articles/${articleId}/validation`,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      unite_cdt: params.uniteCdt,
      unite_fact: params.uniteFact,
      ratio: params.ratio,
    }),
  });
}
