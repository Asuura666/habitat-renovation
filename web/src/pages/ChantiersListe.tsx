import { type FormEvent, type ReactElement, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import {
  cleBilanChantiers,
  type FiltresBilan,
  type LigneBilanChantier,
  listerBilanChantiers,
  urlExportBilanChantiers,
  urlExportBilanDetail,
} from "../api/bilan";
import { ErreurApi } from "../api/client";
import {
  CLE_AGENCES,
  CLE_CHANTIERS,
  CLE_CHANTIERS_SILENCIEUX,
  CLE_DEPOTS_PAR_AGENT,
  type Chantier,
  type ChantierDuMois,
  cleChantiersDuMois,
  ChantierEnDoubleErreur,
  type ChantierSilencieux,
  creerChantier,
  type DepotAgent,
  listerChantiers,
  listerChantiersDuMois,
  obtenirAgences,
  obtenirChantiersSansDepot,
  obtenirDepotsParAgent,
} from "../api/referentiels";
import { CLE_PARAMETRES, listerParametres } from "../api/parametres";
import { cleTableauDeBord, obtenirTableauDeBord, type TableauDeBord } from "../api/tableauDeBord";
import {
  estMontantNul,
  formaterDateHeure,
  formaterMontant,
  lireMois,
  moisApi,
  moisCourantParis,
  TIRET,
} from "../lib/formats";
import { correspondRecherche } from "../lib/recherche";
import { Bouton, Carte, EnTetePage, type Etat, EtatVide, Filtres, PastilleACompleter, PastilleEtat } from "../ui";

const CLASSES_CHAMP =
  "min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
const CLASSES_LABEL = "mb-1 block text-xs font-medium text-encre-2";
// Exports visibles aussi au téléphone (revue finale, constat COUVERTURE-11 :
// ils y étaient masqués) — même habillage que les autres boutons-liens.
const CLASSES_LIEN_EXPORT =
  "inline-flex min-h-[44px] items-center rounded-lg border border-bordure bg-surface px-4 py-2 text-sm font-medium text-encre outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2";

/** Couleur d'un montant d'alerte ou d'écart : neutre quand il vaut zéro
 * (revue finale, constats ECRAN-15/TELEPHONE-11 — « 0,00 € » en rouge ou
 * en orange faisait croire à un problème et diluait l'alerte). Choix de
 * présentation sur une valeur du serveur, jamais un calcul. */
function classeMontant(valeur: string | null, classeSiNonNul: string): string {
  return valeur === null || estMontantNul(valeur) ? "text-encre-2" : classeSiNonNul;
}

/** Une ligne de tableau affichable, qu'elle vienne du bilan brut (tous les
 * mois, `GET /api/bilan/chantiers`) ou du tableau de bord d'un mois choisi
 * (`GET /api/tableau-de-bord`) — deux sources différentes, jamais mélangées
 * ni recalculées l'une à partir de l'autre (voir `depuisBilan`/
 * `depuisTableauDeBord` ci-dessous). `etat`/`aVerifier` valent `null` quand
 * la source est le bilan brut (aucun état calculé sans mois choisi, decision
 * du contrôleur d'après la consigne de la Task 7) : la carte/le tableau
 * affiche alors « En écart »/« Non justifié » séparément plutôt qu'un
 * « À vérifier » qui additionnerait les deux côté front (interdit). */
interface LigneChantierAffichee {
  chantierId: string | null;
  nom: string | null;
  client: string | null;
  agence: string | null;
  etat: Etat | null;
  aVerifier: string | null;
  /** `null` : aucun montant connu pour ce chantier sur la période (un tiret
   * s'affiche). */
  factureHt: string | null;
  enEcart: string | null;
  nonJustifie: string | null;
  problemes: number | null;
  /** Vue « du mois » seulement : bons déposés ce mois-ci (`null` ailleurs). */
  nbBons: number | null;
  /** Vue « tous » seulement : `null` pour la ligne « à rattacher ». */
  actif: boolean | null;
  aCompleter: boolean;
}

function depuisBilan(lignes: LigneBilanChantier[]): LigneChantierAffichee[] {
  return lignes.map((ligne) => ({
    chantierId: ligne.chantier_id,
    nom: ligne.nom_canonique,
    client: ligne.client,
    agence: ligne.agence,
    etat: null,
    aVerifier: null,
    factureHt: ligne.montants.facture_ht,
    enEcart: ligne.montants.en_ecart,
    nonJustifie: ligne.montants.non_justifie,
    problemes: ligne.montants.nb_anomalies_ouvertes,
    nbBons: null,
    actif: null,
    aCompleter: false,
  }));
}

/** `agence` n'est pas un paramètre de `GET /api/tableau-de-bord` (Task 2) :
 * appliqué ici en simple filtre de sélection sur le nom déjà renvoyé par le
 * serveur — une comparaison de chaînes, jamais une somme/écart/pourcentage
 * sur un montant, donc hors de l'interdiction « aucun calcul métier ». */
function depuisTableauDeBord(
  chantiers: TableauDeBord["chantiers"],
  agence: string | undefined,
): LigneChantierAffichee[] {
  return chantiers
    .filter((chantier) => agence === undefined || chantier.agence === agence)
    .map((chantier) => ({
      chantierId: chantier.chantier_id,
      nom: chantier.nom_canonique,
      client: chantier.client,
      agence: chantier.agence,
      etat: chantier.etat,
      aVerifier: chantier.a_verifier,
      factureHt: chantier.montants.facture_ht,
      enEcart: null,
      nonJustifie: null,
      problemes: chantier.montants.nb_anomalies_ouvertes,
      nbBons: null,
      actif: null,
      aCompleter: false,
    }));
}

type Vue = "mois" | "tous";

/** Une ligne par chantier de la vue choisie, jointe par identifiant aux
 * montants déjà chargés (bilan ou tableau de bord selon « Mois de
 * facturation ») : la liste des chantiers vient du serveur (`du-mois`) ou du
 * référentiel complet, jamais d'un calcul ici. Un chantier sans montant
 * garde des tirets. Les montants « sans chantier » (chantier à rattacher)
 * restent en fin de liste, comme avant. */
function lignesDeLaVue(
  vue: Vue,
  chantiers: Chantier[],
  duMois: ChantierDuMois[] | undefined,
  montants: LigneChantierAffichee[],
  agence: string | undefined,
): LigneChantierAffichee[] {
  const montantsParId = new Map<string, LigneChantierAffichee>();
  const sansChantier: LigneChantierAffichee[] = [];
  for (const ligne of montants) {
    if (ligne.chantierId === null) sansChantier.push(ligne);
    else montantsParId.set(ligne.chantierId, ligne);
  }
  const base: { chantier: Chantier; nbBons: number | null }[] =
    vue === "tous"
      ? chantiers
          .filter((chantier) => agence === undefined || chantier.agence === agence)
          .sort((a, b) => a.nom_canonique.localeCompare(b.nom_canonique, "fr"))
          .map((chantier) => ({ chantier, nbBons: null }))
      : (duMois ?? []).flatMap((ligne) => {
          const chantier = chantiers.find((candidat) => candidat.id === ligne.chantier_id);
          return chantier === undefined ? [] : [{ chantier, nbBons: ligne.nb_bons }];
        });
  const lignes = base.map(({ chantier, nbBons }): LigneChantierAffichee => {
    const montant = montantsParId.get(chantier.id);
    return {
      chantierId: chantier.id,
      nom: chantier.nom_canonique,
      client: chantier.client,
      agence: chantier.agence,
      etat: montant?.etat ?? null,
      aVerifier: montant?.aVerifier ?? null,
      factureHt: montant?.factureHt ?? null,
      enEcart: montant?.enEcart ?? null,
      nonJustifie: montant?.nonJustifie ?? null,
      problemes: montant?.problemes ?? null,
      nbBons,
      actif: vue === "tous" ? chantier.actif : null,
      aCompleter: vue === "tous" && chantier.a_completer,
    };
  });
  return [...lignes, ...sansChantier];
}

/** « Chantier à rattacher » (corrections de revue, tour 4, constat 2) :
 * repli d'un bloc dont le fournisseur a résolu un chantier que la
 * normalisation n'a pas su relier à un chantier du référentiel — même
 * libellé que `VueEnsemble.tsx`/`FicheFournisseur.tsx`/`PageBl.tsx` (Tâches
 * 5, 9 et 8, déjà fusionnées dans `refonte-front`). Le texte précédent
 * nommait un mécanisme technique (la résolution d'un nom en entité) sans
 * dire quoi faire ; « à rattacher » pointe vers l'action possible, reprise
 * ci-dessous par `destinationLigne`. */
function nomAffiche(ligne: LigneChantierAffichee): string {
  return ligne.nom ?? "Chantier à rattacher";
}

/** Lien vers la fiche d'un chantier, en reportant le mois choisi sur cet
 * écran (fix round 1, constat 3) : sans ce report, un clic depuis « Chantiers »
 * filtré sur un mois ouvrait la fiche sans aucune indication de période, sur
 * des chiffres d'un tout autre mois (le mois courant implicite de la fiche)
 * — deux périodes différentes sur le même écran, sans libellé. */
function lienChantier(chantierId: string, mois: string | undefined): string {
  if (mois === undefined) {
    return `/chantiers/${chantierId}`;
  }
  return `/chantiers/${chantierId}?${new URLSearchParams({ mois }).toString()}`;
}

/** Destination d'une ligne de chantier (corrections de revue, tour 4,
 * constat 2) : la fiche du chantier s'il est résolu, sinon l'écran « À
 * régler » filtré sur les chantiers à rattacher — même convention que
 * `VueEnsemble.tsx`/`FicheFournisseur.tsx`. Avant ce correctif, un chantier
 * non résolu s'affichait en texte simple, sans aucun lien, dans le tableau
 * principal comme dans les cartes téléphone. */
function destinationLigne(ligne: LigneChantierAffichee, mois: string | undefined): string {
  if (ligne.chantierId === null) {
    return "/a-regler?filtre=rattacher";
  }
  // Le mois de facturation n'est reporté que si la ligne a des montants sur
  // ce mois (02/10/2026) : sinon la fiche s'ouvrirait filtrée sur un mois sans
  // livraison facturée et afficherait « Aucune livraison enregistrée » -- même
  // règle que l'ancienne carte « Tous les chantiers » (fix round 2, constat 1).
  return lienChantier(ligne.chantierId, ligne.factureHt !== null ? mois : undefined);
}

function NomChantier({ ligne, mois }: { ligne: LigneChantierAffichee; mois: string | undefined }): ReactElement {
  return (
    <Link
      to={destinationLigne(ligne, mois)}
      className="font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
    >
      {nomAffiche(ligne)}
    </Link>
  );
}

/** Carte téléphone d'un chantier (< md) : toute la carte est cliquable
 * (corrections de revue, tour 4, constat 1) — avant ce correctif, seul le
 * nom (`NomChantier`, un lien texte sans marge intérieure) menait à la
 * fiche, avec une zone à toucher d'environ 20 à 24 px de haut, sous les
 * 44 px exigés. Même solution que `CarteChantierConcerne`
 * (`FicheFournisseur.tsx`, Task 9) : un `<Link className="block … p-4">`
 * autour de toute la carte plutôt qu'un `min-h-[44px]` sur le seul nom, qui
 * n'aurait pas agrandi la zone cliquable elle-même. Le nom reste un texte
 * simple ici (pas de `NomChantier` imbriqué : un `<a>` ne peut pas contenir
 * un autre `<a>`), la carte entière porte le lien. */
function CarteChantier({
  ligne,
  mois,
  vue,
  avecEtat,
}: {
  ligne: LigneChantierAffichee;
  mois: string | undefined;
  vue: Vue;
  avecEtat: boolean;
}): ReactElement {
  return (
    <li>
      <Link
        to={destinationLigne(ligne, mois)}
        className="block rounded-carte border border-bordure bg-surface p-4 outline-none transition-colors hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h3 className="font-medium text-encre">{nomAffiche(ligne)}</h3>
            <p className="text-sm text-encre-2">
              {ligne.client ?? "Client non renseigné"} · {ligne.agence ?? "Agence non renseignée"}
            </p>
            {vue === "tous" && ligne.actif !== null && (
              <p className={`mt-1 text-xs font-medium ${ligne.actif ? "text-conforme" : "text-encre-2"}`}>
                {ligne.actif ? "Actif" : "Inactif"}
              </p>
            )}
            {ligne.aCompleter && <PastilleACompleter className="mt-1" />}
          </div>
          {ligne.etat !== null && <PastilleEtat etat={ligne.etat} />}
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <div>
            <dt className="text-xs text-encre-2">Facturé</dt>
            <dd className="font-mono tabular-nums text-encre">{formaterMontant(ligne.factureHt)}</dd>
          </div>
          {vue === "mois" && (
            <div>
              <dt className="text-xs text-encre-2">Bons du mois</dt>
              <dd className="text-encre">{ligne.nbBons ?? TIRET}</dd>
            </div>
          )}
          {avecEtat ? (
            <div>
              <dt className="text-xs text-encre-2">À vérifier</dt>
              <dd className={`font-mono tabular-nums ${classeMontant(ligne.aVerifier, "text-ecart-texte")}`}>
                {formaterMontant(ligne.aVerifier)}
              </dd>
            </div>
          ) : (
            <>
              <div>
                <dt className="text-xs text-encre-2">En écart</dt>
                <dd className={`font-mono tabular-nums ${classeMontant(ligne.enEcart, "text-ecart-texte")}`}>
                  {formaterMontant(ligne.enEcart)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-encre-2">Sans bon</dt>
                <dd className={`font-mono tabular-nums ${classeMontant(ligne.nonJustifie, "text-alerte")}`}>
                  {formaterMontant(ligne.nonJustifie)}
                </dd>
              </div>
            </>
          )}
          <div>
            <dt className="text-xs text-encre-2">Problèmes</dt>
            <dd className="text-encre">{ligne.problemes ?? TIRET}</dd>
          </div>
        </dl>
      </Link>
    </li>
  );
}

function TableauChantiers({
  lignes,
  mois,
  vue,
  avecEtat,
}: {
  lignes: LigneChantierAffichee[];
  mois: string | undefined;
  vue: Vue;
  avecEtat: boolean;
}): ReactElement {
  return (
    <div className="hidden overflow-x-auto rounded-carte border border-bordure bg-surface md:block">
      <table className="w-full min-w-[960px] divide-y divide-bordure text-sm">
        <caption className="sr-only">Chantiers</caption>
        <thead className="text-left text-xs font-medium uppercase tracking-wide text-encre-2">
          <tr>
            <th scope="col" className="px-4 py-3">Chantier · client</th>
            <th scope="col" className="px-4 py-3">Agence</th>
            {vue === "mois" ? (
              <th scope="col" className="px-4 py-3 text-right">Bons du mois</th>
            ) : (
              <th scope="col" className="px-4 py-3">Statut</th>
            )}
            {avecEtat && <th scope="col" className="px-4 py-3">État</th>}
            <th scope="col" className="px-4 py-3 text-right">Facturé</th>
            {avecEtat ? (
              <th scope="col" className="px-4 py-3 text-right">À vérifier</th>
            ) : (
              <>
                <th scope="col" className="px-4 py-3 text-right">En écart</th>
                <th scope="col" className="px-4 py-3 text-right">Sans bon</th>
              </>
            )}
            <th scope="col" className="px-4 py-3 text-right">Problèmes</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-bordure">
          {lignes.map((ligne, index) => (
            <tr key={ligne.chantierId ?? `non-resolu-${index}`}>
              <th scope="row" className="px-4 py-3 text-left font-medium text-encre">
                <NomChantier ligne={ligne} mois={mois} />
                <p className="text-xs font-normal text-encre-2">{ligne.client ?? "Client non renseigné"}</p>
              </th>
              <td className="px-4 py-3 text-encre-2">{ligne.agence ?? TIRET}</td>
              {vue === "mois" ? (
                <td className="px-4 py-3 text-right text-encre">{ligne.nbBons ?? TIRET}</td>
              ) : (
                <td className="px-4 py-3">
                  {ligne.actif !== null && (
                    <span className={`font-medium ${ligne.actif ? "text-conforme" : "text-encre-2"}`}>
                      {ligne.actif ? "Actif" : "Inactif"}
                    </span>
                  )}
                  {ligne.aCompleter && <PastilleACompleter className="ml-2" />}
                </td>
              )}
              {avecEtat && (
                <td className="px-4 py-3">{ligne.etat !== null && <PastilleEtat etat={ligne.etat} />}</td>
              )}
              <td className="px-4 py-3 text-right font-mono tabular-nums text-encre">
                {formaterMontant(ligne.factureHt)}
              </td>
              {avecEtat ? (
                <td
                  className={`px-4 py-3 text-right font-mono tabular-nums ${classeMontant(ligne.aVerifier, "text-ecart-texte")}`}
                >
                  {formaterMontant(ligne.aVerifier)}
                </td>
              ) : (
                <>
                  <td
                    className={`px-4 py-3 text-right font-mono tabular-nums ${classeMontant(ligne.enEcart, "text-ecart-texte")}`}
                  >
                    {formaterMontant(ligne.enEcart)}
                  </td>
                  <td
                    className={`px-4 py-3 text-right font-mono tabular-nums ${classeMontant(ligne.nonJustifie, "text-alerte")}`}
                  >
                    {formaterMontant(ligne.nonJustifie)}
                  </td>
                </>
              )}
              <td className="px-4 py-3 text-right text-encre">{ligne.problemes ?? TIRET}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ListeChantiers({
  lignes,
  mois,
  vue,
  avecEtat,
}: {
  lignes: LigneChantierAffichee[];
  mois: string | undefined;
  vue: Vue;
  avecEtat: boolean;
}): ReactElement {
  if (lignes.length === 0) {
    return <EtatVide message="Aucun chantier pour ces filtres." />;
  }
  return (
    <>
      <ul className="space-y-3 md:hidden">
        {lignes.map((ligne, index) => (
          <CarteChantier
            key={ligne.chantierId ?? `non-resolu-${index}`}
            ligne={ligne}
            mois={mois}
            vue={vue}
            avecEtat={avecEtat}
          />
        ))}
      </ul>
      <TableauChantiers lignes={lignes} mois={mois} vue={vue} avecEtat={avecEtat} />
    </>
  );
}

/** Clé du navigateur qui retient si la carte « sans bon déposé » est
 * dépliée (repliée tant qu'aucun choix n'est enregistré). Lecture et écriture
 * dans un `try/catch` : en navigation privée, le stockage peut être
 * indisponible, la carte reste alors simplement repliée au chargement. */
const CLE_SILENCIEUX_OUVERT = "habitat.chantiers.silencieux.ouvert";

function lireSilencieuxOuvert(): boolean {
  try {
    return window.localStorage.getItem(CLE_SILENCIEUX_OUVERT) === "1";
  } catch {
    return false;
  }
}

function ecrireSilencieuxOuvert(ouvert: boolean): void {
  try {
    window.localStorage.setItem(CLE_SILENCIEUX_OUVERT, ouvert ? "1" : "0");
  } catch {
    // Stockage indisponible : le choix n'est simplement pas retenu.
  }
}

/** Bandeau « Chantiers sans bon déposé depuis N jours » (reprise de
 * `Chantiers.tsx::SectionChantiersSilencieux`, L5-T8) : seuil lu et calculé
 * côté serveur (`GET /api/referentiels/chantiers-silencieux`), jamais
 * recalculé ici. Chaque nom mène à la fiche du chantier (fix round 1,
 * constat 1) : avant, ce bandeau affichait des noms sans aucun lien —
 * impossible d'ouvrir la fiche d'un chantier silencieux pour, par exemple,
 * constater qu'il vient d'être créé. Lien isolé au milieu d'une ligne dense
 * (nom · agence · dernier dépôt) : plutôt que rendre toute la `<li>`
 * cliquable (ce qui masquerait le reste de la ligne), le lien lui-même
 * garantit une cible d'au moins 44 px (`inline-flex min-h-[44px]
 * items-center`, corrections de revue, tour 4, constat 1). */
function BandeauSilencieux({
  chantiers,
  delaiJours,
}: {
  chantiers: ChantierSilencieux[];
  delaiJours: string | undefined;
}): ReactElement {
  const [ouvert, setOuvert] = useState(lireSilencieuxOuvert);
  function basculer(): void {
    const suivant = !ouvert;
    setOuvert(suivant);
    ecrireSilencieuxOuvert(suivant);
  }
  // Revue finale (constat COUVERTURE-20) : le délai est un réglage
  // (`delai_chantier_silencieux_j`, écran Réglages) — le titre ne l'écrit
  // plus en dur (« 7 jours » devenait faux dès qu'il changeait) ; valeur lue
  // telle quelle sur `GET /api/parametres`, repli sans chiffre.
  const titre =
    delaiJours !== undefined
      ? `Chantiers sans bon déposé depuis ${delaiJours} jours`
      : "Chantiers sans bon déposé récemment";
  if (chantiers.length === 0) {
    return (
      <Carte className="border-conforme bg-[#e4f1ea]">
        <p className="text-sm font-medium text-encre">
          Aucun chantier silencieux : tous les chantiers actifs ont déposé un bon récemment.
        </p>
      </Carte>
    );
  }
  return (
    <Carte className="border-ecart">
      <h2 className="font-titre text-xl font-medium text-encre">
        <button
          type="button"
          aria-expanded={ouvert}
          aria-controls="liste-chantiers-silencieux"
          onClick={basculer}
          className="flex min-h-[44px] w-full items-center justify-between gap-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <span>
            {titre} ({chantiers.length})
          </span>
          <span aria-hidden="true" className="text-encre-2">
            {ouvert ? "▾" : "▸"}
          </span>
        </button>
      </h2>
      <ul id="liste-chantiers-silencieux" hidden={!ouvert} className="mt-4 space-y-2 text-sm">
        {chantiers.map((chantier) => (
          <li key={chantier.chantier_id} className="flex flex-wrap items-baseline justify-between gap-2 border-b border-bordure py-2 last:border-0">
            <span className="font-medium text-encre">
              <Link
                to={lienChantier(chantier.chantier_id, undefined)}
                className="inline-flex min-h-[44px] items-center text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
              >
                {chantier.nom_canonique}
              </Link>{" "}
              <span className="font-normal text-encre-2">· {chantier.agence ?? "Agence non renseignée"}</span>
            </span>
            <span className="text-encre-2">
              {chantier.dernier_depot_le === null
                ? "Aucun dépôt enregistré"
                : `Dernier dépôt le ${formaterDateHeure(chantier.dernier_depot_le)}`}
            </span>
          </li>
        ))}
      </ul>
    </Carte>
  );
}

/** Même correspondance que `Comptes.tsx::LIBELLES_ROLE` (repris tel quel,
 * corrections de revue tour 3, constat 1 ; libellé « agent » aligné sur
 * « Employé » par le Ruling C5 de la revue finale du 27/09/2026 -- les deux
 * écrans disaient un mot différent pour le même rôle) : `DepotAgent.role`
 * porte la valeur brute d'`Utilisateur.role` (`admin`/`agent`), jamais un
 * libellé affichable. Sans cette table, un administrateur qui a déposé un
 * bon apparaîtrait comme un employé de terrain de plus — exactement la
 * confusion que le Ruling L5-R7 (décision du contrôleur) et l'ajout du
 * champ côté serveur (`ingest/referentiels_vue.py`, tour de correction 1
 * bis) visaient à éviter. Chaque écran garde sa propre table de deux
 * entrées (décision du contrôleur, pas de fichier partagé pour une
 * correspondance aussi courte). */
const LIBELLES_ROLE: Record<string, string> = {
  admin: "Administrateur",
  agent: "Employé",
};

function libelleRole(role: string): string {
  return LIBELLES_ROLE[role] ?? role;
}

/** Activité de terrain (reprise de `Chantiers.tsx::SectionDepotsParAgent`,
 * L5-T7/T8, exigée par le CDC §4 « Chantiers & fournisseurs : […] dépôts par
 * agent sur 30 jours ») : qui a déposé quoi sur les 30 derniers jours
 * calendaires. Carte secondaire, sous le tableau des chantiers — ce n'est
 * pas ce qu'un dirigeant regarde en premier (spec §1), mais la
 * fonctionnalité reste accessible (spec §3, « aucune fonctionnalité
 * existante n'est supprimée »). Rôle affiché à côté du nom (corrections de
 * revue tour 3, constat 1) : disparu de cette carte alors que l'ancien
 * `Chantiers.tsx` l'affichait (colonne « Rôle », Ruling L5-R7) — sans lui,
 * un administrateur ayant déposé un bon se confondait avec un agent de
 * terrain. */
function CarteDepotsRecents({ depots }: { depots: DepotAgent[] }): ReactElement {
  if (depots.length === 0) {
    return (
      <Carte titre="Dépôts récents (30 jours)">
        <p className="text-sm text-encre-2">Aucun compte agent enregistré.</p>
      </Carte>
    );
  }
  return (
    <Carte titre="Dépôts récents (30 jours)">
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:hidden">
        {depots.map((depot) => (
          <li key={depot.agent_id} className="rounded-lg border border-bordure p-3">
            <p className="truncate text-sm font-medium text-encre">{depot.nom ?? TIRET}</p>
            <p className="text-xs text-encre-2">
              {libelleRole(depot.role)} · {depot.nombre_depots} dépôt{depot.nombre_depots > 1 ? "s" : ""}
            </p>
          </li>
        ))}
      </ul>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[480px] divide-y divide-bordure text-sm">
          <caption className="sr-only">Dépôts par personne sur 30 jours</caption>
          <thead className="text-left text-xs font-medium uppercase tracking-wide text-encre-2">
            <tr>
              <th scope="col" className="py-2 pr-4">Personne</th>
              <th scope="col" className="py-2 pr-4">Rôle</th>
              <th scope="col" className="py-2 pr-4">Dépôts (30 j)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-bordure">
            {depots.map((depot) => (
              <tr key={depot.agent_id}>
                <td className="py-2 pr-4">
                  <p className="font-medium text-encre">{depot.nom ?? TIRET}</p>
                  <p className="text-xs text-encre-2">{depot.email}</p>
                </td>
                <td className="py-2 pr-4 text-encre-2">{libelleRole(depot.role)}</td>
                <td className="py-2 pr-4 text-encre">{depot.nombre_depots}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Carte>
  );
}

/** Formulaire de création (nom, client, agence — brief Task 7) : reprise du
 * formulaire de `Chantiers.tsx`, `client` en plus (Task 1). Repliable
 * derrière le bouton « Nouveau chantier » de l'en-tête plutôt que toujours
 * visible (écran désormais centré sur la liste, pas sur la création). */
function FormulaireCreationChantier({
  chantiers,
  onCree,
}: {
  chantiers: Chantier[];
  onCree: () => void;
}): ReactElement {
  const queryClient = useQueryClient();
  const [nom, setNom] = useState("");
  const [client, setClient] = useState("");
  const [agence, setAgence] = useState("");

  const creation = useMutation({
    mutationFn: () =>
      creerChantier(nom, agence.trim() === "" ? null : agence.trim(), client.trim() === "" ? null : client.trim()),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS }),
        queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS_SILENCIEUX }),
        queryClient.invalidateQueries({ queryKey: CLE_BILAN_CHANTIERS_TOUTES }),
        // tâche T7 (audit rapidité) : une nouvelle agence saisie ici (champ
        // libre) n'apparaissait dans le filtre « Agence » de cet écran
        // qu'après un remontage — masqué tant que `staleTime` valait 0
        // (`agences_connues` relit `chantier.agence` en base à chaque appel,
        // `ingest/referentiels_vue.py`), révélé par le nouveau défaut de
        // 30 s (`main.tsx`).
        queryClient.invalidateQueries({ queryKey: CLE_AGENCES }),
      ]);
      setNom("");
      setClient("");
      setAgence("");
      onCree();
    },
  });

  function messageErreur(erreur: unknown): string {
    if (erreur instanceof ChantierEnDoubleErreur) {
      const existant = chantiers.find((chantier) => chantier.id === erreur.originalId);
      return existant
        ? `Le chantier « ${existant.nom_canonique} » existe déjà.`
        : "Ce chantier existe déjà.";
    }
    if (erreur instanceof ErreurApi) {
      return erreur.detail;
    }
    return "Une erreur est survenue, réessayez.";
  }

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    creation.mutate();
  }

  return (
    <Carte titre="Nouveau chantier">
      <form onSubmit={soumettre} className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[2fr_2fr_1.5fr_auto]">
        <div>
          <label htmlFor="nouveau-chantier-nom" className={CLASSES_LABEL}>
            Nom du chantier
          </label>
          <input
            id="nouveau-chantier-nom"
            type="text"
            value={nom}
            onChange={(evenement) => setNom(evenement.target.value)}
            className={CLASSES_CHAMP}
          />
        </div>
        <div>
          <label htmlFor="nouveau-chantier-client" className={CLASSES_LABEL}>
            Client
          </label>
          <input
            id="nouveau-chantier-client"
            type="text"
            value={client}
            onChange={(evenement) => setClient(evenement.target.value)}
            className={CLASSES_CHAMP}
          />
        </div>
        <div>
          <label htmlFor="nouveau-chantier-agence" className={CLASSES_LABEL}>
            Agence
          </label>
          <input
            id="nouveau-chantier-agence"
            type="text"
            value={agence}
            onChange={(evenement) => setAgence(evenement.target.value)}
            className={CLASSES_CHAMP}
          />
        </div>
        <Bouton type="submit" disabled={nom.trim() === "" || creation.isPending}>
          Créer le chantier
        </Bouton>
        {creation.isError && (
          <p role="alert" className="text-sm text-alerte sm:col-span-4">
            {messageErreur(creation.error)}
          </p>
        )}
      </form>
    </Carte>
  );
}

const CLE_BILAN_CHANTIERS_TOUTES = cleBilanChantiers({});

export function ChantiersListe(): ReactElement {
  const [parametres, setParametres] = useSearchParams();
  // Mois de l'URL au format `AAAA-MM` (convention unique depuis la revue
  // finale, constat LIENS-5 ; `AAAA-MM-01` des anciens liens accepté par
  // `lireMois`), converti en `AAAA-MM-01` au seul moment de l'appel à l'API.
  const mois = lireMois(parametres.get("mois"));
  const filtres: FiltresBilan = {
    mois: mois !== undefined ? moisApi(mois) : undefined,
    agence: parametres.get("agence") || undefined,
  };
  const moisChoisi = mois !== undefined;
  // Vue choisie (`?vue=tous`, absent = chantiers du mois) et mois des
  // chantiers (`?mois_chantiers=AAAA-MM`, mois en cours par défaut) : deux
  // réglages distincts du « Mois de facturation » ci-dessus, qui ne pilote
  // que les montants.
  const vue: Vue = parametres.get("vue") === "tous" ? "tous" : "mois";
  const moisChantiers = lireMois(parametres.get("mois_chantiers")) ?? moisCourantParis();
  const [creationOuverte, setCreationOuverte] = useState(false);
  // Lot 2, B2 : recherche par nom (et client), côté écran seulement.
  const [recherche, setRecherche] = useState("");

  const chantiers = useQuery({ queryKey: CLE_CHANTIERS, queryFn: listerChantiers });
  const agences = useQuery({ queryKey: CLE_AGENCES, queryFn: obtenirAgences });
  const bilan = useQuery({
    queryKey: cleBilanChantiers(filtres),
    queryFn: () => listerBilanChantiers(filtres),
    enabled: !moisChoisi,
  });
  const tableauDeBord = useQuery({
    queryKey: cleTableauDeBord(filtres.mois ?? ""),
    queryFn: () => obtenirTableauDeBord(filtres.mois ?? ""),
    enabled: moisChoisi,
  });
  const duMois = useQuery({
    queryKey: cleChantiersDuMois(moisApi(moisChantiers), filtres.agence),
    queryFn: () => listerChantiersDuMois(moisApi(moisChantiers), filtres.agence),
  });
  const silencieux = useQuery({ queryKey: CLE_CHANTIERS_SILENCIEUX, queryFn: obtenirChantiersSansDepot });
  const depots = useQuery({ queryKey: CLE_DEPOTS_PAR_AGENT, queryFn: obtenirDepotsParAgent });
  const reglages = useQuery({ queryKey: CLE_PARAMETRES, queryFn: listerParametres });
  const delaiSilence = reglages.data?.find((parametre) => parametre.cle === "delai_chantier_silencieux_j")?.valeur;

  function changerFiltre(nom: "mois" | "mois_chantiers" | "agence", valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur.trim() === "") suivants.delete(nom);
    else suivants.set(nom, valeur);
    setParametres(suivants, { replace: true });
  }

  function changerVue(valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur === "tous") suivants.set("vue", "tous");
    else suivants.delete("vue");
    setParametres(suivants, { replace: true });
  }

  const montants = moisChoisi
    ? tableauDeBord.data
      ? depuisTableauDeBord(tableauDeBord.data.chantiers, filtres.agence)
      : undefined
    : bilan.data
      ? depuisBilan(bilan.data)
      : undefined;
  const toutesLesLignes =
    montants !== undefined && chantiers.data !== undefined && (vue === "tous" || duMois.data !== undefined)
      ? lignesDeLaVue(vue, chantiers.data, duMois.data, montants, filtres.agence)
      : undefined;
  const lignes = toutesLesLignes?.filter((ligne) => correspondRecherche(recherche, ligne.nom, ligne.client));
  const chargementListe =
    (moisChoisi ? tableauDeBord.isPending : bilan.isPending) ||
    chantiers.isPending ||
    (vue === "mois" && duMois.isPending);
  const erreurListe =
    (moisChoisi ? tableauDeBord.isError : bilan.isError) || chantiers.isError || (vue === "mois" && duMois.isError);
  const nbChantiersDuMois = duMois.data?.length;
  const nbTousLesChantiers = chantiers.data?.filter(
    (chantier) => filtres.agence === undefined || chantier.agence === filtres.agence,
  ).length;

  return (
    <div className="space-y-6">
      <EnTetePage
        titre="Chantiers"
        actions={
          <>
            <Bouton variante="secondaire" onClick={() => setCreationOuverte((ouvert) => !ouvert)}>
              Nouveau chantier
            </Bouton>
            {/* Libellés alignés sur la vue d'ensemble (revue finale,
                constat COUVERTURE-11 : le nom du format de fichier était un terme technique). */}
            <a href={urlExportBilanChantiers(filtres)} className={CLASSES_LIEN_EXPORT}>
              Exporter pour Excel
            </a>
            <a href={urlExportBilanDetail(filtres)} className={CLASSES_LIEN_EXPORT}>
              Exporter le détail pour Excel
            </a>
          </>
        }
      />

      {creationOuverte && (
        <FormulaireCreationChantier
          chantiers={chantiers.data ?? []}
          onCree={() => setCreationOuverte(false)}
        />
      )}

      <Carte>
        <form onSubmit={(evenement) => evenement.preventDefault()} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label htmlFor="filtre-recherche" className={CLASSES_LABEL}>
              Rechercher un chantier
            </label>
            <input
              id="filtre-recherche"
              type="search"
              value={recherche}
              onChange={(evenement) => setRecherche(evenement.target.value)}
              placeholder="Nom ou client"
              autoComplete="off"
              className={CLASSES_CHAMP}
            />
          </div>
          <div>
            <label htmlFor="filtre-mois-chantiers" className={CLASSES_LABEL}>
              Mois
            </label>
            <input
              id="filtre-mois-chantiers"
              type="month"
              value={moisChantiers}
              disabled={vue === "tous"}
              onChange={(evenement) => changerFiltre("mois_chantiers", evenement.target.value)}
              className={`${CLASSES_CHAMP} disabled:opacity-60`}
            />
          </div>
          <div>
            <label htmlFor="filtre-mois" className={CLASSES_LABEL}>
              Mois de facturation
            </label>
            <input
              id="filtre-mois"
              type="month"
              value={mois ?? ""}
              onChange={(evenement) => changerFiltre("mois", evenement.target.value)}
              className={CLASSES_CHAMP}
              placeholder="Tous les mois"
            />
          </div>
          <div>
            <label htmlFor="filtre-agence" className={CLASSES_LABEL}>
              Agence
            </label>
            <select
              id="filtre-agence"
              value={filtres.agence ?? ""}
              onChange={(evenement) => changerFiltre("agence", evenement.target.value)}
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
      </Carte>

      {silencieux.data && <BandeauSilencieux chantiers={silencieux.data} delaiJours={delaiSilence} />}

      <Filtres
        options={[
          {
            valeur: "mois",
            libelle: `Chantiers du mois${nbChantiersDuMois === undefined ? "" : ` (${nbChantiersDuMois})`}`,
          },
          {
            valeur: "tous",
            libelle: `Tous les chantiers${nbTousLesChantiers === undefined ? "" : ` (${nbTousLesChantiers})`}`,
          },
        ]}
        valeur={vue}
        onChange={changerVue}
      />

      {chargementListe && <p role="status" className="text-sm text-encre-2">Chargement…</p>}
      {erreurListe && <p role="alert" className="text-sm text-alerte">Impossible de charger les chantiers.</p>}
      {lignes && <ListeChantiers lignes={lignes} mois={mois} vue={vue} avecEtat={moisChoisi} />}

      {depots.data && <CarteDepotsRecents depots={depots.data} />}
    </div>
  );
}
