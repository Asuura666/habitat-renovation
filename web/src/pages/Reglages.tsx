import { type FormEvent, type ReactElement, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErreurApi } from "../api/client";
import {
  CLE_PARAMETRES,
  listerParametres,
  modifierParametre,
  type Parametre,
} from "../api/parametres";
import { CLE_CHANTIERS_SILENCIEUX } from "../api/referentiels";
import { Bouton, Carte, EnTetePage, EtatVide } from "../ui";

/** Seul réglage lu en direct par une autre route à chaque appel, jamais
 * seulement « aux prochains contrôles » comme les huit autres seuils
 * (`ingest/rapprochement.py`, `rules/rules/R*.py`) : `chantiers_sans_depot`
 * (`GET /api/referentiels/chantiers-silencieux`) relit
 * `delai_chantier_silencieux_j` dans la table `parametre` à chaque requête
 * (`ingest/referentiels_vue.py`), jamais reçu en paramètre. Tâche T7 (audit
 * rapidité) : avec `staleTime` par défaut à 0, un remontage de l'écran
 * « Chantiers » après ce réglage relançait de toute façon la requête ; à
 * 30 s (nouveau défaut, `main.tsx`), la liste des chantiers silencieux
 * pouvait rester fausse jusqu'à 30 s après l'enregistrement. */
const CLE_PARAMETRE_DELAI_SILENCE = "delai_chantier_silencieux_j";

function messageErreur(erreur: unknown): string {
  if (erreur instanceof ErreurApi) {
    return erreur.detail;
  }
  return "Le réglage n'a pas pu être enregistré.";
}

/** Une ligne = un seuil administrable, avec ses bornes et son unité
 * (`ingest/parametres.py`) — comportement inchangé depuis le lot 5, seul
 * l'habillage change ici (Task 10 de la refonte du front). Le libellé vient
 * déjà en français courant du serveur (« Seuil de tolérance de prix », pas
 * de clé technique affichée). Un réglage propre à un contrôle désactivé
 * (prix, R06) n'est jamais listé ici : le serveur ne le renvoie plus du
 * tout (`ingest/parametres.py::_cle_masquee`) tant que le contrôle reste
 * désactivé — ce composant n'a donc plus besoin de connaître les deux
 * drapeaux ni d'afficher de mention à ce sujet. */
function LigneParametre({ parametre }: { parametre: Parametre }): ReactElement {
  const queryClient = useQueryClient();
  const [valeur, setValeur] = useState(parametre.valeur);

  useEffect(() => setValeur(parametre.valeur), [parametre.valeur]);

  const modification = useMutation({
    mutationFn: () => modifierParametre(parametre.cle, valeur),
    onSuccess: async (parametreModifie) => {
      setValeur(parametreModifie.valeur);
      const invalidations = [queryClient.invalidateQueries({ queryKey: CLE_PARAMETRES })];
      if (parametre.cle === CLE_PARAMETRE_DELAI_SILENCE) {
        invalidations.push(queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS_SILENCIEUX }));
      }
      await Promise.all(invalidations);
    },
  });

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    modification.mutate();
  }

  return (
    <form
      onSubmit={soumettre}
      className="grid gap-3 py-5 first:pt-0 last:pb-0 md:grid-cols-[minmax(16rem,1fr)_11rem_8rem] md:items-end"
    >
      <div>
        <label htmlFor={`parametre-${parametre.cle}`} className="font-medium text-encre">
          {parametre.libelle}
        </label>
        <p className="mt-1 text-sm text-encre-2">
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
            className="min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent"
          />
          <span className="shrink-0 text-sm text-encre-2">{parametre.unite}</span>
        </div>
        {modification.isError && (
          <p role="alert" className="mt-1 text-sm text-alerte">
            {messageErreur(modification.error)}
          </p>
        )}
        {modification.isSuccess && !modification.isPending && (
          <p className="mt-1 text-sm text-conforme">Enregistré</p>
        )}
      </div>
      <Bouton type="submit" disabled={modification.isPending || valeur === parametre.valeur} className="w-full md:w-auto">
        {modification.isPending ? "Enregistrement…" : "Enregistrer"}
      </Bouton>
    </form>
  );
}

/** Écran « Réglages » (spec §4, Task 10 de la refonte du front) : seuils
 * administrables exposés par `ingest/parametres.py` — contenu inchangé
 * depuis le lot 5 (mêmes champs, mêmes bornes, même appel), seul
 * l'habillage change. Réservé à l'admin par `GardeAdmin` (`App.tsx`) :
 * aucune vérification de rôle ici. */
export function Reglages(): ReactElement {
  const parametres = useQuery({ queryKey: CLE_PARAMETRES, queryFn: listerParametres });

  return (
    <div className="max-w-4xl space-y-6">
      <EnTetePage titre="Réglages" />
      <p className="text-sm text-encre-2">
        Ces seuils s'appliquent aux prochains contrôles des factures. Chaque modification est
        conservée dans le journal.
      </p>

      {parametres.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement des réglages…
        </p>
      )}
      {parametres.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les réglages.
        </p>
      )}
      {parametres.data && parametres.data.length === 0 && (
        <EtatVide message="Aucun réglage disponible." />
      )}
      {parametres.data !== undefined && parametres.data.length > 0 && (
        <Carte>
          <div className="divide-y divide-bordure">
            {parametres.data.map((parametre) => (
              <LigneParametre key={parametre.cle} parametre={parametre} />
            ))}
          </div>
        </Carte>
      )}
    </div>
  );
}
