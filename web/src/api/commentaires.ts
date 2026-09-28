import { appelerApi } from "./client";
import type { components } from "./schema";

/** Un commentaire, sous sa ligne, dans `sansLigne`, ou seul (retour de
 * `ajouterCommentaire`) — mêmes attributs des deux côtés (voir
 * `app/modules/api/schemas.py::CommentaireReponse`). */
export type CommentaireLigne = components["schemas"]["CommentaireReponse"];
export type LigneCommentee = components["schemas"]["LigneCommenteeReponse"];
export type CommentairesBon = components["schemas"]["CommentairesBonReponse"];

export function cleCommentaires(documentId: string): readonly [string, string, string] {
  return ["document", documentId, "commentaires"] as const;
}

/** `GET /api/commentaires/documents/{id}` (tâche C3 de la phase 3,
 * `docs/superpowers/specs/2026-09-27-commentaires-lignes-design.md` §5) :
 * commentaires d'un BL/enlèvement, groupés par ligne dans l'ordre du bon,
 * puis ceux dont la ligne a disparu (`sans_ligne`, libellé figé). Même
 * visibilité que `lireDocument` (un agent ne voit que ses dépôts) : 404 si
 * le document est invisible ou n'en est pas un — voir
 * `ingest/commentaires.py::commentaires_du_bon`. */
export function lireCommentaires(documentId: string): Promise<CommentairesBon> {
  return appelerApi<CommentairesBon>("/api/commentaires/documents/{document_id}", {
    url: `/api/commentaires/documents/${documentId}`,
  });
}

/** `POST /api/commentaires/lignes/{id}` : ajoute un commentaire sur une
 * ligne du bon, pour tout compte connecté (admin ou agent sur son propre
 * dépôt, décision d'Ilane du 27/09/2026). 404 si la ligne est absente ou
 * invisible (bon d'un autre agent, ou facture) ; 422 si le texte est vide ou
 * dépasse 1000 caractères une fois nettoyé — voir
 * `ingest/commentaires.py::ajouter_commentaire`. */
export function ajouterCommentaire(ligneId: string, texte: string): Promise<CommentaireLigne> {
  return appelerApi<CommentaireLigne>("/api/commentaires/lignes/{ligne_id}", {
    url: `/api/commentaires/lignes/${ligneId}`,
    method: "POST",
    json: { texte },
  });
}
