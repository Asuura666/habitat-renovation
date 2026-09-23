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
  ChantierEnDoubleErreur,
  type ChantierSilencieux,
  creerChantier,
  type DepotAgent,
  listerChantiers,
  obtenirAgences,
  obtenirChantiersSansDepot,
  obtenirDepotsParAgent,
} from "../api/referentiels";
import { cleTableauDeBord, obtenirTableauDeBord, type TableauDeBord } from "../api/tableauDeBord";
import { formaterDateHeure, formaterMontant, TIRET } from "../lib/formats";
import { Bouton, Carte, EnTetePage, type Etat, EtatVide, PastilleEtat } from "../ui";

const CLASSES_CHAMP =
  "min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
const CLASSES_LABEL = "mb-1 block text-xs font-medium text-encre-2";
const CLASSES_LIEN_EXPORT =
  "hidden min-h-[44px] items-center rounded-lg border border-bordure bg-surface px-4 py-2 text-sm font-medium text-encre outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 md:inline-flex";

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
  factureHt: string;
  enEcart: string | null;
  nonJustifie: string | null;
  problemes: number;
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
      etat: chantier.etat as Etat,
      aVerifier: chantier.a_verifier,
      factureHt: chantier.montants.facture_ht,
      enEcart: null,
      nonJustifie: null,
      problemes: chantier.montants.nb_anomalies_ouvertes,
    }));
}

function nomAffiche(ligne: LigneChantierAffichee): string {
  return ligne.nom ?? "Chantier non résolu";
}

function NomChantier({ ligne }: { ligne: LigneChantierAffichee }): ReactElement {
  if (ligne.chantierId === null) {
    return <>{nomAffiche(ligne)}</>;
  }
  return (
    <Link
      to={`/chantiers/${ligne.chantierId}`}
      className="font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
    >
      {nomAffiche(ligne)}
    </Link>
  );
}

