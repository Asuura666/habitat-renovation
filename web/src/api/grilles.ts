/**
 * Grille de prix d'un fournisseur (phase 3, tâche P5, spec
 * `docs/superpowers/specs/2026-09-27-prix-design.md` §9-§10) : lecture des
 * prix en vigueur (recherche, pagination serveur), saisie/retrait manuels,
 * aperçu puis import d'un fichier Excel, téléchargement du modèle. Aucune
 * règle métier ici (mise en forme des dates/montants laissée à l'écran,
 * `lib/formats.ts`) -- ce module ne fait qu'appeler l'API et typer ses
 * réponses (même principe que `api/documents.ts`, `api/factures.ts`).
 */

import { appelerApi } from "./client";
import type { components } from "./schema";

export type GrilleFournisseur = components["schemas"]["GrilleFournisseurReponse"];
export type ProduitGrille = components["schemas"]["ProduitGrilleReponse"];
export type ApercuImport = components["schemas"]["ApercuImportReponse"];
export type ImportEffectue = components["schemas"]["ImportEffectueReponse"];
export type LigneComparee = components["schemas"]["LigneCompareeGrilleReponse"];
export type ProduitAbsent = components["schemas"]["ProduitAbsentReponse"];
export type ContestationPrix = components["schemas"]["ContestationReponse"];
export type EntreeHistorique = components["schemas"]["EntreeHistoriqueReponse"];
export type ErreurImportLigne = components["schemas"]["ErreurImportReponse"];

export function cleGrilleFournisseur(
  fournisseurId: string,
  recherche: string,
  page: number,
): readonly [string, string, string, string, number] {
  return ["grille", fournisseurId, "produits", recherche, page] as const;
}

/** `GET /api/grilles/fournisseurs/{id}` (admin, spec §9) : prix en vigueur
 * aujourd'hui, recherche par référence ou désignation côté serveur, 50 par
 * page. */
export function obtenirGrilleFournisseur(
  fournisseurId: string,
  options: { recherche?: string; page?: number } = {},
): Promise<GrilleFournisseur> {
  const parametres = new URLSearchParams();
  if (options.recherche) {
    parametres.set("recherche", options.recherche);
  }
  if (options.page && options.page > 1) {
    parametres.set("page", String(options.page));
  }
  const requete = parametres.toString();
  return appelerApi<GrilleFournisseur>("/api/grilles/fournisseurs/{fournisseur_id}", {
    url: `/api/grilles/fournisseurs/${fournisseurId}${requete ? `?${requete}` : ""}`,
  });
}

/** Clé de requête des contestations : sous `["grille", fournisseurId]`, donc
 * rafraîchie par les invalidations déjà faites après un import ou un retrait. */
export function cleContestations(
  fournisseurId: string,
): readonly [string, string, string] {
  return ["grille", fournisseurId, "contestations"] as const;
}

/** `GET /api/grilles/fournisseurs/{id}/contestations` (admin) : les prix
 * contestés depuis la page Prix, plus récents d'abord. */
export function listerContestations(fournisseurId: string): Promise<ContestationPrix[]> {
  return appelerApi<ContestationPrix[]>("/api/grilles/fournisseurs/{fournisseur_id}/contestations", {
    url: `/api/grilles/fournisseurs/${fournisseurId}/contestations`,
  });
}

/** Clé de requête de l'historique d'un produit, sous `["grille", fournisseurId]`
 * comme les contestations (rafraîchie par les mêmes invalidations). */
export function cleHistoriqueProduit(
  fournisseurId: string,
  cleProduit: string,
): readonly [string, string, string, string] {
  return ["grille", fournisseurId, "historique", cleProduit] as const;
}

/** `GET /api/grilles/fournisseurs/{id}/produits/{cle}/historique-complet`
 * (admin, lot 2 du 31/10/2026) : versions de la grille, prix vus sur les
 * bons et factures du fournisseur et prix observés importés, du plus récent
 * au plus ancien, 100 lignes au plus. */
export function obtenirHistoriqueProduit(
  fournisseurId: string,
  cleProduit: string,
): Promise<EntreeHistorique[]> {
  return appelerApi<EntreeHistorique[]>(
    "/api/grilles/fournisseurs/{fournisseur_id}/produits/{cle_produit}/historique-complet",
    {
      url: `/api/grilles/fournisseurs/${fournisseurId}/produits/${encodeURIComponent(cleProduit)}/historique-complet`,
    },
  );
}

/** Corps de `POST /api/grilles/fournisseurs/{id}/prix` (saisie manuelle,
 * « Modifier » ou « Ajouter un produit », spec §9). `date_effet` absente
 * -> aujourd'hui, résolu côté serveur. */
export interface SaisiePrixGrille {
  reference?: string | null;
  designation: string;
  unite?: string | null;
  prix_ht: string;
  remise_pct?: string | null;
  date_effet?: string | null;
  marque?: string | null;
  famille?: string | null;
}

export function enregistrerPrixGrille(
  fournisseurId: string,
  saisie: SaisiePrixGrille,
): Promise<ProduitGrille> {
  return appelerApi<ProduitGrille>("/api/grilles/fournisseurs/{fournisseur_id}/prix", {
    url: `/api/grilles/fournisseurs/${fournisseurId}/prix`,
    method: "POST",
    json: saisie,
  });
}

/** `POST /api/grilles/fournisseurs/{id}/retrait` -- retire un produit de la
 * grille à une date d'effet, avec confirmation côté écran. */
export function retirerProduitGrille(
  fournisseurId: string,
  cleProduit: string,
  dateEffet: string,
): Promise<{ detail: string }> {
  return appelerApi<{ detail: string }>("/api/grilles/fournisseurs/{fournisseur_id}/retrait", {
    url: `/api/grilles/fournisseurs/${fournisseurId}/retrait`,
    method: "POST",
    json: { cle_produit: cleProduit, date_effet: dateEffet },
  });
}

function corpsFichierGrille(fichier: File, dateEffet: string): FormData {
  const corps = new FormData();
  corps.append("fichier", fichier);
  corps.append("date_effet", dateEffet);
  return corps;
}

/** `POST /api/grilles/fournisseurs/{id}/import/apercu` -- aucune écriture,
 * seulement les compteurs et le détail des lignes comparées (spec §9). */
export function apercevoirImportGrille(
  fournisseurId: string,
  fichier: File,
  dateEffet: string,
): Promise<ApercuImport> {
  return appelerApi<ApercuImport>("/api/grilles/fournisseurs/{fournisseur_id}/import/apercu", {
    url: `/api/grilles/fournisseurs/${fournisseurId}/import/apercu`,
    method: "POST",
    body: corpsFichierGrille(fichier, dateEffet),
  });
}

/** `POST /api/grilles/fournisseurs/{id}/import` -- confirme l'import (mêmes
 * fichier et date d'effet que l'aperçu déjà validé à l'écran). */
export function importerGrille(
  fournisseurId: string,
  fichier: File,
  dateEffet: string,
): Promise<ImportEffectue> {
  return appelerApi<ImportEffectue>("/api/grilles/fournisseurs/{fournisseur_id}/import", {
    url: `/api/grilles/fournisseurs/${fournisseurId}/import`,
    method: "POST",
    body: corpsFichierGrille(fichier, dateEffet),
  });
}

/** URL du modèle Excel à télécharger (`<a href download>`, même principe
 * que `urlTelechargement` dans `api/documents.ts` -- jamais via `fetch`,
 * le navigateur gère lui-même le téléchargement et le cookie de session). */
export function urlModeleGrille(): string {
  return "/api/grilles/modele";
}
