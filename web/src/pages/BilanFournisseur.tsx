import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router";

import {
  cleBilanBl,
  cleBilanFournisseurs,
  type FiltresBilan,
  type LigneBilanBl,
  type LigneBilanChantier,
  type LigneBilanFournisseur,
  listerBilanBl,
  listerBilanChantiersFournisseur,
  listerBilanFournisseurs,
  listerBilanFournisseursGlobal,
  urlExportBilanBl,
  urlExportBilanChantiersFournisseur,
  urlExportBilanFournisseurs,
} from "../api/bilan";
import { formaterDate, formaterMontant, TIRET } from "../lib/formats";

const CLASSES_LIEN = "font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600";
const CLASSES_EXPORT = "hidden rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-none hover:bg-blue-700 focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 md:block";

function filtresDepuis(parametres: URLSearchParams): FiltresBilan {
  return {
    mois: parametres.get("mois") || undefined,
    agence: parametres.get("agence") || undefined,
  };
}

function lienAvecFiltres(chemin: string, filtres: FiltresBilan): string {
  const parametres = new URLSearchParams();
  if (filtres.mois) parametres.set("mois", filtres.mois);
  if (filtres.agence) parametres.set("agence", filtres.agence);
  const requete = parametres.toString();
  return requete === "" ? chemin : `${chemin}?${requete}`;
}

