import { type MouseEvent, type ReactElement } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import type { LigneBilanBl } from "../api/bilan";
import { formaterDate, formaterMontant, TIRET } from "../lib/formats";
import { EtatVide, Filtres, type OptionFiltre } from "../ui";

/** Les seuls champs de `LigneBilanBl`/`LigneLivraison` dont ce composant a
 * besoin (Task 13) : les deux schémas partagent la même forme de
 * `montants`/`statut_rapprochement`/`bl_document_id`/`facture_id`, ce type
 * structurel accepte donc l'un ou l'autre sans conversion -- extrait de
 * `FicheChantier.tsx` (revue finale de la refonte du front), qui ne
 * connaissait jusqu'ici que `LigneBilanBl`. */
type LivraisonMontants = Pick<
  LigneBilanBl,
  "statut_rapprochement" | "bl_document_id" | "facture_id" | "montants"
>;

/** Une livraison affichée par ce composant, sur les trois écrans qui le
 * montent (fiche chantier, fiche fournisseur, `/livraisons`). `chantier`
 * n'est fourni que par les écrans où il varie d'une ligne à l'autre (fiche
 * fournisseur, `/livraisons`) -- la fiche chantier, qui fixe déjà le
 * chantier par son URL, ne le renseigne pas. */
export interface LivraisonAffichee {
  blocId: string;
  numeroBl: string | null;
  dateBl: string | null;
  fournisseur: string;
  chantier?: string;
  ligne: LivraisonMontants;
}

export type CategorieLivraison = "conforme" | "ecart" | "alerte" | "inconnu";

const CLASSES_POINT_STATUT: Record<CategorieLivraison, string> = {
  conforme: "bg-conforme",
  ecart: "bg-ecart",
  alerte: "bg-alerte",
  inconnu: "bg-encre-2",
};

/** État d'une livraison (extrait de l'ancien `EtatBon` de `FicheChantier
 * .tsx`) : reçue sans problème ouvert (conforme), reçue avec un problème
 * ouvert (à vérifier), jamais reçue/livrée sans bon (sans bon) -- même
 * logique que le filtre « Conformes/À vérifier/Sans bon » ci-dessous,
 * jamais deux définitions divergentes du même état. */
export function categorieLivraison(ligne: LivraisonMontants): CategorieLivraison {
  if (ligne.statut_rapprochement === "recu") {
    return ligne.montants.nb_anomalies_ouvertes > 0 ? "ecart" : "conforme";
  }
  if (ligne.statut_rapprochement === "non_recu" || ligne.statut_rapprochement === "pas_de_bon") {
    return "alerte";
  }
  return "inconnu";
}

function libelleStatutBon(statut: string | null): string {
  if (statut === "recu") return "Reçu";
  if (statut === "non_recu") return "Jamais reçu";
  if (statut === "pas_de_bon") return "Livré sans bon";
  return "Statut inconnu";
}

/** Point de couleur + libellé (jamais la couleur seule, spec §2) résumant
 * l'état d'une ligne de livraison — `nb_anomalies_ouvertes` déjà fourni par
 * le serveur, aucun calcul ici. */
function EtatBon({ ligne }: { ligne: LivraisonMontants }): ReactElement {
  const categorie = categorieLivraison(ligne);
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span aria-hidden="true" className={`h-2.5 w-2.5 shrink-0 rounded-full ${CLASSES_POINT_STATUT[categorie]}`} />
      {libelleStatutBon(ligne.statut_rapprochement)}
    </span>
  );
}

/** Destination d'une livraison : la page du BL quand la photo a été
 * retrouvée par le rapprochement, sinon la facture qui la cite. */
export function lienLivraison(ligne: LivraisonMontants): string {
  return ligne.bl_document_id !== null ? `/bl/${ligne.bl_document_id}` : `/documents/${ligne.facture_id}`;
}

/** Problèmes d'une livraison précise : « À régler » filtré sur cette
 * livraison (`?blocId=`), exactement les problèmes comptés dans la colonne
 * « Problèmes » (anomalies ouvertes portées par la livraison). */
function lienProblemesLivraison(livraison: LivraisonAffichee): string {
  return `/a-regler?${new URLSearchParams({ blocId: livraison.blocId }).toString()}`;
}

function libelleProblemesLivraison(nombre: number): string {
  return nombre > 1 ? `Voir les ${nombre} problèmes de cette livraison` : "Voir le problème de cette livraison";
}

