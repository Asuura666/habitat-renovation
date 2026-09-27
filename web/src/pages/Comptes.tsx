import { type FormEvent, type ReactElement, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  CLE_COMPTES,
  type Compte,
  creerCompte,
  listerComptes,
  modifierCompte,
  changerMotDePasse,
  retablirAcces,
  retirerAcces,
} from "../api/comptes";
import { ErreurApi } from "../api/client";
import { CLE_MOI, DUREE_CACHE_MOI, recupererMoi } from "../api/moi";
import { Bouton, Carte, EnTetePage, EtatVide } from "../ui";

const CLASSES_CHAMP =
  "min-h-[44px] w-full rounded-lg border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent";
const CLASSES_LABEL = "mb-1 block text-xs font-medium text-encre-2";
const INDICE_MOT_DE_PASSE = "12 caractères minimum, à transmettre à la personne.";

/** Écran « Comptes » (spec §3, Task 11) : rôle affiché en toutes lettres,
 * jamais la valeur brute `admin`/`agent` de l'API — distinct de
 * `ChantiersListe.tsx::LIBELLES_ROLE` (« qui a déposé ce bon »), le brief de
 * cet écran demande « Employé » ici plutôt que « Agent ». */
const LIBELLES_ROLE: Record<string, string> = {
  admin: "Administrateur",
  agent: "Employé",
};

function libelleRole(role: string): string {
  return LIBELLES_ROLE[role] ?? role;
}

function messageErreur(erreur: unknown): string {
  if (erreur instanceof ErreurApi) {
    return erreur.detail;
  }
  return "Une erreur est survenue, réessayez.";
}

function nomAffiche(compte: Compte): string {
  return compte.nom ?? compte.email;
}

interface DonneesFormulaire {
  nom: string;
  email: string;
  role: "admin" | "agent";
  agence: string;
  telegramUserId: string;
}

/** Création (spec §3 : « Créer ») et modification (« Modifier ») partagent
 * les mêmes champs — seul le mot de passe provisoire n'existe qu'à la
 * création (`compte === undefined`), jamais réaffiché ni redemandé ici
 * ensuite (« Changer le mot de passe » est un formulaire séparé,
 * `FormulaireMotDePasse` ci-dessous). */
