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
import {
  CLE_CHANTIERS,
  CLE_FOURNISSEURS,
  type Chantier,
  type Fournisseur,
  listerChantiers,
  listerFournisseurs,
} from "../api/referentiels";
import { formaterDate, formaterDateHeure, formaterMontant, moisParis, TIRET } from "../lib/formats";
import { Bouton, EnTetePage, EtatVide, Filtres, type OptionFiltre } from "../ui";

type CodeFiltre = "tous" | "factures" | "bl" | "a_corriger";

/** Borne de `GET /api/documents` (`LIMITE_DOCUMENTS_DEFAUT`,
 * `ingest/lecture.py`) — dupliquée ici (aucune route ne l'expose) pour
 * signaler à l'admin, quand un filtre est actif, qu'un document plus ancien
 * que les 100 derniers déposés peut manquer à la liste (constat de revue,
 * tour de correction 1 : la borne existait déjà mais n'était jamais
 * signalée). */
const LIMITE_DOCUMENTS_LISTE = 100;

const OPTIONS_FILTRE: OptionFiltre[] = [
  { valeur: "tous", libelle: "Tous" },
  { valeur: "factures", libelle: "Factures" },
  { valeur: "bl", libelle: "Bons de livraison" },
  { valeur: "a_corriger", libelle: "À corriger" },
];

/** Ligne unifiée (document BL/enlèvement ou facture) affichée par la liste
 * « Documents » (brief Task 8) — un seul écran, un seul tableau, plutôt que
 * les deux onglets historiques (`BlDeposes`/`FacturesListe`).
 *
 * Constats de revue corrigés ici (tour de correction 1) : `chantierId`
 * (identifiant, ajouté à `DocumentReponse`), `numeroInterne`, `deposant` et
 * `confirmation` avaient disparu de la liste unifiée par rapport à l'ancien
 * `BlDeposes.tsx` ; `dateDoc`/`totalHt`/`confianceReduite` (une facture
 * seulement) par rapport à l'ancien `FacturesListe.tsx`. `chantierId` vaut
 * `null` pour une facture (l'API ne rattache un chantier qu'aux livraisons
 * qui la composent, pas à la facture elle-même — le filtre `?chantier=`
 * exclut donc les factures). `dateDoc` (tour de correction 2 : un BL/
 * enlèvement l'expose désormais aussi, `DocumentReponse.date_doc` — la
 * date du bon telle qu'imprimée, sa date de livraison, pas sa date de
 * dépôt) ne vaut `null` que si l'extraction n'a pas pu la lire. */
interface LigneListe {
  cle: string;
  lien: string;
  origine: "document" | "facture";
  libelleType: string;
  numero: string;
  numeroInterne: number | null;
  fournisseur: string | null;
  chantierBrut: string | null;
  chantierId: string | null;
  contexte: string | null;
  statut: string;
  creeLe: string;
  dateDoc: string | null;
  totalHt: string | null;
  confianceReduite: boolean;
  deposant: string | null;
  confirmation: "verifiee" | "ecart" | null;
}

function libelleTypeDocument(type: string): string {
  return type === "enlevement" ? "Enlèvement" : "Livraison";
}

/** Contexte affiché sous le numéro d'un bon (carte et tableau) : la date de
 * livraison (`date_doc`, la date du bon telle qu'imprimée) quand elle est
 * connue, suivie du chantier — constat de revue (tour de correction 3) : le
 * filtre `?mois=` classe un BL sur `date_doc` depuis le tour précédent, mais
 * cette date n'apparaissait jamais nulle part dans la liste (seule la date
 * de dépôt, `creeLe`, était affichée) — un BL déposé en septembre mais livré
 * en août paraissait donc mal classé par le filtre « August 2026 ». Repli
 * sur le seul chantier quand `date_doc` est inconnue (comportement d'avant
 * ce tour), jamais un texte vide. */