function LigneLivraisonCarte({ livraison }: { livraison: LivraisonAffichee }): ReactElement {
  const nbProblemes = livraison.ligne.montants.nb_anomalies_ouvertes;
  return (
    <li className="rounded-lg border border-bordure bg-surface">
      <Link
        to={lienLivraison(livraison.ligne)}
        className="block rounded-lg p-4 outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
      >
        <div className="mb-2 flex items-start justify-between gap-3">
          <div>
            <p className="font-medium text-encre">BL {livraison.numeroBl ?? TIRET}</p>
            <p className="text-xs text-encre-2">
              {formaterDate(livraison.dateBl)} · {livraison.fournisseur}
              {livraison.chantier !== undefined && ` · ${livraison.chantier}`}
            </p>
          </div>
          <p className="font-mono text-sm tabular-nums text-encre">
            {formaterMontant(livraison.ligne.montants.facture_ht)}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <EtatBon ligne={livraison.ligne} />
          <span className="text-encre-2">
            {nbProblemes} problème{nbProblemes > 1 ? "s" : ""}
          </span>
        </div>
      </Link>
      {nbProblemes > 0 && (
        <Link
          to={lienProblemesLivraison(livraison)}
          className="flex min-h-[44px] items-center border-t border-bordure px-4 text-sm font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
        >
          {libelleProblemesLivraison(nbProblemes)}
        </Link>
      )}
    </li>
  );
}

/** Toute la ligne mène vers la page BL : navigation au clic sur la `<tr>`
 * pour la cible tactile la plus large possible, **et** un vrai lien
 * accessible (N° BL) pour le clavier et les lecteurs d'écran — jamais la
 * `<tr>` seule, qui ne serait pas atteignable sans souris. */
function LigneLivraisonTableau({
  livraison,
  colonneChantier,
  naviguer,
}: {
  livraison: LivraisonAffichee;
  colonneChantier: boolean;
  naviguer: () => void;
}): ReactElement {
  // Garde contre la double navigation : le n° BL porte un vrai <Link>
  // (accessibilité clavier/lecteur d'écran) dont le gestionnaire de clic
  // (react-router `useLinkClickHandler`) fait `preventDefault` puis
  // navigue, mais ne fait jamais `stopPropagation` — le clic remonte
  // ensuite jusqu'à cette <tr>, qui naviguerait une seconde fois. On ignore
  // donc les clics déjà traités par un lien (`defaultPrevented` ou une
  // cible à l'intérieur d'un `<a>`) et les clics avec modificateur ou
  // bouton autre que le clic gauche.
  function gererClicLigne(evenement: MouseEvent<HTMLTableRowElement>): void {
    if (evenement.defaultPrevented) return;
    if ((evenement.target as HTMLElement).closest("a") !== null) return;
    if (evenement.button !== 0 || evenement.metaKey || evenement.ctrlKey || evenement.shiftKey || evenement.altKey) {
      return;
    }
    naviguer();
  }

  return (
    <tr onClick={gererClicLigne} className="cursor-pointer outline-none hover:bg-fond focus-within:bg-fond">
      <td className="py-2.5 pl-2 text-encre">{formaterDate(livraison.dateBl)}</td>
      <td className="py-2.5 font-mono text-encre">
        <Link
          to={lienLivraison(livraison.ligne)}
          className="rounded font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
        >
          {livraison.numeroBl ?? TIRET}
        </Link>
      </td>
      {colonneChantier && <td className="py-2.5 pr-2 text-encre">{livraison.chantier ?? TIRET}</td>}
      <td className="py-2.5 pr-2 text-encre">{livraison.fournisseur}</td>
      <td className="py-2.5 pr-2">
        <EtatBon ligne={livraison.ligne} />
      </td>
      <td className="py-2.5 pr-2 text-right font-mono tabular-nums text-encre">
        {formaterMontant(livraison.ligne.montants.facture_ht)}
      </td>
      <td className="py-2.5 pr-2 text-right text-encre">
        {livraison.ligne.montants.nb_anomalies_ouvertes > 0 ? (
          <Link
            to={lienProblemesLivraison(livraison)}
            aria-label={libelleProblemesLivraison(livraison.ligne.montants.nb_anomalies_ouvertes)}
            title={libelleProblemesLivraison(livraison.ligne.montants.nb_anomalies_ouvertes)}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-end rounded font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            {livraison.ligne.montants.nb_anomalies_ouvertes}
          </Link>
        ) : (
          livraison.ligne.montants.nb_anomalies_ouvertes
        )}
      </td>
    </tr>
  );
}

