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
import {
  CLE_AGENCES,
  CLE_FOURNISSEURS,
  type Fournisseur,
  listerFournisseurs,
  obtenirAgences,
} from "../api/referentiels";
import { estMontantNul, formaterMontant, libelleMois, lireMois, moisApi } from "../lib/formats";
import { Carte, EnTetePage, EtatVide } from "../ui";

/** Bouton d'export visuellement identique à `ui/Bouton.tsx` (variante
 * « secondaire ») mais posé sur un vrai `<a>` : un téléchargement de fichier
 * n'est pas une action de formulaire. */
const CLASSES_BOUTON_LIEN =
  "inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border border-bordure bg-surface px-4 py-2 text-sm font-medium text-encre outline-none transition-colors hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2";

/** Cible d'au moins 44 px même sur le lien du nom dans le tableau
 * (ordinateur) — la carte téléphone porte elle-même le lien en bloc. */
const CLASSES_LIEN_NOM =
  "inline-flex min-h-[44px] items-center font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent";

const CLASSES_CHAMP =
  "min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
const CLASSES_LABEL = "mb-1 block text-xs font-medium text-encre-2";

/** Mois (`AAAA-MM`) et agence lus dans l'URL — voir `FournisseursListe`. */
interface FiltresUrl {
  mois: string | undefined;
  agence: string | undefined;
}

function filtresApi(filtres: FiltresUrl): FiltresBilan {
  return { mois: filtres.mois !== undefined ? moisApi(filtres.mois) : undefined, agence: filtres.agence };
}

/** Résumé de la période affichée (`surtitre` d'`EnTetePage`) — mise en
 * forme uniquement : un non-technicien doit savoir sur quelle période
 * portent les montants affichés. */
function texteSurtitre(filtres: FiltresUrl): string {
  const periode = filtres.mois !== undefined ? `Période : ${libelleMois(filtres.mois)}` : "Tous les mois";
  return filtres.agence ? `${periode} · Agence ${filtres.agence}` : periode;
}

function lienAvecFiltres(chemin: string, filtres: FiltresUrl): string {
  const parametres = new URLSearchParams();
  if (filtres.mois !== undefined) {
    parametres.set("mois", filtres.mois);
  }
  if (filtres.agence) {
    parametres.set("agence", filtres.agence);
  }
  const requete = parametres.toString();
  return requete === "" ? chemin : `${chemin}?${requete}`;
}

/** Couleur d'un montant d'alerte ou d'écart : neutre quand il vaut zéro
 * (revue finale, constats ECRAN-15/TELEPHONE-11). */
function classeMontant(valeur: string, classeSiNonNul: string): string {
  return estMontantNul(valeur) ? "text-encre-2" : classeSiNonNul;
}

/** Nom du fournisseur, tel qu'affiché dans le tableau (ordinateur) : un
 * lien vers la fiche quand le fournisseur est identifié, sinon un texte
 * simple, en français courant. */
