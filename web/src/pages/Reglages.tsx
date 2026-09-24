import { type FormEvent, type ReactElement, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { CLE_COMPTE_A_REGLER, obtenirCompteARegler } from "../api/aTraiter";
import { ErreurApi } from "../api/client";
import {
  CLE_PARAMETRES,
  listerParametres,
  modifierParametre,
  type Parametre,
} from "../api/parametres";
import { Bouton, Carte, EnTetePage, EtatVide } from "../ui";

// Les trois seuils que la décision d'Ilane du 24/09/2026 (`docs/dette.md`)
// rend sans effet tant que les contrôles de prix restent désactivés (voir
// `Reglages` ci-dessous) : R07/R08 lisent `seuil_prix_pct`/`seuil_prix_
// fort_pct`, R07/R08/R09 lisent `occurrences_prix_min` (`app/modules/rules/
// rules/R07-R09.py`) -- aucun seuil propre à la remise n'existe à part
// celui-ci (R09 le réutilise). Affichage seulement : la valeur reste
// modifiable (plus simple qu'un formulaire à moitié désactivé) et
// s'appliquera dès la réactivation du drapeau côté serveur.
const CLES_SEUILS_PRIX: ReadonlySet<string> = new Set([
  "seuil_prix_pct",
  "seuil_prix_fort_pct",
  "occurrences_prix_min",
]);

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
 * de clé technique affichée). */
function LigneParametre({
  parametre,
  controlePrixActif,
}: {
  parametre: Parametre;
  controlePrixActif: boolean;
}): ReactElement {
  const queryClient = useQueryClient();
  const [valeur, setValeur] = useState(parametre.valeur);
  const seuilDePrix = CLES_SEUILS_PRIX.has(parametre.cle);

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
      className="grid gap-3 py-5 first:pt-0 last:pb-0 md:grid-cols-[minmax(16rem,1fr)_11rem_8rem] md:items-end"
    >
      <div>
        <label htmlFor={`parametre-${parametre.cle}`} className="font-medium text-encre">
          {parametre.libelle}
        </label>
        <p className="mt-1 text-sm text-encre-2">
          De {parametre.minimum} à {parametre.maximum} {parametre.unite}
        </p>
        {seuilDePrix && !controlePrixActif && (
          <p className="mt-1 text-sm text-encre-2">Contrôle des prix désactivé pour le moment.</p>
        )}
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
  // Même clé que `Gabarit`/`VueEnsemble`/`ARegler` (décision d'Ilane du
  // 24/09/2026, `docs/dette.md`) : seul endroit qui porte `controle_prix_
  // actif`, lu ici pour la mention des seuils de prix ci-dessous.
  const compteARegler = useQuery({ queryKey: CLE_COMPTE_A_REGLER, queryFn: obtenirCompteARegler });
  const controlePrixActif = compteARegler.data?.controle_prix_actif ?? true;

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
              <LigneParametre
                key={parametre.cle}
                parametre={parametre}
                controlePrixActif={controlePrixActif}
              />
            ))}
          </div>
        </Carte>
      )}
    </div>
  );
}