function TableauLivraisonsOrdi({
  livraisons,
  colonneChantier,
}: {
  livraisons: LivraisonAffichee[];
  colonneChantier: boolean;
}): ReactElement {
  const navigate = useNavigate();
  return (
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full text-sm">
        <caption className="sr-only">Livraisons</caption>
        <thead className="text-left text-xs font-medium uppercase tracking-wide text-encre-2">
          <tr>
            <th scope="col" className="py-2 pl-2">Date</th>
            <th scope="col" className="py-2">N° BL</th>
            {colonneChantier && <th scope="col" className="py-2 pr-2">Chantier</th>}
            <th scope="col" className="py-2 pr-2">Fournisseur</th>
            <th scope="col" className="py-2 pr-2">Bon de livraison</th>
            <th scope="col" className="py-2 pr-2 text-right">Montant</th>
            <th scope="col" className="py-2 pr-2 text-right">Problèmes</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-bordure">
          {livraisons.map((livraison) => (
            <LigneLivraisonTableau
              key={livraison.blocId}
              livraison={livraison}
              colonneChantier={colonneChantier}
              naviguer={() => navigate(lienLivraison(livraison.ligne))}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

const OPTIONS_ETAT: OptionFiltre[] = [
  { valeur: "toutes", libelle: "Toutes" },
  { valeur: "conforme", libelle: "Conformes" },
  { valeur: "ecart", libelle: "À vérifier" },
  { valeur: "alerte", libelle: "Sans bon" },
];

const VALEURS_ETAT_CONNUES = new Set(OPTIONS_ETAT.map((option) => option.valeur));

/**
 * Livraisons (Task 13, spec §4.3) : extrait de `FicheChantier.tsx` (revue
 * finale de la refonte du front) — tableau ordinateur + cartes téléphone,
 * plus le filtre d'état `Toutes/Conformes/À vérifier/Sans bon` (nouveau à
 * cette tâche), initialisé par `?etat=` et partagé par les trois écrans qui
 * montent ce composant (fiche chantier, fiche fournisseur, `/livraisons`) —
 * jamais une définition divergente de « conforme » d'un écran à l'autre.
 *
 * `colonneChantier` (défaut `false`) : la fiche chantier fixe déjà son
 * chantier par son URL, elle ne l'affiche pas ; la fiche fournisseur et
 * `/livraisons`, qui listent des livraisons de plusieurs chantiers, la
 * passent à `true`. Ancre `id="livraisons"` (fixe) : cible du lien de la
 * tuile « Conforme » (`Chiffre`, `vers="?etat=conforme#livraisons"`) sur les
 * deux fiches qui embarquent ce composant.
 *
 * `messageVide` distingue « aucune livraison du tout sur ce périmètre »
 * (fourni par l'appelant, qui sait décrire la période) de « aucune ne
 * correspond au filtre d'état choisi » (générique, ce composant le sait
 * déjà).
 */
export function TableauLivraisons({
  livraisons,
  colonneChantier = false,
  messageVide,
}: {
  livraisons: LivraisonAffichee[];
  colonneChantier?: boolean;
  messageVide: string;
}): ReactElement {
  const [parametres, setParametres] = useSearchParams();
  // T13 (revue finale du 27/09/2026) : une valeur `?etat=` inconnue (lien
  // périmé, modifiée à la main) ne doit plus filtrer sur une catégorie qui
  // n'existe pas -- `categorieLivraison` ne renvoie jamais cette valeur,
  // donc `filtrees` restait vide en silence. Repli sur « toutes ».
  const etatParam = parametres.get("etat");
  const etat = etatParam !== null && VALEURS_ETAT_CONNUES.has(etatParam) ? etatParam : "toutes";

  function changerEtat(valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur === "toutes") {
      suivants.delete("etat");
    } else {
      suivants.set("etat", valeur);
    }
    setParametres(suivants, { replace: true });
  }

  const filtrees =
    etat === "toutes" ? livraisons : livraisons.filter((livraison) => categorieLivraison(livraison.ligne) === etat);

  return (
    <div id="livraisons" className="space-y-4">
      {livraisons.length > 0 && <Filtres options={OPTIONS_ETAT} valeur={etat} onChange={changerEtat} />}
      {livraisons.length === 0 ? (
        <EtatVide message={messageVide} />
      ) : filtrees.length === 0 ? (
        <EtatVide message="Aucune livraison ne correspond à ce filtre." />
      ) : (
        <>
          <ul className="space-y-3 md:hidden">
            {filtrees.map((livraison) => (
              <LigneLivraisonCarte key={livraison.blocId} livraison={livraison} />
            ))}
          </ul>
          <TableauLivraisonsOrdi livraisons={filtrees} colonneChantier={colonneChantier} />
        </>
      )}
    </div>
  );
}
