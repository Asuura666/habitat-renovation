import { useEffect, useState, type MouseEvent, type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router";

import { urlExportBilanDetail } from "../api/bilan";
import { CLE_MOI, DUREE_CACHE_MOI, recupererMoi } from "../api/moi";
import {
  cleTableauDeBord,
  type TableauDeBord,
  obtenirTableauDeBord,
} from "../api/tableauDeBord";
import { Carte, Chiffre, EnTetePage, EtatVide, PastilleEtat, phraseProbleme, titreRegle } from "../ui";
import { formaterMontant, libelleMois, lireMois, moisApi, TIRET } from "../lib/formats";
import { lienChantier } from "../lib/liens";

type Chantier = TableauDeBord["chantiers"][number];
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

/** Nom affiché d'un chantier : celui non résolu (brief T5) porte le nom
 * fixe « Chantier à rattacher » et renvoie vers l'écran « À régler » plutôt
 * que vers une fiche chantier qui n'existe pas encore pour lui. */
function nomChantier(chantier: Chantier): string {
  return chantier.nom_canonique ?? "Chantier à rattacher";
}

/** « Client · agence », avec « Client non renseigné » plutôt que l'agence
 * seule, qui se lisait comme un nom de client (revue finale, constat
 * ECRAN-19 — même libellé que l'écran « Chantiers »). */
function clientEtAgence(chantier: Chantier): string {
  if (chantier.chantier_id === null) {
    return TIRET;
  }
  const client = chantier.client ?? "Client non renseigné";
  return chantier.agence !== null ? `${client} · ${chantier.agence}` : client;
}

/** Nombre de problèmes ouverts d'un chantier, ou tiret cadratin quand il
 * n'y en a aucun (maquette `Main`) — valeur déjà comptée côté serveur,
 * jamais recalculée ici. */
function nbProblemesChantier(chantier: Chantier): string {
  const nb = chantier.montants.nb_anomalies_ouvertes;
  return nb > 0 ? String(nb) : TIRET;
}

/** Ligne du tableau (ordinateur) : un vrai `<table>` (revue finale, constat
 * COUVERTURE-6 — chaque ligne était une grille indépendante, une pastille
 * longue élargissait sa colonne dans sa seule ligne et désalignait le
 * tableau). Toute la ligne ouvre le chantier (clic), et le nom porte le
 * vrai lien pour le clavier et les lecteurs d'écran — même motif que la
 * carte « Livraisons » de la fiche chantier. */
function LigneChantier({ chantier, lien }: { chantier: Chantier; lien: string }): ReactElement {
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
          {nomChantier(chantier)}
        </Link>
        <span className="block text-xs text-encre-2">{clientEtAgence(chantier)}</span>
      </th>
      <td className="py-3 pr-3">
        <PastilleEtat etat={chantier.etat} />
      </td>
      <td className="py-3 pr-3 text-right font-mono">{formaterMontant(chantier.montants.facture_ht)}</td>
      <td className="py-3 pr-3 text-right font-mono">{formaterMontant(chantier.a_verifier)}</td>
      <td className="py-3 pr-1 text-right">{nbProblemesChantier(chantier)}</td>
    </tr>
  );
}

function CarteChantier({ chantier, lien }: { chantier: Chantier; lien: string }): ReactElement {
  return (
    <li>
      <Link
        to={lien}
        className="block rounded-carte border border-bordure bg-surface p-4 outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <p className="font-medium text-encre">{nomChantier(chantier)}</p>
        <p className="text-xs text-encre-2">{clientEtAgence(chantier)}</p>
        <div className="mt-3">
          <PastilleEtat etat={chantier.etat} />
        </div>
        <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
          <div>
            <dt className="text-xs text-encre-2">Facturé</dt>
            <dd className="font-mono">{formaterMontant(chantier.montants.facture_ht)}</dd>
          </div>
          <div>
            <dt className="text-xs text-encre-2">À vérifier</dt>
            <dd className="font-mono">{formaterMontant(chantier.a_verifier)}</dd>
          </div>
          <div>
            <dt className="text-xs text-encre-2">Problèmes</dt>
            <dd>{nbProblemesChantier(chantier)}</dd>
          </div>
        </dl>
      </Link>
    </li>
  );
}