function FilAriane({ segments }: { segments: Array<{ libelle: string; chemin?: string }> }): ReactElement {
  return (
    <nav aria-label="Fil d’Ariane" className="text-sm text-slate-600">
      <ol className="flex flex-wrap items-center gap-2">
        {segments.map((segment, index) => (
          <li key={`${segment.libelle}-${index}`} className="flex items-center gap-2">
            {index > 0 && <span aria-hidden="true">›</span>}
            {segment.chemin ? <Link to={segment.chemin} className={CLASSES_LIEN}>{segment.libelle}</Link> : <span>{segment.libelle}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}

function Montants({ montants }: { montants: LigneBilanChantier["montants"] }): ReactElement {
  const valeurs: Array<[string, string]> = [
    ["Facturé HT", montants.facture_ht],
    ["Rapproché", montants.rapproche],
    ["En écart", montants.en_ecart],
    ["Non justifié", montants.non_justifie],
  ];
  return (
    <>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
        {valeurs.map(([libelle, valeur]) => (
          <div key={libelle}>
            <dt className="text-xs text-slate-500">{libelle}</dt>
            <dd className="font-semibold tabular-nums text-slate-900">{formaterMontant(valeur)}</dd>
          </div>
        ))}
      </dl>
      <p className={`mt-3 text-sm ${montants.nb_anomalies_ouvertes > 0 ? "font-semibold text-red-700" : "text-slate-600"}`}>
        {montants.nb_anomalies_ouvertes} {montants.nb_anomalies_ouvertes > 1 ? "anomalies ouvertes" : "anomalie ouverte"}
      </p>
    </>
  );
}

function EnteteNiveau({ titre, exportUrl, segments }: { titre: string; exportUrl: string; segments: Array<{ libelle: string; chemin?: string }> }): ReactElement {
  return (
    <>
      <FilAriane segments={segments} />
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-slate-900">{titre}</h1>
        <a href={exportUrl} className={CLASSES_EXPORT}>Exporter en CSV</a>
      </div>
      <p className="text-sm text-slate-600">Les quatre montants ne s’additionnent pas : un montant rapproché peut aussi être en écart.</p>
    </>
  );
}

function ListeFournisseurs({ lignes, chemin, filtres }: { lignes: LigneBilanFournisseur[]; chemin: (id: string) => string; filtres: FiltresBilan }): ReactElement {
  if (lignes.length === 0) return <p className="text-sm text-slate-600">Aucun fournisseur pour ces filtres.</p>;
  return (
    <>
      <ul className="space-y-3 md:hidden">
        {lignes.map((ligne) => (
          <li key={ligne.fournisseur_id ?? "non-resolu"} className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="mb-3 font-semibold">
              {ligne.fournisseur_id === null ? (ligne.nom ?? "Fournisseur non résolu") : <Link className={CLASSES_LIEN} to={lienAvecFiltres(chemin(ligne.fournisseur_id), filtres)}>{ligne.nom ?? "Fournisseur non résolu"}</Link>}
            </h2>
            <Montants montants={ligne.montants} />
          </li>
        ))}
      </ul>
      <div className="hidden overflow-x-auto rounded-lg border border-slate-200 bg-white md:block">
        <table className="w-full min-w-[850px] divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium uppercase text-slate-500"><tr><th className="px-4 py-3">Fournisseur</th><th className="px-4 py-3">Facturé HT</th><th className="px-4 py-3">Rapproché</th><th className="px-4 py-3">En écart</th><th className="px-4 py-3">Non justifié</th><th className="px-4 py-3">Anomalies</th></tr></thead>
          <tbody className="divide-y divide-slate-200">{lignes.map((ligne) => <tr key={ligne.fournisseur_id ?? "non-resolu"}><th className="px-4 py-3 text-left">{ligne.fournisseur_id === null ? (ligne.nom ?? "Fournisseur non résolu") : <Link className={CLASSES_LIEN} to={lienAvecFiltres(chemin(ligne.fournisseur_id), filtres)}>{ligne.nom ?? "Fournisseur non résolu"}</Link>}</th><td className="px-4 py-3">{formaterMontant(ligne.montants.facture_ht)}</td><td className="px-4 py-3">{formaterMontant(ligne.montants.rapproche)}</td><td className="px-4 py-3">{formaterMontant(ligne.montants.en_ecart)}</td><td className="px-4 py-3">{formaterMontant(ligne.montants.non_justifie)}</td><td className="px-4 py-3">{ligne.montants.nb_anomalies_ouvertes}</td></tr>)}</tbody>
        </table>
      </div>
    </>
  );
}

function statutBl(statut: string | null): string {
  if (statut === "recu") return "BL reçu";
  if (statut === "pas_de_bon") return "Pas de bon";
  if (statut === "non_recu") return "BL non reçu";
  return "Statut inconnu";
}

function LiensBl({ ligne }: { ligne: LigneBilanBl }): ReactElement {
  return (
    <div className="mt-3 flex flex-wrap gap-3 text-sm">
      {ligne.bl_document_id !== null ? (
        <Link to={`/documents/${ligne.bl_document_id}`} className={CLASSES_LIEN}>Voir la photo</Link>
      ) : (
        <Link to={`/factures/${ligne.facture_id}#bloc-${ligne.bloc_id}`} className={CLASSES_LIEN}>Voir le bloc facture</Link>
      )}
      <Link to={`/anomalies?blocId=${ligne.bloc_id}`} className={CLASSES_LIEN}>Voir les anomalies</Link>
    </div>
  );
}

function ListeBl({ lignes }: { lignes: LigneBilanBl[] }): ReactElement {
  if (lignes.length === 0) return <p className="text-sm text-slate-600">Aucun BL pour ces filtres.</p>;
  return (
    <>
      <ul className="space-y-3 md:hidden">{lignes.map((ligne) => <li key={ligne.bloc_id} className="rounded-lg border border-slate-200 bg-white p-4"><div className="mb-3"><h2 className="font-semibold">BL {ligne.numero_bl ?? TIRET}</h2><p className="text-sm text-slate-500">{formaterDate(ligne.date_bl)} · {statutBl(ligne.statut_rapprochement)}</p></div><Montants montants={ligne.montants} /><LiensBl ligne={ligne} /></li>)}</ul>
      <div className="hidden overflow-x-auto rounded-lg border border-slate-200 bg-white md:block"><table className="w-full min-w-[1000px] divide-y divide-slate-200 text-sm"><thead className="bg-slate-50 text-left text-xs font-medium uppercase text-slate-500"><tr><th className="px-4 py-3">BL</th><th className="px-4 py-3">Date</th><th className="px-4 py-3">Statut</th><th className="px-4 py-3">Facturé HT</th><th className="px-4 py-3">Rapproché</th><th className="px-4 py-3">En écart</th><th className="px-4 py-3">Non justifié</th><th className="px-4 py-3">Sources</th></tr></thead><tbody className="divide-y divide-slate-200">{lignes.map((ligne) => <tr key={ligne.bloc_id}><th className="px-4 py-3 text-left">{ligne.numero_bl ?? TIRET}</th><td className="px-4 py-3">{formaterDate(ligne.date_bl)}</td><td className="px-4 py-3">{statutBl(ligne.statut_rapprochement)}</td><td className="px-4 py-3">{formaterMontant(ligne.montants.facture_ht)}</td><td className="px-4 py-3">{formaterMontant(ligne.montants.rapproche)}</td><td className="px-4 py-3">{formaterMontant(ligne.montants.en_ecart)}</td><td className="px-4 py-3">{formaterMontant(ligne.montants.non_justifie)}</td><td className="px-4 py-3"><LiensBl ligne={ligne} /></td></tr>)}</tbody></table></div>
    </>
  );
}

export function BilanFournisseursChantier(): ReactElement {
  const { chantierId } = useParams();
  const [parametres] = useSearchParams();
  const filtres = filtresDepuis(parametres);
  const bilan = useQuery({ queryKey: cleBilanFournisseurs(chantierId ?? null, filtres), queryFn: () => listerBilanFournisseurs(chantierId ?? "", filtres), enabled: chantierId !== undefined });
  return <div className="space-y-6"><EnteteNiveau titre="Fournisseurs du chantier" exportUrl={urlExportBilanFournisseurs(chantierId ?? null, filtres)} segments={[{ libelle: "Bilan", chemin: lienAvecFiltres("/bilan", filtres) }, { libelle: "Chantier" }]} />{bilan.isPending && <p>Chargement…</p>}{bilan.isError && <p role="alert" className="text-red-700">Impossible de charger le bilan.</p>}{bilan.data && <ListeFournisseurs lignes={bilan.data} chemin={(id) => `/bilan/${chantierId}/${id}`} filtres={filtres} />}</div>;
}

export function BilanBl(): ReactElement {
  const { chantierId, fournisseurId } = useParams();
  const [parametres] = useSearchParams();
  const filtres = filtresDepuis(parametres);
  const bilan = useQuery({ queryKey: cleBilanBl(chantierId ?? "", fournisseurId ?? "", filtres), queryFn: () => listerBilanBl(chantierId ?? "", fournisseurId ?? "", filtres), enabled: chantierId !== undefined && fournisseurId !== undefined });
  return <div className="space-y-6"><EnteteNiveau titre="Bons de livraison" exportUrl={urlExportBilanBl(chantierId ?? "", fournisseurId ?? "", filtres)} segments={[{ libelle: "Bilan", chemin: lienAvecFiltres("/bilan", filtres) }, { libelle: "Chantier", chemin: lienAvecFiltres(`/bilan/${chantierId}`, filtres) }, { libelle: "Fournisseur" }]} />{bilan.isPending && <p>Chargement…</p>}{bilan.isError && <p role="alert" className="text-red-700">Impossible de charger le bilan.</p>}{bilan.data && <ListeBl lignes={bilan.data} />}</div>;
}

export function BilanFournisseursGlobal(): ReactElement {
  const [parametres] = useSearchParams();
  const filtres = filtresDepuis(parametres);
  const bilan = useQuery({ queryKey: cleBilanFournisseurs(null, filtres), queryFn: () => listerBilanFournisseursGlobal(filtres) });
  return <div className="space-y-6"><EnteteNiveau titre="Bilan par fournisseur" exportUrl={urlExportBilanFournisseurs(null, filtres)} segments={[{ libelle: "Bilan", chemin: lienAvecFiltres("/bilan", filtres) }, { libelle: "Fournisseurs" }]} />{bilan.isPending && <p>Chargement…</p>}{bilan.isError && <p role="alert" className="text-red-700">Impossible de charger le bilan.</p>}{bilan.data && <ListeFournisseurs lignes={bilan.data} chemin={(id) => `/bilan/fournisseurs/${id}`} filtres={filtres} />}</div>;
}

export function BilanChantiersFournisseur(): ReactElement {
  const { fournisseurId } = useParams();
  const [parametres] = useSearchParams();
  const filtres = filtresDepuis(parametres);
  const bilan = useQuery({ queryKey: ["bilan", "chantiers-fournisseur", fournisseurId, filtres], queryFn: () => listerBilanChantiersFournisseur(fournisseurId ?? "", filtres), enabled: fournisseurId !== undefined });
  return <div className="space-y-6"><EnteteNiveau titre="Chantiers du fournisseur" exportUrl={urlExportBilanChantiersFournisseur(fournisseurId ?? "", filtres)} segments={[{ libelle: "Bilan", chemin: lienAvecFiltres("/bilan", filtres) }, { libelle: "Fournisseurs", chemin: lienAvecFiltres("/bilan/fournisseurs", filtres) }, { libelle: "Fournisseur" }]} />{bilan.isPending && <p>Chargement…</p>}{bilan.isError && <p role="alert" className="text-red-700">Impossible de charger le bilan.</p>}{bilan.data && <ul className="space-y-3">{bilan.data.map((ligne) => <li key={ligne.chantier_id ?? "non-resolu"} className="rounded-lg border border-slate-200 bg-white p-4"><h2 className="mb-3 font-semibold">{ligne.chantier_id === null ? (ligne.nom_canonique ?? "Chantier non résolu") : <Link className={CLASSES_LIEN} to={lienAvecFiltres(`/bilan/${ligne.chantier_id}/${fournisseurId}`, filtres)}>{ligne.nom_canonique ?? "Chantier non résolu"}</Link>}</h2><Montants montants={ligne.montants} /></li>)}</ul>}</div>;
}