function NomFournisseur({ ligne, filtres }: { ligne: LigneBilanFournisseur; filtres: FiltresUrl }): ReactElement {
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

/** Carte téléphone (< `md`) pour une ligne du tableau — mêmes valeurs que
 * le tableau, empilées. Toute la carte est cliquable quand le fournisseur
 * est identifié. */
function CarteFournisseur({ ligne, filtres }: { ligne: LigneBilanFournisseur; filtres: FiltresUrl }): ReactElement {
  const contenu = (
    <>
      <h2 className="mb-3 font-titre text-lg font-medium text-encre">{ligne.nom ?? "Fournisseur non identifié"}</h2>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <div>
          <dt className="text-xs text-encre-2">Facturé</dt>
          <dd className="mt-0.5 font-mono font-medium text-encre">{formaterMontant(ligne.montants.facture_ht)}</dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Conforme</dt>
          <dd className={`mt-0.5 font-mono font-medium ${classeMontant(ligne.montants.conforme, "text-conforme")}`}>
            {formaterMontant(ligne.montants.conforme)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Écart</dt>
          <dd className={`mt-0.5 font-mono font-medium ${classeMontant(ligne.montants.en_ecart, "text-ecart-texte")}`}>
            {formaterMontant(ligne.montants.en_ecart)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Sans bon</dt>
          <dd className={`mt-0.5 font-mono font-medium ${classeMontant(ligne.montants.non_justifie, "text-alerte")}`}>
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

/** Tableau/cartes du bilan par fournisseur : quatre montants (spec §4 —
 * « Conforme » fourni par le serveur depuis la revue finale, constat
 * COUVERTURE-12) et le nombre de problèmes. */
function TableauFournisseurs({ lignes, filtres }: { lignes: LigneBilanFournisseur[]; filtres: FiltresUrl }): ReactElement {
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
                Conforme
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
                <td className="px-5 py-3 text-right font-mono text-encre">{formaterMontant(ligne.montants.facture_ht)}</td>
                <td className={`px-5 py-3 text-right font-mono ${classeMontant(ligne.montants.conforme, "text-conforme")}`}>
                  {formaterMontant(ligne.montants.conforme)}
                </td>
                <td className={`px-5 py-3 text-right font-mono ${classeMontant(ligne.montants.en_ecart, "text-ecart-texte")}`}>
                  {formaterMontant(ligne.montants.en_ecart)}
                </td>
                <td className={`px-5 py-3 text-right font-mono ${classeMontant(ligne.montants.non_justifie, "text-alerte")}`}>
                  {formaterMontant(ligne.montants.non_justifie)}
                </td>
                <td className="px-5 py-3 text-right text-encre">{ligne.montants.nb_anomalies_ouvertes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** Référentiel complet des fournisseurs (revue finale, constat
 * COUVERTURE-8) : le tableau ci-dessus ne connaît que les fournisseurs
 * présents sur au moins une facture — un fournisseur sans facture (Point.P
 * tant que son parseur n'existe pas) n'avait plus aucune entrée vers sa
 * fiche ni vers ses agences. Même principe que « Tous les chantiers » de
 * l'écran « Chantiers ». */
function CarteTousLesFournisseurs({ fournisseurs }: { fournisseurs: Fournisseur[] }): ReactElement {
  const tries = [...fournisseurs].sort((a, b) => a.nom.localeCompare(b.nom, "fr"));
  return (
    <Carte titre={`Tous les fournisseurs (${tries.length})`}>
      {tries.length === 0 ? (
        <EtatVide message="Aucun fournisseur enregistré." />
      ) : (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {tries.map((fournisseur) => (
            <li key={fournisseur.id}>
              <Link
                to={`/fournisseurs/${fournisseur.id}`}
                className="block min-h-[44px] rounded-lg border border-bordure p-3 outline-none transition-colors hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
              >
                <p className="font-medium text-encre">{fournisseur.nom}</p>
                <p className="mt-1 text-xs text-encre-2">
                  {fournisseur.agences.length === 0
                    ? "Aucune agence connue"
                    : `${fournisseur.agences.length} agence${fournisseur.agences.length > 1 ? "s" : ""} connue${
                        fournisseur.agences.length > 1 ? "s" : ""
                      }`}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Carte>
  );
}

/** Formulaire de filtres (mois, agence) — mêmes filtres que « Chantiers ». */
function FormulaireFiltres({
  filtres,
  onChangerFiltre,
}: {
  filtres: FiltresUrl;
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
          value={filtres.mois ?? ""}
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
 * filtres que « Chantiers » ; mois au format `AAAA-MM`, convention unique
 * depuis la revue finale — constat LIENS-5). Chaque ligne ouvre la fiche du
 * fournisseur (`/fournisseurs/:id`, filtres reportés dans le lien) ; le
 * fournisseur non identifié reste un texte simple, sans fiche à ouvrir. */
export function FournisseursListe(): ReactElement {
  const [parametres, setParametres] = useSearchParams();
  const filtresUrl: FiltresUrl = {
    mois: lireMois(parametres.get("mois")),
    agence: parametres.get("agence") || undefined,
  };
  const filtres = filtresApi(filtresUrl);

  const bilan = useQuery({
    queryKey: cleBilanFournisseurs(null, filtres),
    queryFn: () => listerBilanFournisseursGlobal(filtres),
  });
  const referentiel = useQuery({ queryKey: CLE_FOURNISSEURS, queryFn: listerFournisseurs });

  function changerFiltre(nom: "mois" | "agence", valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur.trim() === "") {
      suivants.delete(nom);
    } else {
      suivants.set(nom, valeur);
    }
    setParametres(suivants, { replace: true });
  }

  return (
    <div className="space-y-6">
      <EnTetePage
        surtitre={texteSurtitre(filtresUrl)}
        titre="Fournisseurs"
        actions={
          <a href={urlExportBilanFournisseurs(null, filtres)} className={CLASSES_BOUTON_LIEN}>
            Exporter pour Excel
          </a>
        }
      />

      <FormulaireFiltres filtres={filtresUrl} onChangerFiltre={changerFiltre} />

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
      {bilan.data && <TableauFournisseurs lignes={bilan.data} filtres={filtresUrl} />}

      {referentiel.data && <CarteTousLesFournisseurs fournisseurs={referentiel.data} />}
    </div>
  );
}
