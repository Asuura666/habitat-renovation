import { type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import {
  cleBilanChantiers,
  type FiltresBilan,
  type LigneBilanChantier,
  listerBilanChantiers,
  urlExportBilanChantiers,
  urlExportBilanDetail,
} from "../api/bilan";
import { formaterMontant, TIRET } from "../lib/formats";
import { CLE_AGENCES, obtenirAgences } from "../api/referentiels";

const CLASSES_CHAMP =
  "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600";
const CLASSES_LABEL = "mb-1 block text-xs font-medium text-slate-700";
const CLASSES_LIEN =
  "text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600";

function nomChantier(ligne: LigneBilanChantier): string {
  return ligne.nom_canonique ?? "Chantier non résolu";
}

function lienAvecFiltres(chemin: string, filtres: FiltresBilan): string {
  const parametres = new URLSearchParams();
  if (filtres.mois) parametres.set("mois", filtres.mois);
  if (filtres.agence) parametres.set("agence", filtres.agence);
  const requete = parametres.toString();
  return requete === "" ? chemin : `${chemin}?${requete}`;
}

function NomChantier({ ligne, filtres }: { ligne: LigneBilanChantier; filtres: FiltresBilan }): ReactElement {
  if (ligne.chantier_id === null) return <>{nomChantier(ligne)}</>;
  return (
    <Link to={lienAvecFiltres(`/bilan/${ligne.chantier_id}`, filtres)} className={CLASSES_LIEN}>
      {nomChantier(ligne)}
    </Link>
  );
}

function NombreAnomalies({ nombre }: { nombre: number }): ReactElement {
  return (
    <span className={nombre > 0 ? "font-semibold text-red-700" : "text-slate-600"}>
      {nombre} {nombre > 1 ? "anomalies ouvertes" : "anomalie ouverte"}
    </span>
  );
}

function ValeurMontant({ libelle, valeur }: { libelle: string; valeur: string }): ReactElement {
  return (
    <div>
      <dt className="text-xs text-slate-500">{libelle}</dt>
      <dd className="mt-0.5 text-sm font-semibold tabular-nums text-slate-900">
        {formaterMontant(valeur)}
      </dd>
    </div>
  );
}

function CarteChantier({ ligne, filtres }: { ligne: LigneBilanChantier; filtres: FiltresBilan }): ReactElement {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-4">
        <h2 className="font-semibold text-slate-900"><NomChantier ligne={ligne} filtres={filtres} /></h2>
        <p className="text-sm text-slate-500">{ligne.agence ?? "Agence non renseignée"}</p>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        <ValeurMontant libelle="Facturé HT" valeur={ligne.montants.facture_ht} />
        <ValeurMontant libelle="Rapproché" valeur={ligne.montants.rapproche} />
        <ValeurMontant libelle="En écart" valeur={ligne.montants.en_ecart} />
        <ValeurMontant libelle="Non justifié" valeur={ligne.montants.non_justifie} />
      </dl>
      <p className="mt-4 border-t border-slate-100 pt-3 text-sm">
        <NombreAnomalies nombre={ligne.montants.nb_anomalies_ouvertes} />
      </p>
    </li>
  );
}

