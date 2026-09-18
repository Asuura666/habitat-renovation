import { type FormEvent, type ReactElement, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import {
  type Anomalie,
  CLE_ANOMALIES,
  cleAnomalies,
  type FiltresAnomalies,
  type GraviteAnomalie,
  listerAnomalies,
  type StatutAnomalie,
  traiterAnomalie,
} from "../api/anomalies";
import { CLE_A_TRAITER } from "../api/aTraiter";
import { ErreurApi } from "../api/client";
import {
  type Chantier,
  CLE_CHANTIERS,
  CLE_FOURNISSEURS,
  type Fournisseur,
  listerChantiers,
  listerFournisseurs,
} from "../api/referentiels";
import { formaterDateHeure, TIRET } from "../lib/formats";
import { justification, libelleGravite, libelleRegle } from "../lib/regles";

/** Codes des 17 règles du catalogue (CDC §5), pour le sélecteur de filtre —
 * table figée ici comme dans `lib/regles.ts` (décision du contrôleur). */
const CODES_REGLE = [
  "R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09",
  "R10", "R11", "R12", "R13", "R14", "R15", "R16", "R17",
] as const;

const CLASSES_CHAMP =
  "w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-blue-600";
const CLASSES_LABEL = "mb-1 block text-xs font-medium text-slate-700";

const CLASSES_GRAVITE: Record<string, string> = {
  haute: "bg-red-100 text-red-800",
  moyenne: "bg-orange-100 text-orange-800",
  basse: "bg-slate-100 text-slate-700",
};

/** Pastille de gravité (décision du contrôleur : haute rouge, moyenne
 * orange, basse slate — même principe que `PastilleReception` de
 * `FactureDetail.tsx`). */
function PastilleGravite({ gravite }: { gravite: string }): ReactElement {
  const classe = CLASSES_GRAVITE[gravite] ?? CLASSES_GRAVITE.basse;
  return (
    <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium ${classe}`}>
      {libelleGravite(gravite)}
    </span>
  );
}

/** Chemin du document source (même logique que `cheminDocument` dans
 * `ATraiter.tsx`) : `null` quand l'anomalie n'a pas de document rattaché
 * (R14 — alias, R16 — chantier). */
function cheminDocumentSource(anomalie: Anomalie): string | null {
  if (anomalie.document_id === null) {
    return null;
  }
  return anomalie.type === "facture" ? `/factures/${anomalie.document_id}` : `/documents/${anomalie.document_id}`;
}

function LienDocumentSource({ anomalie }: { anomalie: Anomalie }): ReactElement {
  const chemin = cheminDocumentSource(anomalie);
  if (chemin === null) {
    return <span className="text-sm text-slate-500">{TIRET}</span>;
  }
  return (
    <Link
      to={chemin}
      className="text-sm font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
    >
      {anomalie.type === "facture" ? "Voir la facture" : "Voir le document"}
    </Link>
  );
}

/** Actions du cycle de vie (L4-D15) : « Traitée »/« Ignorée » ouvrent un
 * champ de commentaire obligatoire ; une anomalie déjà traitée affiche son
 * dénouement au lieu des boutons. Invalide `["anomalies"]` (toutes les
 * variantes de filtres, correspondance partielle de TanStack Query) et
 * `["a-traiter"]` après un traitement réussi (décision du contrôleur). */
function ActionsAnomalie({ anomalie }: { anomalie: Anomalie }): ReactElement {
  const queryClient = useQueryClient();
  const [action, setAction] = useState<"traitee" | "ignoree" | null>(null);
  const [commentaire, setCommentaire] = useState("");

  const traitement = useMutation({
    mutationFn: (statut: "traitee" | "ignoree") =>
      traiterAnomalie(anomalie.id, { statut, commentaire: commentaire.trim() }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: CLE_ANOMALIES }),
        queryClient.invalidateQueries({ queryKey: CLE_A_TRAITER }),
      ]);
      setAction(null);
      setCommentaire("");
    },
  });

  if (anomalie.statut !== "ouverte") {
    return (
      <p className="text-xs text-slate-500">
        {anomalie.statut === "traitee" ? "Traitée" : "Ignorée"}
        {anomalie.traitee_par !== null ? ` par ${anomalie.traitee_par}` : ""}
        {anomalie.traitee_le !== null ? ` le ${formaterDateHeure(anomalie.traitee_le)}` : ""}
        {anomalie.commentaire !== null && anomalie.commentaire !== "" ? ` — ${anomalie.commentaire}` : ""}
      </p>
    );
  }

  function messageErreur(erreur: unknown): string {
    if (erreur instanceof ErreurApi && erreur.status === 409) {
      return "Cette anomalie a déjà été traitée entre-temps : rechargez la liste.";
    }
    if (erreur instanceof ErreurApi && erreur.status === 422) {
      return "Le commentaire est obligatoire (1 à 500 caractères).";
    }
    if (erreur instanceof ErreurApi) {
      return erreur.detail;
    }
    return "Une erreur est survenue, réessayez.";
  }

  function soumettre(evenement: FormEvent<HTMLFormElement>): void {
    evenement.preventDefault();
    if (action === null) {
      return;
    }
    traitement.mutate(action);
  }

  function annuler(): void {
    setAction(null);
    setCommentaire("");
    traitement.reset();
  }

  if (action === null) {
    return (
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setAction("traitee")}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 outline-none hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-blue-600"
        >
          Traitée
        </button>
        <button
          type="button"
          onClick={() => setAction("ignoree")}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 outline-none hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-blue-600"
        >
          Ignorée
        </button>
      </div>
    );
  }

  const soumissionValide = commentaire.trim() !== "";

  return (
    <form onSubmit={soumettre} className="space-y-2">
      <label htmlFor={`commentaire-${anomalie.id}`} className={CLASSES_LABEL}>
        Commentaire ({action === "traitee" ? "anomalie traitée" : "anomalie ignorée"})
      </label>
      <textarea
        id={`commentaire-${anomalie.id}`}
        value={commentaire}
        onChange={(evenement) => setCommentaire(evenement.target.value)}
        maxLength={500}
        rows={2}
        required
        className={CLASSES_CHAMP}
      />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={!soumissionValide || traitement.isPending}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white outline-none hover:bg-blue-700 focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Confirmer
        </button>
        <button
          type="button"
          onClick={annuler}
          className="text-sm font-medium text-slate-600 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
        >
          Annuler
        </button>
      </div>
      {traitement.isError && (
        <p role="alert" className="text-sm text-red-700">
          {messageErreur(traitement.error)}
        </p>
      )}
    </form>
  );
}

function EnTeteAnomalie({ anomalie }: { anomalie: Anomalie }): ReactElement {
  return (
    <p className="text-xs text-slate-500">
      {anomalie.fournisseur ?? TIRET} · {anomalie.chantier ?? TIRET} ·{" "}
      {formaterDateHeure(anomalie.cree_le)}
    </p>
  );
}

function LiensAnomalie({ anomalie }: { anomalie: Anomalie }): ReactElement {
  return (
    <div className="flex flex-wrap gap-3">
      <LienDocumentSource anomalie={anomalie} />
      {anomalie.bl_document_id !== null && (
        <Link
          to={`/documents/${anomalie.bl_document_id}`}
          className="text-sm font-medium text-blue-700 underline outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
        >
          Photo du BL
        </Link>
      )}
    </div>
  );
}

function AnomalieCarte({ anomalie }: { anomalie: Anomalie }): ReactElement {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm font-semibold text-slate-900">{libelleRegle(anomalie.regle)}</p>
        <PastilleGravite gravite={anomalie.gravite} />
      </div>
      <EnTeteAnomalie anomalie={anomalie} />
      <p className="my-3 text-sm text-slate-700">{justification(anomalie)}</p>
      <div className="mb-3">
        <LiensAnomalie anomalie={anomalie} />
      </div>
      <ActionsAnomalie anomalie={anomalie} />
    </li>
  );
}

function AnomalieLigne({ anomalie }: { anomalie: Anomalie }): ReactElement {
  return (
    <tr>
      <td className="px-4 py-3 align-top text-slate-700">{libelleRegle(anomalie.regle)}</td>
      <td className="px-4 py-3 align-top">
        <PastilleGravite gravite={anomalie.gravite} />
      </td>
      <td className="px-4 py-3 align-top text-slate-700">{justification(anomalie)}</td>
      <td className="px-4 py-3 align-top text-slate-700">
        {anomalie.fournisseur ?? TIRET} · {anomalie.chantier ?? TIRET}
      </td>
      <td className="px-4 py-3 align-top">
        <LiensAnomalie anomalie={anomalie} />
      </td>
      <td className="px-4 py-3 align-top">
        <ActionsAnomalie anomalie={anomalie} />
      </td>
    </tr>
  );
}

function SectionListeAnomalies({ anomalies }: { anomalies: Anomalie[] }): ReactElement {
  if (anomalies.length === 0) {
    return <p className="text-sm text-slate-600">Aucune anomalie pour ces filtres.</p>;
  }
  return (
    <>
      {/* Cartes empilées : téléphone (< md) */}
      <ul className="space-y-3 md:hidden">
        {anomalies.map((anomalie) => (
          <AnomalieCarte key={anomalie.id} anomalie={anomalie} />
        ))}
      </ul>

      {/* Tableau : ordinateur (>= md) */}
      <div className="hidden overflow-x-auto rounded-lg border border-slate-200 bg-white md:block">
        <table className="w-full min-w-[1100px] divide-y divide-slate-200 text-sm">
          <caption className="sr-only">Anomalies</caption>
          <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
            <tr>
              <th scope="col" className="px-4 py-3">Règle</th>
              <th scope="col" className="px-4 py-3">Gravité</th>
              <th scope="col" className="px-4 py-3">Justification</th>
              <th scope="col" className="px-4 py-3">Fournisseur / chantier</th>
              <th scope="col" className="px-4 py-3">Source</th>
              <th scope="col" className="px-4 py-3">Traitement</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {anomalies.map((anomalie) => (
              <AnomalieLigne key={anomalie.id} anomalie={anomalie} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

interface FormFiltresProps {
  filtres: FiltresAnomalies;
  onChange: (filtres: FiltresAnomalies) => void;
  chantiers: Chantier[];
  fournisseurs: Fournisseur[];
}

/** Filtres combinables (règle, gravité, statut, chantier, fournisseur,
 * période) — chaque changement met à jour `filtres` immédiatement, sans
 * bouton « appliquer » (décision du contrôleur, cohérent avec des menus
 * déroulants et des dates plutôt qu'une recherche texte à débouncer). */
function FormFiltres({ filtres, onChange, chantiers, fournisseurs }: FormFiltresProps): ReactElement {
  return (
    <form
      onSubmit={(evenement) => evenement.preventDefault()}
      className="grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      <div>
        <label htmlFor="filtre-regle" className={CLASSES_LABEL}>
          Règle
        </label>
        <select
          id="filtre-regle"
          value={filtres.regle ?? ""}
          onChange={(evenement) =>
            onChange({ ...filtres, regle: evenement.target.value === "" ? undefined : evenement.target.value })
          }
          className={CLASSES_CHAMP}
        >
          <option value="">Toutes les règles</option>
          {CODES_REGLE.map((code) => (
            <option key={code} value={code}>
              {libelleRegle(code)}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="filtre-gravite" className={CLASSES_LABEL}>
          Gravité
        </label>
        <select
          id="filtre-gravite"
          value={filtres.gravite ?? ""}
          onChange={(evenement) =>
            onChange({
              ...filtres,
              gravite: evenement.target.value === "" ? undefined : (evenement.target.value as GraviteAnomalie),
            })
          }
          className={CLASSES_CHAMP}
        >
          <option value="">Toutes les gravités</option>
          <option value="haute">Haute</option>
          <option value="moyenne">Moyenne</option>
          <option value="basse">Basse</option>
        </select>
      </div>

      <div>
        <label htmlFor="filtre-statut" className={CLASSES_LABEL}>
          Statut
        </label>
        <select
          id="filtre-statut"
          value={filtres.statut ?? "ouverte"}
          onChange={(evenement) =>
            onChange({ ...filtres, statut: evenement.target.value as StatutAnomalie })
          }
          className={CLASSES_CHAMP}
        >
          <option value="ouverte">Ouvertes</option>
          <option value="traitee">Traitées</option>
          <option value="ignoree">Ignorées</option>
          <option value="toutes">Toutes</option>
        </select>
      </div>

      <div>
        <label htmlFor="filtre-chantier" className={CLASSES_LABEL}>
          Chantier
        </label>
        <select
          id="filtre-chantier"
          value={filtres.chantierId ?? ""}
          onChange={(evenement) =>
            onChange({ ...filtres, chantierId: evenement.target.value === "" ? undefined : evenement.target.value })
          }
          className={CLASSES_CHAMP}
        >
          <option value="">Tous les chantiers</option>
          {chantiers.map((chantier) => (
            <option key={chantier.id} value={chantier.id}>
              {chantier.nom_canonique}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="filtre-fournisseur" className={CLASSES_LABEL}>
          Fournisseur
        </label>
        <select
          id="filtre-fournisseur"
          value={filtres.fournisseurId ?? ""}
          onChange={(evenement) =>
            onChange({
              ...filtres,
              fournisseurId: evenement.target.value === "" ? undefined : evenement.target.value,
            })
          }
          className={CLASSES_CHAMP}
        >
          <option value="">Tous les fournisseurs</option>
          {fournisseurs.map((fournisseur) => (
            <option key={fournisseur.id} value={fournisseur.id}>
              {fournisseur.nom}
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
    </form>
  );
}

/** Écran « Anomalies » de l'admin (L4-D17, CDC §4.6) : liste filtrable des
 * anomalies de rapprochement, mobile d'abord (cartes < `md`, tableau au-delà
 * — même convention que `ATraiter.tsx`). Réservé à l'admin par `GardeAdmin`
 * (voir `App.tsx`) : aucune vérification de rôle ici. */
export function Anomalies(): ReactElement {
  const [filtres, setFiltres] = useState<FiltresAnomalies>({ statut: "ouverte" });
  const chantiers = useQuery({ queryKey: CLE_CHANTIERS, queryFn: listerChantiers });
  const fournisseurs = useQuery({ queryKey: CLE_FOURNISSEURS, queryFn: listerFournisseurs });
  const anomalies = useQuery({
    queryKey: cleAnomalies(filtres),
    queryFn: () => listerAnomalies(filtres),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-slate-900">Anomalies</h1>

      <FormFiltres
        filtres={filtres}
        onChange={setFiltres}
        chantiers={chantiers.data ?? []}
        fournisseurs={fournisseurs.data ?? []}
      />

      {anomalies.isPending && (
        <p role="status" className="text-sm text-slate-500">
          Chargement…
        </p>
      )}
      {anomalies.isError && (
        <p role="alert" className="text-sm text-red-700">
          Impossible de charger les anomalies.
        </p>
      )}
      {anomalies.data && <SectionListeAnomalies anomalies={anomalies.data} />}
    </div>
  );
}
