import { useEffect, useState, type MouseEvent, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router";

import { CLE_COMPTE_A_REGLER, type CompteARegler, obtenirCompteARegler } from "../api/aTraiter";
import { urlExportBilanDetail } from "../api/bilan";
import { CLE_MOI, DUREE_CACHE_MOI, recupererMoi } from "../api/moi";
import {
  cleTableauDeBord,
  type TableauDeBord,
  obtenirTableauDeBord,
} from "../api/tableauDeBord";
import { SyntheseCommentaires } from "../components/SyntheseCommentaires";
import {
  Carte,
  Chiffre,
  EnTetePage,
  EtatVide,
  phraseProbleme,
  titreRegle,
} from "../ui";
import { formaterMontant, libelleMois, lireMois, mentionFactureAVerifier, moisApi, TIRET } from "../lib/formats";
import { lienChantier } from "../lib/liens";

type SuiviChantier = TableauDeBord["suivi_chantiers"][number];
type Priorite = TableauDeBord["priorites"][number];

/** `AAAA-MM`, mois restreint à `01`-`12` (correction de revue, tour 1 :
 * `^\d{4}-\d{2}$` acceptait `00` et `13` à `99` — `new Date("2026-13-01")`
 * est invalide et faisait lever `Intl.DateTimeFormat.format` avec
 * `RangeError: Invalid time value`, sans `ErrorBoundary` dans l'app, d'où un
 * écran blanc sur `/?mois=2026-13`). Valide la saisie du sélecteur de mois
 * (`changerMois`) ; la lecture de l'URL passe par `lireMois` (`lib/
 * formats.ts`, même garde, partagée par tous les écrans depuis la revue
 * finale — constat LIENS-5). */
const REGEX_MOIS = /^\d{4}-(0[1-9]|1[0-2])$/;

/** Mois courant au format `AAAA-MM`, fuseau Europe/Paris (brief T5 : « mois
 * courant Europe/Paris » par défaut) — même fuseau que `lib/formats.ts`. */
function moisCourant(): string {
  const formateur = new Intl.DateTimeFormat("fr-FR", {
    timeZone: "Europe/Paris",
    year: "numeric",
    month: "2-digit",
  });
  const parties = formateur.formatToParts(new Date());
  const annee = parties.find((partie) => partie.type === "year")?.value ?? "0000";
  const mois = parties.find((partie) => partie.type === "month")?.value ?? "01";
  return `${annee}-${mois}`;
}

/** Titre de l'en-tête (« Septembre 2026 »), dérivé du mois affiché — mise en
 * forme uniquement, aucun calcul. */
function titreMois(mois: string): string {
  const texte = libelleMois(mois);
  return texte.charAt(0).toUpperCase() + texte.slice(1);
}

/** Premier prénom du dirigeant, ou repli sur la partie locale de son
 * adresse e-mail quand `nom` est absent — mise en forme d'affichage
 * uniquement (surtitre « Bonjour {prénom} », brief T5). */
function prenomAffiche(nom: string | null, email: string): string {
  const source = nom !== null && nom.trim() !== "" ? nom.trim() : (email.split("@")[0] ?? email);
  return source.split(/\s+/)[0] ?? source;
}

/** Nom affiché d'une ligne du suivi : la ligne `chantier_id === null`
 * regroupe les bons sans chantier. */
function nomSuivi(ligne: SuiviChantier): string {
  return ligne.nom_canonique ?? "Sans chantier";
}

/** Facturé du mois, ou « Pas encore » tant que rien n'est facturé pour ce
 * chantier (lot 3, C2). */
function libelleFacture(ligne: SuiviChantier): string {
  return ligne.facture_ht !== null ? formaterMontant(ligne.facture_ht) : "Pas encore";
}

/** Nombre de problèmes, ou tiret quand il n'y en a aucun — valeur déjà
 * comptée côté serveur, jamais recalculée ici. */
function nbProblemesSuivi(ligne: SuiviChantier): string {
  return ligne.nb_problemes > 0 ? String(ligne.nb_problemes) : TIRET;
}

function nbBonsAVerifier(ligne: SuiviChantier): string {
  return ligne.nb_bons_a_verifier > 0 ? String(ligne.nb_bons_a_verifier) : TIRET;
}

/** Ligne du tableau (ordinateur) : toute la ligne ouvre le chantier (clic),
 * et le nom porte le vrai lien pour le clavier et les lecteurs d'écran. */
function LigneChantier({ ligne, lien }: { ligne: SuiviChantier; lien: string }): ReactElement {
  const navigate = useNavigate();

  function gererClic(evenement: MouseEvent<HTMLTableRowElement>): void {
    if (evenement.defaultPrevented) return;
    if ((evenement.target as HTMLElement).closest("a") !== null) return;
    if (evenement.button !== 0 || evenement.metaKey || evenement.ctrlKey || evenement.shiftKey || evenement.altKey) {
      return;
    }
    navigate(lien);
  }

  return (
    <tr onClick={gererClic} className="cursor-pointer hover:bg-fond">
      <th scope="row" className="py-3 pl-1 pr-3 text-left font-normal">
        <Link
          to={lien}
          className="font-medium text-encre outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
        >
          {nomSuivi(ligne)}
        </Link>
      </th>
      <td className="py-3 pr-3 text-right">{ligne.nb_bons}</td>
      <td className="py-3 pr-3 text-right font-mono">{formaterMontant(ligne.montant_bons)}</td>
      <td className="py-3 pr-3 text-right">{nbBonsAVerifier(ligne)}</td>
      <td className="py-3 pr-3 text-right">{nbProblemesSuivi(ligne)}</td>
      <td className="py-3 pr-1 text-right font-mono">{libelleFacture(ligne)}</td>
    </tr>
  );
}

function CarteChantier({ ligne, lien }: { ligne: SuiviChantier; lien: string }): ReactElement {
  return (
    <li>
      <Link
        to={lien}
        className="block rounded-carte border border-bordure bg-surface p-4 outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <p className="font-medium text-encre">{nomSuivi(ligne)}</p>
        <p className="text-xs text-encre-2">
          {ligne.nb_bons} bon{ligne.nb_bons > 1 ? "s" : ""}
        </p>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <div>
            <dt className="text-xs text-encre-2">Montant des bons</dt>
            <dd className="font-mono">{formaterMontant(ligne.montant_bons)}</dd>
          </div>
          <div>
            <dt className="text-xs text-encre-2">Facturé</dt>
            <dd className="font-mono">{libelleFacture(ligne)}</dd>
          </div>
          <div>
            <dt className="text-xs text-encre-2">Bons à vérifier</dt>
            <dd>{nbBonsAVerifier(ligne)}</dd>
          </div>
          <div>
            <dt className="text-xs text-encre-2">Problèmes</dt>
            <dd>{nbProblemesSuivi(ligne)}</dd>
          </div>
        </dl>
      </Link>
    </li>
  );
}

/** Lot 3, C2 : « même si ce n'est pas encore facturé, on peut voir le suivi
 * des chantiers du mois en cours ». Une ligne par chantier qui a un bon ou
 * une facture dans le mois, plus « Sans chantier » ; tri et comptes faits
 * par le serveur. */
function SectionChantiers({ suivi, mois }: { suivi: SuiviChantier[]; mois: string }): ReactElement {
  // La fiche s'ouvre sur le mois affiché ici ; « Sans chantier » mène à
  // « À régler » filtré sur les chantiers à rattacher (`lienChantier(null)`).
  const lien = (ligne: SuiviChantier): string => lienChantier(ligne.chantier_id, mois);

  if (suivi.length === 0) {
    return <EtatVide message="Aucun bon ce mois-ci." />;
  }
  return (
    <>
      {/* Cartes empilées — téléphone (< md) */}
      <ul className="space-y-3 md:hidden">
        {suivi.map((ligne) => (
          <CarteChantier key={ligne.chantier_id ?? "sans-chantier"} ligne={ligne} lien={lien(ligne)} />
        ))}
      </ul>

      {/* Tableau — ordinateur (>= md) */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm text-encre">
          <caption className="sr-only">Suivi des chantiers du mois</caption>
          <thead className="border-b border-bordure text-left text-xs font-medium uppercase tracking-wide text-encre-2">
            <tr>
              <th scope="col" className="pb-2 pl-1 pr-3">Chantier</th>
              <th scope="col" className="pb-2 pr-3 text-right">Bons</th>
              <th scope="col" className="pb-2 pr-3 text-right">Montant des bons</th>
              <th scope="col" className="pb-2 pr-3 text-right">À vérifier</th>
              <th scope="col" className="pb-2 pr-3 text-right">Problèmes</th>
              <th scope="col" className="pb-2 pr-1 text-right">Facturé</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-fond">
            {suivi.map((ligne) => (
              <LigneChantier key={ligne.chantier_id ?? "sans-chantier"} ligne={ligne} lien={lien(ligne)} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function contextePriorite(priorite: Priorite): string {
  const { chantier, fournisseur } = priorite.anomalie;
  return `${chantier ?? "Chantier à rattacher"} · ${fournisseur ?? TIRET}`;
}

function CartePriorite({ priorite }: { priorite: Priorite }): ReactElement {
  // Revue finale (constat COUVERTURE-3) : un problème prioritaire ouvre son
  // détail dans « À régler » (uuid brut, accepté par la route
  // `/a-regler/:id`), là où on peut le contester — plus la fiche chantier.
  const montant = priorite.montant_en_jeu;
  // Un avoir (montant négatif, signé par le serveur comme dans « À
  // régler ») n'est pas une somme perdue : couleur neutre, pas d'alerte.
  const classeMontant = montant !== null && montant.startsWith("-") ? "text-encre-2" : "text-alerte";
  return (
    <li>
      <Link
        to={`/a-regler/${priorite.anomalie.id}`}
        className="flex flex-col gap-1 rounded-lg border border-bordure bg-fond px-3.5 py-3 outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-accent"
      >
        <span className="flex items-start justify-between gap-2">
          <span className="text-sm font-semibold text-encre">{titreRegle(priorite.anomalie.regle)}</span>
          {montant !== null && (
            <span className={`whitespace-nowrap font-mono text-sm ${classeMontant}`}>{formaterMontant(montant)}</span>
          )}
        </span>
        <span className="text-sm text-encre">{phraseProbleme(priorite.anomalie)}</span>
        <span className="text-xs text-encre-2">{contextePriorite(priorite)}</span>
      </Link>
    </li>
  );
}

/** Lien vers « À régler » : il annonce le nombre que l'écran affichera en
 * tête (compte unique du serveur, « en tout », tous mois confondus) —
 * jamais le nombre du seul mois affiché ici. Sans nombre tant que le compte
 * n'est pas chargé. */
function libelleLienARegler(compte: CompteARegler | undefined): string {
  if (compte === undefined) {
    return "Voir tous les problèmes à régler →";
  }
  if (compte.nb_problemes === 0) {
    return "Aucun problème à régler, tous mois confondus";
  }
  return compte.nb_problemes === 1
    ? "Voir l'unique problème à régler →"
    : `Voir les ${compte.nb_problemes} problèmes à régler en tout →`;
}

function SectionPriorites({
  priorites,
  compte,
}: {
  priorites: Priorite[];
  compte: CompteARegler | undefined;
}): ReactElement {
  return (
    <>
      {priorites.length === 0 ? (
        <p className="text-sm text-encre-2">Rien à régler sur les factures de ce mois.</p>
      ) : (
        <ul className="flex flex-col gap-2.5">
          {priorites.map((priorite) => (
            <CartePriorite key={priorite.anomalie.id} priorite={priorite} />
          ))}
        </ul>
      )}
      {/* Revue finale (constats LIENS-2, ECRAN-6, TELEPHONE-2,
          COUVERTURE-2) : « Voir les 6 problèmes » (ceux du mois) ouvrait une
          liste de 10 (tous les mois, plus les bons illisibles et les
          chantiers à rattacher). Le lien annonce désormais le compte
          unique « en tout » — le nombre exact que l'écran « À régler »
          affiche en tête et que porte la pastille de navigation. Toujours
          affiché, même sans problème ce mois-ci : d'autres mois peuvent en
          avoir. */}
      <Link
        to="/a-regler"
        className="mt-3 inline-flex min-h-[44px] items-center text-sm font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
      >
        {libelleLienARegler(compte)}
      </Link>
    </>
  );
}

/** « dont 4 urgents · 10 en tout, tous mois confondus » — urgents du mois affiché,
 * puis le compte unique de toute la liste « À régler ». Espace insécable
 * entre le nombre et « en tout » : au téléphone, « 10 » restait seul en
 * fin de ligne. */
function sousTexteProblemes(nbUrgentsDuMois: number, compte: CompteARegler | undefined): string {
  const urgents = `dont ${nbUrgentsDuMois} urgent${nbUrgentsDuMois > 1 ? "s" : ""}`;
  return compte === undefined ? urgents : `${urgents} · ${compte.nb_problemes}\u00a0en tout, tous mois confondus`;
}

/** Lot 3, C3 : « 2 factures ce mois-ci → » (nombre lu tel quel du serveur). */
function libelleFacturesDuMois(nombre: number): string {
  if (nombre === 0) return "Aucune facture ce mois-ci, voir les factures →";
  return `${nombre} facture${nombre > 1 ? "s" : ""} ce mois-ci →`;
}

function sousTexteBonsRecus(nbManquants: number): string {
  if (nbManquants === 0) {
    return "aucun bon à réclamer";
  }
  return `${nbManquants} bon${nbManquants > 1 ? "s" : ""} à réclamer`;
}

/** Sous-texte de la tuile « Montant des bons du mois » (lot 2, B6,
 * 31/10/2026 : le montant compte tous les bons du mois, même pas encore
 * vérifiés) : « N bon(s) · dont M à vérifier · K sans montant lu », les
 * parties à zéro étant omises. Mise en forme d'affichage seulement : les
 * comptes viennent tels quels du serveur. */
function sousTexteMontantBonsDuMois(nbBons: number, nbAVerifier: number, nbSansMontant: number): string {
  const parties = [nbBons === 0 ? "aucun bon" : `${nbBons} bon${nbBons > 1 ? "s" : ""}`];
  if (nbAVerifier > 0) parties.push(`dont ${nbAVerifier} à vérifier`);
  if (nbSansMontant > 0) parties.push(`${nbSansMontant} sans montant lu`);
  return parties.join(" · ");
}

/** Vue d'ensemble (Task 5, maquette `Main`) — écran d'accueil de l'admin :
 * six chiffres du mois, santé des chantiers, problèmes à régler en
 * priorité. Réservé à l'admin (`GardeAdmin`, voir `App.tsx`) : aucune
 * vérification de rôle ici. Le mois affiché vit dans l'URL (`?mois=AAAA-
 * MM`) — défaut au mois courant Europe/Paris, jamais recalculé côté front
 * au-delà de cette mise en forme (aucune somme/différence/pourcentage sur
 * un montant, chaque valeur vient telle quelle de `GET /api/tableau-de-
 * bord`, y compris le nombre de bons à réclamer depuis la revue finale).
 * Décision d'Ilane du 25/09/2026 : la 3e tuile, autrefois « Écart de
 * quantité » (`totaux.en_ecart`), affiche désormais « Montant des bons du mois » — l'accueil se construisait uniquement à partir des factures, un
 * bon validé mais pas encore retrouvé sur une facture n'y apparaissait
 * nulle part. `libelleEcart`/`sousTexteEcart` restent utilisés par la
 * fiche chantier et la fiche fournisseur, seul cet écran change. */
export function VueEnsemble(): ReactElement {
  const [parametres, setParametres] = useSearchParams();
  const mois = lireMois(parametres.get("mois")) ?? moisCourant();
  const moisPourApi = moisApi(mois);

  const moi = useQuery({ queryKey: CLE_MOI, queryFn: recupererMoi, staleTime: DUREE_CACHE_MOI });
  const tableauDeBord = useQuery({
    queryKey: cleTableauDeBord(moisPourApi),
    queryFn: () => obtenirTableauDeBord(moisPourApi),
  });
  // Compte unique « à régler, en tout » (même clé que la pastille de
  // navigation : un seul appel, un seul nombre à l'écran).
  const compteARegler = useQuery({ queryKey: CLE_COMPTE_A_REGLER, queryFn: obtenirCompteARegler });

  // Brouillon local du sélecteur de mois (correction de revue, tour 1).
  // `mois` ci-dessus est la valeur *effective* (repli sur le mois courant
  // si absente/invalide) : la contrôler directement dans le champ empêchait
  // de saisir un mois, notamment sur Firefox où `type="month"` retombe en
  // champ texte. `brouillonMois` affiche toujours exactement ce que la
  // personne tape ; seule une valeur qui passe `REGEX_MOIS` est poussée dans
  // l'URL. Resynchronisé depuis `mois` quand celui-ci change pour une raison
  // extérieure à la frappe (navigation, lien, retour arrière).
  const [brouillonMois, setBrouillonMois] = useState(mois);
  useEffect(() => {
    setBrouillonMois(mois);
  }, [mois]);

  function changerMois(valeur: string): void {
    setBrouillonMois(valeur);
    if (!REGEX_MOIS.test(valeur)) {
      // Valeur incomplète ou hors bornes : affichée telle quelle dans le
      // champ, jamais poussée dans l'URL.
      return;
    }
    const suivants = new URLSearchParams(parametres);
    suivants.set("mois", valeur);
    setParametres(suivants, { replace: true });
  }

  const donnees = tableauDeBord.data;
  const dernierMoisFacture =
    donnees?.dernier_mois_facture !== null && donnees?.dernier_mois_facture !== undefined
      ? lireMois(donnees.dernier_mois_facture)
      : undefined;

  return (
    <div className="space-y-6">
      <EnTetePage
        surtitre={moi.data ? `Bonjour ${prenomAffiche(moi.data.nom, moi.data.email)}` : undefined}
        titre={titreMois(mois)}
        actions={
          <>
            <div className="flex items-center gap-2">
              <label htmlFor="mois" className="text-sm text-encre-2">
                Mois
              </label>
              <input
                id="mois"
                type="month"
                value={brouillonMois}
                onChange={(evenement) => changerMois(evenement.target.value)}
                className="min-h-[44px] rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </div>
            <a
              href={urlExportBilanDetail({ mois: moisPourApi })}
              className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-accent bg-accent px-4 py-2 text-sm font-medium text-white outline-none hover:bg-accent-fonce focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
            >
              Exporter pour Excel
            </a>
          </>
        }
      />

      {tableauDeBord.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {tableauDeBord.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger la vue d'ensemble.
        </p>
      )}

      {donnees && (
        <>
          {/* Sous-textes (revue finale, constats ECRAN-20, COUVERTURE-4,
              LIENS-2) : décrire ce que le montant contient, sans promettre
              une somme à réclamer que les définitions monétaires (à
              confirmer par Ilane) ne garantissent pas ; préciser que les
              problèmes sont ceux des factures du mois affiché. */}
          <section
            aria-label="Chiffres du mois"
            className="grid grid-cols-2 gap-3.5 md:grid-cols-3 xl:grid-cols-6"
          >
            <Chiffre
              libelle="Facturé ce mois"
              valeur={formaterMontant(donnees.totaux.facture_ht)}
              sousTexte={mentionFactureAVerifier(donnees.totaux.facture_a_verifier)}
            />
            <Chiffre
              libelle="Conforme"
              valeur={formaterMontant(donnees.totaux.conforme)}
              ton="conforme"
              vers={`/livraisons?mois=${moisPourApi}&etat=conforme`}
            />
            <Chiffre
              libelle="Montant des bons du mois"
              valeur={formaterMontant(donnees.montant_bons_mois)}
              sousTexte={sousTexteMontantBonsDuMois(
                donnees.nb_bons_mois,
                donnees.nb_bons_a_verifier,
                donnees.nb_bons_mois_sans_montant,
              )}
            />
            <Chiffre
              libelle="Sans bon de livraison"
              valeur={formaterMontant(donnees.totaux.non_justifie)}
              sousTexte="facturé sans bon reçu"
              ton="alerte"
            />
            {/* Deux périmètres, chacun nommé (revue finale, constats
                LIENS-2, ECRAN-6, TELEPHONE-2, COUVERTURE-2) : le grand
                chiffre compte les problèmes des factures du mois affiché ;
                « … en tout » reprend le compte unique de la pastille et de
                l'écran « À régler ». */}
            <Chiffre
              libelle="Problèmes à régler ce mois"
              valeur={String(donnees.nb_problemes_ouverts)}
              sousTexte={sousTexteProblemes(donnees.nb_problemes_urgents, compteARegler.data)}
            />
            <Chiffre
              libelle="Bons de livraison reçus"
              valeur={`${donnees.nb_bl_recus} / ${donnees.nb_bl_factures}`}
              sousTexte={sousTexteBonsRecus(donnees.nb_bl_manquants)}
            />
          </section>

          {/* Lot 3, C3 : « je trouve pas la facture » -- raccourci discret vers
              la liste des factures. */}
          <Link
            to="/documents?filtre=factures"
            className="inline-flex min-h-[44px] items-center text-sm font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
          >
            {libelleFacturesDuMois(donnees.nb_factures_mois)}
          </Link>
          {/* Complément discret (lot 3, C2) : le cadre « Chantiers » n'est plus
              vide faute de facture, ce raccourci vers le dernier mois facturé
              n'est qu'une commodité (les factures arrivent avec un mois de
              retard). */}
          {dernierMoisFacture !== undefined && dernierMoisFacture !== mois && (
            <Link
              to={`/?mois=${dernierMoisFacture}`}
              className="ml-4 inline-flex min-h-[44px] items-center text-xs text-encre-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
            >
              Dernier mois facturé : {libelleMois(dernierMoisFacture)}
            </Link>
          )}

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <Carte titre="Chantiers" className="xl:col-span-2">
              <SectionChantiers suivi={donnees.suivi_chantiers} mois={mois} />
            </Carte>

            <Carte titre="À régler en priorité" className="flex flex-col">
              <SectionPriorites priorites={donnees.priorites} compte={compteARegler.data} />
            </Carte>
          </div>
        </>
      )}

      {/* Carte « Commentaires de la semaine » (T5, phase 4 IA, spec §4.6) :
          après les chantiers et les problèmes à régler, plus urgents et
          consultés à chaque visite -- cette synthèse hebdomadaire est un
          point d'étape, plus utile en fin de lecture qu'en tête d'écran, où
          elle repousserait sur téléphone les deux sections d'action sous la
          ligne de flottaison. En dehors du `{donnees && (...)}` ci-dessus :
          sa propre requête, indépendante du tableau de bord (une panne de
          l'une n'empêche jamais l'autre de s'afficher). */}
      <SyntheseCommentaires />
    </div>
  );
}
