import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import {
  cleBilanFournisseurs,
  type FiltresBilan,
  type LigneBilanFournisseur,
  listerBilanFournisseursGlobal,
  urlExportBilanFournisseurs,
} from "../api/bilan";
import { CLE_AGENCES, obtenirAgences } from "../api/referentiels";
import { formaterMontant } from "../lib/formats";
import { EnTetePage, EtatVide } from "../ui";

/** Bouton d'export visuellement identique à `ui/Bouton.tsx` (variante
 * « secondaire ») mais posé sur un vrai `<a>` : un téléchargement de fichier
 * n'est pas une action de formulaire (Task 9, ne modifie pas `ui/Bouton.tsx`
 * — pas de composant partagé pour un lien stylé en bouton aujourd'hui). */
const CLASSES_BOUTON_LIEN =
  "inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-bordure bg-surface px-4 py-2 text-sm font-medium text-encre outline-none transition-colors hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2";

/** Cible d'au moins 44 px même sur le lien du nom dans le tableau
 * (ordinateur) — la carte téléphone porte elle-même le lien en bloc
 * (correction de revue, tour 1 : `inline-flex min-h-[44px]` en repli,
 * documenté par la piste de revue quand tout l'élément n'est pas
 * cliquable). */
const CLASSES_LIEN_NOM =
  "inline-flex min-h-[44px] items-center font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent";

const CLASSES_CHAMP =
  "min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
const CLASSES_LABEL = "mb-1 block text-xs font-medium text-encre-2";

const FORMATEUR_MOIS = new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric" });

/** Résumé de la période affichée (spec §2, `surtitre` d'`EnTetePage`) —
 * mise en forme uniquement (aucun calcul métier) : correction de revue,
 * tour 1, un non-technicien ne pouvait pas savoir sur quelle période
 * portaient les montants affichés. */
function texteSurtitre(filtres: FiltresBilan): string {
  const periode = filtres.mois
    ? `Période : ${FORMATEUR_MOIS.format(new Date(`${filtres.mois}T00:00:00`))}`
    : "Tous les mois";
  return filtres.agence ? `${periode} · Agence ${filtres.agence}` : periode;
}

function lienAvecFiltres(chemin: string, filtres: FiltresBilan): string {
  const parametres = new URLSearchParams();
  if (filtres.mois) {
    parametres.set("mois", filtres.mois);
  }
  if (filtres.agence) {
    parametres.set("agence", filtres.agence);
  }
  const requete = parametres.toString();
  return requete === "" ? chemin : `${chemin}?${requete}`;
}

/** Nom du fournisseur, tel qu'affiché dans le tableau (ordinateur) : un
 * lien vers la fiche quand le fournisseur est identifié, sinon un texte
 * simple, en français courant (correction de revue, tour 1 : l'ancien
 * texte était du jargon technique de résolution d'entité, jamais
 * expliqué). Pas de fiche à ouvrir pour un fournisseur non identifié :
 * aucune route ne l'accepte. */
function NomFournisseur({
  ligne,
  filtres,
}: {
  ligne: LigneBilanFournisseur;
  filtres: FiltresBilan;
}): ReactElement {
  const nom = ligne.nom ?? "Fournisseur non identifié";
  if (ligne.fournisseur_id === null) {
    return <>{nom}</>;
  }
  return (
    <Link to={lienAvecFiltres(`/fournisseurs/${ligne.fournisseur_id}`, filtres)} className={CLASSES_LIEN_NOM}>
      {nom}
    </Link>
  );
}

/** Carte téléphone (< `md`) pour une ligne du tableau — mêmes quatre
 * valeurs que le tableau, empilées (spec §7 : 375 px = cible à part
 * entière). Toute la carte est cliquable quand le fournisseur est identifié
 * (correction de revue, tour 1 : un lien texte de ~24 px de haut n'atteint
 * pas la cible tactile de 44 px) — un seul lien par carte, jamais de lien
 * imbriqué dans un autre. */
function CarteFournisseur({
  ligne,
  filtres,
}: {
  ligne: LigneBilanFournisseur;
  filtres: FiltresBilan;
}): ReactElement {
  const contenu = (
    <>
      <h2 className="mb-3 font-titre text-lg font-medium text-encre">
        {ligne.nom ?? "Fournisseur non identifié"}
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
    </>
  );

  if (ligne.fournisseur_id === null) {
    return <li className="rounded-carte border border-bordure bg-surface p-4">{contenu}</li>;
  }

  return (
    <li>
      <Link
        to={lienAvecFiltres(`/fournisseurs/${ligne.fournisseur_id}`, filtres)}
        className="block rounded-carte border border-bordure bg-surface p-4 outline-none transition-colors hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
      >
        {contenu}
      </Link>
    </li>
  );
}