function FormulaireCompte({
  compte,
  onSucces,
  onAnnuler,
}: {
  compte?: Compte;
  onSucces: () => void;
  onAnnuler: () => void;
}): ReactElement {
  const queryClient = useQueryClient();
  const [valeurs, setValeurs] = useState<DonneesFormulaire>({
    nom: compte?.nom ?? "",
    email: compte?.email ?? "",
    role: (compte?.role as "admin" | "agent" | undefined) ?? "agent",
    agence: compte?.agence ?? "",
    telegramUserId:
      compte?.telegram_user_id !== null && compte?.telegram_user_id !== undefined
        ? String(compte.telegram_user_id)
        : "",
  });
  const [motDePasse, setMotDePasse] = useState("");

  // Fix round 1 (constat Important 2) : un identifiant Telegram non
  // numérique donnait `Number(...) === NaN`, silencieusement transformé en
  // `null` par `JSON.stringify` — la requête réussissait comme si le champ
  // était vide, sans jamais prévenir la personne. Vérifié ici (facultatif,
  // donc vide reste valide) plutôt que dans `mutationFn`, pour bloquer la
  // soumission et afficher une erreur sous le champ.
  const telegramTrim = valeurs.telegramUserId.trim();
  const telegramValide = telegramTrim === "" || /^\d+$/.test(telegramTrim);

  const mutation = useMutation({
    mutationFn: () => {
      const donnees = {
        nom: valeurs.nom.trim(),
        email: valeurs.email.trim(),
        role: valeurs.role,
        agence: valeurs.agence.trim() === "" ? null : valeurs.agence.trim(),
        telegram_user_id: telegramTrim === "" ? null : Number(telegramTrim),
      };
      if (compte === undefined) {
        return creerCompte({ ...donnees, mot_de_passe: motDePasse });
      }
      return modifierCompte(compte.id, donnees);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: CLE_COMPTES });
      onSucces();
    },
  });

  function changer<C extends keyof DonneesFormulaire>(champ: C, valeur: DonneesFormulaire[C]): void {
    mutation.reset();
    setValeurs((precedent) => ({ ...precedent, [champ]: valeur }));
  }

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    mutation.mutate();
  }

  const champsValides =
    valeurs.nom.trim() !== "" &&
    valeurs.email.trim() !== "" &&
    telegramValide &&
    (compte !== undefined || motDePasse.length >= 12);

  return (
    <Carte titre={compte === undefined ? "Nouveau compte" : `Modifier ${nomAffiche(compte)}`}>
      <form onSubmit={soumettre} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="compte-nom" className={CLASSES_LABEL}>
            Nom
          </label>
          <input
            id="compte-nom"
            type="text"
            value={valeurs.nom}
            onChange={(evenement) => changer("nom", evenement.target.value)}
            required
            className={CLASSES_CHAMP}
          />
        </div>
        <div>
          <label htmlFor="compte-email" className={CLASSES_LABEL}>
            E-mail
          </label>
          <input
            id="compte-email"
            type="email"
            autoComplete="off"
            value={valeurs.email}
            onChange={(evenement) => changer("email", evenement.target.value)}
            required
            className={CLASSES_CHAMP}
          />
        </div>
        <div>
          <label htmlFor="compte-role" className={CLASSES_LABEL}>
            Rôle
          </label>
          <select
            id="compte-role"
            value={valeurs.role}
            onChange={(evenement) => changer("role", evenement.target.value as "admin" | "agent")}
            className={CLASSES_CHAMP}
          >
            <option value="agent">Employé</option>
            <option value="admin">Administrateur</option>
          </select>
        </div>
        <div>
          <label htmlFor="compte-agence" className={CLASSES_LABEL}>
            Agence
          </label>
          <input
            id="compte-agence"
            type="text"
            value={valeurs.agence}
            onChange={(evenement) => changer("agence", evenement.target.value)}
            className={CLASSES_CHAMP}
          />
        </div>
        <div>
          <label htmlFor="compte-telegram" className={CLASSES_LABEL}>
            Identifiant Telegram
          </label>
          <input
            id="compte-telegram"
            type="text"
            inputMode="numeric"
            value={valeurs.telegramUserId}
            onChange={(evenement) => changer("telegramUserId", evenement.target.value)}
            placeholder="Facultatif"
            aria-invalid={!telegramValide}
            aria-describedby={!telegramValide ? "compte-telegram-erreur" : undefined}
            className={CLASSES_CHAMP}
          />
          {!telegramValide && (
            <p id="compte-telegram-erreur" role="alert" className="mt-1 text-xs text-alerte">
              L'identifiant Telegram ne contient que des chiffres.
            </p>
          )}
        </div>
        {compte === undefined && (
          <div>
            <label htmlFor="compte-mot-de-passe" className={CLASSES_LABEL}>
              Mot de passe provisoire
            </label>
            <input
              id="compte-mot-de-passe"
              type="password"
              autoComplete="new-password"
              value={motDePasse}
              onChange={(evenement) => {
                mutation.reset();
                setMotDePasse(evenement.target.value);
              }}
              required
              className={CLASSES_CHAMP}
            />
            <p className="mt-1 text-xs text-encre-2">{INDICE_MOT_DE_PASSE}</p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
          <Bouton type="submit" disabled={!champsValides || mutation.isPending}>
            {mutation.isPending ? "Enregistrement…" : compte === undefined ? "Créer le compte" : "Enregistrer"}
          </Bouton>
          <Bouton type="button" variante="secondaire" onClick={onAnnuler}>
            Annuler
          </Bouton>
        </div>
        {mutation.isError && (
          <p role="alert" className="text-sm text-alerte sm:col-span-2">
            {messageErreur(mutation.error)}
          </p>
        )}
      </form>
    </Carte>
  );
}

/** « Changer le mot de passe » (spec §3) : l'admin saisit lui-même le
 * nouveau mot de passe, jamais d'envoi d'e-mail — formulaire séparé de
 * `FormulaireCompte` (aucun autre champ du compte n'y est modifiable), le
 * serveur coupe les sessions ouvertes du compte visé. Le mot de passe créé
 * n'est jamais réaffiché : la carte se referme sur le succès. */
function FormulaireMotDePasse({
  compte,
  onSucces,
  onAnnuler,
}: {
  compte: Compte;
  onSucces: () => void;
  onAnnuler: () => void;
}): ReactElement {
  const queryClient = useQueryClient();
  const [motDePasse, setMotDePasse] = useState("");

  const mutation = useMutation({
    mutationFn: () => changerMotDePasse(compte.id, motDePasse),
    onSuccess: async () => {
      // Fix round 1 (minor) : les sessions ouvertes sont coupées côté
      // serveur, mais rien côté liste ne dépendait jusqu'ici de ce
      // changement — invalidé quand même pour rester cohérent avec les
      // deux autres mutations d'écriture de cet écran (`FormulaireCompte`,
      // `ActionsCompte`), qui invalident systématiquement `CLE_COMPTES`.
      await queryClient.invalidateQueries({ queryKey: CLE_COMPTES });
      onSucces();
    },
  });

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    mutation.mutate();
  }

  return (
    <Carte titre={`Changer le mot de passe de ${nomAffiche(compte)}`}>
      <form onSubmit={soumettre} className="grid max-w-sm gap-3">
        <div>
          <label htmlFor="nouveau-mot-de-passe" className={CLASSES_LABEL}>
            Nouveau mot de passe
          </label>
          <input
            id="nouveau-mot-de-passe"
            type="password"
            autoComplete="new-password"
            value={motDePasse}
            onChange={(evenement) => {
              mutation.reset();
              setMotDePasse(evenement.target.value);
            }}
            required
            className={CLASSES_CHAMP}
          />
          <p className="mt-1 text-xs text-encre-2">{INDICE_MOT_DE_PASSE}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Bouton type="submit" disabled={motDePasse.length < 12 || mutation.isPending}>
            {mutation.isPending ? "Enregistrement…" : "Changer le mot de passe"}
          </Bouton>
          <Bouton type="button" variante="secondaire" onClick={onAnnuler}>
            Annuler
          </Bouton>
        </div>
        {mutation.isError && (
          <p role="alert" className="text-sm text-alerte">
            {messageErreur(mutation.error)}
          </p>
        )}
      </form>
    </Carte>
  );
}

