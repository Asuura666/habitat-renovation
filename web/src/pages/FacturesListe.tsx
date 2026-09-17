import { type ChangeEvent, type ReactElement, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";

import { ErreurApi } from "../api/client";
import {
  CLE_FACTURES,
  FactureEnDoubleErreur,
  deposerFacture,
  listerFactures,
} from "../api/factures";
import { formaterDate, formaterMontant } from "../lib/formats";

/** Couleur du badge « BL reçus x / y » (décision du contrôleur L2-T7 :
 * uniquement une correspondance libellé/couleur, pas une règle métier —
 * `nb_blocs`/`nb_blocs_recus` viennent tels quels de l'API). */
function classesBadgeReception(nbRecus: number, nbBlocs: number): string {
  if (nbBlocs === 0) {
    return "bg-slate-100 text-slate-600";
  }
  if (nbRecus === nbBlocs) {
    return "bg-green-100 text-green-800";
  }
  if (nbRecus === 0) {
    return "bg-red-100 text-red-800";
  }
  return "bg-orange-100 text-orange-800";
}

function ContenuErreurDepot({ erreur }: { erreur: unknown }): ReactElement {
  if (erreur instanceof FactureEnDoubleErreur) {
    return (
      <>
        Facture déjà déposée.{" "}
        <Link to={`/factures/${erreur.originalId}`} className="font-medium underline">
          Voir la facture d'origine
        </Link>
      </>
    );
  }
  if (erreur instanceof ErreurApi) {
    return <>{erreur.detail}</>;
  }
  return <>Une erreur est survenue, réessayez.</>;
}

/** Onglet « Factures » (admin, L2-T7) : liste + dépôt d'un PDF. Aucune règle
 * métier : le dépôt, la détection du doublon et le format Unikalo
 * appartiennent tous à `deposer_facture` (`ingest/service.py`) ; cette page
 * ne fait que traduire ses erreurs typées en texte (déjà en français côté
 * API, voir `api/factures.ts`). */
export function FacturesListe(): ReactElement {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const entreeFichier = useRef<HTMLInputElement>(null);

  const factures = useQuery({ queryKey: CLE_FACTURES, queryFn: listerFactures });

  const depot = useMutation({
    mutationFn: (fichier: File) => deposerFacture(fichier),
    onSuccess: async (deposee) => {
      await queryClient.invalidateQueries({ queryKey: CLE_FACTURES });
      navigate(`/factures/${deposee.id}`);
    },
  });

  function surChangementFichier(evenement: ChangeEvent<HTMLInputElement>): void {
    const fichier = evenement.target.files?.[0];
    // Réinitialisé tout de suite : redéposer le même fichier après une
    // erreur doit redéclencher `onChange` (sinon le navigateur l'ignore, la
    // valeur de l'input n'ayant pas changé).
    evenement.target.value = "";
    if (fichier) {
      depot.mutate(fichier);
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-slate-900">Factures</h1>
        <div>
          <label htmlFor="depot-facture" className="sr-only">
            Fichier PDF de la facture à déposer
          </label>
          <input
            ref={entreeFichier}
            id="depot-facture"
            type="file"
            accept="application/pdf"
            className="sr-only"
            disabled={depot.isPending}
            onChange={surChangementFichier}
          />
          <button
            type="button"
            onClick={() => entreeFichier.current?.click()}
            disabled={depot.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-none hover:bg-blue-700 focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Déposer une facture
          </button>
        </div>
      </div>

      <div aria-live="polite">
        {depot.isPending && (
          <p className="mb-4 text-sm text-slate-600">
            Lecture de la facture en cours (jusqu'à une minute)…
          </p>
        )}
        {depot.isError && (
          <p role="alert" className="mb-4 text-sm text-red-700">
            <ContenuErreurDepot erreur={depot.error} />
          </p>
        )}
      </div>

      {factures.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Chargement…
        </p>
      )}
      {factures.isError && (
        <p role="alert" className="text-sm text-red-700">
          Impossible de charger les factures.
        </p>
      )}

      {factures.data && factures.data.length === 0 && (
        <p className="text-sm text-slate-600">Aucune facture déposée.</p>
      )}

      {factures.data && factures.data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full min-w-[640px] divide-y divide-slate-200 text-sm">
            <caption className="sr-only">Liste des factures déposées</caption>
            <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-4 py-3">
                  Numéro
                </th>
                <th scope="col" className="px-4 py-3">
                  Fournisseur
                </th>
                <th scope="col" className="px-4 py-3">
                  Date
                </th>
                <th scope="col" className="px-4 py-3">
                  Total HT
                </th>
                <th scope="col" className="px-4 py-3">
                  BL reçus
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {factures.data.map((facture) => (
                <tr key={facture.id}>
                  <td className="px-4 py-3 font-medium text-slate-900">
                    <Link
                      to={`/factures/${facture.id}`}
                      className="underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
                    >
                      {facture.numero}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-slate-700">{facture.fournisseur}</td>
                  <td className="px-4 py-3 text-slate-700">{formaterDate(facture.date_doc)}</td>
                  <td className="px-4 py-3 text-slate-700">{formaterMontant(facture.total_ht)}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${classesBadgeReception(facture.nb_blocs_recus, facture.nb_blocs)}`}
                    >
                      {facture.nb_blocs_recus} / {facture.nb_blocs}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