function CarteChantier({ ligne }: { ligne: LigneChantierAffichee }): ReactElement {
  return (
    <li className="rounded-carte border border-bordure bg-surface p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-medium text-encre">
            <NomChantier ligne={ligne} />
          </h3>
          <p className="text-sm text-encre-2">
            {ligne.client ?? "Client non renseigné"} · {ligne.agence ?? "Agence non renseignée"}
          </p>
        </div>
        {ligne.etat !== null && <PastilleEtat etat={ligne.etat} />}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div>
          <dt className="text-xs text-encre-2">Facturé</dt>
          <dd className="font-mono tabular-nums text-encre">{formaterMontant(ligne.factureHt)}</dd>
        </div>
        {ligne.etat !== null ? (
          <div>
            <dt className="text-xs text-encre-2">À vérifier</dt>
            <dd className="font-mono tabular-nums text-ecart-texte">
              {formaterMontant(ligne.aVerifier)}
            </dd>
          </div>
        ) : (
          <>
            <div>
              <dt className="text-xs text-encre-2">En écart</dt>
              <dd className="font-mono tabular-nums text-ecart-texte">
                {formaterMontant(ligne.enEcart)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-encre-2">Sans bon</dt>
              <dd className="font-mono tabular-nums text-alerte">
                {formaterMontant(ligne.nonJustifie)}
              </dd>
            </div>
          </>
        )}
        <div>
          <dt className="text-xs text-encre-2">Problèmes</dt>
          <dd className="text-encre">{ligne.problemes}</dd>
        </div>
      </dl>
    </li>
  );
}

function TableauChantiers({ lignes }: { lignes: LigneChantierAffichee[] }): ReactElement {
  const avecEtat = lignes.some((ligne) => ligne.etat !== null);
  return (
    <div className="hidden overflow-x-auto rounded-carte border border-bordure bg-surface md:block">
      <table className="w-full min-w-[880px] divide-y divide-bordure text-sm">
        <caption className="sr-only">Chantiers</caption>
        <thead className="text-left text-xs font-medium uppercase tracking-wide text-encre-2">
          <tr>
            <th scope="col" className="px-4 py-3">Chantier · client</th>
            <th scope="col" className="px-4 py-3">Agence</th>
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
                <NomChantier ligne={ligne} />
                <p className="text-xs font-normal text-encre-2">{ligne.client ?? "Client non renseigné"}</p>
              </th>
              <td className="px-4 py-3 text-encre-2">{ligne.agence ?? TIRET}</td>
              {avecEtat && (
                <td className="px-4 py-3">{ligne.etat !== null && <PastilleEtat etat={ligne.etat} />}</td>
              )}
              <td className="px-4 py-3 text-right font-mono tabular-nums text-encre">
                {formaterMontant(ligne.factureHt)}
              </td>
              {avecEtat ? (
                <td className="px-4 py-3 text-right font-mono tabular-nums text-ecart-texte">
                  {formaterMontant(ligne.aVerifier)}
                </td>
              ) : (
                <>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-ecart-texte">
                    {formaterMontant(ligne.enEcart)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-alerte">
                    {formaterMontant(ligne.nonJustifie)}
                  </td>
                </>
              )}
              <td className="px-4 py-3 text-right text-encre">{ligne.problemes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ListeChantiers({ lignes }: { lignes: LigneChantierAffichee[] }): ReactElement {
  if (lignes.length === 0) {
    return <EtatVide message="Aucun chantier pour ces filtres." />;
  }
  return (
    <>
      <ul className="space-y-3 md:hidden">
        {lignes.map((ligne, index) => (
          <CarteChantier key={ligne.chantierId ?? `non-resolu-${index}`} ligne={ligne} />
        ))}
      </ul>
      <TableauChantiers lignes={lignes} />
    </>
  );
}

/** Bandeau « Chantiers sans bon déposé depuis 7 jours » (reprise de
 * `Chantiers.tsx::SectionChantiersSilencieux`, L5-T8) : seuil lu et calculé
 * côté serveur (`GET /api/referentiels/chantiers-silencieux`), jamais
 * recalculé ici. */
function BandeauSilencieux({ chantiers }: { chantiers: ChantierSilencieux[] }): ReactElement {
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
    <Carte titre="Chantiers sans bon déposé depuis 7 jours" className="border-ecart">
      <ul className="space-y-2 text-sm">
        {chantiers.map((chantier) => (
          <li key={chantier.chantier_id} className="flex flex-wrap items-baseline justify-between gap-2 border-b border-bordure py-2 last:border-0">
            <span className="font-medium text-encre">
              {chantier.nom_canonique} <span className="font-normal text-encre-2">· {chantier.agence ?? "Agence non renseignée"}</span>
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

/** Activité de terrain (reprise de `Chantiers.tsx::SectionDepotsParAgent`,
 * L5-T7/T8, exigée par le CDC §4 « Chantiers & fournisseurs : […] dépôts par
 * agent sur 30 jours ») : qui a déposé quoi sur les 30 derniers jours
 * calendaires. Carte secondaire, sous le tableau des chantiers — ce n'est
 * pas ce qu'un dirigeant regarde en premier (spec §1), mais la
 * fonctionnalité reste accessible (spec §3, « aucune fonctionnalité
 * existante n'est supprimée »). */
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
            <p className="text-xs text-encre-2">{depot.nombre_depots} dépôt{depot.nombre_depots > 1 ? "s" : ""}</p>
          </li>
        ))}
      </ul>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[480px] divide-y divide-bordure text-sm">
          <caption className="sr-only">Dépôts par personne sur 30 jours</caption>
          <thead className="text-left text-xs font-medium uppercase tracking-wide text-encre-2">
            <tr>
              <th scope="col" className="py-2 pr-4">Personne</th>
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
  const filtres: FiltresBilan = {
    mois: parametres.get("mois") || undefined,
    agence: parametres.get("agence") || undefined,
  };
  const moisChoisi = filtres.mois !== undefined;
  const [creationOuverte, setCreationOuverte] = useState(false);

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
  const silencieux = useQuery({ queryKey: CLE_CHANTIERS_SILENCIEUX, queryFn: obtenirChantiersSansDepot });
  const depots = useQuery({ queryKey: CLE_DEPOTS_PAR_AGENT, queryFn: obtenirDepotsParAgent });

  function changerFiltre(nom: "mois" | "agence", valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    const valeurApi = nom === "mois" && valeur !== "" ? `${valeur}-01` : valeur;
    if (valeurApi.trim() === "") suivants.delete(nom);
    else suivants.set(nom, valeurApi);
    setParametres(suivants, { replace: true });
  }

  const lignes = moisChoisi
    ? tableauDeBord.data
      ? depuisTableauDeBord(tableauDeBord.data.chantiers, filtres.agence)
      : undefined
    : bilan.data
      ? depuisBilan(bilan.data)
      : undefined;
  const chargementListe = moisChoisi ? tableauDeBord.isPending : bilan.isPending;
  const erreurListe = moisChoisi ? tableauDeBord.isError : bilan.isError;

  return (
    <div className="space-y-6">
      <EnTetePage
        titre="Chantiers"
        actions={
          <>
            <Bouton variante="secondaire" onClick={() => setCreationOuverte((ouvert) => !ouvert)}>
              Nouveau chantier
            </Bouton>
            <a href={urlExportBilanChantiers(filtres)} className={CLASSES_LIEN_EXPORT}>
              Exporter en CSV
            </a>
            <a href={urlExportBilanDetail(filtres)} className={CLASSES_LIEN_EXPORT}>
              Export détaillé (CSV)
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
        <form onSubmit={(evenement) => evenement.preventDefault()} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="filtre-mois" className={CLASSES_LABEL}>
              Mois de facturation
            </label>
            <input
              id="filtre-mois"
              type="month"
              value={filtres.mois?.slice(0, 7) ?? ""}
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

      {silencieux.data && <BandeauSilencieux chantiers={silencieux.data} />}

      {chargementListe && <p role="status" className="text-sm text-encre-2">Chargement…</p>}
      {erreurListe && <p role="alert" className="text-sm text-alerte">Impossible de charger les chantiers.</p>}
      {lignes && <ListeChantiers lignes={lignes} />}

      {depots.data && <CarteDepotsRecents depots={depots.data} />}
    </div>
  );
}