/** Boutons d'action d'un compte (spec §3), partagés par la carte téléphone
 * et la ligne de tableau : « Modifier »/« Changer le mot de passe » ouvrent
 * le panneau partagé de l'écran (`onModifier`/`onChangerMotDePasse`) ;
 * « Retirer l'accès »/« Rétablir l'accès » agissent directement (mutation
 * locale), avec confirmation pour le retrait (texte imposé par le brief).
 * « Retirer l'accès » est absent sur sa propre ligne (`estSoi`) : le
 * serveur refuse de toute façon (`ActionSurSoiInterdite`, Task 10), mais
 * proposer un bouton qui échoue à coup sûr serait trompeur. */
function ActionsCompte({
  compte,
  estSoi,
  onModifier,
  onChangerMotDePasse,
}: {
  compte: Compte;
  estSoi: boolean;
  onModifier: () => void;
  onChangerMotDePasse: () => void;
}): ReactElement {
  const queryClient = useQueryClient();
  const [erreurAcces, setErreurAcces] = useState<string | null>(null);

  const retrait = useMutation({
    mutationFn: () => retirerAcces(compte.id),
    onSuccess: async () => {
      setErreurAcces(null);
      await queryClient.invalidateQueries({ queryKey: CLE_COMPTES });
    },
    onError: (erreur: unknown) => setErreurAcces(messageErreur(erreur)),
  });
  const retablissement = useMutation({
    mutationFn: () => retablirAcces(compte.id),
    onSuccess: async () => {
      setErreurAcces(null);
      await queryClient.invalidateQueries({ queryKey: CLE_COMPTES });
    },
    onError: (erreur: unknown) => setErreurAcces(messageErreur(erreur)),
  });

  function confirmerRetrait(): void {
    if (
      window.confirm(
        `${nomAffiche(compte)} ne pourra plus se connecter ni déposer de bons. Son nom reste sur les bons déjà déposés.`,
      )
    ) {
      retrait.mutate();
    }
  }

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        <Bouton variante="secondaire" onClick={onModifier} className="px-3 py-1.5 text-xs">
          Modifier
        </Bouton>
        <Bouton
          variante="secondaire"
          onClick={onChangerMotDePasse}
          className="px-3 py-1.5 text-xs"
        >
          Changer le mot de passe
        </Bouton>
        {compte.actif ? (
          !estSoi && (
            <Bouton
              variante="secondaire"
              onClick={confirmerRetrait}
              disabled={retrait.isPending}
              className="px-3 py-1.5 text-xs"
            >
              Retirer l'accès
            </Bouton>
          )
        ) : (
          <Bouton
            variante="secondaire"
            onClick={() => retablissement.mutate()}
            disabled={retablissement.isPending}
            className="px-3 py-1.5 text-xs"
          >
            Rétablir l'accès
          </Bouton>
        )}
      </div>
      {erreurAcces !== null && (
        <p role="alert" className="mt-1 text-xs text-alerte">
          {erreurAcces}
        </p>
      )}
    </div>
  );
}

