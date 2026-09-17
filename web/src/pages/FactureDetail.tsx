import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";

import { type BlocFacture, cleFacture, obtenirFacture } from "../api/factures";
import { formaterDate, formaterMontant, TIRET } from "../lib/formats";
import { libelleMotif } from "../lib/motifs";

/** Mêmes badges que `FacturesListe.tsx` (décision du contrôleur, L3-T9) :
 * dupliqués plutôt que partagés, comme le reste des petits composants de
 * présentation de ces deux pages (`BadgePhotoCompressee` de `BlDeposes.tsx`
 * n'est pas partagé non plus). */
function BadgeAVerifier(): ReactElement {
  return (
    <span className="inline-flex shrink-0 rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-800">
      À vérifier
    </span>
  );
}

function BadgeConfianceReduite(): ReactElement {
  return (
    <span className="inline-flex shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">
      Confiance réduite (OCR)
    </span>
  );
}

function PastilleReception({ recu }: { recu: boolean }): ReactElement {
  const classes = recu ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800";
  return (
    <span className={`inline-flex shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}>
      {recu ? "Reçu" : "Non reçu"}
    </span>
  );
}

function BlocCarte({ bloc }: { bloc: BlocFacture }): ReactElement {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-slate-900">
            BL {bloc.numero_bl ?? "non détecté"}
          </p>
          <p className="text-xs text-slate-500">{formaterDate(bloc.date_bl)}</p>
        </div>
        <PastilleReception recu={bloc.bl_recu} />
      </div>

      <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm text-slate-700 sm:grid-cols-3">
        <div>
          <dt className="text-xs text-slate-500">Chantier (brut)</dt>
          <dd>{bloc.chantier_brut ?? TIRET}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Commande</dt>
          <dd>{bloc.numero_commande ?? TIRET}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Montant HT</dt>
          <dd>{formaterMontant(bloc.montant_ht)}</dd>
        </div>
      </dl>

      {bloc.commentaire && (
        <p className="mb-3 whitespace-pre-line text-sm text-slate-600">{bloc.commentaire}</p>
      )}

      {bloc.bl_recu && bloc.bl_document_id && (
        <a
          href={`/api/documents/${bloc.bl_document_id}/fichier`}
          target="_blank"
          rel="noopener noreferrer"
          className="mb-3 inline-block text-sm font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
        >
          Voir la photo
        </a>
      )}

      <details>
        <summary className="cursor-pointer text-sm font-medium text-slate-700 outline-none focus-visible:ring-2 focus-visible:ring-blue-600">
          Lignes ({bloc.lignes.length})
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[640px] divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-3 py-2">Article</th>
                <th scope="col" className="px-3 py-2">Qté livrée</th>
                <th scope="col" className="px-3 py-2">Qté totale</th>
                <th scope="col" className="px-3 py-2">PU HT</th>
                <th scope="col" className="px-3 py-2">Remise</th>
                <th scope="col" className="px-3 py-2">Montant HT</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {bloc.lignes.map((ligne) => (
                <tr key={ligne.ordre}>
                  <td className="px-3 py-2 text-slate-700">
                    {ligne.article_brut ?? ligne.code_brut ?? TIRET}
                  </td>
                  <td className="px-3 py-2 text-slate-700">{ligne.qte_livree ?? TIRET}</td>
                  <td className="px-3 py-2 text-slate-700">{ligne.qte_totale ?? TIRET}</td>
                  <td className="px-3 py-2 text-slate-700">{formaterMontant(ligne.pu_ht)}</td>
                  <td className="px-3 py-2 text-slate-700">
                    {ligne.remise_pct !== null ? `${ligne.remise_pct} %` : TIRET}
                  </td>
                  <td className="px-3 py-2 text-slate-700">{formaterMontant(ligne.montant_ht)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </li>
  );
}

/** `GET /api/factures/{id}` (décisions du contrôleur L2-T7). Réservé à
 * l'admin par `GardeAdmin` (voir `App.tsx`) : aucune vérification de rôle
 * ici. */
export function FactureDetail(): ReactElement {
  const { id } = useParams<{ id: string }>();

  const facture = useQuery({
    queryKey: id !== undefined ? cleFacture(id) : ["factures", "sans-identifiant"],
    queryFn: () => obtenirFacture(id ?? ""),
    enabled: id !== undefined,
  });

  if (id === undefined) {
    return (
      <p role="alert" className="text-sm text-red-700">
        Facture introuvable.
      </p>
    );
  }

  if (facture.isPending) {
    return (
      <p role="status" className="text-sm text-slate-500">
        Chargement…
      </p>
    );
  }

  if (facture.isError || !facture.data) {
    return (
      <p role="alert" className="text-sm text-red-700">
        Facture introuvable.
      </p>
    );
  }

  const donnees = facture.data;

  const aDesBadges = donnees.statut === "a_verifier" || donnees.confiance_reduite;

  return (
    <div>
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Facture {donnees.numero}</h1>

      {aDesBadges && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {donnees.statut === "a_verifier" && <BadgeAVerifier />}
          {donnees.confiance_reduite && <BadgeConfianceReduite />}
        </div>
      )}

      <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm text-slate-700 sm:grid-cols-4">
        <div>
          <dt className="text-xs text-slate-500">Fournisseur</dt>
          <dd>{donnees.fournisseur}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Date</dt>
          <dd>{formaterDate(donnees.date_doc)}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Total HT</dt>
          <dd>{formaterMontant(donnees.total_ht)}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Déposée par</dt>
          <dd>{donnees.deposant ?? TIRET}</dd>
        </div>
      </dl>

      {donnees.statut === "a_verifier" && donnees.motifs.length > 0 && (
        <div className="mb-6 rounded-lg border border-orange-200 bg-orange-50 p-4">
          <h2 className="mb-2 text-sm font-semibold text-orange-900">Motifs</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-orange-900">
            {donnees.motifs.map((motif, index) => (
              <li key={index}>{libelleMotif(motif)}</li>
            ))}
          </ul>
        </div>
      )}

      <a
        href={`/api/factures/${donnees.id}/fichier`}
        target="_blank"
        rel="noopener noreferrer"
        className="mb-6 inline-block text-sm font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
      >
        Voir le PDF
      </a>

      <h2 className="mb-3 text-base font-semibold text-slate-900">
        Blocs BL ({donnees.blocs.length})
      </h2>
      <ul className="space-y-4">
        {donnees.blocs.map((bloc) => (
          <BlocCarte key={bloc.id} bloc={bloc} />
        ))}
      </ul>
    </div>
  );
}
