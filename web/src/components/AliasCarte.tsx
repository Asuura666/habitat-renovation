import { type FormEvent, type ReactElement, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { CLE_A_TRAITER, type AliasEnAttente } from "../api/aTraiter";
import { ErreurApi } from "../api/client";
import { invaliderApresChangementAnomalies } from "../api/invalidations";
import {
  type Chantier,
  CLE_AGENCES,
  CLE_CHANTIERS,
  CLE_CHANTIERS_SILENCIEUX,
  ChantierEnDoubleErreur,
  creerChantier,
  validerAlias,
} from "../api/referentiels";
import { Bouton } from "../ui";

/** Classes des champs de la charte (mêmes que les formulaires des écrans
 * « Chantiers » et fiche chantier) : cible de 44 px, bordure et surface de
 * la charte. */
const CLASSES_CHAMP =
  "min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
const CLASSES_LABEL = "mb-1 block text-sm font-semibold text-encre";

/** Levée par la mutation d'`AliasCarte` (fix round 1, revue L3-T9) quand
 * `creerChantier` a réussi mais que `validerAlias` échoue ensuite : le
 * chantier existe déjà en base, ce n'est pas une erreur de création (jamais
 * un `ChantierEnDoubleErreur`) mais un échec **partiel** qu'il faut nommer
 * distinctement — sinon un réessai recréerait le même chantier et
 * échouerait sur un 409 « existe déjà » sans issue depuis l'écran. */
class RattachementApresCreationErreur extends Error {
  constructor(cause: unknown) {
    super("chantier créé, rattachement échoué", { cause });
    this.name = "RattachementApresCreationErreur";
  }
}

/** Formulaire « Chantier à rattacher » (L3-D7) : un sélecteur « Chantier
 * existant » ou la création d'un chantier (nom, client, agence) puis le
 * rattachement avec l'id renvoyé, en une action (décision du contrôleur).
 * Monté par le détail d'un problème de l'écran « À régler » (seul
 * utilisateur depuis la refonte).
 *
 * Revue finale de la refonte du front :
 * - habillé à la charte (constats LIENS-3, COUVERTURE-7, ECRAN-10,
 *   TELEPHONE-5) : `Bouton` principal/secondaire, champs de 44 px, jetons
 *   de couleur — c'était la seule tache bleue de l'application, avec des
 *   cibles d'environ 32 px au téléphone ; plus de double cadre dans la carte
 *   du détail ;
 * - champ « Client » à la création, comme « Nouveau chantier » (spec §6.1) ;
 * - après un rattachement réussi, les problèmes sont invalidés (constat
 *   LIENS-4 : le chantier des livraisons change côté serveur) et
 *   `onReussite` passe au problème suivant (constat LIENS-11 : l'écran
 *   affichait « Ce problème n'est plus disponible » juste après sa propre
 *   action). */
export function AliasCarte({
  alias,
  chantiers,
  onReussite,
}: {
  alias: AliasEnAttente;
  chantiers: Chantier[];
  onReussite?: () => void;
}): ReactElement {
  const queryClient = useQueryClient();
  const [modeCreation, setModeCreation] = useState(false);
  const [chantierChoisi, setChantierChoisi] = useState("");
  const [nom, setNom] = useState("");
  const [client, setClient] = useState("");
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
          const cree = await creerChantier(
            nom,
            agence.trim() === "" ? null : agence.trim(),
            client.trim() === "" ? null : client.trim(),
          );
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
    // de chantiers périmée depuis le cache (fix round 1). L'agence saisie au
    // même formulaire suit la même règle (Task 7, audit rapidité — même
    // raison que `ChantiersListe.tsx`/`FicheChantier.tsx`).
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS });
      void queryClient.invalidateQueries({ queryKey: CLE_AGENCES });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: CLE_A_TRAITER }),
        // Ruling L5-R11 (tour de correction 2 de L5-T8) : rattacher écrit
        // `document.chantier_id`, précisément le champ sur lequel repose le
        // calcul du silence d'un chantier.
        queryClient.invalidateQueries({ queryKey: CLE_CHANTIERS_SILENCIEUX }),
        invaliderApresChangementAnomalies(queryClient),
      ]);
      setModeCreation(false);
      setChantierChoisi("");
      setNom("");
      setClient("");
      setAgence("");
      onReussite?.();
    },
  });

  function messageErreur(erreur: unknown): string {
    if (erreur instanceof RattachementApresCreationErreur) {
      return "Le chantier a été créé, son rattachement a échoué : réessayez.";
    }
    if (erreur instanceof ChantierEnDoubleErreur) {
      const existant = chantiers.find((chantier) => chantier.id === erreur.originalId);
      return existant ? `Le chantier « ${existant.nom_canonique} » existe déjà.` : "Ce chantier existe déjà.";
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
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border border-bordure bg-fond p-4">
        <p className="text-sm text-encre-2">Libellé lu sur les documents</p>
        <p className="mt-0.5 font-medium text-encre">{alias.libelle}</p>
        {alias.exemple_brut !== null && <p className="mt-1 text-sm text-encre-2">Exemple : {alias.exemple_brut}</p>}
      </div>

      <form onSubmit={soumettre} className="flex flex-col gap-3">
        {!modeCreation && (
          <div>
            <label htmlFor={`chantier-${alias.id}`} className={CLASSES_LABEL}>
              Chantier existant
            </label>
            <select
              id={`chantier-${alias.id}`}
              value={chantierChoisi}
              onChange={(evenement) => setChantierChoisi(evenement.target.value)}
              className={CLASSES_CHAMP}
            >
              <option value="">— Choisir un chantier —</option>
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
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label htmlFor={`nom-${alias.id}`} className={CLASSES_LABEL}>
                Nom du chantier
              </label>
              <input
                id={`nom-${alias.id}`}
                type="text"
                value={nom}
                onChange={(evenement) => setNom(evenement.target.value)}
                className={CLASSES_CHAMP}
              />
            </div>
            <div>
              <label htmlFor={`client-${alias.id}`} className={CLASSES_LABEL}>
                Client
              </label>
              <input
                id={`client-${alias.id}`}
                type="text"
                value={client}
                onChange={(evenement) => setClient(evenement.target.value)}
                className={CLASSES_CHAMP}
              />
            </div>
            <div>
              <label htmlFor={`agence-${alias.id}`} className={CLASSES_LABEL}>
                Agence
              </label>
              <input
                id={`agence-${alias.id}`}
                type="text"
                value={agence}
                onChange={(evenement) => setAgence(evenement.target.value)}
                className={CLASSES_CHAMP}
              />
            </div>
          </div>
        )}

        <div className="flex flex-col gap-2 sm:flex-row">
          <Bouton type="submit" disabled={!soumissionValide || validation.isPending} className="sm:flex-1">
            {modeCreation ? "Créer et rattacher" : "Rattacher à ce chantier"}
          </Bouton>
          <Bouton variante="secondaire" onClick={() => setModeCreation((valeur) => !valeur)} className="sm:flex-1">
            {modeCreation ? "Choisir un chantier existant" : "Créer un chantier"}
          </Bouton>
        </div>

        {validation.isError && (
          <p role="alert" className="text-sm text-alerte">
            {messageErreur(validation.error)}
          </p>
        )}
      </form>
    </div>
  );
}
