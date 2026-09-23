import { type ChangeEvent, type ReactElement, useMemo, useRef } from "react";
import { type UseQueryResult, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router";

import { ErreurApi } from "../api/client";
import { CLE_DOCUMENTS, type DocumentResume, listerDocuments } from "../api/documents";
import {
  CLE_FACTURES,
  type FactureResume,
  FactureEnDoubleErreur,
  deposerFacture,
  listerFactures,
} from "../api/factures";
import { CLE_MOI, DUREE_CACHE_MOI, recupererMoi } from "../api/moi";
import { CLE_CHANTIERS, type Chantier, listerChantiers } from "../api/referentiels";
import { formaterDateHeure, TIRET } from "../lib/formats";
import { Bouton, EnTetePage, EtatVide, Filtres, type OptionFiltre } from "../ui";

type CodeFiltre = "tous" | "factures" | "bl" | "a_corriger";

const OPTIONS_FILTRE: OptionFiltre[] = [
  { valeur: "tous", libelle: "Tous" },
  { valeur: "factures", libelle: "Factures" },
  { valeur: "bl", libelle: "Bons de livraison" },
  { valeur: "a_corriger", libelle: "À corriger" },
];

/** Ligne unifiée (document BL/enlèvement ou facture) affichée par la liste
 * « Documents » (brief Task 8) — un seul écran, un seul tableau, plutôt que
 * les deux onglets historiques (`BlDeposes`/`FacturesListe`). `chantierBrut`
 * reste `null` pour une facture (l'API ne rattache un chantier qu'aux
 * livraisons qui la composent, pas à la facture elle-même) : le filtre
 * `?chantier=` (best-effort, voir plus bas) exclut donc naturellement les
 * factures. */
interface LigneListe {
  cle: string;
  lien: string;
  origine: "document" | "facture";
  libelleType: string;
  numero: string;
  fournisseur: string | null;
  chantierBrut: string | null;
  contexte: string | null;
  statut: string;
  creeLe: string;
}

function libelleTypeDocument(type: string): string {
  return type === "enlevement" ? "Enlèvement" : "Livraison";
}

function depuisDocument(document: DocumentResume): LigneListe {
  return {
    cle: `document-${document.id}`,
    lien: `/bl/${document.id}`,
    origine: "document",
    libelleType: libelleTypeDocument(document.type),
    numero: document.numero ?? "non détecté",
    fournisseur: document.fournisseur,
    chantierBrut: document.chantier_brut,
    contexte: document.chantier_brut,
    statut: document.statut,
    creeLe: document.cree_le,
  };
}

function depuisFacture(facture: FactureResume): LigneListe {
  return {
    cle: `facture-${facture.id}`,
    lien: `/documents/${facture.id}`,
    origine: "facture",
    libelleType: "Facture",
    numero: facture.numero,
    fournisseur: facture.fournisseur,
    chantierBrut: null,
    contexte: `${facture.nb_blocs_recus} / ${facture.nb_blocs} BL reçus`,
    statut: facture.statut,
    creeLe: facture.cree_le,
  };
}

function correspondFiltre(ligne: LigneListe, filtre: CodeFiltre): boolean {
  if (filtre === "tous") {
    return true;
  }
  if (filtre === "factures") {
    return ligne.origine === "facture";
  }
  if (filtre === "bl") {
    return ligne.origine === "document";
  }
  return ligne.statut === "a_verifier";
}

function libelleStatut(statut: string): string {
  return statut === "a_verifier" ? "À vérifier" : "Reçu";
}

function PastilleStatut({ statut }: { statut: string }): ReactElement {
  const classes =
    statut === "a_verifier" ? "bg-[#fbe9c6] text-[#7a4a00]" : "bg-[#e4f1ea] text-encre";
  return (
    <span className={`inline-flex shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}>
      {libelleStatut(statut)}
    </span>
  );
}

function ContenuErreurDepot({ erreur }: { erreur: unknown }): ReactElement {
  if (erreur instanceof FactureEnDoubleErreur) {
    return (
      <>
        Facture déjà déposée.{" "}
        <Link to={`/documents/${erreur.originalId}`} className="font-medium underline">
          Voir la facture d'origine
        </Link>
      </>
    );
  }
  if (erreur instanceof ErreurApi) {
    return <>{erreur.detail}</>;
  }
  return <>Une erreur est survenue, réessayez.</>;
}

/** Bouton + entrée fichier masquée de dépôt d'une facture PDF (admin,
 * reprise de l'ancienne `FacturesListe.tsx`) — même logique, même service
 * (`deposerFacture`), seule la redirection change : vers `/documents/:id`
 * (qui sait désormais afficher une facture), plus `/factures/:id`. */
function DepotFacture(): ReactElement {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const entreeFichier = useRef<HTMLInputElement>(null);

  const depot = useMutation({
    mutationFn: (fichier: File) => deposerFacture(fichier),
    onSuccess: async (deposee) => {
      await queryClient.invalidateQueries({ queryKey: CLE_FACTURES });
      navigate(`/documents/${deposee.id}`);
    },
  });

  function surChangementFichier(evenement: ChangeEvent<HTMLInputElement>): void {
    const fichier = evenement.target.files?.[0];
    // Réinitialisé tout de suite : redéposer le même fichier après une
    // erreur doit redéclencher `onChange` (sinon le navigateur l'ignore, la
    // valeur de l'input n'ayant pas changé).
    evenement.target.value = "";
    if (fichier) {
      depot.mutate(fichier);
    }
  }

  return (
    <div>
      <label htmlFor="depot-facture" className="sr-only">
        Fichier PDF de la facture à déposer
      </label>
      <input
        ref={entreeFichier}
        id="depot-facture"
        type="file"
        accept="application/pdf"
        className="sr-only"
        disabled={depot.isPending}
        onChange={surChangementFichier}
      />
      <Bouton onClick={() => entreeFichier.current?.click()} disabled={depot.isPending}>
        Déposer une facture
      </Bouton>
      <div aria-live="polite">
        {depot.isPending && (
          <p className="mt-2 text-sm text-encre-2">Lecture de la facture en cours (jusqu'à une minute)…</p>
        )}
        {depot.isError && (
          <p role="alert" className="mt-2 text-sm text-alerte">
            <ContenuErreurDepot erreur={depot.error} />
          </p>
        )}
      </div>
    </div>
  );
}

function CarteLigne({ ligne }: { ligne: LigneListe }): ReactElement {
  return (
    <li className="rounded-lg border border-bordure bg-surface p-4">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-encre">
            <Link to={ligne.lien} className="underline outline-none focus-visible:ring-2 focus-visible:ring-accent">
              {ligne.libelleType} {ligne.numero}
            </Link>
          </p>
          <p className="text-xs text-encre-2">{ligne.fournisseur ?? TIRET}</p>
          {ligne.contexte !== null && <p className="text-xs text-encre-2">{ligne.contexte}</p>}
        </div>
        <PastilleStatut statut={ligne.statut} />
      </div>
      <p className="text-xs text-encre-2">{formaterDateHeure(ligne.creeLe)}</p>
    </li>
  );
}

function LigneTableau({ ligne }: { ligne: LigneListe }): ReactElement {
  return (
    <tr>
      <td className="px-4 py-3 font-medium text-encre">
        <Link to={ligne.lien} className="underline outline-none focus-visible:ring-2 focus-visible:ring-accent">
          {ligne.numero}
        </Link>
      </td>
      <td className="px-4 py-3 text-encre">{ligne.libelleType}</td>
      <td className="px-4 py-3 text-encre">{ligne.fournisseur ?? TIRET}</td>
      <td className="px-4 py-3 text-encre">{ligne.contexte ?? TIRET}</td>
      <td className="px-4 py-3 font-mono text-encre">{formaterDateHeure(ligne.creeLe)}</td>
      <td className="px-4 py-3">
        <PastilleStatut statut={ligne.statut} />
      </td>
    </tr>
  );
}

function ListeUnifiee({ lignes }: { lignes: LigneListe[] }): ReactElement {
  if (lignes.length === 0) {
    return <EtatVide message="Aucun document pour ces filtres." />;
  }
  return (
    <>
      {/* Cartes empilées : téléphone (< md) */}
      <ul className="space-y-3 md:hidden">
        {lignes.map((ligne) => (
          <CarteLigne key={ligne.cle} ligne={ligne} />
        ))}
      </ul>

      {/* Tableau : ordinateur (>= md) */}
      <div className="hidden overflow-x-auto rounded-lg border border-bordure bg-surface md:block">
        <table className="w-full min-w-[880px] divide-y divide-bordure text-sm">
          <caption className="sr-only">Liste des documents (bons de livraison et factures)</caption>
          <thead className="border-b border-bordure text-left text-xs font-medium uppercase tracking-wide text-encre-2">
            <tr>
              <th scope="col" className="px-4 py-3">Numéro</th>
              <th scope="col" className="px-4 py-3">Type</th>
              <th scope="col" className="px-4 py-3">Fournisseur</th>
              <th scope="col" className="px-4 py-3">Chantier / réception</th>
              <th scope="col" className="px-4 py-3">Déposé le</th>
              <th scope="col" className="px-4 py-3">Statut</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-bordure">
            {lignes.map((ligne) => (
              <LigneTableau key={ligne.cle} ligne={ligne} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** Vue agent (terrain, Task 8) : reprise de l'ancienne `BlDeposes.tsx`, sans
 * filtre ni dépôt de facture (les factures sont réservées à l'admin, comme
 * aujourd'hui) — un agent ne voit que ses propres dépôts, droit vérifié par
 * `ingest.service.lister_documents`, jamais ici. */
function VueAgent({ documents }: { documents: UseQueryResult<DocumentResume[]> }): ReactElement {
  const lignes = useMemo(
    () => [...(documents.data ?? [])].sort((a, b) => b.cree_le.localeCompare(a.cree_le)).map(depuisDocument),
    [documents.data],
  );
  return (
    <div className="space-y-6">
      <EnTetePage titre="Mes dépôts" />
      {documents.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {documents.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger vos dépôts.
        </p>
      )}
      {!documents.isPending && !documents.isError && lignes.length === 0 && (
        <EtatVide message="Aucun bon de livraison déposé pour l'instant." />
      )}
      {!documents.isPending && lignes.length > 0 && <ListeUnifiee lignes={lignes} />}
    </div>
  );
}

/** Liste « Documents » (maquette de la refonte, Task 8) : fusionne les BL/
 * enlèvements (`GET /api/documents`) et les factures (`GET /api/factures`,
 * admin) dans un seul tableau filtrable, avec le dépôt d'une facture PDF —
 * remplace les anciens écrans « BL déposés » et « Factures ». Montée sur
 * `/documents`, sans garde de rôle explicite (comme avant Task 8) :
 * l'agent voit une vue simplifiée (`VueAgent`), l'admin la vue complète.
 * Filtres, mois et chantier dans l'URL (`?filtre=&mois=&chantier=`, brief
 * Task 8) : mois et chantier filtrent côté client sur `cree_le`/
 * `chantier_brut` (l'API ne les expose pas en paramètre de requête pour ces
 * deux listes), `chantier_brut` comparé en préfixe au nom canonique du
 * chantier (`startsWith`, insensible à la casse — gère « VILLA DES TILLEULS
 * (4521) », constat de la vérification visuelle Task 8 : `chantier_brut`
 * porte presque toujours un code entre parenthèses après le nom) — limite
 * connue malgré tout, notée dans `docs/dette.md` : un document dont
 * `chantier_brut` diffère plus profondément du nom canonique (variante,
 * faute de frappe, ordre des mots) n'apparaît pas quand le filtre
 * `?chantier=` est actif. */
export function DocumentsListe(): ReactElement {
  const [parametres, setParametres] = useSearchParams();
  const { data: moi } = useQuery({ queryKey: CLE_MOI, queryFn: recupererMoi, staleTime: DUREE_CACHE_MOI });
  const estAdmin = moi?.role === "admin";

  const documents = useQuery({ queryKey: CLE_DOCUMENTS, queryFn: listerDocuments, refetchInterval: 15000 });
  const factures = useQuery({ queryKey: CLE_FACTURES, queryFn: listerFactures, enabled: estAdmin });
  const chantiers = useQuery({ queryKey: CLE_CHANTIERS, queryFn: listerChantiers, enabled: estAdmin });

  const filtre = (parametres.get("filtre") as CodeFiltre | null) ?? "tous";
  const mois = parametres.get("mois") ?? "";
  const chantierId = parametres.get("chantier") ?? "";

  function changerFiltre(valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur === "tous") {
      suivants.delete("filtre");
    } else {
      suivants.set("filtre", valeur);
    }
    setParametres(suivants, { replace: true });
  }

  function changerMois(valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur === "") {
      suivants.delete("mois");
    } else {
      suivants.set("mois", valeur);
    }
    setParametres(suivants, { replace: true });
  }

  function retirerFiltreChantier(): void {
    const suivants = new URLSearchParams(parametres);
    suivants.delete("chantier");
    setParametres(suivants, { replace: true });
  }

  const chantierCible: Chantier | undefined = chantiers.data?.find((c) => c.id === chantierId);

  const lignes = useMemo(() => {
    const brutes: LigneListe[] = [
      ...(documents.data?.map(depuisDocument) ?? []),
      ...(estAdmin ? (factures.data?.map(depuisFacture) ?? []) : []),
    ];
    const filtrees = brutes.filter((ligne) => {
      if (!correspondFiltre(ligne, filtre)) {
        return false;
      }
      if (mois !== "" && !ligne.creeLe.startsWith(mois)) {
        return false;
      }
      if (chantierCible !== undefined) {
        if (ligne.chantierBrut === null) {
          return false;
        }
        // `chantier_brut` porte souvent un code entre parenthèses après le
        // nom (« VILLA DES TILLEULS (4521) », constat de la vérification
        // visuelle Task 8, cohérent avec toutes les fixtures démo) : une
        // égalité stricte avec le nom canonique ne matchait jamais aucun
        // document. `startsWith` reste précis (un préfixe partagé par
        // coïncidence entre deux chantiers différents est possible mais
        // rare) sans dépendre d'un format de code particulier.
        if (
          !ligne.chantierBrut.trim().toLowerCase().startsWith(chantierCible.nom_canonique.trim().toLowerCase())
        ) {
          return false;
        }
      }
      return true;
    });
    return filtrees.sort((a, b) => b.creeLe.localeCompare(a.creeLe));
  }, [documents.data, factures.data, estAdmin, filtre, mois, chantierCible]);

  if (!estAdmin) {
    return <VueAgent documents={documents} />;
  }

  return (
    <div className="space-y-6">
      <EnTetePage titre="Documents" actions={<DepotFacture />} />

      <div className="flex flex-wrap items-center justify-between gap-4">
        <Filtres options={OPTIONS_FILTRE} valeur={filtre} onChange={changerFiltre} />
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <label htmlFor="documents-mois" className="mb-1 block text-xs font-medium text-encre-2">
              Mois
            </label>
            <input
              id="documents-mois"
              type="month"
              value={mois}
              onChange={(evenement) => changerMois(evenement.target.value)}
              className="rounded-md border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent"
            />
          </div>
        </div>
      </div>

      {chantierCible !== undefined && (
        <p className="text-sm text-encre-2">
          Filtré sur le chantier <strong className="text-encre">{chantierCible.nom_canonique}</strong>{" "}
          <button
            type="button"
            onClick={retirerFiltreChantier}
            className="ml-1 underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Retirer le filtre
          </button>
        </p>
      )}

      {documents.isPending && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {documents.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les documents.
        </p>
      )}
      {estAdmin && factures.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les factures.
        </p>
      )}

      {!documents.isPending && <ListeUnifiee lignes={lignes} />}
    </div>
  );
}