function CarteCompte({
  compte,
  estSoi,
  onModifier,
  onChangerMotDePasse,
}: {
  compte: Compte;
  estSoi: boolean;
  onModifier: () => void;
  onChangerMotDePasse: () => void;
}): ReactElement {
  return (
    <li className="rounded-carte border border-bordure bg-surface p-4">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-medium text-encre">
            {nomAffiche(compte)}
            {estSoi && <span className="ml-1 text-xs font-normal text-encre-2">(vous)</span>}
          </h3>
          <p className="text-sm text-encre-2">{compte.email}</p>
        </div>
        <span className={`text-xs font-medium ${compte.actif ? "text-conforme" : "text-encre-2"}`}>
          {compte.actif ? "Accès actif" : "Accès retiré"}
        </span>
      </div>
      <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <div>
          <dt className="text-xs text-encre-2">Rôle</dt>
          <dd className="text-encre">{libelleRole(compte.role)}</dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Agence</dt>
          <dd className="text-encre">{compte.agence ?? "Non renseignée"}</dd>
        </div>
        <div>
          <dt className="text-xs text-encre-2">Telegram</dt>
          <dd className="text-encre">{compte.telegram_user_id !== null ? "relié" : "non relié"}</dd>
        </div>
      </dl>
      <ActionsCompte
        compte={compte}
        estSoi={estSoi}
        onModifier={onModifier}
        onChangerMotDePasse={onChangerMotDePasse}
      />
    </li>
  );
}

