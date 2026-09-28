/**
 * Page « Prix à vérifier » (phase 3, tâche P9, spec
 * `docs/superpowers/specs/2026-09-27-prix-design.md` §8, §10) : liste des
 * alertes de prix ouvertes, regroupées par produit (`GET /api/prix/alertes`),
 * et ses quatre actions (`valider`/`contester`/`ignorer`/`recontrole`).
 * Aucune règle métier ici -- même principe que `api/grilles.ts`, ce module
 * ne fait qu'appeler l'API et typer ses réponses.
 */

import { appelerApi } from "./client";
import type { components } from "./schema";

export type AlerteProduit = components["schemas"]["AlerteProduitReponse"];
export type ValidationPrix = components["schemas"]["ValidationPrixReponse"];
export type FermetureAlertes = components["schemas"]["FermetureAlertesReponse"];
export type RecontrolePrix = components["schemas"]["RecontrolePrixReponse"];

export type PeriodeAlertesPrix = "jour" | "tout";

export const CLE_ALERTES_PRIX = ["prix", "alertes"] as const;

/** Clé de requête TanStack Query, filtres inclus (même principe que
 * `cleGrilleFournisseur`, `api/grilles.ts`). */
export function cleAlertesPrix(
  periode: PeriodeAlertesPrix,
  fournisseurId: string,
): readonly [string, string, PeriodeAlertesPrix, string] {
  return [...CLE_ALERTES_PRIX, periode, fournisseurId] as const;
}

/** `GET /api/prix/alertes` (admin, spec §8.1) : alertes ouvertes et non
 * masquées, regroupées par produit -- `periode="jour"` limite aux alertes
 * créées aujourd'hui (heure de Paris), `"tout"` (défaut serveur) ne filtre
 * pas. */
export function listerAlertesPrix(
  options: { periode?: PeriodeAlertesPrix; fournisseurId?: string } = {},
): Promise<AlerteProduit[]> {
  const parametres = new URLSearchParams();
  if (options.periode) {
    parametres.set("periode", options.periode);
  }
  if (options.fournisseurId) {
    parametres.set("fournisseur_id", options.fournisseurId);
  }
  const requete = parametres.toString();
  return appelerApi<AlerteProduit[]>("/api/prix/alertes", {
    url: `/api/prix/alertes${requete ? `?${requete}` : ""}`,
  });
}

/** « Valider ce prix » (spec §8.2) : nouvelle ligne de grille au prix du
 * bon de `ligneId`, alertes du groupe au même prix réglées. `anomalieIds`
 * porte toutes les alertes ouvertes du groupe (le serveur revérifie que
 * toutes appartiennent au même groupe, sinon 409). */
export function validerPrix(anomalieIds: readonly string[], ligneId: string): Promise<ValidationPrix> {
  return appelerApi<ValidationPrix>("/api/prix/valider", {
    method: "POST",
    json: { anomalie_ids: anomalieIds, ligne_id: ligneId },
  });
}

/** « Contester » (spec §8.2) : commentaire obligatoire (1 à 500
 * caractères), grille inchangée. */
export function contesterPrix(anomalieIds: readonly string[], commentaire: string): Promise<FermetureAlertes> {
  return appelerApi<FermetureAlertes>("/api/prix/contester", {
    method: "POST",
    json: { anomalie_ids: anomalieIds, commentaire },
  });
}

/** « Ignorer » (spec §8.2) : commentaire facultatif -- une chaîne vide ou
 * absente retombe sur le commentaire par défaut côté serveur. */
export function ignorerPrix(anomalieIds: readonly string[], commentaire: string): Promise<FermetureAlertes> {
  return appelerApi<FermetureAlertes>("/api/prix/ignorer", {
    method: "POST",
    json: { anomalie_ids: anomalieIds, commentaire: commentaire.trim() === "" ? undefined : commentaire.trim() },
  });
}

/** Bouton « Recontrôler les bons » (spec §8.2, §6.2) -- recontrôle tous les
 * bons non archivés datés depuis le 1ᵉʳ jour du mois précédent. */
export function recontrolerPrix(): Promise<RecontrolePrix> {
  return appelerApi<RecontrolePrix>("/api/prix/recontrole", { method: "POST" });
}
