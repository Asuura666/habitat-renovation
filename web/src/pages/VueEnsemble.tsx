import type { ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";

import { urlExportBilanDetail } from "../api/bilan";
import { CLE_MOI, DUREE_CACHE_MOI, recupererMoi } from "../api/moi";
import {
  cleTableauDeBord,
  type TableauDeBord,
  obtenirTableauDeBord,
} from "../api/tableauDeBord";
import {
  Carte,
  Chiffre,
  ETATS,
  type Etat,
  EnTetePage,
  EtatVide,
  PastilleEtat,
  phraseProbleme,
  titreRegle,
} from "../ui";
import { formaterMontant, TIRET } from "../lib/formats";

type Chantier = TableauDeBord["chantiers"][number];
type Priorite = TableauDeBord["priorites"][number];

const REGEX_MOIS = /^\d{4}-\d{2}$/;

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
 * forme uniquement, aucun calcul. `mois` est au format `AAAA-MM`. */
function titreMois(mois: string): string {
  // Forme « date seule » (pas de suffixe `T...`), interprétée en UTC par
  // `Date` (même convention que `formaterDate`/`formaterDateHeure`, `lib/
  // formats.ts`) : le fuseau du navigateur n'entre jamais en jeu, seul le
  // `timeZone: "Europe/Paris"` du formateur ci-dessous compte.
  const date = new Date(`${mois}-01`);
  const formateur = new Intl.DateTimeFormat("fr-FR", {
    timeZone: "Europe/Paris",
    month: "long",
    year: "numeric",
  });
  const texte = formateur.format(date);
  return texte.charAt(0).toUpperCase() + texte.slice(1);
}

/** Premier prénom du dirigeant, ou repli sur la partie locale de son
 * adresse e-mail quand `nom` est absent — mise en forme d'affichage
 * uniquement (surtitre « Bonjour {prénom} », brief T5). */
function prenomAffiche(nom: string | null, email: string): string {
  const source = nom !== null && nom.trim() !== "" ? nom.trim() : (email.split("@")[0] ?? email);
  return source.split(/\s+/)[0] ?? source;
}

/** `etat` vient de l'API sous forme de chaîne libre côté schéma OpenAPI
 * (voir `ChantierTableauReponse`, non restreinte au niveau des types
 * générés) : repli défensif sur « à voir » pour toute valeur inconnue,
 * jamais un plantage de `PastilleEtat`. */
function etatValide(etat: string): Etat {
  return (ETATS as readonly string[]).includes(etat) ? (etat as Etat) : "a_voir";
}

/** Nom affiché d'un chantier : celui non résolu (brief T5) porte le nom
 * fixe « Chantier à rattacher » et renvoie vers l'écran « À régler » plutôt
 * que vers une fiche chantier qui n'existe pas encore pour lui. */
function nomChantier(chantier: Chantier): string {
  return chantier.nom_canonique ?? "Chantier à rattacher";
}

function lienChantier(chantier: Chantier): string {
  return chantier.chantier_id === null
    ? "/a-regler?filtre=rattacher"
    : `/chantiers/${chantier.chantier_id}`;
}

/** Nombre de problèmes ouverts d'un chantier, ou tiret cadratin quand il
 * n'y en a aucun (maquette `Main`) — valeur déjà comptée côté serveur,
 * jamais recalculée ici. */
function nbProblemesChantier(chantier: Chantier): string {
  const nb = chantier.montants.nb_anomalies_ouvertes;
  return nb > 0 ? String(nb) : TIRET;
}

function LigneChantier({ chantier }: { chantier: Chantier }): ReactElement {
  return (
    <Link
      to={lienChantier(chantier)}
      className="grid grid-cols-[2.2fr_1.4fr_1fr_1fr_1fr] items-center gap-3 border-b border-fond px-1 py-3 text-sm text-encre outline-none last:border-b-0 hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
    >
      <span className="flex min-w-0 flex-col">
        <span className="truncate font-medium">{nomChantier(chantier)}</span>
        <span className="truncate text-xs text-encre-2">
          {[chantier.client, chantier.agence].filter((valeur) => valeur !== null).join(" · ") || TIRET}
        </span>
      </span>
      <span>
        <PastilleEtat etat={etatValide(chantier.etat)} />
      </span>
      <span className="text-right font-mono">{formaterMontant(chantier.montants.facture_ht)}</span>
      <span className="text-right font-mono">{formaterMontant(chantier.a_verifier)}</span>
      <span className="text-right">{nbProblemesChantier(chantier)}</span>
    </Link>
  );
}

function CarteChantier({ chantier }: { chantier: Chantier }): ReactElement {
  return (
    <li>
      <Link
        to={lienChantier(chantier)}
        className="block rounded-carte border border-bordure bg-surface p-4 outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <p className="font-medium text-encre">{nomChantier(chantier)}</p>
        <p className="text-xs text-encre-2">
          {[chantier.client, chantier.agence].filter((valeur) => valeur !== null).join(" · ") || TIRET}
        </p>
        <div className="mt-3">
          <PastilleEtat etat={etatValide(chantier.etat)} />
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

function SectionChantiers({ chantiers }: { chantiers: Chantier[] }): ReactElement {
  if (chantiers.length === 0) {
    return <EtatVide message="Aucune facture ce mois-ci." />;
  }
  return (
    <>
      {/* Cartes empilées — téléphone (< md) */}
      <ul className="space-y-3 md:hidden">
        {chantiers.map((chantier) => (
          <CarteChantier key={chantier.chantier_id ?? "a-rattacher"} chantier={chantier} />
        ))}
      </ul>

      {/* Tableau — ordinateur (>= md) */}
      <div className="hidden md:block">
        <div className="grid grid-cols-[2.2fr_1.4fr_1fr_1fr_1fr] gap-3 border-b border-bordure px-1 pb-2 text-xs font-medium uppercase tracking-wide text-encre-2">
          <span>Chantier · client</span>
          <span>État</span>
          <span className="text-right">Facturé</span>
          <span className="text-right">À vérifier</span>
          <span className="text-right">Problèmes</span>
        </div>
        <div>
          {chantiers.map((chantier) => (
            <LigneChantier key={chantier.chantier_id ?? "a-rattacher"} chantier={chantier} />
          ))}
        </div>
      </div>
    </>
  );
}

function contextePriorite(priorite: Priorite): string {
  const { chantier, fournisseur } = priorite.anomalie;
  return `${chantier ?? "Chantier à rattacher"} · ${fournisseur ?? TIRET}`;
}

function CartePriorite({ priorite }: { priorite: Priorite }): ReactElement {
  const chemin =
    priorite.anomalie.chantier_id !== null
      ? `/chantiers/${priorite.anomalie.chantier_id}`
      : "/a-regler";
  return (
    <li>
      <Link
        to={chemin}
        className="flex flex-col gap-1 rounded-lg border border-bordure bg-fond px-3.5 py-3 outline-none hover:bg-surface focus-visible:ring-2 focus-visible:ring-accent"
      >
        <span className="flex items-start justify-between gap-2">
          <span className="text-sm font-semibold text-encre">{titreRegle(priorite.anomalie.regle)}</span>
          {priorite.montant_en_jeu !== null && (
            <span className="whitespace-nowrap font-mono text-sm text-alerte">
              {formaterMontant(priorite.montant_en_jeu)}
            </span>
          )}
        </span>
        <span className="text-sm text-encre">{phraseProbleme(priorite.anomalie)}</span>
        <span className="text-xs text-encre-2">{contextePriorite(priorite)}</span>
      </Link>
    </li>
  );
}

function SectionPriorites({
  priorites,
  nbProblemesOuverts,
}: {
  priorites: Priorite[];
  nbProblemesOuverts: number;
}): ReactElement {
  if (priorites.length === 0) {
    return <p className="text-sm text-encre-2">Rien à régler ce mois-ci.</p>;
  }
  return (
    <>
      <ul className="flex flex-col gap-2.5">
        {priorites.map((priorite) => (
          <CartePriorite key={priorite.anomalie.id} priorite={priorite} />
        ))}
      </ul>
      <Link to="/a-regler" className="text-sm font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent">
        Voir les {nbProblemesOuverts} problèmes →
      </Link>
    </>
  );
}

/** Vue d'ensemble (Task 5, maquette `Main`) — écran d'accueil de l'admin :
 * six chiffres du mois, santé des chantiers, problèmes à régler en
 * priorité. Réservé à l'admin (`GardeAdmin`, voir `App.tsx`) : aucune
 * vérification de rôle ici. Le mois affiché vit dans l'URL (`?mois=AAAA-
 * MM`) — défaut au mois courant Europe/Paris, jamais recalculé côté front
 * au-delà de cette mise en forme (aucune somme/différence/pourcentage sur
 * un montant, chaque valeur vient telle quelle de `GET /api/tableau-de-
 * bord`). */
export function VueEnsemble(): ReactElement {
  const [parametres, setParametres] = useSearchParams();
  const moisParam = parametres.get("mois");
  const mois = moisParam !== null && REGEX_MOIS.test(moisParam) ? moisParam : moisCourant();
  const moisApi = `${mois}-01`;

  const moi = useQuery({ queryKey: CLE_MOI, queryFn: recupererMoi, staleTime: DUREE_CACHE_MOI });
  const tableauDeBord = useQuery({
    queryKey: cleTableauDeBord(moisApi),
    queryFn: () => obtenirTableauDeBord(moisApi),
  });

  function changerMois(valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (REGEX_MOIS.test(valeur)) {
      suivants.set("mois", valeur);
    } else {
      suivants.delete("mois");
    }
    setParametres(suivants, { replace: true });
  }

  const donnees = tableauDeBord.data;

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
                value={mois}
                onChange={(evenement) => changerMois(evenement.target.value)}
                className="min-h-[44px] rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent"
              />
            </div>
            <a
              href={urlExportBilanDetail({ mois: moisApi })}
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
              sousTexte="à contester au fournisseur"
              ton="ecart"
            />
            <Chiffre
              libelle="Sans bon de livraison"
              valeur={formaterMontant(donnees.totaux.non_justifie)}
              sousTexte="BL à réclamer à l'équipe"
              ton="alerte"
            />
            <Chiffre
              libelle="Problèmes à régler"
              valeur={String(donnees.nb_problemes_ouverts)}
              sousTexte={`dont ${donnees.nb_problemes_urgents} urgent${donnees.nb_problemes_urgents > 1 ? "s" : ""}`}
            />
            <Chiffre
              libelle="Bons de livraison reçus"
              valeur={`${donnees.nb_bl_recus} / ${donnees.nb_bl_factures}`}
              sousTexte={`${donnees.nb_bl_factures - donnees.nb_bl_recus} manquant${
                donnees.nb_bl_factures - donnees.nb_bl_recus > 1 ? "s" : ""
              } à réclamer`}
            />
          </section>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
            <Carte titre="Chantiers" className="xl:col-span-2">
              <SectionChantiers chantiers={donnees.chantiers} />
            </Carte>

            <Carte titre="À régler en priorité">
              <SectionPriorites
                priorites={donnees.priorites}
                nbProblemesOuverts={donnees.nb_problemes_ouverts}
              />
            </Carte>
          </div>
        </>
      )}
    </div>
  );
}
