import { type ReactElement, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { type EntreeJournal, type FiltresJournal, cleJournal, listerJournal } from "../api/journal";
import { formaterDateHeure, TIRET } from "../lib/formats";
import { ACTIONS_CONNUES, CIBLES_CONNUES, libelleAction, libelleAuteur, lignesAvantApres } from "../lib/journal";

const CLASSES_CHAMP =
  "w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600";
const CLASSES_LABEL = "mb-1 block text-xs font-medium text-slate-700";
const CLASSES_TABLEAU = "overflow-x-auto rounded-lg border border-slate-200 bg-white";

const OPTIONS_LIMITE = [50, 100, 200, 500] as const;
const LIMITE_DEFAUT = 100;

/** Comparaison `avant`/`apres` d'une entrée (décision du contrôleur, L5-T9) :
 * clé par clé, valeurs telles quelles, une clé absente d'un côté marquée
 * explicitement — aucune traduction, aucun calcul (voir `lib/journal.ts`). */
function DetailAvantApres({
  avant,
  apres,
}: {
  avant: EntreeJournal["avant"];
  apres: EntreeJournal["apres"];
}): ReactElement {
  const lignes = lignesAvantApres(avant, apres);
  if (lignes.length === 0) {
    return <p className="text-slate-500">Aucun détail conservé pour cette action.</p>;
  }
  return (
    <ul className="space-y-1">
      {lignes.map((ligne) => (
        <li key={ligne.cle}>
          <span className="font-medium text-slate-700">{ligne.cle}</span>
          {" : "}
          {ligne.avant}
          {" → "}
          {ligne.apres}
        </li>
      ))}
    </ul>
  );
}

function LigneJournal({ entree }: { entree: EntreeJournal }): ReactElement {
  return (
    <tr>
      <td className="whitespace-nowrap px-4 py-3 align-top text-slate-700">
        {formaterDateHeure(entree.horodatage)}
      </td>
      <td className="px-4 py-3 align-top font-medium text-slate-900">
        {libelleAction(entree.action)}
      </td>
      <td className="px-4 py-3 align-top text-slate-700">{libelleAuteur(entree.auteur)}</td>
      <td className="px-4 py-3 align-top text-slate-700">
        {entree.cible_table ?? TIRET}
        {entree.cible_id !== null && (
          <>
            <br />
            <span className="text-xs text-slate-500">{entree.cible_id}</span>
          </>
        )}
      </td>
      <td className="px-4 py-3 align-top text-slate-700">
        <DetailAvantApres avant={entree.avant} apres={entree.apres} />
      </td>
    </tr>
  );
}

interface FormFiltresProps {
  filtres: FiltresJournal;
  onChange: (filtres: FiltresJournal) => void;
}

/** Filtres combinables (auteur, action, table cible, période — L5-D10),
 * plus le nombre de résultats affichés (le journal grossit indéfiniment,
 * décision du contrôleur : un plafond visible et réglable, jamais une
 * route sans limite). Chaque changement met à jour `filtres` immédiatement,
 * même convention que `pages/Anomalies.tsx::FormFiltres`. */
function FormFiltres({ filtres, onChange }: FormFiltresProps): ReactElement {
  return (
    <form
      onSubmit={(evenement) => evenement.preventDefault()}
      className="grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-3"
    >
      <div>
        <label htmlFor="filtre-action" className={CLASSES_LABEL}>
          Action
        </label>
        <select
          id="filtre-action"
          value={filtres.action ?? ""}
          onChange={(evenement) =>
            onChange({ ...filtres, action: evenement.target.value === "" ? undefined : evenement.target.value })
          }
          className={CLASSES_CHAMP}
        >
          <option value="">Toutes les actions</option>
          {ACTIONS_CONNUES.map((action) => (
            <option key={action} value={action}>
              {libelleAction(action)}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="filtre-cible-table" className={CLASSES_LABEL}>
          Table cible
        </label>
        <select
          id="filtre-cible-table"
          value={filtres.cibleTable ?? ""}
          onChange={(evenement) =>
            onChange({
              ...filtres,
              cibleTable: evenement.target.value === "" ? undefined : evenement.target.value,
            })
          }
          className={CLASSES_CHAMP}
        >
          <option value="">Toutes les tables</option>
          {CIBLES_CONNUES.map((cible) => (
            <option key={cible} value={cible}>
              {cible}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="filtre-utilisateur-id" className={CLASSES_LABEL}>
          Auteur (identifiant)
        </label>
        <input
          id="filtre-utilisateur-id"
          type="text"
          placeholder="UUID de l'utilisateur"
          value={filtres.utilisateurId ?? ""}
          onChange={(evenement) =>
            onChange({
              ...filtres,
              utilisateurId: evenement.target.value.trim() === "" ? undefined : evenement.target.value.trim(),
            })
          }
          className={CLASSES_CHAMP}
        />
      </div>

      <div>
        <label htmlFor="filtre-depuis" className={CLASSES_LABEL}>
          Depuis
        </label>
        <input
          id="filtre-depuis"
          type="date"
          value={filtres.depuis ?? ""}
          onChange={(evenement) =>
            onChange({ ...filtres, depuis: evenement.target.value === "" ? undefined : evenement.target.value })
          }
          className={CLASSES_CHAMP}
        />
      </div>

      <div>
        <label htmlFor="filtre-jusqu-a" className={CLASSES_LABEL}>
          Jusqu'à
        </label>
        <input
          id="filtre-jusqu-a"
          type="date"
          value={filtres.jusquA ?? ""}
          onChange={(evenement) =>
            onChange({ ...filtres, jusquA: evenement.target.value === "" ? undefined : evenement.target.value })
          }
          className={CLASSES_CHAMP}
        />
      </div>

      <div>
        <label htmlFor="filtre-limite" className={CLASSES_LABEL}>
          Nombre de résultats
        </label>
        <select
          id="filtre-limite"
          value={filtres.limite ?? LIMITE_DEFAUT}
          onChange={(evenement) => onChange({ ...filtres, limite: Number(evenement.target.value) })}
          className={CLASSES_CHAMP}
        >
          {OPTIONS_LIMITE.map((valeur) => (
            <option key={valeur} value={valeur}>
              {valeur}
            </option>
          ))}
        </select>
      </div>
    </form>
  );
}

/** Écran « Journal » (CDC §4.6, registre des traitements §8, L5-T9) :
 * lecture paginée de la table `journal` — traçabilité de toute modification
 * de donnée métier depuis le lot 1. Réservé à l'admin par `GardeAdmin`
 * (voir `App.tsx`, question Q4 du plan lot 5) : aucune vérification de rôle
 * ici. Écran « ordinateur » (comme `Chantiers.tsx`/`FacturesListe.tsx`) :
 * un seul tableau, défilement horizontal sur téléphone, aucune version en
 * cartes — le Journal n'est pas dans la liste « téléphone d'abord » du
 * CDC §4.6 (Bilan, Anomalies). Aucune règle métier ici : `avant`/`apres`
 * sont affichés tels quels, sans interprétation (`lib/journal.ts`). */
export function Journal(): ReactElement {
  const [filtres, setFiltres] = useState<FiltresJournal>({ limite: LIMITE_DEFAUT });

  const entrees = useQuery({
    queryKey: cleJournal(filtres),
    queryFn: () => listerJournal(filtres),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-slate-900">Journal</h1>
      <p className="text-sm text-slate-600">
        Traçabilité de toute modification de donnée métier : qui a fait quoi, et quand — les décisions
        automatiques du système apparaissent sans auteur humain (« Automatique »).
      </p>

      <FormFiltres filtres={filtres} onChange={setFiltres} />

      {entrees.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Chargement…
        </p>
      )}
      {entrees.isError && (
        <p role="alert" className="text-sm text-red-700">
          Impossible de charger le journal.
        </p>
      )}
      {entrees.data && entrees.data.length === 0 && (
        <p className="text-sm text-slate-600">Aucune entrée pour ces filtres.</p>
      )}
      {entrees.data && entrees.data.length > 0 && (
        <div className={CLASSES_TABLEAU}>
          <table className="w-full min-w-[900px] divide-y divide-slate-200 text-sm">
            <caption className="sr-only">Journal des modifications</caption>
            <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
              <tr>
                <th scope="col" className="px-4 py-3">Horodatage</th>
                <th scope="col" className="px-4 py-3">Action</th>
                <th scope="col" className="px-4 py-3">Auteur</th>
                <th scope="col" className="px-4 py-3">Cible</th>
                <th scope="col" className="px-4 py-3">Détail (avant → après)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {entrees.data.map((entree) => (
                <LigneJournal key={entree.id} entree={entree} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
