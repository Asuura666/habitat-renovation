import { appelerApi } from "./client";
import type { components } from "./schema";

export type Compte = components["schemas"]["CompteReponse"];
export type CompteCreation = components["schemas"]["CompteCreationRequete"];
export type CompteModification = components["schemas"]["CompteModificationRequete"];

export const CLE_COMPTES = ["comptes"] as const;

/** `GET /api/comptes` (Task 10, admin uniquement) : tri déjà fait côté
 * serveur (actifs d'abord, puis nom, puis e-mail) — jamais retrié ici. */
export function listerComptes(): Promise<Compte[]> {
  return appelerApi<Compte[]>("/api/comptes");
}

export function creerCompte(donnees: CompteCreation): Promise<Compte> {
  return appelerApi<Compte>("/api/comptes", {
    method: "POST",
    json: donnees,
  });
}

export function modifierCompte(compteId: string, donnees: CompteModification): Promise<Compte> {
  return appelerApi<Compte>("/api/comptes/{compte_id}", {
    url: `/api/comptes/${encodeURIComponent(compteId)}`,
    method: "PUT",
    json: donnees,
  });
}

/** `PUT /api/comptes/{id}/mot-de-passe` (204) : coupe les sessions ouvertes
 * du compte visé côté serveur — rien à faire de plus ici, aucun mot de
 * passe n'est jamais renvoyé ni réaffiché. */
export function changerMotDePasse(compteId: string, motDePasse: string): Promise<void> {
  return appelerApi<void>("/api/comptes/{compte_id}/mot-de-passe", {
    url: `/api/comptes/${encodeURIComponent(compteId)}/mot-de-passe`,
    method: "PUT",
    json: { mot_de_passe: motDePasse },
  });
}

/** « Retirer l'accès » (spec §3, « Supprimer » côté client) : `is_active`
 * passe à faux, sessions coupées côté serveur — le nom du compte reste sur
 * les bons déjà déposés, aucune suppression physique. */
export function retirerAcces(compteId: string): Promise<Compte> {
  return appelerApi<Compte>("/api/comptes/{compte_id}/retirer-acces", {
    url: `/api/comptes/${encodeURIComponent(compteId)}/retirer-acces`,
    method: "POST",
  });
}

export function retablirAcces(compteId: string): Promise<Compte> {
  return appelerApi<Compte>("/api/comptes/{compte_id}/retablir-acces", {
    url: `/api/comptes/${encodeURIComponent(compteId)}/retablir-acces`,
    method: "POST",
  });
}
