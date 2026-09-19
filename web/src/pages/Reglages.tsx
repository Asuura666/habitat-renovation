import { type FormEvent, type ReactElement, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErreurApi } from "../api/client";
import {
  CLE_PARAMETRES,
  listerParametres,
  modifierParametre,
  type Parametre,
} from "../api/parametres";

function messageErreur(erreur: unknown): string {
  if (erreur instanceof ErreurApi) {
    return erreur.detail;
  }
  return "Le réglage n'a pas pu être enregistré.";
}

function LigneParametre({ parametre }: { parametre: Parametre }): ReactElement {
  const queryClient = useQueryClient();
  const [valeur, setValeur] = useState(parametre.valeur);

  useEffect(() => setValeur(parametre.valeur), [parametre.valeur]);

  const modification = useMutation({
    mutationFn: () => modifierParametre(parametre.cle, valeur),
    onSuccess: async (parametreModifie) => {
      setValeur(parametreModifie.valeur);
      await queryClient.invalidateQueries({ queryKey: CLE_PARAMETRES });
    },
  });

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    modification.mutate();
  }

  return (
    <form
      onSubmit={soumettre}
      className="grid gap-3 border-b border-slate-200 px-4 py-4 last:border-b-0 md:grid-cols-[minmax(16rem,1fr)_11rem_8rem] md:items-end"
    >
      <div>
        <label htmlFor={`parametre-${parametre.cle}`} className="font-medium text-slate-900">
          {parametre.libelle}
        </label>
        <p className="mt-1 text-sm text-slate-600">
          De {parametre.minimum} à {parametre.maximum} {parametre.unite}
        </p>
      </div>
      <div>
        <div className="flex items-center gap-2">
          <input
            id={`parametre-${parametre.cle}`}
            type="number"
            inputMode="decimal"
            min={parametre.minimum}
            max={parametre.maximum}
            step={parametre.entier ? "1" : "any"}
            value={valeur}
            onChange={(evenement) => {
              modification.reset();
              setValeur(evenement.target.value);
            }}
            required
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
          />
          <span className="shrink-0 text-sm text-slate-600">{parametre.unite}</span>
        </div>
        {modification.isError && (
          <p role="alert" className="mt-1 text-sm text-red-700">
            {messageErreur(modification.error)}
          </p>
        )}
        {modification.isSuccess && !modification.isPending && (
          <p className="mt-1 text-sm text-green-700">Enregistré</p>
        )}
      </div>
      <button
        type="submit"
        disabled={modification.isPending || valeur === parametre.valeur}
        className="rounded-md bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {modification.isPending ? "Enregistrement…" : "Enregistrer"}
      </button>
    </form>
  );
}

export function Reglages(): ReactElement {
  const parametres = useQuery({ queryKey: CLE_PARAMETRES, queryFn: listerParametres });

  if (parametres.isLoading) {
    return <p>Chargement des réglages…</p>;
  }
  if (parametres.isError) {
    return <p role="alert" className="text-red-700">Impossible de charger les réglages.</p>;
  }

  return (
    <section className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">Réglages</h1>
        <p className="mt-2 text-sm text-slate-600">
          Ces seuils s'appliquent aux prochains contrôles et rapprochements. Chaque modification est conservée dans le journal.
        </p>
      </header>
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        {parametres.data?.map((parametre) => (
          <LigneParametre key={parametre.cle} parametre={parametre} />
        ))}
      </div>
    </section>
  );
}
