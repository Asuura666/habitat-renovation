import { appelerApi } from "./client";
import type { components } from "./schema";

export type DocumentResume = components["schemas"]["DocumentReponse"];

export const CLE_DOCUMENTS = ["documents"] as const;

/** Admin : tous les BL/enlèvements non archivés. Agent : ceux qu'il a
 * déposés (droit vérifié par `ingest.service.lister_documents`, jamais
 * ici — voir `app/modules/api/documents.py`). */
export function listerDocuments(): Promise<DocumentResume[]> {
  return appelerApi<DocumentResume[]>("/api/documents");
}
