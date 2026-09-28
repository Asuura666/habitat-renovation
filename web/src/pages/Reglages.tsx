import { type FormEvent, type ReactElement, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

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

/** Une ligne interrupteur (phase 3, tâche P5, spec §3.4) : `valeur` ne vaut
 * que « 0 » ou « 1 » côté serveur (`ingest/parametres.py`, borne de
 * `DefinitionParametre`) -- rendue en case « Oui / Non » plutôt qu'un champ
 * numérique, mêmes `useMutation`/invalidation que `LigneParametre`. Aucune
 * de ces clés n'a besoin de `CLE_CHANTIERS_SILENCIEUX` (aucun interrupteur
 * ne touche au délai des chantiers silencieux). */
function LigneInterrupteur({ parametre }: { parametre: Parametre }): ReactElement {
  const queryClient = useQueryClient();
  const [valeur, setValeur] = useState(parametre.valeur);

  useEffect(() => setValeur(parametre.valeur), [parametre.valeur]);

  const modification = useMutation({
    mutationFn: (nouvelleValeur: string) => modifierParametre(parametre.cle, nouvelleValeur),
    onSuccess: async (parametreModifie) => {
      setValeur(parametreModifie.valeur);
      await queryClient.invalidateQueries({ queryKey: CLE_PARAMETRES });
    },
    onError: (_erreur, nouvelleValeur) => {
      // Échec de l'enregistrement : on revient à l'ancienne valeur, sinon
      // l'interrupteur reste affiché sur la valeur refusée (constat de
      // relecture qualité, tour 2).
      setValeur(nouvelleValeur === "1" ? "0" : "1");
    },
  });

  function basculer(evenement: FormEvent<HTMLInputElement>): void {
    const active = evenement.currentTarget.checked;
    const nouvelleValeur = active ? "1" : "0";
    // Comme `LigneParametre` : l'état local change dès le clic, avant même
    // la réponse du serveur, sinon l'interrupteur -- un champ contrôlé par
    // `valeur` -- revient visuellement en arrière pendant toute la requête
    // (constat de relecture qualité, tour 2).
    setValeur(nouvelleValeur);
    modification.mutate(nouvelleValeur);
  }

  return (
    <div className="flex items-center justify-between gap-4 py-5 first:pt-0 last:pb-0">
      <label htmlFor={`parametre-${parametre.cle}`} className="font-medium text-encre">
        {parametre.libelle}
      </label>
      <div className="flex items-center gap-3">
        {modification.isError && (
          <p role="alert" className="text-sm text-alerte">
            {messageErreur(modification.error)}
          </p>
        )}
        <span className="text-sm text-encre-2">{valeur === "1" ? "Oui" : "Non"}</span>
        <input
          id={`parametre-${parametre.cle}`}
          type="checkbox"
          role="switch"
          checked={valeur === "1"}
          disabled={modification.isPending}
          onChange={basculer}
          className="h-6 w-11 shrink-0 cursor-pointer rounded-full border border-bordure bg-fond outline-none accent-accent focus-visible:ring-2 focus-visible:ring-accent"
        />
      </div>
    </div>
  );
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

/** Regroupe les réglages par `groupe` (phase 3, tâche P5, spec §3.4) --
 * l'ordre des sections suit l'ordre de `DEFINITIONS_PARAMETRES` renvoyé par
 * l'API (`Map` : ordre d'insertion), jamais un tri alphabétique qui
 * mélangerait les sections. `""` (section générale actuelle, tous les
 * réglages d'avant cette phase) est toujours la première rencontrée. */
function grouperParametres(parametres: Parametre[]): Map<string, Parametre[]> {
  const groupes = new Map<string, Parametre[]>();
  for (const parametre of parametres) {
    const ligne = groupes.get(parametre.groupe);
    if (ligne) {
      ligne.push(parametre);
    } else {
      groupes.set(parametre.groupe, [parametre]);
    }
  }
  return groupes;
}

/** Un groupe de réglages, en carte : sans titre pour la section générale
 * (`groupe === ""`, comportement inchangé depuis le lot 5), avec titre
 * sinon (ex. « Contrôle des prix des bons »). Un interrupteur (`prix_
 * controle_bl_actif`…) se rend en case « Oui / Non » plutôt qu'en champ
 * numérique. */
function SectionParametres({ groupe, parametres }: { groupe: string; parametres: Parametre[] }): ReactElement {
  return (
    <Carte titre={groupe || undefined}>
      <div className="divide-y divide-bordure">
        {parametres.map((parametre) =>
          parametre.interrupteur ? (
            <LigneInterrupteur key={parametre.cle} parametre={parametre} />
          ) : (
            <LigneParametre key={parametre.cle} parametre={parametre} />
          ),
        )}
      </div>
    </Carte>
  );
}

/** Écran « Réglages » (spec §4, Task 10 de la refonte du front) : seuils
 * administrables exposés par `ingest/parametres.py` — contenu inchangé
 * depuis le lot 5 (mêmes champs, mêmes bornes, même appel), seul
 * l'habillage change. Réservé à l'admin par `GardeAdmin` (`App.tsx`) :
 * aucune vérification de rôle ici. Phase 3, tâche P5 : les réglages sont
 * désormais regroupés par section (`groupe`), et un interrupteur
 * (`prix_controle_bl_actif`…) se rend en case « Oui / Non » plutôt qu'en
 * champ numérique -- ces réglages restent toujours visibles, même avant
 * que l'interrupteur général du contrôle des prix ne soit activé (spec
 * §3.4 : il faut pouvoir tout préparer avant d'allumer l'interrupteur
 * général). */
export function Reglages(): ReactElement {
  const parametres = useQuery({ queryKey: CLE_PARAMETRES, queryFn: listerParametres });
  const groupes = parametres.data ? grouperParametres(parametres.data) : undefined;

  return (
    <div className="max-w-4xl space-y-6">
      <EnTetePage
        titre="Réglages"
        actions={
          // Task 11 (spec §3) : l'écran « Comptes » (gestion des comptes par
          // un admin) est accessible depuis Réglages, en plus du lien
          // discret de la navigation (`Gabarit.tsx`).
          <Link
            to="/comptes"
            className="inline-flex min-h-[44px] items-center rounded-lg border border-bordure bg-surface px-4 py-2 text-sm font-medium text-encre outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
          >
            Gérer les comptes
          </Link>
        }
      />
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
      {groupes && groupes.size > 0 && (
        <div className="space-y-6">
          {Array.from(groupes.entries()).map(([groupe, lignes]) => (
            <SectionParametres key={groupe || "general"} groupe={groupe} parametres={lignes} />
          ))}
        </div>
      )}
    </div>
  );
}