function TableauFournisseurs({
  lignes,
  filtres,
}: {
  lignes: LigneBilanFournisseur[];
  filtres: FiltresBilan;
}): ReactElement {
  if (lignes.length === 0) {
    return <EtatVide message="Aucun fournisseur pour ces filtres." />;
  }
  return (
    <>
      {/* Cartes empilées — téléphone (< md, spec §7). */}
      <ul className="space-y-3 md:hidden">
        {lignes.map((ligne) => (
          <CarteFournisseur key={ligne.fournisseur_id ?? "non-resolu"} ligne={ligne} filtres={filtres} />
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
                  <NomFournisseur ligne={ligne} filtres={filtres} />
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

/** Formulaire de filtres (mois, agence) — même principe que l'ancien
 * `Bilan.tsx` et le brief de la Task 7 (« filtres mois [optionnel, « Tous
 * les mois » par défaut] et agence ») : correction de revue, tour 1, ces
 * filtres avaient disparu de l'écran refait alors que le socle transmet
 * `?mois`/`?agence` en redirigeant depuis l'ancienne URL. */
function FormulaireFiltres({
  filtres,
  onChangerFiltre,
}: {
  filtres: FiltresBilan;
  onChangerFiltre: (nom: "mois" | "agence", valeur: string) => void;
}): ReactElement {
  const agences = useQuery({ queryKey: CLE_AGENCES, queryFn: obtenirAgences });
  return (
    <form
      onSubmit={(evenement) => evenement.preventDefault()}
      className="grid grid-cols-1 gap-3 rounded-carte border border-bordure bg-surface p-4 sm:grid-cols-2"
    >
      <div>
        <label htmlFor="filtre-mois" className={CLASSES_LABEL}>
          Mois de facturation
        </label>
        <input
          id="filtre-mois"
          type="month"
          value={filtres.mois?.slice(0, 7) ?? ""}
          onChange={(evenement) => onChangerFiltre("mois", evenement.target.value)}
          className={CLASSES_CHAMP}
        />
      </div>
      <div>
        <label htmlFor="filtre-agence" className={CLASSES_LABEL}>
          Agence
        </label>
        <select
          id="filtre-agence"
          value={filtres.agence ?? ""}
          onChange={(evenement) => onChangerFiltre("agence", evenement.target.value)}
          className={CLASSES_CHAMP}
        >
          <option value="">Toutes les agences</option>
          {agences.data?.map((agence) => (
            <option key={agence} value={agence}>
              {agence}
            </option>
          ))}
        </select>
      </div>
    </form>
  );
}

/** Écran « Fournisseurs » (spec §3/§4, Task 9) : bilan agrégé par
 * fournisseur, filtrable par mois et par agence (`?mois`/`?agence`, mêmes
 * filtres que « Chantiers » — correction de revue, tour 1). Chaque ligne
 * ouvre la fiche du fournisseur (`/fournisseurs/:id`, filtres reportés dans
 * le lien) ; le fournisseur non identifié reste un texte simple, sans fiche
 * à ouvrir. */
export function FournisseursListe(): ReactElement {
  const [parametres, setParametres] = useSearchParams();
  const filtres: FiltresBilan = {
    mois: parametres.get("mois") || undefined,
    agence: parametres.get("agence") || undefined,
  };

  const bilan = useQuery({
    queryKey: cleBilanFournisseurs(null, filtres),
    queryFn: () => listerBilanFournisseursGlobal(filtres),
  });

  function changerFiltre(nom: "mois" | "agence", valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    const valeurApi = nom === "mois" && valeur !== "" ? `${valeur}-01` : valeur;
    if (valeurApi.trim() === "") {
      suivants.delete(nom);
    } else {
      suivants.set(nom, valeurApi);
    }
    setParametres(suivants, { replace: true });
  }

  return (
    <div className="space-y-6">
      <EnTetePage
        surtitre={texteSurtitre(filtres)}
        titre="Fournisseurs"
        actions={
          <a href={urlExportBilanFournisseurs(null, filtres)} className={CLASSES_BOUTON_LIEN}>
            Exporter en CSV
          </a>
        }
      />

      <FormulaireFiltres filtres={filtres} onChangerFiltre={changerFiltre} />

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
      {bilan.data && <TableauFournisseurs lignes={bilan.data} filtres={filtres} />}
    </div>
  );
}