function TableauComptes({
  comptes,
  moiId,
  onModifier,
  onChangerMotDePasse,
}: {
  comptes: Compte[];
  moiId: string | undefined;
  onModifier: (compte: Compte) => void;
  onChangerMotDePasse: (compte: Compte) => void;
}): ReactElement {
  return (
    <div className="hidden overflow-x-auto rounded-carte border border-bordure bg-surface md:block">
      <table className="w-full min-w-[880px] divide-y divide-bordure text-sm">
        <caption className="sr-only">Comptes</caption>
        <thead className="text-left text-xs font-medium uppercase tracking-wide text-encre-2">
          <tr>
            <th scope="col" className="px-4 py-3">Nom · e-mail</th>
            <th scope="col" className="px-4 py-3">Rôle</th>
            <th scope="col" className="px-4 py-3">Agence</th>
            <th scope="col" className="px-4 py-3">Telegram</th>
            <th scope="col" className="px-4 py-3">Accès</th>
            <th scope="col" className="px-4 py-3">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-bordure">
          {comptes.map((compte) => {
            const estSoi = compte.id === moiId;
            return (
              <tr key={compte.id}>
                <th scope="row" className="px-4 py-3 text-left font-medium text-encre">
                  {nomAffiche(compte)}
                  {estSoi && <span className="ml-1 text-xs font-normal text-encre-2">(vous)</span>}
                  <p className="text-xs font-normal text-encre-2">{compte.email}</p>
                </th>
                <td className="px-4 py-3 text-encre-2">{libelleRole(compte.role)}</td>
                <td className="px-4 py-3 text-encre-2">{compte.agence ?? "Non renseignée"}</td>
                <td className="px-4 py-3 text-encre-2">
                  {compte.telegram_user_id !== null ? "relié" : "non relié"}
                </td>
                <td className="px-4 py-3">
                  <span className={`font-medium ${compte.actif ? "text-conforme" : "text-encre-2"}`}>
                    {compte.actif ? "Accès actif" : "Accès retiré"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <ActionsCompte
                    compte={compte}
                    estSoi={estSoi}
                    onModifier={() => onModifier(compte)}
                    onChangerMotDePasse={() => onChangerMotDePasse(compte)}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ListeComptes({
  comptes,
  moiId,
  onModifier,
  onChangerMotDePasse,
}: {
  comptes: Compte[];
  moiId: string | undefined;
  onModifier: (compte: Compte) => void;
  onChangerMotDePasse: (compte: Compte) => void;
}): ReactElement {
  return (
    <>
      <ul className="space-y-3 md:hidden">
        {comptes.map((compte) => (
          <CarteCompte
            key={compte.id}
            compte={compte}
            estSoi={compte.id === moiId}
            onModifier={() => onModifier(compte)}
            onChangerMotDePasse={() => onChangerMotDePasse(compte)}
          />
        ))}
      </ul>
      <TableauComptes
        comptes={comptes}
        moiId={moiId}
        onModifier={onModifier}
        onChangerMotDePasse={onChangerMotDePasse}
      />
    </>
  );
}

type Panneau =
  | { type: "creation" }
  | { type: "modifier"; compte: Compte }
  | { type: "mot-de-passe"; compte: Compte };

/** Écran « Comptes » (spec §3, Task 11) : gestion des comptes par un admin
 * — réservé par `GardeAdmin` (`App.tsx`), accessible depuis Réglages. Un
 * seul panneau ouvert à la fois (création, modification ou changement de
 * mot de passe), affiché juste sous l'en-tête — même convention que
 * `ChantiersListe.tsx::FormulaireCreationChantier` (carte repliable plutôt
 * que toujours visible). `["moi"]` est déjà en cache (`RouteProtegee`) :
 * sert seulement à reconnaître sa propre ligne (`estSoi`), jamais un second
 * appel réseau tant que les données ne sont pas jugées périmées. */
export function Comptes(): ReactElement {
  const [panneau, setPanneau] = useState<Panneau | null>(null);

  const { data: moi } = useQuery({ queryKey: CLE_MOI, queryFn: recupererMoi, staleTime: DUREE_CACHE_MOI });
  const comptes = useQuery({ queryKey: CLE_COMPTES, queryFn: listerComptes });

  function fermerPanneau(): void {
    setPanneau(null);
  }

  return (
    <div className="space-y-6">
      <EnTetePage
        titre="Comptes"
        actions={
          <Bouton
            variante="secondaire"
            onClick={() => setPanneau((actuel) => (actuel?.type === "creation" ? null : { type: "creation" }))}
          >
            Nouveau compte
          </Bouton>
        }
      />

      {panneau !== null && panneau.type === "creation" && (
        <FormulaireCompte onSucces={fermerPanneau} onAnnuler={fermerPanneau} />
      )}
      {/* `key` distincte par compte (fix round 1, constat Important 1,
          même correctif que `ARegler.tsx::ProblemeDetail`, fix round 1
          finding 4) : la liste reste cliquable pendant qu'un panneau est
          ouvert. Sans clé, cliquer « Modifier » sur le compte B pendant que
          « Modifier A » est déjà ouvert réutilisait l'instance en place —
          le titre affichait B mais les champs restaient ceux d'A
          (`useState` n'est initialisé qu'au montage), et la soumission
          écrasait B avec les données d'A. Le préfixe distingue aussi les
          deux panneaux entre eux (défensif : ils occupent déjà des
          emplacements JSX différents, donc ne se confondraient pas sans
          lui, mais la consigne du correctif demande une clé par type de
          panneau en plus du compte). */}
      {panneau !== null && panneau.type === "modifier" && (
        <FormulaireCompte
          key={`modifier-${panneau.compte.id}`}
          compte={panneau.compte}
          onSucces={fermerPanneau}
          onAnnuler={fermerPanneau}
        />
      )}
      {panneau !== null && panneau.type === "mot-de-passe" && (
        <FormulaireMotDePasse
          key={`mot-de-passe-${panneau.compte.id}`}
          compte={panneau.compte}
          onSucces={fermerPanneau}
          onAnnuler={fermerPanneau}
        />
      )}

      {comptes.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement des comptes…
        </p>
      )}
      {comptes.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les comptes.
        </p>
      )}
      {comptes.data && comptes.data.length === 0 && <EtatVide message="Aucun compte enregistré." />}
      {comptes.data && comptes.data.length > 0 && (
        <ListeComptes
          comptes={comptes.data}
          moiId={moi?.id}
          onModifier={(compte) => setPanneau({ type: "modifier", compte })}
          onChangerMotDePasse={(compte) => setPanneau({ type: "mot-de-passe", compte })}
        />
      )}
    </div>
  );
}
