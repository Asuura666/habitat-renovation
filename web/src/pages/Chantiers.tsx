import { type FormEvent, type ReactElement, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { CLE_A_TRAITER, obtenirATraiter } from "../api/aTraiter";
import { ErreurApi } from "../api/client";
import {
  CLE_CHANTIERS,
  CLE_CHANTIERS_SILENCIEUX,
  CLE_DEPOTS_PAR_AGENT,
  CLE_FOURNISSEURS,
  type Chantier,
  ChantierEnDoubleErreur,
  creerChantier,
  listerChantiers,
  listerFournisseurs,
  obtenirChantiersSansDepot,
  obtenirDepotsParAgent,
} from "../api/referentiels";
import { AliasCarte } from "../components/AliasCarte";
import { formaterDateHeure, TIRET } from "../lib/formats";

const CLASSES_CHAMP =
  "w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600";
const CLASSES_LABEL = "mb-1 block text-xs font-medium text-slate-700";
const CLASSES_TABLEAU = "overflow-x-auto rounded-lg border border-slate-200 bg-white";

/** Même correspondance que `Gabarit.tsx::LIBELLES_ROLE` (décision du
 * contrôleur : chaque écran garde sa propre table de libellés, comme
 * `libelleTypeDocument` d'`ATraiter.tsx`/`BlDeposes.tsx` — pas de fichier
 * partagé pour une correspondance à deux entrées). */
const LIBELLES_ROLE: Record<string, string> = {
  admin: "Administrateur",
  agent: "Agent",
};

function libelleRole(role: string): string {
  return LIBELLES_ROLE[role] ?? role;
}

function BadgeActif({ actif }: { actif: boolean }): ReactElement {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        actif ? "bg-green-100 text-green-800" : "bg-slate-100 text-slate-600"
      }`}
    >
      {actif ? "Actif" : "Inactif"}
    </span>
  );
}

/** Formulaire de création d'un chantier (route existante, `POST /api
 * /chantiers`) : mêmes champs et même normalisation (agence vide -> `null`)
 * que le mode création d'`AliasCarte`, en autonome ici (pas de rattachement
 * d'alias à faire dans la foulée). */
function FormulaireCreationChantier({ chantiers }: { chantiers: Chantier[] }): ReactElement {
  const queryClient = useQueryClient();
  const [nom, setNom] = useState("");
  const [agence, setAgence] = useState("");

  const creation = useMutation({
    mutationFn: () => creerChantier(nom, agence.trim() === "" ? null : agence.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS });
      setNom("");
      setAgence("");
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
    <form
      onSubmit={soumettre}
      className="mb-4 grid grid-cols-1 items-end gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-[2fr_2fr_auto]"
    >
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
      <button
        type="submit"
        disabled={nom.trim() === "" || creation.isPending}
        className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white outline-none hover:bg-blue-700 focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
      >
        Créer le chantier
      </button>
      {creation.isError && (
        <p role="alert" className="text-sm text-red-700 sm:col-span-3">
          {messageErreur(creation.error)}
        </p>
      )}
    </form>
  );
}

/** Section 1 (décision du contrôleur L5-T8) : référentiel chantier complet
 * (actifs d'abord, tri de l'API), avec la création. Écran « ordinateur »
 * (CDC §4.6) : un seul tableau, défilement horizontal sur téléphone, aucune
 * version en cartes. */
function SectionChantiers({ chantiers }: { chantiers: Chantier[] }): ReactElement {
  return (
    <section>
      <h2 className="mb-3 text-base font-semibold text-slate-900">
        Chantiers ({chantiers.length})
      </h2>
      <FormulaireCreationChantier chantiers={chantiers} />
      {chantiers.length === 0 ? (
        <p className="text-sm text-slate-600">Aucun chantier enregistré.</p>
      ) : (
        <div className={CLASSES_TABLEAU}>
          <table className="w-full min-w-[480px] divide-y divide-slate-200 text-sm">
            <caption className="sr-only">Référentiel des chantiers</caption>
            <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-4 py-3">Nom</th>
                <th scope="col" className="px-4 py-3">Agence</th>
                <th scope="col" className="px-4 py-3">Statut</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {chantiers.map((chantier) => (
                <tr key={chantier.id}>
                  <td className="px-4 py-3 font-medium text-slate-900">{chantier.nom_canonique}</td>
                  <td className="px-4 py-3 text-slate-700">{chantier.agence ?? TIRET}</td>
                  <td className="px-4 py-3">
                    <BadgeActif actif={chantier.actif} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Section 2 : référentiel fournisseur. `GET /api/fournisseurs` n'expose à
 * ce jour que `id`/`nom` (`ingest.referentiels.FournisseurResume`) — les
 * agences d'un fournisseur (table `agence_fournisseur`) ne sont lues que
 * pour la résolution automatique (`normalize.fournisseur.resoudre_agence`)
 * et par la CLI `fournisseur-definir`, jamais renvoyées par une route de
 * lecture. Écart signalé au contrôleur (fiche L5-T8 §6 : « Fournisseurs et
 * leurs agences ») plutôt que d'ajouter une route ou de la deviner : cette
 * tâche ne construit aucune route (consigne du contrôleur). */
function SectionFournisseurs({ fournisseurs }: { fournisseurs: { id: string; nom: string }[] }): ReactElement {
  return (
    <section>
      <h2 className="mb-3 text-base font-semibold text-slate-900">
        Fournisseurs ({fournisseurs.length})
      </h2>
      {fournisseurs.length === 0 ? (
        <p className="text-sm text-slate-600">Aucun fournisseur enregistré.</p>
      ) : (
        <div className={CLASSES_TABLEAU}>
          <table className="w-full min-w-[320px] divide-y divide-slate-200 text-sm">
            <caption className="sr-only">Référentiel des fournisseurs</caption>
            <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-4 py-3">Fournisseur</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {fournisseurs.map((fournisseur) => (
                <tr key={fournisseur.id}>
                  <td className="px-4 py-3 font-medium text-slate-900">{fournisseur.nom}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-xs text-slate-500">
        Les agences par fournisseur ne sont pas exposées par l'API à ce jour (signalé au
        contrôleur).
      </p>
    </section>
  );
}

/** Section 4a : dépôts par personne sur 30 jours (`GET /api/referentiels
 * /depots-par-agent`, fenêtre par défaut de l'API — aucun filtre sur cet
 * écran). Colonne « Rôle » (décision du contrôleur L5-T8) : la liste
 * contient les agents et tout compte ayant déposé, y compris un
 * administrateur (Ruling L5-R7) — sans elle, un lecteur croirait à un agent
 * de plus. */
function SectionDepotsParAgent({
  depots,
}: {
  depots: { agent_id: string; nom: string | null; email: string; role: string; nombre_depots: number }[];
}): ReactElement {
  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold text-slate-900">
        Dépôts par personne (30 derniers jours)
      </h3>
      {depots.length === 0 ? (
        <p className="text-sm text-slate-600">Aucun compte agent enregistré.</p>
      ) : (
        <div className={CLASSES_TABLEAU}>
          <table className="w-full min-w-[480px] divide-y divide-slate-200 text-sm">
            <caption className="sr-only">Dépôts par personne sur 30 jours</caption>
            <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-4 py-3">Personne</th>
                <th scope="col" className="px-4 py-3">Rôle</th>
                <th scope="col" className="px-4 py-3">Dépôts (30 j)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {depots.map((depot) => (
                <tr key={depot.agent_id}>
                  <td className="px-4 py-3 text-slate-700">
                    <p className="font-medium text-slate-900">{depot.nom ?? TIRET}</p>
                    <p className="text-xs text-slate-500">{depot.email}</p>
                  </td>
                  <td className="px-4 py-3 text-slate-700">{libelleRole(depot.role)}</td>
                  <td className="px-4 py-3 text-slate-700">{depot.nombre_depots}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Section 4b : chantiers sans dépôt depuis plus que le seuil de silence
 * (`GET /api/referentiels/chantiers-silencieux`, seuil lu et appliqué
 * côté API — jamais recalculé ici). Décision du contrôleur L5-T8 : mise en
 * évidence (encadré, compte en tête), l'état vide est présenté comme une
 * bonne nouvelle plutôt qu'un simple tableau vide. */
function SectionChantiersSilencieux({
  chantiers,
}: {
  chantiers: { chantier_id: string; nom_canonique: string; agence: string | null; dernier_depot_le: string | null }[];
}): ReactElement {
  if (chantiers.length === 0) {
    return (
      <div className="rounded-lg border border-green-200 bg-green-50 p-4">
        <p className="text-sm font-medium text-green-900">
          Aucun chantier silencieux : tous les chantiers actifs ont déposé récemment.
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p className="mb-3 text-sm font-semibold text-amber-900">
        {chantiers.length} chantier{chantiers.length > 1 ? "s" : ""} sans dépôt récent
      </p>
      <div className="overflow-x-auto rounded-lg border border-amber-100 bg-white">
        <table className="w-full min-w-[480px] divide-y divide-slate-200 text-sm">
          <caption className="sr-only">Chantiers sans dépôt récent</caption>
          <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
            <tr>
              <th scope="col" className="px-4 py-3">Chantier</th>
              <th scope="col" className="px-4 py-3">Agence</th>
              <th scope="col" className="px-4 py-3">Dernier dépôt</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {chantiers.map((chantier) => (
              <tr key={chantier.chantier_id}>
                <td className="px-4 py-3 font-medium text-slate-900">{chantier.nom_canonique}</td>
                <td className="px-4 py-3 text-slate-700">{chantier.agence ?? TIRET}</td>
                <td className="px-4 py-3 text-slate-700">
                  {chantier.dernier_depot_le === null
                    ? "Aucun dépôt enregistré"
                    : formaterDateHeure(chantier.dernier_depot_le)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Écran « Chantiers & fournisseurs » (CDC §4.6, L5-T8), réservé à l'admin
 * (`GardeAdmin`, voir `App.tsx`) : référentiel chantiers (avec création),
 * référentiel fournisseurs, alias en attente de validation et activité de
 * terrain (dépôts par personne, chantiers silencieux). Écran « ordinateur »
 * (décision du contrôleur) : tableaux avec défilement horizontal, aucune
 * version en cartes — contrairement à Bilan/Anomalies. Aucune règle
 * métier ici : chaque valeur affichée vient telle quelle de l'API. */
export function Chantiers(): ReactElement {
  const chantiers = useQuery({ queryKey: CLE_CHANTIERS, queryFn: listerChantiers });
  const fournisseurs = useQuery({ queryKey: CLE_FOURNISSEURS, queryFn: listerFournisseurs });
  const aTraiter = useQuery({ queryKey: CLE_A_TRAITER, queryFn: obtenirATraiter });
  const depotsParAgent = useQuery({
    queryKey: CLE_DEPOTS_PAR_AGENT,
    queryFn: obtenirDepotsParAgent,
  });
  const chantiersSilencieux = useQuery({
    queryKey: CLE_CHANTIERS_SILENCIEUX,
    queryFn: obtenirChantiersSansDepot,
  });

  const chargement =
    chantiers.isPending ||
    fournisseurs.isPending ||
    aTraiter.isPending ||
    depotsParAgent.isPending ||
    chantiersSilencieux.isPending;
  const enErreur =
    chantiers.isError ||
    fournisseurs.isError ||
    aTraiter.isError ||
    depotsParAgent.isError ||
    chantiersSilencieux.isError;

  return (
    <div className="space-y-8">
      <h1 className="text-lg font-semibold text-slate-900">Chantiers &amp; fournisseurs</h1>

      {chargement && (
        <p role="status" className="text-sm text-slate-500">
          Chargement…
        </p>
      )}
      {enErreur && (
        <p role="alert" className="text-sm text-red-700">
          Impossible de charger l'écran « Chantiers &amp; fournisseurs ».
        </p>
      )}

      {chantiers.data && <SectionChantiers chantiers={chantiers.data} />}

      {fournisseurs.data && <SectionFournisseurs fournisseurs={fournisseurs.data} />}

      {aTraiter.data && (
        <section>
          <h2 className="mb-3 text-base font-semibold text-slate-900">
            Alias en attente de validation ({aTraiter.data.alias.length})
          </h2>
          {aTraiter.data.alias.length === 0 ? (
            <p className="text-sm text-slate-600">Aucun alias en attente de validation.</p>
          ) : (
            <ul className="space-y-3">
              {aTraiter.data.alias.map((alias) => (
                <AliasCarte key={alias.id} alias={alias} chantiers={chantiers.data ?? []} />
              ))}
            </ul>
          )}
        </section>
      )}

      {depotsParAgent.data && chantiersSilencieux.data && (
        <section className="space-y-6">
          <h2 className="text-base font-semibold text-slate-900">Activité</h2>
          <SectionDepotsParAgent depots={depotsParAgent.data} />
          <SectionChantiersSilencieux chantiers={chantiersSilencieux.data} />
        </section>
      )}
    </div>
  );
}
