/**
 * Petit helper `fetch` typé (L2-D15 : pas d'`openapi-fetch`, pas d'axios).
 *
 * - `chemin` est restreint aux routes connues du schéma OpenAPI exporté
 *   (`keyof paths`, généré par `openapi-typescript` dans `./schema.d.ts` —
 *   régénéré par `npm run api:schema && npm run api:types`).
 * - `credentials: "same-origin"` : l'authentification passe uniquement par
 *   le cookie de session posé par `/api/auth/login` (jamais de jeton stocké
 *   côté navigateur, ni `localStorage` ni `sessionStorage`).
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

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ErreurApi";
    this.status = status;
    this.detail = detail;
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
}

async function extraireDetail(reponse: Response): Promise<string> {
  try {
    const donnees: unknown = await reponse.clone().json();
    if (
      donnees !== null &&
      typeof donnees === "object" &&
      "detail" in donnees &&
      typeof (donnees as { detail: unknown }).detail === "string"
    ) {
      return (donnees as { detail: string }).detail;
    }
  } catch {
    // Corps non JSON (ou vide) : on garde le texte de statut par défaut.
  }
  return reponse.statusText || `erreur ${reponse.status}`;
}

export async function appelerApi<TReponse = undefined>(
  chemin: CheminApi,
  options: OptionsRequete = {},
): Promise<TReponse> {
  const reponse = await fetch(chemin, {
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
    throw new ErreurApi(reponse.status, await extraireDetail(reponse));
  }
  if (reponse.status === 204) {
    return undefined as TReponse;
  }
  return (await reponse.json()) as TReponse;
}
