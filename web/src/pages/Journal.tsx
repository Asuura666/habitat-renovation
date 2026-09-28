import { type ReactElement, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { CLE_COMPTES, listerComptes } from "../api/comptes";
import { type EntreeJournal, type FiltresJournal, cleJournal, listerJournal } from "../api/journal";
import { formaterDateHeure, TIRET } from "../lib/formats";
import {
  ACTIONS_CONNUES,
  CIBLES_CONNUES,
  libelleAction,
  libelleAuteur,
  libelleCible,
  libelleCibleId,
  lienCible,
  lignesAvantApres,
} from "../lib/journal";
import { Carte, EnTetePage, EtatVide, Filtres } from "../ui";

const CLASSES_CHAMP =
  "min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
const CLASSES_LABEL = "mb-1 block text-xs font-medium text-encre-2";
// Même cible tactile (44 px) que les autres liens de l'application
// (`FicheChantier.tsx::CLASSES_LIEN`) — un lien direct vers l'élément
// concerné par une entrée (`lib/journal.ts::lienCible`), jamais un jargon
// technique répété ici.
const CLASSES_LIEN_CIBLE =
  "inline-flex min-h-[44px] items-center font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent";

const OPTIONS_LIMITE = [50, 100, 200, 500] as const;
const LIMITE_DEFAUT = 100;
const OPTIONS_FILTRE_LIMITE = OPTIONS_LIMITE.map((valeur) => ({
  valeur: String(valeur),
  libelle: String(valeur),
}));

/** Comparaison `avant`/`apres` d'une entrée (décision du contrôleur, L5-T9) :
 * clé par clé, une clé absente d'un côté marquée explicitement — chaque clé
 * et valeur passe par le langage courant de `lib/journal.ts` quand il la
 * connaît (montant, date, phrase chiffrée d'un problème…), la valeur brute
 * reste le repli sinon ; aucun calcul métier, uniquement de la présentation
 * (voir `lib/journal.ts`). */
function DetailAvantApres({
  avant,
  apres,
  noms,
}: {
  avant: EntreeJournal["avant"];
  apres: EntreeJournal["apres"];
  noms: EntreeJournal["noms"];
}): ReactElement {
  const lignes = lignesAvantApres(avant, apres, noms);
  if (lignes.length === 0) {
    return <p className="text-encre-2">Aucun détail conservé pour cette action.</p>;
  }
  return (
    <ul className="space-y-1">
      {lignes.map((ligne) => (
        <li key={ligne.cle} className="[overflow-wrap:anywhere]">
          <span className="font-medium text-encre">{ligne.libelle}</span>
          {" : "}
          <span className="font-mono text-xs [overflow-wrap:anywhere]">{ligne.avant}</span>
          {" → "}
          <span className="font-mono text-xs [overflow-wrap:anywhere]">{ligne.apres}</span>
        </li>
      ))}
    </ul>
  );
}

function LigneJournal({ entree }: { entree: EntreeJournal }): ReactElement {
  // Nom de la cible, seulement quand il a un sens pour le lecteur (nom d'un
  // réglage, nom d'un compte) — jamais un identifiant (revue finale,
  // COUVERTURE-10 ; recette du 28/09/2026 pour les comptes).
  const idCible = entree.cible_id !== null ? libelleCibleId(entree.cible_table, entree.cible_id, entree.noms) : null;
  const lien = lienCible(entree.cible_table, entree.cible_id, entree.action, entree.apres);
  return (
    <tr>
      <td className="px-4 py-3 align-top font-mono text-xs text-encre-2 [overflow-wrap:anywhere]">
        {formaterDateHeure(entree.horodatage)}
      </td>
      <td className="px-4 py-3 align-top font-medium text-encre [overflow-wrap:anywhere]">
        {libelleAction(entree.action)}
      </td>
      <td className="px-4 py-3 align-top text-encre-2 [overflow-wrap:anywhere]">
        {libelleAuteur(entree.auteur)}
      </td>
      <td className="px-4 py-3 align-top text-encre-2">
        {entree.cible_table !== null ? libelleCible(entree.cible_table) : TIRET}
        {idCible !== null && (
          <>
            <br />
            <span className="text-xs text-encre-2 [overflow-wrap:anywhere]">{idCible}</span>
          </>
        )}
        {lien !== null && (
          <>
            <br />
            <Link to={lien.href} className={CLASSES_LIEN_CIBLE}>
              {lien.libelle}
            </Link>
          </>
        )}
      </td>
      <td className="px-4 py-3 align-top text-encre-2 [overflow-wrap:anywhere]">
        <DetailAvantApres avant={entree.avant} apres={entree.apres} noms={entree.noms} />
      </td>
    </tr>
  );
}

/** Une entrée du journal, présentée en carte pour le téléphone (< `md`) —
 * mêmes informations que `LigneJournal`, un tableau ne tenant pas dans
 * 375 px (contrainte téléphone = cible à part entière, spec §7). */
function CarteJournal({ entree }: { entree: EntreeJournal }): ReactElement {
  const idCible = entree.cible_id !== null ? libelleCibleId(entree.cible_table, entree.cible_id, entree.noms) : null;
  const lien = lienCible(entree.cible_table, entree.cible_id, entree.action, entree.apres);
  return (
    <Carte>
      <div className="flex items-baseline justify-between gap-3">
        <p className="font-medium text-encre">{libelleAction(entree.action)}</p>
        <p className="shrink-0 font-mono text-xs text-encre-2">{formaterDateHeure(entree.horodatage)}</p>
      </div>
      <p className="mt-1 text-sm text-encre-2 [overflow-wrap:anywhere]">
        {libelleAuteur(entree.auteur)}
        {entree.cible_table !== null && ` · ${libelleCible(entree.cible_table)}`}
        {idCible !== null && (
          <>
            {" "}
            <span className="text-xs [overflow-wrap:anywhere]">{idCible}</span>
          </>
        )}
      </p>
      {lien !== null && (
        <Link to={lien.href} className={CLASSES_LIEN_CIBLE}>
          {lien.libelle}
        </Link>
      )}
      <div className="mt-3 border-t border-bordure pt-3 text-sm">
        <DetailAvantApres avant={entree.avant} apres={entree.apres} noms={entree.noms} />
      </div>
    </Carte>
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
  const comptes = useQuery({ queryKey: CLE_COMPTES, queryFn: listerComptes });
  return (
    <Carte>
      <form onSubmit={(evenement) => evenement.preventDefault()} className="space-y-5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
              Élément concerné
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
              <option value="">Tous les éléments</option>
              {CIBLES_CONNUES.map((cible) => (
                <option key={cible} value={cible}>
                  {libelleCible(cible)}
                </option>
              ))}
            </select>
          </div>

          {/* Recette du 28/09/2026 : le filtre « Auteur » demandait un
              identifiant de compte à recopier (affiché sous « Compte
              utilisateur ») ; c'est désormais la liste des comptes, par nom
              (`GET /api/comptes`, admin comme cet écran). Liste pas encore
              chargée ou en échec : seul « Tous les auteurs » reste proposé. */}
          <div>
            <label htmlFor="filtre-utilisateur-id" className={CLASSES_LABEL}>
              Auteur
            </label>
            <select
              id="filtre-utilisateur-id"
              value={filtres.utilisateurId ?? ""}
              onChange={(evenement) =>
                onChange({
                  ...filtres,
                  utilisateurId: evenement.target.value === "" ? undefined : evenement.target.value,
                })
              }
              className={CLASSES_CHAMP}
            >
              <option value="">Tous les auteurs</option>
              {(comptes.data ?? []).map((compte) => (
                <option key={compte.id} value={compte.id}>
                  {compte.nom ?? compte.email}
                </option>
              ))}
            </select>
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
        </div>

        <fieldset className="m-0 border-0 p-0">
          <legend className={CLASSES_LABEL}>Nombre de résultats</legend>
          <Filtres
            options={OPTIONS_FILTRE_LIMITE}
            valeur={String(filtres.limite ?? LIMITE_DEFAUT)}
            onChange={(valeur) => onChange({ ...filtres, limite: Number(valeur) })}
          />
        </fieldset>
      </form>
    </Carte>
  );
}

/** Écran « Journal » (CDC §4.6, registre des traitements §8, L5-T9, Task 10
 * de la refonte du front) : lecture paginée de la table `journal` —
 * traçabilité de toute modification de donnée métier depuis le lot 1.
 * Réservé à l'admin par `GardeAdmin` (voir `App.tsx`, question Q4 du plan
 * lot 5) : aucune vérification de rôle ici. Contenu inchangé depuis le
 * lot 5 (mêmes filtres, même pagination) — seul l'habillage change : un
 * tableau sur ordinateur (`>= md`), les mêmes entrées en cartes empilées
 * sur téléphone (`< md`, contrainte « téléphone = cible à part entière »,
 * spec §7). Aucune règle métier ici : `avant`/`apres` ne sont que mis en
 * forme et traduits en langage courant par `lib/journal.ts`, jamais
 * réinterprétés ni recalculés. */
export function Journal(): ReactElement {
  const [filtres, setFiltres] = useState<FiltresJournal>({ limite: LIMITE_DEFAUT });

  const entrees = useQuery({
    queryKey: cleJournal(filtres),
    queryFn: () => listerJournal(filtres),
  });

  return (
    <div className="space-y-6">
      <EnTetePage titre="Journal" />
      <p className="text-sm text-encre-2">
        Traçabilité de toute modification de donnée métier : qui a fait quoi, et quand — les décisions
        automatiques du système apparaissent sans auteur humain (« Automatique »).
      </p>

      <FormFiltres filtres={filtres} onChange={setFiltres} />

      {entrees.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {entrees.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger le journal.
        </p>
      )}
      {entrees.data && entrees.data.length === 0 && <EtatVide message="Aucune entrée pour ces filtres." />}
      {entrees.data && entrees.data.length > 0 && (
        <>
          {/* Tableau — ordinateur (>= md) */}
          <Carte className="hidden overflow-x-auto md:block">
            {/* `table-fixed` + largeurs de colonnes en pourcentage (plutôt
             * qu'une largeur minimale fixe) : la colonne Détail peut porter
             * des valeurs longues et sans espace (identifiants,
             * `lib/journal.ts::lignesAvantApres`) — sans largeur figée, son
             * contenu minimal forcerait le tableau, la carte, puis la page
             * entière à déborder horizontalement (constat de la revue,
             * captures 1440/375 trop larges). Les pourcentages tiennent
             * seuls, sans dépendre d'un correctif `min-w-0` posé plus haut
             * dans `Gabarit.tsx`, hors périmètre de cette tâche). */}
            <table className="w-full table-fixed text-sm">
              <caption className="sr-only">Journal des modifications</caption>
              <thead className="border-b border-bordure text-left text-xs font-medium uppercase tracking-wide text-encre-2">
                <tr>
                  <th scope="col" className="w-[13%] px-4 py-3">Horodatage</th>
                  <th scope="col" className="w-[15%] px-4 py-3">Action</th>
                  <th scope="col" className="w-[13%] px-4 py-3">Auteur</th>
                  <th scope="col" className="w-[15%] px-4 py-3">Cible</th>
                  <th scope="col" className="w-[44%] px-4 py-3">Détail (avant → après)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bordure">
                {entrees.data.map((entree) => (
                  <LigneJournal key={entree.id} entree={entree} />
                ))}
              </tbody>
            </table>
          </Carte>

          {/* Cartes empilées — téléphone (< md) */}
          <div className="space-y-3 md:hidden">
            {entrees.data.map((entree) => (
              <CarteJournal key={entree.id} entree={entree} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