function contexteDocument(document: DocumentResume): string | null {
  if (document.date_doc === null) {
    return document.chantier_brut;
  }
  const livre = `Livré le ${formaterDate(document.date_doc)}`;
  return document.chantier_brut === null ? livre : `${livre} · ${document.chantier_brut}`;
}

function depuisDocument(document: DocumentResume): LigneListe {
  return {
    cle: `document-${document.id}`,
    lien: `/bl/${document.id}`,
    origine: "document",
    libelleType: libelleTypeDocument(document.type),
    numero: document.numero ?? "non détecté",
    numeroInterne: document.numero_interne,
    fournisseur: document.fournisseur,
    chantierBrut: document.chantier_brut,
    chantierId: document.chantier_id,
    contexte: contexteDocument(document),
    statut: document.statut,
    creeLe: document.cree_le,
    dateDoc: document.date_doc,
    totalHt: null,
    confianceReduite: false,
    deposant: document.deposant,
    confirmation: document.confirmation,
  };
}

function depuisFacture(facture: FactureResume): LigneListe {
  return {
    cle: `facture-${facture.id}`,
    lien: `/documents/${facture.id}`,
    origine: "facture",
    libelleType: "Facture",
    numero: facture.numero,
    numeroInterne: null,
    fournisseur: facture.fournisseur,
    chantierBrut: null,
    chantierId: null,
    contexte:
      `Facture du ${formaterDate(facture.date_doc)} · ` +
      `${facture.nb_blocs_recus} / ${facture.nb_blocs} BL reçus`,
    statut: facture.statut,
    creeLe: facture.cree_le,
    dateDoc: facture.date_doc,
    totalHt: facture.total_ht,
    confianceReduite: facture.confiance_reduite,
    deposant: null,
    confirmation: null,
  };
}

/** Mois d'une ligne, pour le filtre `?mois=` (tour de correction 1) — même
 * convention que le mois retenu pour une facture (L5-D4, `ingest/bilan.py`) :
 * la date du document (`date_doc`, une simple date « AAAA-MM-JJ », sans
 * fuseau — la date de facture pour une facture, la date du bon telle
 * qu'imprimée, donc sa date de livraison, pour un BL/enlèvement depuis le
 * tour de correction 2, `DocumentReponse.date_doc`) fait foi quand elle est
 * connue ; à défaut (extraction n'ayant pas pu la lire), la date de dépôt
 * (`cree_le`, un horodatage UTC) convertie en heure de Paris. Jamais une
 * simple troncature de la chaîne ISO (constat de revue : un dépôt entre
 * minuit et 2 h, heure de Paris, tombait sinon dans le mois suivant). */
