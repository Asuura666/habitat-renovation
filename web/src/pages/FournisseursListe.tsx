import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import {
  cleBilanFournisseurs,
  type LigneBilanFournisseur,
  listerBilanFournisseursGlobal,
  urlExportBilanFournisseurs,
} from "../api/bilan";
import { formaterMontant } from "../lib/formats";
import { EnTetePage, EtatVide } from "../ui";

/** Bouton d'export visuellement identique à `ui/Bouton.tsx` (variante
 * « secondaire ») mais posé sur un vrai `<a>` : un téléchargement de fichier
 * n'est pas une action de formulaire (Task 9, ne modifie pas `ui/Bouton.tsx`
 * — pas de composant partagé pour un lien stylé en bouton aujourd'hui). */
const CLASSES_BOUTON_LIEN =
  "inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-bordure bg-surface px-4 py-2 text-sm font-medium text-encre outline-none transition-colors hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2";

const CLASSES_LIEN_NOM =
  "font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent";

/** Une ligne du fournisseur non résolu (aucun fournisseur identifié sur ces
 * blocs) : pas de fiche à ouvrir, même convention que `Bilan.tsx`/l'ancien
 * `BilanFournisseur.tsx` (« Fournisseur non résolu », jamais de lien). */
function NomFournisseur({ ligne }: { ligne: LigneBilanFournisseur }): ReactElement {
  const nom = ligne.nom ?? "Fournisseur non résolu";
  if (ligne.fournisseur_id === null) {
    return <>{nom}</>;
  }
  return (
    <Link to={`/fournisseurs/${ligne.fournisseur_id}`} className={CLASSES_LIEN_NOM}>
      {nom}
    </Link>
  );
}

/** Carte téléphone (< `md`) pour une ligne du tableau — mêmes quatre
 * valeurs que le tableau, empilées (spec §7 : 375 px = cible à part
 * entière). */
function CarteFournisseur({ ligne }: { ligne: LigneBilanFournisseur }): ReactElement {
  return (
    <li className="rounded-carte border border-bordure bg-surface p-4">
      <h2 className="mb-3 font-titre text-lg font-medium text-encre">
        <NomFournisseur ligne={ligne} />
      </h2>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <div>
          <dt className="text-xs text-encre-2">Facturé</dt>
          <dd className="mt-0.5 font-mono font-medium text-encre">
            {formaterMontant(ligne.montants.facture_ht)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Écart</dt>
          <dd className="mt-0.5 font-mono font-medium text-ecart-texte">
            {formaterMontant(ligne.montants.en_ecart)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Sans bon</dt>
          <dd className="mt-0.5 font-mono font-medium text-alerte">
            {formaterMontant(ligne.montants.non_justifie)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Problèmes</dt>
          <dd className="mt-0.5 font-medium text-encre">{ligne.montants.nb_anomalies_ouvertes}</dd>
        </div>
      </dl>
    </li>
  );
}

function TableauFournisseurs({ lignes }: { lignes: LigneBilanFournisseur[] }): ReactElement {
  if (lignes.length === 0) {
    return <EtatVide message="Aucun fournisseur pour l'instant." />;
  }
  return (
    <>
      {/* Cartes empilées — téléphone (< md, spec §7). */}
      <ul className="space-y-3 md:hidden">
        {lignes.map((ligne) => (
          <CarteFournisseur key={ligne.fournisseur_id ?? "non-resolu"} ligne={ligne} />
        ))}
      </ul>

      {/* Tableau — ordinateur (>= md). */}
      <div className="hidden overflow-x-auto rounded-carte border border-bordure bg-surface md:block">
        <table className="w-full min-w-[720px] divide-y divide-bordure text-sm">
          <caption className="sr-only">Bilan par fournisseur</caption>
          <thead className="text-left text-xs font-medium uppercase tracking-wide text-encre-2">
            <tr>
              <th scope="col" className="px-5 py-3">
                Fournisseur
              </th>
              <th scope="col" className="px-5 py-3 text-right">
                Facturé
              </th>
              <th scope="col" className="px-5 py-3 text-right">
                Écart
              </th>
              <th scope="col" className="px-5 py-3 text-right">
                Sans bon
              </th>
              <th scope="col" className="px-5 py-3 text-right">
                Problèmes
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-bordure">
            {lignes.map((ligne) => (
              <tr key={ligne.fournisseur_id ?? "non-resolu"}>
                <th scope="row" className="px-5 py-3 text-left font-medium text-encre">
                  <NomFournisseur ligne={ligne} />
                </th>
                <td className="px-5 py-3 text-right font-mono text-encre">
                  {formaterMontant(ligne.montants.facture_ht)}
                </td>
                <td className="px-5 py-3 text-right font-mono text-ecart-texte">
                  {formaterMontant(ligne.montants.en_ecart)}
                </td>
                <td className="px-5 py-3 text-right font-mono text-alerte">
                  {formaterMontant(ligne.montants.non_justifie)}
                </td>
                <td className="px-5 py-3 text-right text-encre">
                  {ligne.montants.nb_anomalies_ouvertes}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** Écran « Fournisseurs » (spec §3/§4, Task 9) : bilan agrégé par
 * fournisseur sur tous les chantiers et toutes les périodes (`mois` non
 * transmis — l'API renvoie alors tout l'historique, `api/bilan.py`), sans
 * filtre (aucun mentionné par la maquette ni le plan pour cet écran,
 * contrairement à « Chantiers »). Chaque ligne ouvre la fiche du
 * fournisseur (`/fournisseurs/:id`) ; le fournisseur non résolu reste un
 * texte simple, sans fiche à ouvrir. */
export function FournisseursListe(): ReactElement {
  const bilan = useQuery({
    queryKey: cleBilanFournisseurs(null, {}),
    queryFn: () => listerBilanFournisseursGlobal({}),
  });

  return (
    <div className="space-y-6">
      <EnTetePage
        titre="Fournisseurs"
        actions={
          <a href={urlExportBilanFournisseurs(null, {})} className={CLASSES_BOUTON_LIEN}>
            Exporter en CSV
          </a>
        }
      />

      {bilan.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {bilan.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les fournisseurs.
        </p>
      )}
      {bilan.data && <TableauFournisseurs lignes={bilan.data} />}
    </div>
  );
}
