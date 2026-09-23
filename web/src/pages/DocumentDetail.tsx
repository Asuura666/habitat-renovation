import { type FormEvent, type ReactElement, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router";

import { CLE_A_TRAITER } from "../api/aTraiter";
import { ErreurApi } from "../api/client";
import { invaliderApresChangementAnomalies } from "../api/invalidations";
import {
  CLE_DOCUMENTS,
  type ChampDocument,
  type ChampsDocument,
  type CorrectionEntete,
  type DocumentDetail as DocumentDetailApi,
  type LigneDocument,
  type LigneSaisie,
  type Motif,
  ValidationRefuseeErreur,
  archiverDocument,
  cleDocument,
  corrigerEntete,
  corrigerLignes,
  lireDocument,
  relancerExtraction,
  validerDocument,
} from "../api/documents";
import {
  CLE_CHANTIERS,
  CLE_CHANTIERS_SILENCIEUX,
  CLE_FOURNISSEURS,
  type Fournisseur,
  listerFournisseurs,
} from "../api/referentiels";
import { formaterDate, formaterDateHeure, formaterMontant, formaterQuantite, TIRET } from "../lib/formats";
import { libelleMotif } from "../lib/motifs";

type NomChampDocument = keyof ChampsDocument;

/** Champs cités par au moins un motif (`motif.champ`, hors `ligne:<ordre>`) :
 * bordure orange sur le champ concerné (décision du contrôleur, L3-T10). */
function champsSurlignes(motifs: Motif[]): Set<string> {
  const resultat = new Set<string>();
  for (const motif of motifs) {
    if (motif.champ !== null && !motif.champ.startsWith("ligne:")) {
      resultat.add(motif.champ);
    }
  }
  return resultat;
}

/** Ordres de ligne cités par un motif (`champ === "ligne:<ordre>"`) —
 * ligne surlignée dans le tableau/les cartes (décision du contrôleur). */
function lignesSurlignees(motifs: Motif[]): Set<number> {
  const resultat = new Set<number>();
  for (const motif of motifs) {
    if (motif.champ?.startsWith("ligne:") === true) {
      const ordre = Number(motif.champ.slice("ligne:".length));
      if (!Number.isNaN(ordre)) {
        resultat.add(ordre);
      }
    }
  }
  return resultat;
}

/** Motif `somme_incoherente` ou `total_absent` (le seul qui porte la somme
 * des lignes et l'écart au total) : affiché tel que formé par
 * `libelleMotif`, jamais recalculé ici (décision du contrôleur — la somme
 * et l'écart viennent uniquement du `detail` renvoyé par l'API). */
function ResumeSomme({ motifs }: { motifs: Motif[] }): ReactElement | null {
  const motif = motifs.find(
    (candidat) => candidat.code === "somme_incoherente" || candidat.code === "total_absent",
  );
  if (motif === undefined) {
    return null;
  }
  return (
    <p className="mb-3 rounded-md border border-ecart/40 bg-[#fbe9c6] px-3 py-2 text-sm text-[#7a4a00]">
      {libelleMotif(motif)}
    </p>
  );
}

/** Badge de confiance (pourcentage arrondi) : orange si `confiance < seuil`
 * — seule comparaison numérique de deux chaînes décimales autorisée côté
 * front, exclusivement pour la couleur (décision du contrôleur). Absent si
 * la confiance est `null` (champ corrigé à la main, ligne ajoutée). */
function BadgeConfiance({
  confiance,
  seuil,
}: {
  confiance: string | null;
  seuil: string;
}): ReactElement | null {
  if (confiance === null) {
    return null;
  }
  const faible = Number(confiance) < Number(seuil);
  const classes = faible ? "bg-[#fbe9c6] text-[#7a4a00]" : "bg-fond text-encre";
  return (
    <span className={`inline-flex shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}>
      {Math.round(Number(confiance) * 100)} %
    </span>
  );
}

function ChampAffiche({
  libelle,
  champ,
  seuil,
  surligne,
  formater,
}: {
  libelle: string;
  champ: ChampDocument;
  seuil: string;
  surligne: boolean;
  formater?: (valeur: string | null) => string;
}): ReactElement {
  const valeurAffichee = formater ? formater(champ.valeur) : (champ.valeur ?? TIRET);
  return (
    <div
      className={`rounded-md border p-2 ${
        surligne ? "border-ecart bg-[#fbe9c6]" : "border-transparent"
      }`}
    >
      <dt className="flex flex-wrap items-center gap-2 text-xs text-encre-2">
        {libelle}
        <BadgeConfiance confiance={champ.confiance} seuil={seuil} />
      </dt>
      <dd className="text-sm text-encre">{valeurAffichee}</dd>
      {champ.corrige && (
        <p className="mt-1 text-xs text-encre-2">
          Valeur lue : {champ.valeur_ocr ?? TIRET} — corrigée par {champ.corrige_par ?? TIRET} le{" "}
          {formaterDateHeure(champ.corrige_le)}
        </p>
      )}
    </div>
  );
}

const CHAMPS_AFFICHES: Array<{
  cle: NomChampDocument;
  libelle: string;
  formater?: (valeur: string | null) => string;
}> = [
  { cle: "fournisseur", libelle: "Fournisseur" },
  { cle: "numero", libelle: "Numéro" },
  { cle: "date_doc", libelle: "Date", formater: formaterDate },
  { cle: "chantier_brut", libelle: "Chantier indiqué sur le bon" },
  { cle: "numero_commande", libelle: "Commande" },
  { cle: "enleve_par", libelle: "Enlevé par" },
  { cle: "total_ht", libelle: "Total HT", formater: formaterMontant },
  { cle: "total_tva", libelle: "Total TVA", formater: formaterMontant },
  { cle: "total_ttc", libelle: "Total TTC", formater: formaterMontant },
];

// --------------------------------------------------------------------------
// Correction de l'en-tête (PATCH, L3-D13)
// --------------------------------------------------------------------------

interface EnteteBrouillon {
  type: string;
  fournisseurId: string;
  numero: string;
  dateDoc: string;
  chantierBrut: string;
  numeroCommande: string;
  enlevePar: string;
  totalHt: string;
  totalTva: string;
  totalTtc: string;
}

function brouillonEnteteDepuis(donnees: DocumentDetailApi): EnteteBrouillon {
  return {
    type: donnees.type,
    fournisseurId: donnees.fournisseur_id ?? "",
    numero: donnees.champs.numero.valeur ?? "",
    dateDoc: donnees.champs.date_doc.valeur ?? "",
    chantierBrut: donnees.champs.chantier_brut.valeur ?? "",
    numeroCommande: donnees.champs.numero_commande.valeur ?? "",
    enlevePar: donnees.champs.enleve_par.valeur ?? "",
    totalHt: donnees.champs.total_ht.valeur ?? "",
    totalTva: donnees.champs.total_tva.valeur ?? "",
    totalTtc: donnees.champs.total_ttc.valeur ?? "",
  };
}

function videOuTexte(valeur: string): string | null {
  const texte = valeur.trim();
  return texte === "" ? null : texte;
}

function videOuDecimal(valeur: string): string | null {
  const texte = valeur.trim();
  return texte === "" ? null : texte.replace(",", ".");
}

/** Seuls les champs dont la valeur envoyée diffère de la valeur initiale
 * sont inclus (décision du contrôleur : « le serveur distingue absent et
 * `null` », un champ non touché par l'admin ne doit jamais être envoyé). */
function construireCorrection(brouillon: EnteteBrouillon, initial: EnteteBrouillon): CorrectionEntete {
  const correction: CorrectionEntete = {};
  if (brouillon.type !== initial.type) {
    // Le `<select>` n'offre que ces deux valeurs (voir le formulaire) :
    // conversion sûre malgré le typage large de `EnteteBrouillon.type`.
    correction.type = brouillon.type as "bl" | "enlevement";
  }
  if (brouillon.fournisseurId !== initial.fournisseurId) {
    correction.fournisseur_id = brouillon.fournisseurId === "" ? null : brouillon.fournisseurId;
  }
  if (brouillon.numero !== initial.numero) {
    correction.numero = videOuTexte(brouillon.numero);
  }
  if (brouillon.dateDoc !== initial.dateDoc) {
    correction.date_doc = brouillon.dateDoc === "" ? null : brouillon.dateDoc;
  }
  if (brouillon.chantierBrut !== initial.chantierBrut) {
    correction.chantier_brut = videOuTexte(brouillon.chantierBrut);
  }
  if (brouillon.numeroCommande !== initial.numeroCommande) {
    correction.numero_commande = videOuTexte(brouillon.numeroCommande);
  }
  if (brouillon.enlevePar !== initial.enlevePar) {
    correction.enleve_par = videOuTexte(brouillon.enlevePar);
  }
  if (brouillon.totalHt !== initial.totalHt) {
    correction.total_ht = videOuDecimal(brouillon.totalHt);
  }
  if (brouillon.totalTva !== initial.totalTva) {
    correction.total_tva = videOuDecimal(brouillon.totalTva);
  }
  if (brouillon.totalTtc !== initial.totalTtc) {
    correction.total_ttc = videOuDecimal(brouillon.totalTtc);
  }
  return correction;
}

function ChampTexteEntete({
  id,
  label,
  valeur,
  onChange,
  type = "text",
  decimal = false,
}: {
  id: string;
  label: string;
  valeur: string;
  onChange: (valeur: string) => void;
  type?: "text" | "date";
  decimal?: boolean;
}): ReactElement {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-encre">
        {label}
      </label>
      <input
        id={id}
        type={type}
        inputMode={decimal ? "decimal" : undefined}
        value={valeur}
        onChange={(evenement) => onChange(evenement.target.value)}
        className="w-full rounded-md border border-bordure px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
      />
    </div>
  );
}

function FormulaireEntete({
  documentId,
  donnees,
  fournisseurs,
  onEnregistre,
  onAnnuler,
}: {
  documentId: string;
  donnees: DocumentDetailApi;
  fournisseurs: Fournisseur[];
  onEnregistre: (detail: DocumentDetailApi) => void;
  onAnnuler: () => void;
}): ReactElement {
  const [initial] = useState(() => brouillonEnteteDepuis(donnees));
  const [brouillon, setBrouillon] = useState<EnteteBrouillon>(initial);

  const mutation = useMutation({
    mutationFn: (correction: CorrectionEntete) => corrigerEntete(documentId, correction),
    onSuccess: onEnregistre,
  });

  function definir<Champ extends keyof EnteteBrouillon>(champ: Champ, valeur: string): void {
    setBrouillon((precedent) => ({ ...precedent, [champ]: valeur }));
  }

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    const correction = construireCorrection(brouillon, initial);
    if (Object.keys(correction).length === 0) {
      onAnnuler();
      return;
    }
    mutation.mutate(correction);
  }

  return (
    <form
      onSubmit={soumettre}
      className="mb-6 space-y-4 rounded-lg border border-accent/30 bg-fond p-4"
      aria-label="Modifier l'en-tête du document"
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <label htmlFor="entete-type" className="mb-1 block text-xs font-medium text-encre">
            Type
          </label>
          <select
            id="entete-type"
            value={brouillon.type}
            onChange={(evenement) => definir("type", evenement.target.value)}
            className="w-full rounded-md border border-bordure px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <option value="bl">Livraison</option>
            <option value="enlevement">Enlèvement</option>
          </select>
        </div>
        <div>
          <label htmlFor="entete-fournisseur" className="mb-1 block text-xs font-medium text-encre">
            Fournisseur
          </label>
          <select
            id="entete-fournisseur"
            value={brouillon.fournisseurId}
            onChange={(evenement) => definir("fournisseurId", evenement.target.value)}
            className="w-full rounded-md border border-bordure px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <option value="">— Aucun —</option>
            {fournisseurs.map((fournisseur) => (
              <option key={fournisseur.id} value={fournisseur.id}>
                {fournisseur.nom}
              </option>
            ))}
          </select>
        </div>
        <ChampTexteEntete
          id="entete-numero"
          label="Numéro"
          valeur={brouillon.numero}
          onChange={(v) => definir("numero", v)}
        />
        <ChampTexteEntete
          id="entete-date"
          label="Date"
          type="date"
          valeur={brouillon.dateDoc}
          onChange={(v) => definir("dateDoc", v)}
        />
        <ChampTexteEntete
          id="entete-chantier"
          label="Chantier indiqué sur le bon"
          valeur={brouillon.chantierBrut}
          onChange={(v) => definir("chantierBrut", v)}
        />
        <ChampTexteEntete
          id="entete-commande"
          label="Commande"
          valeur={brouillon.numeroCommande}
          onChange={(v) => definir("numeroCommande", v)}
        />
        <ChampTexteEntete
          id="entete-enleve-par"
          label="Enlevé par"
          valeur={brouillon.enlevePar}
          onChange={(v) => definir("enlevePar", v)}
        />
        <ChampTexteEntete
          id="entete-total-ht"
          label="Total HT"
          decimal
          valeur={brouillon.totalHt}
          onChange={(v) => definir("totalHt", v)}
        />
        <ChampTexteEntete
          id="entete-total-tva"
          label="Total TVA"
          decimal
          valeur={brouillon.totalTva}
          onChange={(v) => definir("totalTva", v)}
        />
        <ChampTexteEntete
          id="entete-total-ttc"
          label="Total TTC"
          decimal
          valeur={brouillon.totalTtc}
          onChange={(v) => definir("totalTtc", v)}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={mutation.isPending}
          className="inline-flex min-h-[44px] items-center rounded-md bg-accent px-4 py-2 text-sm font-medium text-white outline-none hover:bg-accent-fonce focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Enregistrer l'en-tête
        </button>
        <button
          type="button"
          onClick={onAnnuler}
          aria-label="Annuler la modification de l'en-tête"
          className="inline-flex min-h-[44px] items-center text-sm font-medium text-encre-2 underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Annuler
        </button>
      </div>

      {mutation.isError && (
        <p role="alert" className="text-sm text-alerte">
          {mutation.error instanceof ErreurApi
            ? mutation.error.detail
            : "Une erreur est survenue, réessayez."}
        </p>
      )}
    </form>
  );
}

// --------------------------------------------------------------------------
// Lecture des lignes (hors édition)
// --------------------------------------------------------------------------

function LignesLecture({
  lignes,
  seuil,
  lignesSurlignees: surlignees,
}: {
  lignes: LigneDocument[];
  seuil: string;
  lignesSurlignees: Set<number>;
}): ReactElement {
  if (lignes.length === 0) {
    return <p className="mb-6 text-sm text-encre-2">Aucune ligne détectée.</p>;
  }
  return (
    <>
      {/* Cartes empilées : téléphone (< md) */}
      <ul className="mb-6 space-y-3 md:hidden">
        {lignes.map((ligne) => (
          <li
            key={ligne.id}
            className={`rounded-lg border p-3 text-sm ${
              surlignees.has(ligne.ordre) ? "border-ecart bg-[#fbe9c6]" : "border-bordure bg-surface"
            }`}
          >
            <div className="mb-2 flex items-start justify-between gap-2">
              <p className="font-medium text-encre">
                {ligne.code_brut ?? TIRET} — {ligne.article_brut ?? TIRET}
              </p>
              <BadgeConfiance confiance={ligne.confiance} seuil={seuil} />
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-encre-2">
              <div>
                <dt>Conditionnements</dt>
                <dd>{formaterQuantite(ligne.qte_livree)}</dd>
              </div>
              <div>
                <dt>Quantité</dt>
                <dd>{formaterQuantite(ligne.qte_totale)}</dd>
              </div>
              <div>
                <dt>Unité</dt>
                <dd>{ligne.unite_brut ?? TIRET}</dd>
              </div>
              <div>
                <dt>PU HT</dt>
                <dd>{formaterMontant(ligne.pu_ht)}</dd>
              </div>
              <div>
                <dt>Montant HT</dt>
                <dd>{formaterMontant(ligne.montant_ht)}</dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>

      {/* Tableau : ordinateur (>= md) */}
      <div className="mb-6 hidden overflow-x-auto rounded-lg border border-bordure bg-surface md:block">
        <table className="w-full min-w-[760px] divide-y divide-bordure text-sm">
          <caption className="sr-only">Lignes du document</caption>
          <thead className="bg-fond text-left text-xs font-medium uppercase tracking-wide text-encre-2">
            <tr>
              <th scope="col" className="px-3 py-2">Code</th>
              <th scope="col" className="px-3 py-2">Désignation</th>
              <th scope="col" className="px-3 py-2">Conditionnements</th>
              <th scope="col" className="px-3 py-2">Quantité</th>
              <th scope="col" className="px-3 py-2">Unité</th>
              <th scope="col" className="px-3 py-2">PU HT</th>
              <th scope="col" className="px-3 py-2">Montant HT</th>
              <th scope="col" className="px-3 py-2">Confiance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-bordure">
            {lignes.map((ligne) => (
              <tr key={ligne.id} className={surlignees.has(ligne.ordre) ? "bg-[#fbe9c6]" : undefined}>
                <td className="px-3 py-2 text-encre">{ligne.code_brut ?? TIRET}</td>
                <td className="px-3 py-2 text-encre">{ligne.article_brut ?? TIRET}</td>
                <td className="px-3 py-2 text-encre">{formaterQuantite(ligne.qte_livree)}</td>
                <td className="px-3 py-2 text-encre">{formaterQuantite(ligne.qte_totale)}</td>
                <td className="px-3 py-2 text-encre">{ligne.unite_brut ?? TIRET}</td>
                <td className="px-3 py-2 text-encre">{formaterMontant(ligne.pu_ht)}</td>
                <td className="px-3 py-2 text-encre">{formaterMontant(ligne.montant_ht)}</td>
                <td className="px-3 py-2">
                  <BadgeConfiance confiance={ligne.confiance} seuil={seuil} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --------------------------------------------------------------------------
// Correction des lignes (PUT, L3-D13)
// --------------------------------------------------------------------------

interface LigneBrouillon {
  cle: string;
  id: string | null;
  codeBrut: string;
  articleBrut: string;
  qteLivree: string;
  qteTotale: string;
  uniteBrut: string;
  puHt: string;
  montantHt: string;
}

function ligneBrouillonDepuis(ligne: LigneDocument): LigneBrouillon {
  return {
    cle: ligne.id,
    id: ligne.id,
    codeBrut: ligne.code_brut ?? "",
    articleBrut: ligne.article_brut ?? "",
    qteLivree: ligne.qte_livree ?? "",
    qteTotale: ligne.qte_totale ?? "",
    uniteBrut: ligne.unite_brut ?? "",
    puHt: ligne.pu_ht ?? "",
    montantHt: ligne.montant_ht ?? "",
  };
}

let compteurNouvelleLigne = 0;

function nouvelleLigneBrouillon(): LigneBrouillon {
  compteurNouvelleLigne += 1;
  return {
    cle: `nouvelle-${compteurNouvelleLigne}`,
    id: null,
    codeBrut: "",
    articleBrut: "",
    qteLivree: "",
    qteTotale: "",
    uniteBrut: "",
    puHt: "",
    montantHt: "",
  };
}

function ligneEnRequete(ligne: LigneBrouillon): LigneSaisie {
  return {
    id: ligne.id,
    code_brut: videOuTexte(ligne.codeBrut),
    article_brut: videOuTexte(ligne.articleBrut),
    qte_livree: videOuDecimal(ligne.qteLivree),
    qte_totale: videOuDecimal(ligne.qteTotale),
    unite_brut: videOuTexte(ligne.uniteBrut),
    pu_ht: videOuDecimal(ligne.puHt),
    montant_ht: videOuDecimal(ligne.montantHt),
  };
}

function ChampLigneEdition({
  id,
  label,
  valeur,
  onChange,
  decimal = false,
  masquerLabel = false,
}: {
  id: string;
  label: string;
  valeur: string;
  onChange: (valeur: string) => void;
  decimal?: boolean;
  masquerLabel?: boolean;
}): ReactElement {
  return (
    <div>
      <label
        htmlFor={id}
        className={masquerLabel ? "sr-only" : "mb-1 block text-xs font-medium text-encre"}
      >
        {label}
      </label>
      <input
        id={id}
        type="text"
        inputMode={decimal ? "decimal" : undefined}
        value={valeur}
        onChange={(evenement) => onChange(evenement.target.value)}
        className="w-full rounded-md border border-bordure px-2 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
      />
    </div>
  );
}

function TableauLignesEdition({
  documentId,
  lignesInitiales,
  onEnregistre,
  onAnnuler,
}: {
  documentId: string;
  lignesInitiales: LigneDocument[];
  onEnregistre: (detail: DocumentDetailApi) => void;
  onAnnuler: () => void;
}): ReactElement {
  const [lignes, setLignes] = useState<LigneBrouillon[]>(() =>
    lignesInitiales.map(ligneBrouillonDepuis),
  );

  const mutation = useMutation({
    mutationFn: () => corrigerLignes(documentId, lignes.map(ligneEnRequete)),
    onSuccess: onEnregistre,
  });

  function modifier(cle: string, champ: keyof LigneBrouillon, valeur: string): void {
    setLignes((precedent) =>
      precedent.map((ligne) => (ligne.cle === cle ? { ...ligne, [champ]: valeur } : ligne)),
    );
  }

  function supprimer(cle: string): void {
    setLignes((precedent) => precedent.filter((ligne) => ligne.cle !== cle));
  }

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    mutation.mutate();
  }

  return (
    <form
      onSubmit={soumettre}
      className="mb-6 space-y-3 rounded-lg border border-accent/30 bg-fond p-4"
      aria-label="Modifier les lignes du document"
    >
      {/* Cartes empilées : téléphone (< md) */}
      <ul className="space-y-3 md:hidden">
        {lignes.map((ligne) => (
          <li key={ligne.cle} className="rounded-lg border border-bordure bg-surface p-3">
            <div className="mb-2 grid grid-cols-2 gap-2">
              <ChampLigneEdition
                id={`code-${ligne.cle}`}
                label="Code"
                valeur={ligne.codeBrut}
                onChange={(v) => modifier(ligne.cle, "codeBrut", v)}
              />
              <ChampLigneEdition
                id={`designation-${ligne.cle}`}
                label="Désignation"
                valeur={ligne.articleBrut}
                onChange={(v) => modifier(ligne.cle, "articleBrut", v)}
              />
              <ChampLigneEdition
                id={`cdt-${ligne.cle}`}
                label="Conditionnements"
                decimal
                valeur={ligne.qteLivree}
                onChange={(v) => modifier(ligne.cle, "qteLivree", v)}
              />
              <ChampLigneEdition
                id={`qte-${ligne.cle}`}
                label="Quantité"
                decimal
                valeur={ligne.qteTotale}
                onChange={(v) => modifier(ligne.cle, "qteTotale", v)}
              />
              <ChampLigneEdition
                id={`unite-${ligne.cle}`}
                label="Unité"
                valeur={ligne.uniteBrut}
                onChange={(v) => modifier(ligne.cle, "uniteBrut", v)}
              />
              <ChampLigneEdition
                id={`pu-${ligne.cle}`}
                label="PU HT"
                decimal
                valeur={ligne.puHt}
                onChange={(v) => modifier(ligne.cle, "puHt", v)}
              />
              <ChampLigneEdition
                id={`montant-${ligne.cle}`}
                label="Montant HT"
                decimal
                valeur={ligne.montantHt}
                onChange={(v) => modifier(ligne.cle, "montantHt", v)}
              />
            </div>
            <button
              type="button"
              onClick={() => supprimer(ligne.cle)}
              className="inline-flex min-h-[44px] items-center text-sm font-medium text-alerte underline outline-none focus-visible:ring-2 focus-visible:ring-alerte"
            >
              Supprimer la ligne
            </button>
          </li>
        ))}
      </ul>

      {/* Tableau : ordinateur (>= md) */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[900px] divide-y divide-bordure text-sm">
          <caption className="sr-only">Lignes du document, en édition</caption>
          <thead className="bg-fond text-left text-xs font-medium uppercase tracking-wide text-encre-2">
            <tr>
              <th scope="col" className="px-2 py-2">Code</th>
              <th scope="col" className="px-2 py-2">Désignation</th>
              <th scope="col" className="px-2 py-2">Cdt</th>
              <th scope="col" className="px-2 py-2">Quantité</th>
              <th scope="col" className="px-2 py-2">Unité</th>
              <th scope="col" className="px-2 py-2">PU HT</th>
              <th scope="col" className="px-2 py-2">Montant HT</th>
              <th scope="col" className="px-2 py-2">
                <span className="sr-only">Supprimer</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-bordure">
            {lignes.map((ligne, index) => (
              <tr key={ligne.cle}>
                <td className="px-2 py-2">
                  <ChampLigneEdition
                    id={`t-code-${ligne.cle}`}
                    label={`Code, ligne ${index + 1}`}
                    masquerLabel
                    valeur={ligne.codeBrut}
                    onChange={(v) => modifier(ligne.cle, "codeBrut", v)}
                  />
                </td>
                <td className="px-2 py-2">
                  <ChampLigneEdition
                    id={`t-designation-${ligne.cle}`}
                    label={`Désignation, ligne ${index + 1}`}
                    masquerLabel
                    valeur={ligne.articleBrut}
                    onChange={(v) => modifier(ligne.cle, "articleBrut", v)}
                  />
                </td>
                <td className="px-2 py-2">
                  <ChampLigneEdition
                    id={`t-cdt-${ligne.cle}`}
                    label={`Conditionnements, ligne ${index + 1}`}
                    masquerLabel
                    decimal
                    valeur={ligne.qteLivree}
                    onChange={(v) => modifier(ligne.cle, "qteLivree", v)}
                  />
                </td>
                <td className="px-2 py-2">
                  <ChampLigneEdition
                    id={`t-qte-${ligne.cle}`}
                    label={`Quantité, ligne ${index + 1}`}
                    masquerLabel
                    decimal
                    valeur={ligne.qteTotale}
                    onChange={(v) => modifier(ligne.cle, "qteTotale", v)}
                  />
                </td>
                <td className="px-2 py-2">
                  <ChampLigneEdition
                    id={`t-unite-${ligne.cle}`}
                    label={`Unité, ligne ${index + 1}`}
                    masquerLabel
                    valeur={ligne.uniteBrut}
                    onChange={(v) => modifier(ligne.cle, "uniteBrut", v)}
                  />
                </td>
                <td className="px-2 py-2">
                  <ChampLigneEdition
                    id={`t-pu-${ligne.cle}`}
                    label={`Prix unitaire HT, ligne ${index + 1}`}
                    masquerLabel
                    decimal
                    valeur={ligne.puHt}
                    onChange={(v) => modifier(ligne.cle, "puHt", v)}
                  />
                </td>
                <td className="px-2 py-2">
                  <ChampLigneEdition
                    id={`t-montant-${ligne.cle}`}
                    label={`Montant HT, ligne ${index + 1}`}
                    masquerLabel
                    decimal
                    valeur={ligne.montantHt}
                    onChange={(v) => modifier(ligne.cle, "montantHt", v)}
                  />
                </td>
                <td className="px-2 py-2">
                  <button
                    type="button"
                    onClick={() => supprimer(ligne.cle)}
                    className="inline-flex min-h-[44px] items-center text-sm font-medium text-alerte underline outline-none focus-visible:ring-2 focus-visible:ring-alerte"
                  >
                    Supprimer
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => setLignes((precedent) => [...precedent, nouvelleLigneBrouillon()])}
          className="inline-flex min-h-[44px] items-center text-sm font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Ajouter une ligne
        </button>
        <button
          type="submit"
          disabled={mutation.isPending}
          className="inline-flex min-h-[44px] items-center rounded-md bg-accent px-4 py-2 text-sm font-medium text-white outline-none hover:bg-accent-fonce focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Enregistrer les lignes
        </button>
        <button
          type="button"
          onClick={onAnnuler}
          aria-label="Annuler la modification des lignes"
          className="inline-flex min-h-[44px] items-center text-sm font-medium text-encre-2 underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Annuler
        </button>
      </div>

      {mutation.isError && (
        <p role="alert" className="text-sm text-alerte">
          {mutation.error instanceof ErreurApi
            ? mutation.error.detail
            : "Une erreur est survenue, réessayez."}
        </p>
      )}
    </form>
  );
}

// --------------------------------------------------------------------------
// Section de correction
// --------------------------------------------------------------------------

/** Section « Corriger la lecture du bon » (Task 8, refonte front) :
 * motifs, champs et lignes lus par la lecture automatique, correction,
 * validation, archivage et relance d'un BL/enlèvement — logique
 * intégralement conservée depuis
 * `GET /api/documents/{id}` (L3-D19, L3-T10), seulement habillée et
 * amputée de son ancien en-tête de page (photo, titre, badge de statut,
 * confirmation) : la page `PageBl` qui la monte, dans un `<details>`
 * repliable, affiche déjà cette information au-dessus. Toujours montée
 * dans le même arbre de route que `PageBl` (`/documents/:id` ou `/bl/:id`),
 * donc `useParams` y lit le même identifiant sans avoir besoin d'une prop.
 * Ouverte à l'admin (tous) et à l'agent (ses dépôts, en lecture seule) —
 * aucune vérification de rôle ici, `donnees.modifiable` (calculé par le
 * service) décide seul de l'affichage des contrôles d'édition ; `PageBl` ne
 * monte de toute façon cette section que lorsque `modifiable` vaut `true`. */
export function DocumentDetail(): ReactElement {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  // Fix round 2 (revue L3-T10) : deux drapeaux indépendants — l'en-tête et
  // les lignes sont deux formulaires distincts, chacun avec son propre
  // brouillon non enregistré (voir `FormulaireEntete`/`TableauLignesEdition`
  // plus bas) ; un seul booléen partagé fermait les deux à l'enregistrement
  // de l'un des deux, perdant silencieusement le brouillon de l'autre.
  const [enEditionEntete, setEnEditionEntete] = useState(false);
  const [enEditionLignes, setEnEditionLignes] = useState(false);
  const [archivageOuvert, setArchivageOuvert] = useState(false);
  const [commentaireArchivage, setCommentaireArchivage] = useState("");

  const document = useQuery({
    queryKey: id !== undefined ? cleDocument(id) : ["document", "sans-identifiant"],
    queryFn: () => lireDocument(id ?? ""),
    enabled: id !== undefined,
  });
  const fournisseurs = useQuery({
    queryKey: CLE_FOURNISSEURS,
    queryFn: listerFournisseurs,
    enabled: enEditionEntete,
  });

  /** Écriture réussie, quelle que soit la mutation (correction d'en-tête,
   * correction de lignes, validation, relance d'extraction, archivage —
   * toutes partagent ce même point de sortie). Invalide aussi les
   * référentiels chantier (Ruling L5-R11, tour de correction 3 de L5-T8) :
   * la correction d'en-tête (`chantier_brut` modifié) et la relance
   * d'extraction (`ingest.extraction_bl._extraire_et_committer` réécrit
   * `document.chantier_id` à chaque relance, y compris quand le chantier
   * résolu ne change pas) réécrivent toutes deux le champ sur lequel
   * repose le calcul du silence — même trou que `valider_alias`/`creer
   * _chantier` sur l'écran « Chantiers & fournisseurs », corrigé ici pour
   * ce même symptôme sur cet écran-ci. Validation et archivage ne touchent
   * jamais `chantier_id` : l'invalidation est inoffensive pour eux (elle
   * ne fait que marquer une liste non montée comme périmée).
   *
   * Revue finale de la refonte du front (constat LIENS-4) : valider,
   * archiver ou relire un bon relance côté serveur la comparaison avec les
   * factures qui le citent (`rapprocher_factures_du_bl`) — des problèmes
   * s'ouvrent ou se ferment. Pastille « À régler », vue d'ensemble,
   * chiffres des chantiers et comparaison du bon sont donc invalidés aussi
   * (`invaliderApresChangementAnomalies`), après la mise à jour immédiate
   * du détail ci-dessous. */
  function surEcriture(detail: DocumentDetailApi): void {
    if (id === undefined) {
      return;
    }
    queryClient.setQueryData(cleDocument(id), detail);
    void queryClient.invalidateQueries({ queryKey: CLE_A_TRAITER });
    void queryClient.invalidateQueries({ queryKey: CLE_DOCUMENTS });
    void queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS });
    void queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS_SILENCIEUX });
    void invaliderApresChangementAnomalies(queryClient);
  }

  /** Fix round 1 (revue L3-T10), corrigé au fix round 2 : une correction
   * réussie referme **seulement la section qu'elle concerne**, plutôt que
   * de laisser `FormulaireEntete`/`TableauLignesEdition` montés avec leur
   * état local d'avant l'écriture (une ligne tout juste créée gardait
   * `id: null` en mémoire, prête à être réinsérée par un second clic). Le
   * « Modifier » suivant de cette section remonte son formulaire (voir la
   * `key` incluant le drapeau d'édition correspondant) à partir du détail à
   * jour renvoyé par l'API — l'autre section, si elle est encore ouverte,
   * n'est jamais touchée : son brouillon non enregistré survit (fix round 2
   * : un seul drapeau partagé perdait silencieusement le brouillon de la
   * section non enregistrée). La trace de la correction (« Valeur lue :
   * … — corrigée par … ») s'affiche tout de suite dans la section
   * refermée, sans qu'il faille annuler ou recharger. */
  function surEcritureEtFermetureEntete(detail: DocumentDetailApi): void {
    surEcriture(detail);
    setEnEditionEntete(false);
  }

  function surEcritureEtFermetureLignes(detail: DocumentDetailApi): void {
    surEcriture(detail);
    setEnEditionLignes(false);
  }

  const mutationValidation = useMutation({
    mutationFn: () => validerDocument(id ?? ""),
    onSuccess: surEcriture,
  });
  const mutationRelance = useMutation({
    mutationFn: () => relancerExtraction(id ?? ""),
    onSuccess: surEcriture,
  });
  const mutationArchivage = useMutation({
    mutationFn: (commentaire: string) => archiverDocument(id ?? "", commentaire),
    onSuccess: (detail) => {
      surEcriture(detail);
      setArchivageOuvert(false);
      setCommentaireArchivage("");
    },
  });

  if (id === undefined) {
    return (
      <p role="alert" className="text-sm text-alerte">
        Document introuvable.
      </p>
    );
  }

  if (document.isPending) {
    return (
      <p role="status" className="text-sm text-encre-2">
        Chargement…
      </p>
    );
  }

  if (document.isError || !document.data) {
    return (
      <p role="alert" className="text-sm text-alerte">
        Document introuvable.
      </p>
    );
  }

  const donnees = document.data;
  const seuil = donnees.seuil_confiance;
  const champsAvecMotif = champsSurlignes(donnees.motifs);
  const lignesAvecMotif = lignesSurlignees(donnees.motifs);

  function relancerAvecConfirmation(): void {
    if (
      window.confirm(
        "Relire le document ? Les valeurs actuelles seront remplacées par une nouvelle lecture automatique.",
      )
    ) {
      mutationRelance.mutate();
    }
  }

  function soumettreArchivage(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    mutationArchivage.mutate(commentaireArchivage);
  }

  return (
    <div>
      {donnees.statut === "a_verifier" && donnees.motifs.length > 0 && (
        <div className="mb-6 rounded-lg border border-ecart/40 bg-[#fbe9c6] p-4">
          <h3 className="mb-2 text-sm font-semibold text-[#7a4a00]">
            Pourquoi une vérification est demandée
          </h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-[#7a4a00]">
            {donnees.motifs.map((motif, index) => (
              <li key={index}>{libelleMotif(motif)}</li>
            ))}
          </ul>
        </div>
      )}

      {donnees.modifiable && !enEditionEntete && (
        <button
          type="button"
          onClick={() => setEnEditionEntete(true)}
          aria-label="Modifier l'en-tête"
          className="inline-flex min-h-[44px] items-center mb-4 rounded-md border border-bordure px-4 py-2 text-sm font-medium text-encre outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
        >
          Modifier
        </button>
      )}

      {enEditionEntete && donnees.modifiable ? (
        <FormulaireEntete
          key={`entete-${donnees.id}-${String(enEditionEntete)}`}
          documentId={donnees.id}
          donnees={donnees}
          fournisseurs={fournisseurs.data ?? []}
          onEnregistre={surEcritureEtFermetureEntete}
          onAnnuler={() => setEnEditionEntete(false)}
        />
      ) : (
        <dl className="mb-2 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {CHAMPS_AFFICHES.map(({ cle, libelle, formater }) => (
            <ChampAffiche
              key={cle}
              libelle={libelle}
              champ={donnees.champs[cle]}
              seuil={seuil}
              surligne={champsAvecMotif.has(cle)}
              formater={formater}
            />
          ))}
        </dl>
      )}

      {!enEditionEntete && (
        <p className="mb-6 text-xs text-encre-2">
          {donnees.agence_fournisseur !== null && <>Agence : {donnees.agence_fournisseur} · </>}
          Chantier rattaché : {donnees.chantier ?? "non rattaché"}
        </p>
      )}

      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-titre text-lg font-medium text-encre">Lignes ({donnees.lignes.length})</h2>
        {donnees.modifiable && !enEditionLignes && (
          <button
            type="button"
            onClick={() => setEnEditionLignes(true)}
            aria-label="Modifier les lignes"
            className="inline-flex min-h-[44px] items-center rounded-md border border-bordure px-4 py-2 text-sm font-medium text-encre outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
          >
            Modifier
          </button>
        )}
      </div>

      <ResumeSomme motifs={donnees.motifs} />

      {enEditionLignes && donnees.modifiable ? (
        <TableauLignesEdition
          key={`lignes-${donnees.id}-${String(enEditionLignes)}`}
          documentId={donnees.id}
          lignesInitiales={donnees.lignes}
          onEnregistre={surEcritureEtFermetureLignes}
          onAnnuler={() => setEnEditionLignes(false)}
        />
      ) : (
        <LignesLecture lignes={donnees.lignes} seuil={seuil} lignesSurlignees={lignesAvecMotif} />
      )}

      {donnees.modifiable && (
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-bordure pt-4">
          {donnees.statut === "a_verifier" && (
            <button
              type="button"
              onClick={() => mutationValidation.mutate()}
              disabled={mutationValidation.isPending}
              className="inline-flex min-h-[44px] items-center rounded-md bg-conforme px-4 py-2 text-sm font-medium text-white outline-none hover:bg-conforme/90 focus-visible:ring-2 focus-visible:ring-conforme focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Valider
            </button>
          )}
          {donnees.statut === "a_verifier" && (
            <button
              type="button"
              onClick={relancerAvecConfirmation}
              disabled={mutationRelance.isPending}
              className="inline-flex min-h-[44px] items-center rounded-md border border-bordure px-4 py-2 text-sm font-medium text-encre outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
            >
              Relire le document
            </button>
          )}
          <button
            type="button"
            onClick={() => setArchivageOuvert((valeur) => !valeur)}
            className="inline-flex min-h-[44px] items-center rounded-md border border-alerte/50 px-4 py-2 text-sm font-medium text-alerte outline-none hover:bg-[#f9dedc] focus-visible:ring-2 focus-visible:ring-alerte"
          >
            Archiver
          </button>
        </div>
      )}

      {mutationValidation.isError && (
        <div role="alert" className="mt-3 rounded-md border border-alerte/30 bg-[#f9dedc] p-3 text-sm text-[#8c1d18]">
          {mutationValidation.error instanceof ValidationRefuseeErreur ? (
            <>
              <p className="mb-1 font-medium">Validation refusée : des points restent à corriger.</p>
              <ul className="list-disc space-y-1 pl-5">
                {mutationValidation.error.motifs.map((motif, index) => (
                  <li key={index}>{libelleMotif(motif)}</li>
                ))}
              </ul>
            </>
          ) : mutationValidation.error instanceof ErreurApi ? (
            mutationValidation.error.detail
          ) : (
            "Une erreur est survenue, réessayez."
          )}
        </div>
      )}

      {mutationRelance.isError && (
        <p role="alert" className="mt-3 text-sm text-alerte">
          {mutationRelance.error instanceof ErreurApi
            ? mutationRelance.error.detail
            : "Une erreur est survenue, réessayez."}
        </p>
      )}

      {archivageOuvert && (
        <form
          onSubmit={soumettreArchivage}
          className="mt-4 space-y-3 rounded-lg border border-alerte/30 bg-[#f9dedc] p-4"
        >
          <div>
            <label
              htmlFor="commentaire-archivage"
              className="mb-1 block text-xs font-medium text-encre"
            >
              Commentaire (obligatoire)
            </label>
            <textarea
              id="commentaire-archivage"
              value={commentaireArchivage}
              onChange={(evenement) => setCommentaireArchivage(evenement.target.value)}
              rows={2}
              className="w-full rounded-md border border-bordure px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={commentaireArchivage.trim() === "" || mutationArchivage.isPending}
              className="inline-flex min-h-[44px] items-center rounded-md bg-alerte px-4 py-2 text-sm font-medium text-white outline-none hover:bg-alerte/90 focus-visible:ring-2 focus-visible:ring-alerte focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Confirmer l'archivage
            </button>
            <button
              type="button"
              onClick={() => setArchivageOuvert(false)}
              className="inline-flex min-h-[44px] items-center text-sm font-medium text-encre-2 underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              Annuler
            </button>
          </div>
          {mutationArchivage.isError && (
            <p role="alert" className="text-sm text-alerte">
              {mutationArchivage.error instanceof ErreurApi
                ? mutationArchivage.error.detail
                : "Une erreur est survenue, réessayez."}
            </p>
          )}
        </form>
      )}
    </div>
  );
}
