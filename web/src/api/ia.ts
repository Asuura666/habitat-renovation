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
 * rangées affichées (toutes les alertes de prix). Mêmes attributs que la dataclasse
 * `ingest.ia_prix.PrixInternetLot`, à ceci près que les clés de `prix` sont
 * des identifiants texte (voir `app/modules/api/schemas.py`).
 */
export type PrixInternetLot = components["schemas"]["PrixInternetLotReponse"];

/** Clé de requête TanStack Query du lot de prix internet -- un lot par
 * ensemble d'identifiants d'anomalies (même principe que `cleAlertesPrix`,
 * `api/prix.ts`) : un nouveau filtre sur la page Prix change les rangées
 * affichées, donc l'ensemble d'identifiants interrogé. */
export function clePrixInternet(anomalieIds: readonly string[]): readonly [string, string, string] {
  return ["ia", "prix-internet", anomalieIds.join(",")] as const;
}

export type RecherchePrix = components["schemas"]["RechercheReponse"];
export type RechercheLancee = components["schemas"]["RechercheLanceeReponse"];

/** `POST /api/ia/prix-internet/recherches` (admin) : lance la recherche du
 * produit de l'alerte en tâche de fond ; le résultat arrive par la lecture
 * groupée. 409 : IA éteinte ou plafond du jour atteint. */
export function lancerRecherchePrix(anomalieId: string): Promise<RechercheLancee> {
  return appelerApi<RechercheLancee>("/api/ia/prix-internet/recherches", {
    method: "POST",
    json: { anomalie_id: anomalieId },
  });
}

/** `GET /api/ia/prix-internet?anomalie_id=…` (admin, paramètre répété) : le
 * prix internet des anomalies demandées, au plus `MAX_ANOMALIES_PRIX_
 * INTERNET` (200, `ingest/ia_prix.py`, 422 au-delà) -- `Prix.tsx` ne demande
 * qu'un identifiant par rangée, très en-deçà en pratique. Les
 * identifiants qui ne désignent pas une alerte de prix ouverte et non masquée
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

/**
 * Laboratoire IA (tâche LABO, admin) : teste les trois usages de l'IA avant
 * de s'y fier, sans jamais rien enregistrer (`ingest.ia_labo`). Mêmes
 * attributs que les dataclasses d'`ingest.ia_labo` (`TraceEssai`,
 * `OutilTrace`, `LigneAppelIA`) et `ingest.opencode.DiagnosticIA` — voir
 * `app/modules/api/schemas.py`.
 */
export type EtatLabo = components["schemas"]["EtatLaboReponse"];
export type ControleEssai = components["schemas"]["ControleReponse"];
export type OutilEssai = components["schemas"]["OutilTraceReponse"];
export type TraceEssai = components["schemas"]["TraceEssaiReponse"];
export type TraceEssaiResume = components["schemas"]["TraceEssaiResumeReponse"];
export type AppelIALigne = components["schemas"]["AppelIALigneReponse"];
export type EssaiLance = components["schemas"]["EssaiLanceReponse"];

/** `GET /api/ia/labo/etat` (admin) : diagnostic d'OpenCode et appels du
 * jour/plafond — rafraîchi toutes les 30 s (`refetchInterval`), même rythme
 * que le reste de l'écran hors essai en cours. */
export const CLE_ETAT_LABO = ["ia", "labo", "etat"] as const;
export function lireEtatLabo(): Promise<EtatLabo> {
  return appelerApi<EtatLabo>("/api/ia/labo/etat");
}

/** `POST /api/ia/labo/essais/prix` (admin) : lance un essai de recherche de
 * prix internet, `202` + l'identifiant de l'essai (`ingest.ia_labo
 * .lancer_essai_prix`) — rien n'est enregistré, l'appel compte dans le
 * plafond du jour. */
export function lancerEssaiPrixLabo(corps: {
  fournisseur?: string;
  designation: string;
  code?: string;
  unite?: string;
}): Promise<EssaiLance> {
  return appelerApi<EssaiLance>("/api/ia/labo/essais/prix", {
    method: "POST",
    json: corps,
  });
}

/** `POST /api/ia/labo/essais/explication` (admin) : lance un essai
 * d'explication d'une alerte prix — 404 si l'anomalie est inconnue ou hors
 * catégorie « prix » (`ingest.ia_labo.lancer_essai_explication`). */
export function lancerEssaiExplicationLabo(anomalieId: string): Promise<EssaiLance> {
  return appelerApi<EssaiLance>("/api/ia/labo/essais/explication", {
    method: "POST",
    json: { anomalie_id: anomalieId },
  });
}

/** `POST /api/ia/labo/essais/synthese` (admin) : lance un essai de synthèse
 * hebdomadaire des commentaires — 422 si `semaineDebut` n'est pas un lundi
 * (`ingest.ia_labo.lancer_essai_synthese`). */
export function lancerEssaiSyntheseLabo(semaineDebut: string): Promise<EssaiLance> {
  return appelerApi<EssaiLance>("/api/ia/labo/essais/synthese", {
    method: "POST",
    json: { semaine_debut: semaineDebut },
  });
}

/** Clé de requête TanStack Query propre à chaque essai (même principe que
 * `cleAvisIA`) : un déroulé par identifiant, jamais partagé entre deux
 * essais différents. */
export function cleEssaiLabo(essaiId: string): readonly [string, string, string, string] {
  return ["ia", "labo", "essai", essaiId] as const;
}

/** `GET /api/ia/labo/essais/{id}` (admin) : la trace complète d'un essai —
 * 404 si l'essai est inconnu ou a été chassé (au-delà des 20 derniers). À
 * interroger toutes les 2 s tant que l'essai est `en_cours` (`refetchInterval`
 * conditionnel côté appelant, `pages/LaboIA.tsx`). */
export function lireEssaiLabo(essaiId: string): Promise<TraceEssai> {
  return appelerApi<TraceEssai>("/api/ia/labo/essais/{essai_id}", {
    url: `/api/ia/labo/essais/${essaiId}`,
  });
}

/** `GET /api/ia/labo/essais` (admin) : les derniers essais (résumé), les
 * plus récents d'abord. */
export const CLE_DERNIERS_ESSAIS_LABO = ["ia", "labo", "essais"] as const;
export function listerDerniersEssaisLabo(): Promise<TraceEssaiResume[]> {
  return appelerApi<TraceEssaiResume[]>("/api/ia/labo/essais");
}

/** `GET /api/ia/labo/appels` (admin) : les 50 derniers appels à l'IA (essais
 * compris), les plus récents d'abord. */
export const CLE_JOURNAL_APPELS_LABO = ["ia", "labo", "appels"] as const;
export function listerJournalAppelsLabo(): Promise<AppelIALigne[]> {
  return appelerApi<AppelIALigne[]>("/api/ia/labo/appels");
}