function TableauChantiers({ lignes, filtres }: { lignes: LigneBilanChantier[]; filtres: FiltresBilan }): ReactElement {
  return (
    <div className="hidden overflow-x-auto rounded-lg border border-slate-200 bg-white md:block">
      <table className="w-full min-w-[900px] divide-y divide-slate-200 text-sm">
        <caption className="sr-only">Bilan mensuel par chantier</caption>
        <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="px-4 py-3">Chantier</th>
            <th scope="col" className="px-4 py-3">Agence</th>
            <th scope="col" className="px-4 py-3 text-right">Facturé HT</th>
            <th scope="col" className="px-4 py-3 text-right">Rapproché</th>
            <th scope="col" className="px-4 py-3 text-right">En écart</th>
            <th scope="col" className="px-4 py-3 text-right">Non justifié</th>
            <th scope="col" className="px-4 py-3 text-right">Anomalies ouvertes</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200">
          {lignes.map((ligne) => (
            <tr key={ligne.chantier_id ?? "non-resolu"}>
              <th scope="row" className="px-4 py-3 text-left font-medium text-slate-900">
                <NomChantier ligne={ligne} filtres={filtres} />
              </th>
              <td className="px-4 py-3 text-slate-600">{ligne.agence ?? TIRET}</td>
              <td className="px-4 py-3 text-right tabular-nums">{formaterMontant(ligne.montants.facture_ht)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{formaterMontant(ligne.montants.rapproche)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{formaterMontant(ligne.montants.en_ecart)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{formaterMontant(ligne.montants.non_justifie)}</td>
              <td className="px-4 py-3 text-right"><NombreAnomalies nombre={ligne.montants.nb_anomalies_ouvertes} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ListeChantiers({ lignes, filtres }: { lignes: LigneBilanChantier[]; filtres: FiltresBilan }): ReactElement {
  if (lignes.length === 0) return <p className="text-sm text-slate-600">Aucun chantier pour ces filtres.</p>;
  return (
    <>
      <ul className="space-y-3 md:hidden">
        {lignes.map((ligne) => <CarteChantier key={ligne.chantier_id ?? "non-resolu"} ligne={ligne} filtres={filtres} />)}
      </ul>
      <TableauChantiers lignes={lignes} filtres={filtres} />
    </>
  );
}

export function Bilan(): ReactElement {
  const [parametres, setParametres] = useSearchParams();
  const filtres: FiltresBilan = {
    mois: parametres.get("mois") || undefined,
    agence: parametres.get("agence") || undefined,
  };
  const bilan = useQuery({ queryKey: cleBilanChantiers(filtres), queryFn: () => listerBilanChantiers(filtres) });
  const agences = useQuery({ queryKey: CLE_AGENCES, queryFn: obtenirAgences });

  function changerFiltre(nom: "mois" | "agence", valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    const valeurApi = nom === "mois" && valeur !== "" ? `${valeur}-01` : valeur;
    if (valeurApi.trim() === "") suivants.delete(nom);
    else suivants.set(nom, valeurApi);
    setParametres(suivants, { replace: true });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-slate-900">Bilan</h1>
        <div className="flex items-center gap-3">
          <Link to={lienAvecFiltres("/bilan/fournisseurs", filtres)} className={`${CLASSES_LIEN} text-sm font-medium`}>
            Vue par fournisseur
          </Link>
          <a href={urlExportBilanChantiers(filtres)} className="hidden rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-none hover:bg-blue-700 focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 md:block">
            Exporter en CSV
          </a>
          <a href={urlExportBilanDetail(filtres)} className="hidden rounded-md border border-blue-600 px-4 py-2 text-sm font-medium text-blue-700 outline-none hover:bg-blue-50 focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 md:block">
            Export détaillé (CSV)
          </a>
        </div>
      </div>
      <form onSubmit={(evenement) => evenement.preventDefault()} className="grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2">
        <div>
          <label htmlFor="filtre-mois" className={CLASSES_LABEL}>Mois de facturation</label>
          <input id="filtre-mois" type="month" value={filtres.mois?.slice(0, 7) ?? ""} onChange={(evenement) => changerFiltre("mois", evenement.target.value)} className={CLASSES_CHAMP} />
        </div>
        <div>
          <label htmlFor="filtre-agence" className={CLASSES_LABEL}>Agence</label>
          <select id="filtre-agence" value={filtres.agence ?? ""} onChange={(evenement) => changerFiltre("agence", evenement.target.value)} className={CLASSES_CHAMP}>
            <option value="">Toutes les agences</option>
            {agences.data?.map((agence) => <option key={agence} value={agence}>{agence}</option>)}
          </select>
        </div>
      </form>
      <p className="text-sm text-slate-600">Les quatre montants ne s’additionnent pas : un montant rapproché peut aussi être en écart.</p>
      {bilan.isPending && <p role="status" className="text-sm text-slate-500">Chargement…</p>}
      {bilan.isError && <p role="alert" className="text-sm text-red-700">Impossible de charger le bilan.</p>}
      {bilan.data && <ListeChantiers lignes={bilan.data} filtres={filtres} />}
    </div>
  );
}
