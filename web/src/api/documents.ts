import { appelerApi, ErreurApi } from "./client";
import type { components } from "./schema";

export type DocumentResume = components["schemas"]["DocumentReponse"];
export type DocumentDetail = components["schemas"]["DocumentDetailReponse"];
export type ChampDocument = components["schemas"]["ChampReponse"];
export type ChampsDocument = components["schemas"]["ChampsDocumentReponse"];
export type LigneDocument = components["schemas"]["LigneDocumentReponse"];
export type Motif = components["schemas"]["MotifReponse"];

export const CLE_DOCUMENTS = ["documents"] as const;

/** Admin : tous les BL/enlèvements non archivés. Agent : ceux qu'il a
 * déposés (droit vérifié par `ingest.service.lister_documents`, jamais
 * ici — voir `app/modules/api/documents.py`). */
export function listerDocuments(): Promise<DocumentResume[]> {
  return appelerApi<DocumentResume[]>("/api/documents");
}

export function cleDocument(id: string): readonly [string, string] {
  return ["document", id] as const;
}

/** `GET /api/documents/{id}` (L3-D19, L3-T10) : détail complet d'un BL/
 * enlèvement — admin (tous) ou agent (ses dépôts, en lecture seule,
 * `modifiable` vaut alors toujours `false`, décidé côté service). */
export function lireDocument(id: string): Promise<DocumentDetail> {
  return appelerApi<DocumentDetail>("/api/documents/{document_id}", {
    url: `/api/documents/${id}`,
  });
}

/** Corps de `PATCH /api/documents/{id}` : seuls les champs réellement
 * modifiés dans le formulaire sont présents (décision du contrôleur) — le
 * serveur distingue absent (non envoyé) et `null` (champ vidé). */
export interface CorrectionEntete {
  type?: "bl" | "enlevement" | null;
  fournisseur_id?: string | null;
  numero?: string | null;
  date_doc?: string | null;
  chantier_brut?: string | null;
  numero_commande?: string | null;
  enleve_par?: string | null;
  total_ht?: string | null;
  total_tva?: string | null;
  total_ttc?: string | null;
}

export function corrigerEntete(id: string, correction: CorrectionEntete): Promise<DocumentDetail> {
  return appelerApi<DocumentDetail>("/api/documents/{document_id}", {
    url: `/api/documents/${id}`,
    method: "PATCH",
    json: correction,
  });
}

/** Une ligne de `PUT /api/documents/{id}/lignes` — `id: null` -> insertion,
 * sinon mise à jour de la ligne existante (décision du contrôleur, L3-T10).
 * Le tableau envoyé est la liste complète des lignes dans l'ordre affiché :
 * une ligne absente du tableau est supprimée. */
export interface LigneSaisie {
  id: string | null;
  code_brut: string | null;
  article_brut: string | null;
  qte_livree: string | null;
  qte_totale: string | null;
  unite_brut: string | null;
  pu_ht: string | null;
  montant_ht: string | null;
}

export function corrigerLignes(id: string, lignes: LigneSaisie[]): Promise<DocumentDetail> {
  return appelerApi<DocumentDetail>("/api/documents/{document_id}/lignes", {
    url: `/api/documents/${id}/lignes`,
    method: "PUT",
    json: { lignes },
  });
}

/** Levée par `validerDocument` sur un 409 « validation refusée » (motifs
 * structurels subsistants, L3-D14) : le corps porte `{detail, motifs}`,
 * jamais `original_id` (autre forme de 409 déjà couverte par
 * `ChantierEnDoubleErreur`/`FactureEnDoubleErreur` dans les autres
 * fichiers) — distingué ici du 409 « document non « à vérifier » » (sans
 * `motifs`), affiché comme une erreur générique par la page. */
export class ValidationRefuseeErreur extends ErreurApi {
  readonly motifs: Motif[];

  constructor(detail: string, motifs: Motif[]) {
    super(409, detail);
    this.name = "ValidationRefuseeErreur";
    this.motifs = motifs;
  }
}

function estCorpsMotifs(corps: unknown): corps is { motifs: Motif[] } {
  return (
    typeof corps === "object" &&
    corps !== null &&
    "motifs" in corps &&
    Array.isArray((corps as { motifs: unknown }).motifs)
  );
}

export async function validerDocument(id: string): Promise<DocumentDetail> {
  try {
    return await appelerApi<DocumentDetail>("/api/documents/{document_id}/validation", {
      url: `/api/documents/${id}/validation`,
      method: "POST",
    });
  } catch (erreur) {
    if (erreur instanceof ErreurApi && erreur.status === 409 && estCorpsMotifs(erreur.corps)) {
      throw new ValidationRefuseeErreur(erreur.detail, erreur.corps.motifs);
    }
    throw erreur;
  }
}

/** `POST /api/documents/{id}/archivage` : commentaire obligatoire côté
 * serveur (1 à 500 caractères, blanc refusé) — revérifié par le formulaire
 * avant l'appel, décision du contrôleur. */
export function archiverDocument(id: string, commentaire: string): Promise<DocumentDetail> {
  return appelerApi<DocumentDetail>("/api/documents/{document_id}/archivage", {
    url: `/api/documents/${id}/archivage`,
    method: "POST",
    json: { commentaire },
  });
}

/** `POST /api/documents/{id}/extraction` (L3-D15) : relit le fichier,
 * rappelle l'OCR, remplace valeurs et lignes. Réservé aux documents
 * `a_verifier` (409 sinon) — la page ne propose le bouton que dans ce cas. */
export function relancerExtraction(id: string): Promise<DocumentDetail> {
  return appelerApi<DocumentDetail>("/api/documents/{document_id}/extraction", {
    url: `/api/documents/${id}/extraction`,
    method: "POST",
  });
}