function SectionChantiers({
  chantiers,
  mois,
  dernierMoisFacture,
}: {
  chantiers: Chantier[];
  mois: string;
  dernierMoisFacture: string | undefined;
}): ReactElement {
  // Revue finale (constats ECRAN-4, COUVERTURE-3) : la fiche s'ouvre sur le
  // mois affiché ici — elle montre alors les mêmes montants que la ligne
  // cliquée, sa pastille d'état et ses quatre chiffres.
  const lien = (chantier: Chantier): string => lienChantier(chantier.chantier_id, mois);

  if (chantiers.length === 0) {
    return (
      <div className="space-y-3">
        <EtatVide message="Aucune facture ce mois-ci." />
        {/* Revue finale (constat COUVERTURE-26) : les factures fournisseur
            sont mensuelles (celle d'août arrive en septembre) — le serveur
            indique le dernier mois facturé, un clic suffit pour y aller. */}
        {dernierMoisFacture !== undefined && dernierMoisFacture !== mois && (
          <Link
            to={`/?mois=${dernierMoisFacture}`}
            className="inline-flex min-h-[44px] items-center text-sm font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
          >
            Voir {libelleMois(dernierMoisFacture)}, dernier mois facturé →
          </Link>
        )}
      </div>
    );
  }
  return (
    <>
      {/* Cartes empilées — téléphone (< md) */}
      <ul className="space-y-3 md:hidden">
        {chantiers.map((chantier) => (
          <CarteChantier key={chantier.chantier_id ?? "a-rattacher"} chantier={chantier} lien={lien(chantier)} />
        ))}
      </ul>

      {/* Tableau — ordinateur (>= md) */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm text-encre">
          <caption className="sr-only">Chantiers du mois</caption>
          <thead className="border-b border-bordure text-left text-xs font-medium uppercase tracking-wide text-encre-2">
            <tr>
              <th scope="col" className="pb-2 pl-1 pr-3">Chantier · client</th>
              <th scope="col" className="pb-2 pr-3">État</th>
              <th scope="col" className="pb-2 pr-3 text-right">Facturé</th>
              <th scope="col" className="pb-2 pr-3 text-right">À vérifier</th>
              <th scope="col" className="pb-2 pr-1 text-right">Problèmes</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-fond">
            {chantiers.map((chantier) => (
              <LigneChantier key={chantier.chantier_id ?? "a-rattacher"} chantier={chantier} lien={lien(chantier)} />
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

function SectionPriorites({ priorites }: { priorites: Priorite[] }): ReactElement {
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
          COUVERTURE-17) : plus de nombre dans ce lien — « Voir les 6
          problèmes » (ceux du mois) ouvrait une liste de 10 (tous les mois,
          plus les bons illisibles et les chantiers à rattacher). Toujours
          affiché, même sans problème ce mois-ci : d'autres mois peuvent en
          avoir. */}
      <Link
        to="/a-regler"
        className="mt-3 inline-flex min-h-[44px] items-center text-sm font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
      >
        Voir tous les problèmes à régler →
      </Link>
    </>
  );
}

function sousTexteBonsRecus(nbManquants: number): string {
  if (nbManquants === 0) {
    return "aucun bon à réclamer";
  }
  return `${nbManquants} bon${nbManquants > 1 ? "s" : ""} à réclamer`;
}

/** Vue d'ensemble (Task 5, maquette `Main`) — écran d'accueil de l'admin :
 * six chiffres du mois, santé des chantiers, problèmes à régler en
 * priorité. Réservé à l'admin (`GardeAdmin`, voir `App.tsx`) : aucune
 * vérification de rôle ici. Le mois affiché vit dans l'URL (`?mois=AAAA-
 * MM`) — défaut au mois courant Europe/Paris, jamais recalculé côté front
 * au-delà de cette mise en forme (aucune somme/différence/pourcentage sur
 * un montant, chaque valeur vient telle quelle de `GET /api/tableau-de-
 * bord`, y compris le nombre de bons à réclamer depuis la revue finale). */
export function VueEnsemble(): ReactElement {
  const [parametres, setParametres] = useSearchParams();
  const mois = lireMois(parametres.get("mois")) ?? moisCourant();
  const moisPourApi = moisApi(mois);

  const moi = useQuery({ queryKey: CLE_MOI, queryFn: recupererMoi, staleTime: DUREE_CACHE_MOI });
  const tableauDeBord = useQuery({
    queryKey: cleTableauDeBord(moisPourApi),
    queryFn: () => obtenirTableauDeBord(moisPourApi),
  });

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
            <Chiffre libelle="Facturé ce mois" valeur={formaterMontant(donnees.totaux.facture_ht)} />
            <Chiffre
              libelle="Conforme"
              valeur={formaterMontant(donnees.totaux.conforme)}
              ton="conforme"
            />
            <Chiffre
              libelle="Écart prix ou quantité"
              valeur={formaterMontant(donnees.totaux.en_ecart)}
              sousTexte="livraisons concernées par un écart"
              ton="ecart"
            />
            <Chiffre
              libelle="Sans bon de livraison"
              valeur={formaterMontant(donnees.totaux.non_justifie)}
              sousTexte="facturé sans bon reçu"
              ton="alerte"
            />
            <Chiffre
              libelle="Problèmes à régler"
              valeur={String(donnees.nb_problemes_ouverts)}
              sousTexte={`dont ${donnees.nb_problemes_urgents} urgent${
                donnees.nb_problemes_urgents > 1 ? "s" : ""
              }, sur les factures du mois`}
            />
            <Chiffre
              libelle="Bons de livraison reçus"
              valeur={`${donnees.nb_bl_recus} / ${donnees.nb_bl_factures}`}
              sousTexte={sousTexteBonsRecus(donnees.nb_bl_manquants)}
            />
          </section>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <Carte titre="Chantiers" className="xl:col-span-2">
              <SectionChantiers
                chantiers={donnees.chantiers}
                mois={mois}
                dernierMoisFacture={dernierMoisFacture}
              />
            </Carte>

            <Carte titre="À régler en priorité" className="flex flex-col">
              <SectionPriorites priorites={donnees.priorites} />
            </Carte>
          </div>
        </>
      )}
    </div>
  );
}
