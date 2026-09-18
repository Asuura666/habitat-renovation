import { type FormEvent, type ReactElement, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { CLE_A_TRAITER, type AliasEnAttente } from "../api/aTraiter";
import { ErreurApi } from "../api/client";
import {
  type Chantier,
  CLE_CHANTIERS,
  CLE_CHANTIERS_SILENCIEUX,
  ChantierEnDoubleErreur,
  creerChantier,
  validerAlias,
} from "../api/referentiels";

/** Levée par la mutation d'`AliasCarte` (fix round 1, revue L3-T9) quand
 * `creerChantier` a réussi mais que `validerAlias` échoue ensuite : le
 * chantier existe déjà en base, ce n'est pas une erreur de création (jamais
 * un `ChantierEnDoubleErreur`) mais un échec **partiel** qu'il faut nommer
 * distinctement — sinon un réessai recréerait le même chantier et
 * échouerait sur un 409 « existe déjà » sans issue depuis l'écran. */
class RattachementApresCreationErreur extends Error {
  constructor(cause: unknown) {
    super("chantier créé, rattachement de l'alias échoué", { cause });
    this.name = "RattachementApresCreationErreur";
  }
}

/** Formulaire de rattachement d'un alias chantier en attente (L3-D7) : un
 * sélecteur « Chantier existant » ou la création d'un chantier (nom,
 * agence) puis validation de l'alias avec l'id renvoyé, en une action
 * (décision du contrôleur).
 *
 * Extrait de `pages/ATraiter.tsx` (L5-T8) pour être partagé avec l'écran
 * « Chantiers & fournisseurs » (section « Alias en attente de validation »,
 * décision du contrôleur L5-T8 : la section la plus utile au quotidien) —
 * aucun changement de comportement, seulement un déplacement de fichier. */
export function AliasCarte({
  alias,
  chantiers,
}: {
  alias: AliasEnAttente;
  chantiers: Chantier[];
}): ReactElement {
  const queryClient = useQueryClient();
  const [modeCreation, setModeCreation] = useState(false);
  const [chantierChoisi, setChantierChoisi] = useState("");
  const [nom, setNom] = useState("");
  const [agence, setAgence] = useState("");
  // Id du chantier créé par un essai précédent de cette même carte, quand
  // `validerAlias` a ensuite échoué (fix round 1) : un réessai réutilise cet
  // id au lieu d'appeler `creerChantier` une seconde fois (qui échouerait,
  // le nom existant déjà). Remis à `null` dès qu'un rattachement réussit.
  const chantierCreeIdRef = useRef<string | null>(null);

  const validation = useMutation({
    mutationFn: async () => {
      let chantierId: string;
      if (modeCreation) {
        if (chantierCreeIdRef.current !== null) {
          chantierId = chantierCreeIdRef.current;
        } else {
          const cree = await creerChantier(nom, agence.trim() === "" ? null : agence.trim());
          chantierCreeIdRef.current = cree.id;
          chantierId = cree.id;
        }
      } else {
        chantierId = chantierChoisi;
      }

      try {
        const resultat = await validerAlias(alias.id, chantierId);
        chantierCreeIdRef.current = null;
        return resultat;
      } catch (erreur) {
        // `chantierId` existe déjà en base à ce stade (créé à cet essai ou
        // à un essai précédent) : le signaler distinctement de l'erreur
        // brute de `validerAlias` (fix round 1).
        if (modeCreation) {
          throw new RattachementApresCreationErreur(erreur);
        }
        throw erreur;
      }
    },
    // Que la validation réussisse ou échoue après une création de chantier,
    // le référentiel a pu changer (chantier créé) : jamais servir une liste
    // de chantiers périmée depuis le cache (`staleTime` global 5 min,
    // `main.tsx`) — fix round 1, invalide dans tous les cas via `onSettled`
    // plutôt que seulement `onSuccess`.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: CLE_A_TRAITER }),
        // Ruling L5-R11 (tour de correction 2 de L5-T8) : valider un alias
        // écrit `document.chantier_id`, précisément le champ sur lequel
        // repose le calcul du silence — sans cette invalidation, un
        // chantier qui vient de recevoir un rattachement restait dans
        // l'encadré ambre des chantiers silencieux jusqu'à un rechargement
        // manuel ou l'expiration du `staleTime` global (5 min, `main.tsx`).
        queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS_SILENCIEUX }),
      ]);
      setModeCreation(false);
      setChantierChoisi("");
      setNom("");
      setAgence("");
    },
  });

  function messageErreur(erreur: unknown): string {
    if (erreur instanceof RattachementApresCreationErreur) {
      return "Le chantier a été créé, son rattachement a échoué : réessayez.";
    }
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
    validation.mutate();
  }

  const soumissionValide = modeCreation ? nom.trim() !== "" : chantierChoisi !== "";

  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3">
        <p className="text-sm font-semibold text-slate-900">{alias.libelle}</p>
        <p className="text-xs text-slate-500">
          {alias.fournisseur} · {alias.nb_documents}{" "}
          {alias.nb_documents > 1 ? "documents" : "document"}
        </p>
        {alias.exemple_brut !== null && (
          <p className="text-xs text-slate-500">Exemple : {alias.exemple_brut}</p>
        )}
      </div>

      <form onSubmit={soumettre} className="space-y-3">
        {!modeCreation && (
          <div>
            <label
              htmlFor={`chantier-${alias.id}`}
              className="mb-1 block text-xs font-medium text-slate-700"
            >
              Chantier existant
            </label>
            <select
              id={`chantier-${alias.id}`}
              value={chantierChoisi}
              onChange={(evenement) => setChantierChoisi(evenement.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600 sm:w-auto"
            >
              <option value="">— Choisir —</option>
              {chantiers.map((chantier) => (
                <option key={chantier.id} value={chantier.id}>
                  {chantier.nom_canonique}
                  {chantier.agence !== null ? ` (${chantier.agence})` : ""}
                </option>
              ))}
            </select>
          </div>
        )}

        {modeCreation && (
          <div className="grid grid-cols-1 gap-3 rounded-md border border-slate-200 bg-slate-50 p-3 sm:grid-cols-2">
            <div>
              <label
                htmlFor={`nom-${alias.id}`}
                className="mb-1 block text-xs font-medium text-slate-700"
              >
                Nom du chantier
              </label>
              <input
                id={`nom-${alias.id}`}
                type="text"
                value={nom}
                onChange={(evenement) => setNom(evenement.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
              />
            </div>
            <div>
              <label
                htmlFor={`agence-${alias.id}`}
                className="mb-1 block text-xs font-medium text-slate-700"
              >
                Agence
              </label>
              <input
                id={`agence-${alias.id}`}
                type="text"
                value={agence}
                onChange={(evenement) => setAgence(evenement.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
              />
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => setModeCreation((valeur) => !valeur)}
            className="text-sm font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          >
            {modeCreation ? "Choisir un chantier existant" : "Créer un chantier"}
          </button>
          <button
            type="submit"
            disabled={!soumissionValide || validation.isPending}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white outline-none hover:bg-blue-700 focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Valider
          </button>
        </div>

        {validation.isError && (
          <p role="alert" className="text-sm text-red-700">
            {messageErreur(validation.error)}
          </p>
        )}
      </form>
    </li>
  );
}
