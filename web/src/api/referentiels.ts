import { appelerApi, ErreurApi } from "./client";
import type { components } from "./schema";

export type Chantier = components["schemas"]["ChantierReponse"];
export type Fournisseur = components["schemas"]["FournisseurReponse"];
export type ValidationAliasReponse = components["schemas"]["ValidationAliasReponse"];
export type DepotAgent = components["schemas"]["DepotAgentReponse"];
export type ChantierSilencieux = components["schemas"]["ChantierSilencieuxReponse"];
export type ChantierDuMois = components["schemas"]["ChantierDuMoisReponse"];
export type ResultatFusion = components["schemas"]["ResultatFusionReponse"];

export const CLE_CHANTIERS = ["chantiers"] as const;
export const CLE_FOURNISSEURS = ["fournisseurs"] as const;
export const CLE_DEPOTS_PAR_AGENT = ["referentiels", "depots-par-agent"] as const;
export const CLE_CHANTIERS_SILENCIEUX = ["referentiels", "chantiers-silencieux"] as const;
export const CLE_AGENCES = ["referentiels", "agences"] as const;

/** Clé de cache des chantiers du mois : sous `CLE_CHANTIERS`, donc invalidée
 * avec elle quand un chantier est créé. `mois` au format `AAAA-MM-01`. */
export function cleChantiersDuMois(mois: string, agence: string | undefined): readonly string[] {
  return ["chantiers", "du-mois", mois, agence ?? ""] as const;
}

/** `GET /api/chantiers/du-mois` : chantiers qui ont un bon daté du mois ou une
 * facture du mois (la liste est décidée par le serveur, jamais recalculée
 * ici). */
export function listerChantiersDuMois(mois: string, agence: string | undefined): Promise<ChantierDuMois[]> {
  const params = new URLSearchParams({ mois });
  if (agence !== undefined) {
    params.set("agence", agence);
  }
  return appelerApi<ChantierDuMois[]>("/api/chantiers/du-mois", {
    url: `/api/chantiers/du-mois?${params.toString()}`,
  });
}

export function listerChantiers(): Promise<Chantier[]> {
  return appelerApi<Chantier[]>("/api/chantiers");
}

export function cleChantier(chantierId: string): readonly [string, string] {
  return ["chantier", chantierId] as const;
}

/** `GET /api/chantiers/{id}` (Task 7, avenant du 27/09/2026, spec §2.7) :
 * seule route qui renvoie encore un chantier fusionné (`fusionne_dans_id`/
 * `fusionne_dans_nom` non `null`), pour le bandeau de sa fiche -- `GET
 * /api/chantiers` (`listerChantiers`) les exclut depuis Task 6. */
export function obtenirChantier(chantierId: string): Promise<Chantier> {
  return appelerApi<Chantier>("/api/chantiers/{chantier_id}", {
    url: `/api/chantiers/${chantierId}`,
  });
}

/** `POST /api/chantiers/{id}/fusionner` (Task 7, avenant du 27/09/2026,
 * spec §2.7) : « Fusionner avec… » de la fiche chantier -- `chantierId`
 * (source) est fusionné dans `cibleId`. */
export function fusionnerChantiers(
  chantierId: string,
  cibleId: string,
): Promise<ResultatFusion> {
  return appelerApi<ResultatFusion>("/api/chantiers/{chantier_id}/fusionner", {
    url: `/api/chantiers/${chantierId}/fusionner`,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cible_id: cibleId }),
  });
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

/** `POST /api/chantiers` : `agence`/`client` vides -> `null` (décision du
 * contrôleur, même règle que le service qui les débarrasse des espaces de
 * bord). `client` : ajout hors CDC du 23/09/2026 (`docs/dette.md`, Task 1
 * de la refonte du front). */
export async function creerChantier(
  nomCanonique: string,
  agence: string | null,
  client: string | null = null,
): Promise<Chantier> {
  try {
    return await appelerApi<Chantier>("/api/chantiers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nom_canonique: nomCanonique, agence, client }),
    });
  } catch (erreur) {
    if (erreur instanceof ErreurApi && erreur.status === 409 && estCorpsDoublon(erreur.corps)) {
      throw new ChantierEnDoubleErreur(erreur.detail, erreur.corps.original_id);
    }
    throw erreur;
  }
}

export interface ModificationChantier {
  nomCanonique: string;
  agence: string | null;
  client: string | null;
  actif: boolean;
}

/** `PUT /api/chantiers/{id}` (Task 1 de la refonte du front, `docs/dette
 * .md`) : remplace nom, agence, client et l'état actif. Même traitement du
 * 409 (doublon de nom) que `creerChantier` ; le 404 (chantier disparu entre
 * l'ouverture de la fiche et l'enregistrement) est laissé tel quel
 * (`ErreurApi`, message du serveur affiché par l'appelant). */
export async function modifierChantier(
  chantierId: string,
  modification: ModificationChantier,
): Promise<Chantier> {
  try {
    return await appelerApi<Chantier>("/api/chantiers/{chantier_id}", {
      url: `/api/chantiers/${chantierId}`,
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        nom_canonique: modification.nomCanonique,
        agence: modification.agence,
        client: modification.client,
        actif: modification.actif,
      }),
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

// ---------------------------------------------------------------------------
// Vue des référentiels (L5-T7, consommée par l'écran « Chantiers &
// fournisseurs », L5-T8) : qui a déposé quoi, quels chantiers ne remontent
// plus rien — voir `ingest/referentiels_vue.py` pour toute la logique.
// ---------------------------------------------------------------------------

/** `GET /api/referentiels/depots-par-agent` (admin) : nombre de documents
 * déposés sur les 30 derniers jours calendaires (Europe/Paris), pour tout
 * agent (y compris à 0) et tout compte ayant effectivement déposé sur la
 * fenêtre (Ruling L5-R7 : le rôle compose la liste de référence, jamais un
 * filtre sur les dépôts). Aucun paramètre `jours` transmis ici (décision du
 * contrôleur L5-T8 : cet écran affiche la fenêtre par défaut de l'API, pas
 * de filtre — la fiche ne demande que « sur 30 jours »). */
export function obtenirDepotsParAgent(): Promise<DepotAgent[]> {
  return appelerApi<DepotAgent[]>("/api/referentiels/depots-par-agent");
}

/** `GET /api/referentiels/chantiers-silencieux` (admin) : chantiers actifs
 * et non fermés dont le dernier dépôt (`document.chantier_id`) dépasse le
 * seuil de silence — lu par le service depuis la table `parametre`, jamais
 * reçu en paramètre de requête (voir `ingest/referentiels_vue.py`). */
export function obtenirChantiersSansDepot(): Promise<ChantierSilencieux[]> {
  return appelerApi<ChantierSilencieux[]>("/api/referentiels/chantiers-silencieux");
}

export function obtenirAgences(): Promise<string[]> {
  return appelerApi<string[]>("/api/referentiels/agences");
}
