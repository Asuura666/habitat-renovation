/**
 * Petit helper `fetch` typé (L2-D15 : pas d'`openapi-fetch`, pas d'axios).
 *
 * - `chemin` est restreint aux routes connues du schéma OpenAPI exporté
 *   (`keyof paths`, généré par `openapi-typescript` dans `./schema.d.ts` —
 *   régénéré par `npm run api:schema && npm run api:types`). Pour une route
 *   à paramètre de chemin (ex. `/api/factures/{facture_id}`), `chemin` reste
 *   le modèle littéral garanti par le schéma (une faute de frappe ou une
 *   route supprimée est détectée à la compilation) ; `options.url` porte
 *   l'URL réellement appelée, construite par l'appelant avec l'identifiant
 *   réel (ex. `` `/api/factures/${id}` ``) — voir `api/factures.ts`.
 * - `credentials: "same-origin"` : l'authentification passe uniquement par
 *   le cookie de session posé par `/api/auth/login` (jamais de jeton stocké
 *   côté navigateur, ni `localStorage` ni `sessionStorage`).
 * - `body` accepte un `FormData` (dépôt de facture, `multipart/form-data`)
 *   sans configuration supplémentaire : le navigateur pose lui-même
 *   l'en-tête `Content-Type` avec sa frontière (`boundary`) tant qu'aucun
 *   `Content-Type` n'est fourni dans `headers`.
 * - Un 401 lève `NonAuthentifie` **et** déclenche le gestionnaire de
 *   redirection enregistré par `EcouteAuthentification` (via le routeur,
 *   jamais `window.location`), pour que toute perte de session en cours
 *   d'usage — pas seulement au chargement d'une route protégée — ramène
 *   l'utilisateur à `/connexion`.
 */

import type { paths } from "./schema";

export type CheminApi = keyof paths;

export class ErreurApi extends Error {
  readonly status: number;
  readonly detail: string;
  /** Corps JSON complet de la réponse d'erreur, quand il a pu être décodé
   * (`undefined` sinon). Utile aux erreurs qui portent plus que `detail`
   * (ex. `original_id` sur le 409 de `POST /api/factures`, voir
   * `api/factures.ts::FactureEnDoubleErreur`) — jamais lu ici, uniquement
   * transporté. */
  readonly corps: unknown;

  constructor(status: number, detail: string, corps?: unknown) {
    super(detail);
    this.name = "ErreurApi";
    this.status = status;
    this.detail = detail;
    this.corps = corps;
  }
}

export class NonAuthentifie extends ErreurApi {
  constructor() {
    super(401, "authentification requise");
    this.name = "NonAuthentifie";
  }
}

type GestionnaireNonAuthentifie = () => void;

let gestionnaireNonAuthentifie: GestionnaireNonAuthentifie | null = null;

/** Enregistré une fois par `EcouteAuthentification`, dans le contexte du
 * routeur (`useNavigate`). Un composant qui se démonte peut réinitialiser à
 * `null` pour ne jamais appeler un `navigate` périmé. */
export function definirGestionnaireNonAuthentifie(
  gestionnaire: GestionnaireNonAuthentifie | null,
): void {
  gestionnaireNonAuthentifie = gestionnaire;
}

interface OptionsRequete {
  method?: "GET" | "POST" | "DELETE";
  body?: BodyInit;
  headers?: Record<string, string>;
  /** URL réellement appelée, quand elle diffère de `chemin` (route à
   * paramètre de chemin — voir le commentaire de tête de fichier). */
  url?: string;
}

async function lireCorpsErreur(reponse: Response): Promise<{ detail: string; corps: unknown }> {
  try {
    const donnees: unknown = await reponse.clone().json();
    if (donnees !== null && typeof donnees === "object") {
      const detail =
        "detail" in donnees && typeof (donnees as { detail: unknown }).detail === "string"
          ? (donnees as { detail: string }).detail
          : reponse.statusText || `erreur ${reponse.status}`;
      return { detail, corps: donnees };
    }
  } catch {
    // Corps non JSON (ou vide) : on garde le texte de statut par défaut.
  }
  return { detail: reponse.statusText || `erreur ${reponse.status}`, corps: undefined };
}

export async function appelerApi<TReponse = undefined>(
  chemin: CheminApi,
  options: OptionsRequete = {},
): Promise<TReponse> {
  const reponse = await fetch(options.url ?? chemin, {
    method: options.method ?? "GET",
    body: options.body,
    headers: options.headers,
    credentials: "same-origin",
  });

  if (reponse.status === 401) {
    gestionnaireNonAuthentifie?.();
    throw new NonAuthentifie();
  }
  if (!reponse.ok) {
    const { detail, corps } = await lireCorpsErreur(reponse);
    throw new ErreurApi(reponse.status, detail, corps);
  }
  if (reponse.status === 204) {
    return undefined as TReponse;
  }
  return (await reponse.json()) as TReponse;
}
