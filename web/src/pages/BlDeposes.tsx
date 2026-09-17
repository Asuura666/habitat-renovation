import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";

import { CLE_DOCUMENTS, type DocumentResume, listerDocuments } from "../api/documents";
import { formaterDateHeure, TIRET } from "../lib/formats";

/** Correspondances libellé/couleur (présentation uniquement, décision du
 * contrôleur L2-T7) : `type`/`statut` viennent tels quels de l'API. */
function libelleType(type: string): string {
  if (type === "bl") {
    return "Livraison";
  }
  if (type === "enlevement") {
    return "Enlèvement";
  }
  return type;
}

function libelleStatut(statut: string): string {
  return statut === "a_verifier" ? "À vérifier" : "Reçu";
}

function classesStatut(statut: string): string {
  return statut === "a_verifier"
    ? "bg-orange-100 text-orange-800"
    : "bg-green-100 text-green-800";
}

/** Ruling L2-R8 (revue L2-T7, tour 1/5, correction) : `confirmation` est un
 * champ explicite de l'API (`"verifiee" | "ecart" | null`), affiché tel
 * quel — plus aucune dérivation à partir de `statut` ici (constat de revue :
 * `statut == "a_verifier"` peut venir de l'OCR, sans rapport avec un clic
 * « Écart constaté »). Le cas « écart » est mis en évidence par un badge
 * (contraste vérifié : `text-amber-900` sur `bg-amber-100`, ≈ 10:1). */
function Confirmation({ document }: { document: DocumentResume }): ReactElement {
  if (document.confirmation === null) {
    return <>En attente</>;
  }
  const qui = document.confirme_par ?? TIRET;
  const quand = formaterDateHeure(document.confirme_le);
  if (document.confirmation === "ecart") {
    return (
      <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">
        Écart signalé par {qui} le {quand}
      </span>
    );
  }
  return (
    <>
      Quantités vérifiées par {qui} le {quand}
    </>
  );
}

function BadgePhotoCompressee(): ReactElement {
  return (
    <span className="inline-flex shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
      Photo compressée
    </span>
  );
}

function LienPhoto({ documentId }: { documentId: string }): ReactElement {
  return (
    <a
      href={`/api/documents/${documentId}/fichier`}
      target="_blank"
      rel="noopener noreferrer"
      className="text-sm font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
    >
      Voir la photo
    </a>
  );
}

/** Onglet « BL déposés » (admin et agent, L2-T7) : admin voit tous les BL,
 * un agent seulement les siens (droit vérifié par `ingest.service.
 * lister_documents`, jamais ici). Rafraîchi toutes les 15 s (L2-D13, critère
 * « visible dans l'application » du lot 2). */
export function BlDeposes(): ReactElement {
  const documents = useQuery({
    queryKey: CLE_DOCUMENTS,
    queryFn: listerDocuments,
    refetchInterval: 15000,
  });

  return (
    <div>
      <h1 className="mb-4 text-lg font-semibold text-slate-900">BL déposés</h1>

      {documents.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Chargement…
        </p>
      )}
      {documents.isError && (
        <p role="alert" className="text-sm text-red-700">
          Impossible de charger les BL déposés.
        </p>
      )}
      {documents.data && documents.data.length === 0 && (
        <p className="text-sm text-slate-600">Aucun BL déposé pour l'instant.</p>
      )}

      {documents.data && documents.data.length > 0 && (
        <>
          {/* Cartes empilées : téléphone (< md) */}
          <ul className="space-y-3 md:hidden">
            {documents.data.map((document) => (
              <li key={document.id} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">
                      Document n° {document.numero_interne} · {libelleType(document.type)}
                    </p>
                    <p className="text-xs text-slate-500">
                      BL {document.numero ?? "non détecté"} · {document.deposant ?? TIRET} ·{" "}
                      {formaterDateHeure(document.cree_le)}
                    </p>
                  </div>
                  <span
                    className={`inline-flex shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${classesStatut(document.statut)}`}
                  >
                    {libelleStatut(document.statut)}
                  </span>
                </div>
                <p className="mb-3 text-sm text-slate-600">
                  <Confirmation document={document} />
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  {document.photo_compressee === true && <BadgePhotoCompressee />}
                  <LienPhoto documentId={document.id} />
                </div>
              </li>
            ))}
          </ul>

          {/* Tableau : ordinateur (>= md) */}
          <div className="hidden overflow-x-auto rounded-lg border border-slate-200 bg-white md:block">
            <table className="w-full min-w-[900px] divide-y divide-slate-200 text-sm">
              <caption className="sr-only">Liste des BL déposés</caption>
              <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-4 py-3">
                    N° interne
                  </th>
                  <th scope="col" className="px-4 py-3">
                    N° BL
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Type
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Déposant
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Date
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Statut
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Confirmation
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Photo
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {documents.data.map((document) => (
                  <tr key={document.id}>
                    <td className="px-4 py-3 text-slate-700">{document.numero_interne}</td>
                    <td className="px-4 py-3 text-slate-700">
                      {document.numero ?? "non détecté"}
                    </td>
                    <td className="px-4 py-3 text-slate-700">{libelleType(document.type)}</td>
                    <td className="px-4 py-3 text-slate-700">{document.deposant ?? TIRET}</td>
                    <td className="px-4 py-3 text-slate-700">
                      {formaterDateHeure(document.cree_le)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${classesStatut(document.statut)}`}
                      >
                        {libelleStatut(document.statut)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-700">
                      <Confirmation document={document} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        {document.photo_compressee === true && <BadgePhotoCompressee />}
                        <LienPhoto documentId={document.id} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