function moisLigne(ligne: LigneListe): string {
  if (ligne.dateDoc !== null) {
    return ligne.dateDoc.slice(0, 7);
  }
  return moisParis(ligne.creeLe);
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

/** Pastille de statut (constat de revue corrigé ici) : « Reçu » ne veut
 * rien dire pour une facture (elle n'est jamais « reçue » au sens où un BL
 * l'est) — seul un statut « À vérifier » reste affiché pour une facture,
 * sinon un tiret (l'ancien `FacturesListe.tsx` n'affichait déjà rien de
 * plus ici, laissant la place aux badges dédiés — confiance réduite,
 * motifs). */
function PastilleStatut({ ligne }: { ligne: LigneListe }): ReactElement {
  if (ligne.statut === "a_verifier") {
    return (
      <span className="inline-flex shrink-0 rounded-full bg-[#fbe9c6] px-2 py-0.5 text-xs font-medium text-[#7a4a00]">
        À vérifier
      </span>
    );
  }
  if (ligne.origine === "facture") {
    return <span className="text-sm text-encre-2">{TIRET}</span>;
  }
  return (
    <span className="inline-flex shrink-0 rounded-full bg-[#e4f1ea] px-2 py-0.5 text-xs font-medium text-encre">
      Reçu
    </span>
  );
}

/** Badge « Confiance réduite » d'une facture (repris de l'ancien
 * `FacturesListe.tsx`, perdu par la fusion dans la liste unifiée — constat
 * de revue) : jamais de jargon technique dans le texte affiché (spec §5,
 * sans jargon). */
function BadgeConfianceReduite(): ReactElement {
  return (
    <span className="inline-flex shrink-0 items-center rounded-full bg-[#fbe9c6] px-2 py-0.5 text-xs font-medium text-[#7a4a00]">
      Confiance réduite (lecture automatique)
    </span>
  );
}

function libelleConfirmationCourt(confirmation: "verifiee" | "ecart"): string {
  return confirmation === "verifiee" ? "Quantités vérifiées" : "Écart signalé";
}

/** Confirmation des quantités d'un bon (repris de l'ancien
 * `BlDeposes.tsx`, perdu par la fusion — constat de revue) : seulement le
 * statut ici (« qui et quand » figure dans le détail du bon, `PageBl.tsx`
 * — spec « et/ou »), pour ne pas surcharger la liste. */
function BadgeConfirmation({ confirmation }: { confirmation: "verifiee" | "ecart" }): ReactElement {
  const classes = confirmation === "verifiee" ? "text-conforme" : "text-ecart-texte";
  return (
    <span className={`inline-flex shrink-0 items-center gap-1.5 text-xs font-medium ${classes}`}>
      <span
        aria-hidden="true"
        className={`h-2 w-2 shrink-0 rounded-full ${confirmation === "verifiee" ? "bg-conforme" : "bg-ecart"}`}
      />
      {libelleConfirmationCourt(confirmation)}
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
          {ligne.numeroInterne !== null && (
            <p className="text-xs text-encre-2">Document n° {ligne.numeroInterne}</p>
          )}
          <p className="text-xs text-encre-2">{ligne.fournisseur ?? TIRET}</p>
          {ligne.contexte !== null && <p className="text-xs text-encre-2">{ligne.contexte}</p>}
          {ligne.deposant !== null && <p className="text-xs text-encre-2">Déposé par {ligne.deposant}</p>}
          {ligne.origine === "facture" && ligne.totalHt !== null && (
            <p className="text-xs text-encre-2">Total HT : {formaterMontant(ligne.totalHt)}</p>
          )}
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <PastilleStatut ligne={ligne} />
          {ligne.confianceReduite && <BadgeConfianceReduite />}
        </div>
      </div>
      {ligne.confirmation !== null && <BadgeConfirmation confirmation={ligne.confirmation} />}
      <p className="mt-2 text-xs text-encre-2">{formaterDateHeure(ligne.creeLe)}</p>
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
        {ligne.numeroInterne !== null && (
          <p className="mt-0.5 text-xs font-normal text-encre-2">Document n° {ligne.numeroInterne}</p>
        )}
        {ligne.deposant !== null && (
          <p className="mt-0.5 text-xs font-normal text-encre-2">Déposé par {ligne.deposant}</p>
        )}
        {/* Constat de revue (tour de correction 3) : le montant d'une facture
            doit rester visible à toute largeur, y compris sous 1440 px où la
            colonne dédiée (ci-dessous) est masquée — repris ici tel quel du
            texte déjà affiché par `CarteLigne` sur téléphone, sans aucune
            classe liée à une largeur d'écran. */}
        {ligne.origine === "facture" && ligne.totalHt !== null && (
          <p className="mt-0.5 text-xs font-normal text-encre-2">Total HT : {formaterMontant(ligne.totalHt)}</p>
        )}
      </td>
      <td className="px-4 py-3 text-encre">{ligne.libelleType}</td>
      <td className="px-4 py-3 text-encre">{ligne.fournisseur ?? TIRET}</td>
      <td className="px-4 py-3 text-encre">{ligne.contexte ?? TIRET}</td>
      <td className="hidden px-4 py-3 text-right font-mono text-encre min-[1440px]:table-cell">
        {ligne.origine === "facture" ? formaterMontant(ligne.totalHt) : null}
      </td>
      <td className="px-4 py-3 font-mono text-encre">{formaterDateHeure(ligne.creeLe)}</td>
      <td className="px-4 py-3">
        <div className="flex flex-col items-start gap-1.5">
          <PastilleStatut ligne={ligne} />
          {ligne.confianceReduite && <BadgeConfianceReduite />}
          {ligne.confirmation !== null && <BadgeConfirmation confirmation={ligne.confirmation} />}
        </div>
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
              <th scope="col" className="hidden px-4 py-3 text-right min-[1440px]:table-cell">Montant</th>
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
 *
 * Filtres dans l'URL (`?filtre=&mois=&chantier=&fournisseur=`, brief
 * Task 8, `fournisseur` ajouté au tour de correction 1 — spec §4) : tous
 * filtrent côté client, l'API n'exposant aucun de ces paramètres pour ces
 * deux listes (voir `docs/dette.md`). `mois` compare `moisLigne` (ci-dessus
 * — jamais une simple troncature de `cree_le`, un horodatage UTC).
 * `chantier`/`fournisseur` comparent respectivement `chantierId` (égalité
 * d'identifiant, corrigé au tour de correction 1 — comparait auparavant
 * `chantier_brut`, un texte non normalisé, par préfixe) et `fournisseur`
 * (égalité du nom résolu, jamais un texte brut). */
export function DocumentsListe(): ReactElement {
  const [parametres, setParametres] = useSearchParams();
  const { data: moi } = useQuery({ queryKey: CLE_MOI, queryFn: recupererMoi, staleTime: DUREE_CACHE_MOI });
  const estAdmin = moi?.role === "admin";

  const documents = useQuery({ queryKey: CLE_DOCUMENTS, queryFn: listerDocuments, refetchInterval: 15000 });
  const factures = useQuery({ queryKey: CLE_FACTURES, queryFn: listerFactures, enabled: estAdmin });
  const chantiers = useQuery({ queryKey: CLE_CHANTIERS, queryFn: listerChantiers, enabled: estAdmin });
  const fournisseurs = useQuery({ queryKey: CLE_FOURNISSEURS, queryFn: listerFournisseurs, enabled: estAdmin });

  const filtre = (parametres.get("filtre") as CodeFiltre | null) ?? "tous";
  const mois = parametres.get("mois") ?? "";
  const chantierId = parametres.get("chantier") ?? "";
  const fournisseurId = parametres.get("fournisseur") ?? "";

  function changerFiltre(valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur === "tous") {
      suivants.delete("filtre");
    } else {
      suivants.set("filtre", valeur);
    }
    setParametres(suivants, { replace: true });
  }

  function changerParametre(cle: string, valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur === "") {
      suivants.delete(cle);
    } else {
      suivants.set(cle, valeur);
    }
    setParametres(suivants, { replace: true });
  }

  // Tour de correction 1 : `chantierCible`/`fournisseurCible` résolus une
  // seule fois ici, tous deux consommés par le filtre ci-dessous et par les
  // deux `<select>` de la barre de filtres — un identifiant de l'URL qui ne
  // correspond à aucun chantier/fournisseur connu (lien obsolète, chantier
  // désactivé) ne filtre simplement plus rien plutôt que de planter.
  const chantierCible: Chantier | undefined = chantiers.data?.find((c) => c.id === chantierId);
  const fournisseurCible: Fournisseur | undefined = fournisseurs.data?.find((f) => f.id === fournisseurId);

  const lignes = useMemo(() => {
    const brutes: LigneListe[] = [
      ...(documents.data?.map(depuisDocument) ?? []),
      ...(estAdmin ? (factures.data?.map(depuisFacture) ?? []) : []),
    ];
    const filtrees = brutes.filter((ligne) => {
      if (!correspondFiltre(ligne, filtre)) {
        return false;
      }
      if (mois !== "" && moisLigne(ligne) !== mois) {
        return false;
      }
      if (chantierCible !== undefined && ligne.chantierId !== chantierCible.id) {
        return false;
      }
      // Comparé par nom (égalité stricte), pas par préfixe : contrairement
      // à `chantier_brut`, `fournisseur` est déjà le nom résolu
      // (`Fournisseur.nom`, jointe côté serveur), jamais un texte brut de
      // lecture automatique — voir `docs/dette.md`.
      if (fournisseurCible !== undefined && ligne.fournisseur !== fournisseurCible.nom) {
        return false;
      }
      return true;
    });
    return filtrees.sort((a, b) => b.creeLe.localeCompare(a.creeLe));
  }, [documents.data, factures.data, estAdmin, filtre, mois, chantierCible, fournisseurCible]);

  if (!estAdmin) {
    return <VueAgent documents={documents} />;
  }

  // Signalé seulement quand un filtre est actif : sans filtre, la liste
  // affiche de toute façon tout ce qui a été chargé, la borne ne cache
  // alors rien (constat de revue, tour de correction 1).
  const filtreActif = mois !== "" || chantierId !== "" || fournisseurId !== "";
  const documentsPeutEtreTronques = (documents.data?.length ?? 0) >= LIMITE_DOCUMENTS_LISTE;

  return (
    <div className="space-y-6">
      <EnTetePage titre="Documents" actions={<DepotFacture />} />

      <div className="flex flex-wrap items-end justify-between gap-4">
        <Filtres options={OPTIONS_FILTRE} valeur={filtre} onChange={changerFiltre} />
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="documents-mois" className="mb-1 block text-xs font-medium text-encre-2">
              Mois
            </label>
            <input
              id="documents-mois"
              type="month"
              value={mois}
              onChange={(evenement) => changerParametre("mois", evenement.target.value)}
              className="min-h-[44px] rounded-md border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent"
            />
          </div>
          <div>
            <label htmlFor="documents-chantier" className="mb-1 block text-xs font-medium text-encre-2">
              Chantier
            </label>
            <select
              id="documents-chantier"
              value={chantierId}
              onChange={(evenement) => changerParametre("chantier", evenement.target.value)}
              className="min-h-[44px] rounded-md border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <option value="">Tous les chantiers</option>
              {chantiers.data?.map((chantier) => (
                <option key={chantier.id} value={chantier.id}>
                  {chantier.nom_canonique}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="documents-fournisseur" className="mb-1 block text-xs font-medium text-encre-2">
              Fournisseur
            </label>
            <select
              id="documents-fournisseur"
              value={fournisseurId}
              onChange={(evenement) => changerParametre("fournisseur", evenement.target.value)}
              className="min-h-[44px] rounded-md border border-bordure bg-surface px-3 py-2 text-sm text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <option value="">Tous les fournisseurs</option>
              {fournisseurs.data?.map((fournisseur) => (
                <option key={fournisseur.id} value={fournisseur.id}>
                  {fournisseur.nom}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {(chantierCible !== undefined || fournisseurCible !== undefined) && (
        <p className="text-sm text-encre-2">
          Filtré sur
          {chantierCible !== undefined && (
            <>
              {" "}
              le chantier <strong className="text-encre">{chantierCible.nom_canonique}</strong>
            </>
          )}
          {chantierCible !== undefined && fournisseurCible !== undefined && " et"}
          {fournisseurCible !== undefined && (
            <>
              {" "}
              le fournisseur <strong className="text-encre">{fournisseurCible.nom}</strong>
            </>
          )}
          {" · "}
          <button
            type="button"
            onClick={() => {
              const suivants = new URLSearchParams(parametres);
              suivants.delete("chantier");
              suivants.delete("fournisseur");
              setParametres(suivants, { replace: true });
            }}
            className="underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Retirer le filtre
          </button>
        </p>
      )}

      {filtreActif && documentsPeutEtreTronques && (
        <p className="text-xs text-encre-2">
          Seuls les {LIMITE_DOCUMENTS_LISTE} bons de livraison les plus récents sont chargés ici — un bon plus
          ancien peut manquer à ce filtre.
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
