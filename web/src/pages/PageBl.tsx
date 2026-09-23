import { type ReactElement, useEffect, useRef, useState } from "react";
import { type UseQueryResult, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";

import { ErreurApi } from "../api/client";
import {
  type ComparaisonBl,
  type DocumentDetail as DonneesDocument,
  type LigneComparee,
  cleComparaisonBl,
  cleDocument,
  lireDocument,
  obtenirComparaisonBl,
  urlTelechargement,
} from "../api/documents";
import { CLE_MOI, DUREE_CACHE_MOI, recupererMoi } from "../api/moi";
import { formaterDate, formaterDateHeure, formaterMontant, formaterQuantite, TIRET } from "../lib/formats";
import { Carte, EtatVide, FilAriane, type ElementFilAriane, titreRegle } from "../ui";
import { DocumentDetail } from "./DocumentDetail";
import { FactureDetail } from "./FactureDetail";

/** `type` d'un document (BL ou enlèvement, seuls types que cette page reçoit
 * — un enlèvement est traité comme un BL, CDC §« Bons d'enlèvement » :
 * « traités comme des BL »). Présentation uniquement, même duplication
 * assumée qu'ailleurs dans ces pages (décision du contrôleur, L3-T9). */
function libelleTypePage(type: string): string {
  return type === "enlevement" ? "Enlèvement" : "Bon de livraison";
}

function libelleStatutDocument(statut: string): string {
  if (statut === "a_verifier") {
    return "À vérifier";
  }
  if (statut === "archive") {
    return "Archivé";
  }
  return "Reçu";
}

function texteConfirmation(confirmation: "verifiee" | "ecart" | null): string {
  if (confirmation === "verifiee") {
    return "oui";
  }
  if (confirmation === "ecart") {
    return "écart signalé";
  }
  return "pas encore";
}

function classesConfirmation(confirmation: "verifiee" | "ecart" | null): string {
  if (confirmation === "verifiee") {
    return "text-conforme";
  }
  if (confirmation === "ecart") {
    return "text-ecart-texte";
  }
  return "text-encre-2";
}

/** Fil d'Ariane « Chantiers › chantier › n° BL » (spec, maquette `BL`) : le
 * chantier n'est un lien que lorsqu'il est rattaché (`chantier_id` connu) —
 * un document jamais rattaché affiche « Chantier à rattacher » en texte
 * seul, jamais un lien mort. */
function construireFilAriane(donnees: DonneesDocument, numero: string): ElementFilAriane[] {
  const elements: ElementFilAriane[] = [{ libelle: "Chantiers", vers: "/chantiers" }];
  if (donnees.chantier !== null) {
    elements.push(
      donnees.chantier_id !== null
        ? { libelle: donnees.chantier, vers: `/chantiers/${donnees.chantier_id}` }
        : { libelle: donnees.chantier },
    );
  } else {
    elements.push({ libelle: "Chantier à rattacher" });
  }
  elements.push({ libelle: numero });
  return elements;
}

/** Pastille combinée statut/problèmes (maquette `BL` : « Reçu · 2 écarts de
 * prix ») — les états possibles (`a_verifier`/`archive`/reçu, croisés avec
 * un compte de problèmes ouverts) ne rentrent pas dans les six valeurs
 * fixes de `ui/PastilleEtat.tsx` (`Etat`) : composant local dédié plutôt que
 * détourner ce composant partagé (consigne : ne pas modifier `ui/`).
 * Toujours doublée d'un libellé en toutes lettres, jamais la couleur seule
 * (spec §2).
 *
 * Constat de revue corrigé au tour de correction 1 : « Conforme »
 * n'apparaît plus que lorsque `nb_problemes` (calculé par le serveur, voir
 * `api/documents.ts::ComparaisonBl`) vaut `0` **et** qu'une facture cite
 * bien ce bon (`factureConnue`) — un bon jamais facturé affichait
 * auparavant « Conforme » à tort (aucune ligne comparée, donc aucune
 * `regles_ouvertes`, mais rien n'a en réalité été vérifié) ; il affiche
 * désormais « Pas encore facturé ». */
function PastilleDocument({
  statut,
  nbProblemes,
  comparaisonChargee,
  factureConnue,
}: {
  statut: string;
  nbProblemes: number;
  comparaisonChargee: boolean;
  factureConnue: boolean;
}): ReactElement {
  const libelleStatut = libelleStatutDocument(statut);
  const pasEncoreFacture = comparaisonChargee && !factureConnue && nbProblemes === 0;
  let texte = libelleStatut;
  if (nbProblemes > 0) {
    texte = `${libelleStatut} · ${nbProblemes} problème${nbProblemes > 1 ? "s" : ""}`;
  } else if (pasEncoreFacture) {
    texte = `${libelleStatut} · Pas encore facturé`;
  } else if (comparaisonChargee) {
    texte = `${libelleStatut} · Conforme`;
  }
  const classes =
    nbProblemes > 0
      ? "bg-[#fbe9c6] text-[#7a4a00]"
      : pasEncoreFacture || statut === "archive"
        ? "bg-bordure text-encre"
        : "bg-[#e4f1ea] text-encre";
  const classeDot =
    nbProblemes > 0 || statut === "a_verifier"
      ? "bg-ecart"
      : pasEncoreFacture || statut === "archive"
        ? "bg-encre-2"
        : "bg-conforme";
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-full px-3 py-1 text-sm font-medium ${classes}`}
    >
      <span aria-hidden="true" className={`h-2.5 w-2.5 shrink-0 rounded-full ${classeDot}`} />
      {texte}
    </span>
  );
}

/** Photo du bon (maquette `BL`) : `onError` couvre le PDF (pas une image)
 * ou le fichier absent du disque — seul le lien « Ouvrir en grand » reste
 * alors utilisable (même technique que l'ancien `Photo` de
 * `DocumentDetail.tsx`, avant que Task 8 ne la reprenne ici). */
function PhotoBl({ id, numero }: { id: string; numero: string }): ReactElement {
  const [enErreur, setEnErreur] = useState(false);
  const src = `/api/documents/${id}/fichier`;
  return (
    <div className="flex flex-1 items-center justify-center overflow-hidden rounded-lg bg-fond">
      {enErreur ? (
        <a
          href={src}
          target="_blank"
          rel="noopener noreferrer"
          className="p-6 text-center text-sm font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Ce fichier ne s'affiche pas ici — l'ouvrir dans un nouvel onglet
        </a>
      ) : (
        <img
          src={src}
          loading="lazy"
          onError={() => setEnErreur(true)}
          alt={`Photo du bon de livraison ${numero}`}
          className="max-h-[420px] w-full object-contain"
        />
      )}
    </div>
  );
}

/** Colonne « Contrôle » d'une ligne comparée (maquette `BL`) : les codes de
 * `regles_ouvertes` (Task 3) sont traduits par `titreRegle` — jamais le code
 * brut affiché (spec §5, sans jargon). Aucune ligne ouverte et une facture
 * citant bien ce bon (`factureConnue`) = « Conforme » ; aucune ligne
 * ouverte mais aucune facture ne cite encore ce bon = « Pas encore
 * facturé » (constat de revue corrigé au tour de correction 1 : cette
 * ligne n'a en réalité jamais été comparée à rien, « Conforme » l'affirmait
 * à tort). */
function ControleLigne({ regles, factureConnue }: { regles: string[]; factureConnue: boolean }): ReactElement {
  if (regles.length === 0) {
    if (!factureConnue) {
      return (
        <span className="inline-flex items-center gap-2 text-encre-2">
          <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full bg-encre-2" />
          Pas encore facturé
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-2 text-conforme">
        <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full bg-conforme" />
        Conforme
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-2 text-ecart-texte">
      <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full bg-ecart" />
      {regles.map((code) => titreRegle(code)).join(", ")}
    </span>
  );
}

function ArticleLigne({ ligne }: { ligne: LigneComparee }): ReactElement {
  return (
    <>
      <p className="font-medium text-encre">{ligne.article ?? ligne.code ?? TIRET}</p>
      {ligne.code !== null && ligne.article !== null && (
        <p className="font-mono text-xs text-encre-2">{ligne.code}</p>
      )}
    </>
  );
}

/** Tableau (ordinateur) / cartes empilées (téléphone) du contenu « Livré et
 * facturé » d'un BL (maquette `BL`) — colonnes Article, Livré, Facturé, Prix
 * unit., Contrôle (brief Task 8). Aucun calcul ici : `qte_livree`/
 * `qte_facturee`/`pu_facture` viennent tels quels de `GET /api/documents/
 * {id}/comparaison` (Task 3). */
function TableauLivreFacture({
  lignes,
  factureConnue,
}: {
  lignes: LigneComparee[];
  factureConnue: boolean;
}): ReactElement {
  if (lignes.length === 0) {
    return <EtatVide message="Aucune ligne sur ce bon." />;
  }
  return (
    <>
      {/* Cartes empilées : téléphone (< md) */}
      <ul className="space-y-3 md:hidden">
        {lignes.map((ligne) => (
          <li key={ligne.ordre} className="rounded-lg border border-bordure p-3 text-sm">
            <ArticleLigne ligne={ligne} />
            <dl className="mt-2 grid grid-cols-3 gap-x-3 gap-y-1 text-xs text-encre-2">
              <div>
                <dt>Livré</dt>
                <dd className="font-mono text-sm text-encre">{formaterQuantite(ligne.qte_livree)}</dd>
              </div>
              <div>
                <dt>Facturé</dt>
                <dd className="font-mono text-sm text-encre">{formaterQuantite(ligne.qte_facturee)}</dd>
              </div>
              <div>
                <dt>Prix unit.</dt>
                <dd className="font-mono text-sm text-encre">{formaterMontant(ligne.pu_facture)}</dd>
              </div>
            </dl>
            <div className="mt-2 text-sm">
              <ControleLigne regles={ligne.regles_ouvertes} factureConnue={factureConnue} />
            </div>
          </li>
        ))}
      </ul>

      {/* Tableau : ordinateur (>= md) */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[560px] text-sm">
          <caption className="sr-only">Lignes livrées et facturées de ce bon</caption>
          <thead className="border-b border-bordure text-left text-xs font-medium uppercase tracking-wide text-encre-2">
            <tr>
              <th scope="col" className="py-2 pr-3">Article</th>
              <th scope="col" className="py-2 pr-3 text-right">Livré</th>
              <th scope="col" className="py-2 pr-3 text-right">Facturé</th>
              <th scope="col" className="py-2 pr-3 text-right">Prix unit.</th>
              <th scope="col" className="py-2">Contrôle</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-bordure">
            {lignes.map((ligne) => (
              <tr key={ligne.ordre}>
                <td className="py-2 pr-3">
                  <ArticleLigne ligne={ligne} />
                </td>
                <td className="py-2 pr-3 text-right font-mono text-encre">
                  {formaterQuantite(ligne.qte_livree)}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-encre">
                  {formaterQuantite(ligne.qte_facturee)}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-encre">
                  {formaterMontant(ligne.pu_facture)}
                </td>
                <td className="py-2">
                  <ControleLigne regles={ligne.regles_ouvertes} factureConnue={factureConnue} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** Carte « Livré et facturé » (admin, BL uniquement — un enlèvement n'a pas
 * de comparaison, le serveur refuse `GET .../comparaison` pour ce type,
 * voir `api/documents.ts::obtenirComparaisonBl`) : contenu de
 * `comparaison`, lien « Voir la facture » et bouton « Régler les N
 * problèmes » (brief Task 8, vers `/a-regler?document=`). */
function CarteLivreFacture({
  documentId,
  comparaison,
  nbProblemes,
}: {
  documentId: string;
  comparaison: UseQueryResult<ComparaisonBl>;
  nbProblemes: number;
}): ReactElement {
  const donnees = comparaison.data;
  return (
    <Carte
      titre="Livré et facturé"
      action={
        donnees?.facture_id !== null && donnees?.facture_id !== undefined ? (
          <Link
            to={`/documents/${donnees.facture_id}`}
            className="text-sm font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
          >
            Voir la facture {donnees.numero_facture}
          </Link>
        ) : undefined
      }
    >
      {comparaison.isPending && (
        <p role="status" className="text-sm text-encre-2">Chargement…</p>
      )}
      {comparaison.isError && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger la comparaison avec la facture.
        </p>
      )}
      {donnees && (
        <>
          <TableauLivreFacture lignes={donnees.lignes} factureConnue={donnees.facture_id !== null} />
          <div className="mt-4 flex items-center justify-between border-t border-bordure pt-3 text-sm">
            <span className="text-encre-2">Montant facturé pour ce bon</span>
            <span className="font-mono font-semibold text-encre">
              {formaterMontant(donnees.montant_facture_ht)} HT
            </span>
          </div>
          {nbProblemes > 0 && (
            <div className="mt-4">
              <Link
                to={`/a-regler?document=${documentId}`}
                className="inline-flex min-h-[44px] items-center justify-center rounded-lg bg-accent px-4 text-sm font-medium text-white outline-none hover:bg-accent-fonce focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
              >
                Régler les {nbProblemes} problèmes
              </Link>
            </div>
          )}
        </>
      )}
    </Carte>
  );
}

/** Section repliable « Corriger la lecture du bon » (brief Task 8) : monte
 * intégralement la logique de correction existante de `DocumentDetail.tsx`
 * (formulaire de correction, ré-extraction, validation, archivage) — jamais
 * réécrite, seulement habillée (voir le commentaire de tête de
 * `DocumentDetail.tsx`). N'est montée que lorsque `modifiable` vaut `true`
 * (admin, document non archivé) : un agent, pour qui `modifiable` vaut
 * toujours `false`, ne voit jamais cette section.
 *
 * `titre`/`ouvertParDefaut` (tour de correction 1) : le même composant sert
 * aussi à l'admin consultant un document archivé (`!donnees.modifiable`,
 * voir `PageBl` ci-dessous) — `DocumentDetail` sait déjà s'afficher en
 * lecture seule dans ce cas (aucun bouton d'édition, `donnees.modifiable`
 * décide seul), mais `PageBl` ne la montait alors pas du tout : plus aucun
 * champ ni ligne n'était visible pour un document archivé (constat de
 * revue). Titre et ouverture par défaut différents pour ce second usage :
 * rien à corriger, la section s'appelle « Lecture du bon » et s'ouvre
 * directement plutôt que de rester repliée sans raison. */
function SectionCorrection({
  titre,
  ouvertParDefaut = false,
}: {
  titre: string;
  ouvertParDefaut?: boolean;
}): ReactElement {
  return (
    <details className="rounded-carte border border-bordure bg-surface p-5" open={ouvertParDefaut}>
      <summary className="inline-flex min-h-[44px] w-full cursor-pointer list-none items-center gap-2 text-sm font-semibold text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent">
        {titre}
      </summary>
      <div className="mt-4">
        <DocumentDetail />
      </div>
    </details>
  );
}

/** Page BL (maquette `BL`, Task 8 de la refonte du front) : montée sur
 * `/bl/:id` et `/documents/:id` (même identifiant de route `id` — voir
 * `App.tsx`). Tente d'abord `GET /api/documents/{id}` (BL ou enlèvement,
 * traité comme un BL — CDC) ; un 404 (identifiant qui n'est pas un
 * document, ex. celui d'une facture) délègue à `FactureDetail`, qui relit
 * le même `id` via `useParams` — décision du contrôleur (Task 8) : un seul
 * identifiant, deux entités possibles (`document`/`facture`), jamais de
 * paramètre supplémentaire dans l'URL pour trancher (`?type=`) — cohérent
 * avec les liens déjà posés par `ATraiter.tsx`/`Anomalies.tsx`/
 * `BilanFournisseur.tsx`, qui pointent vers `/documents/:id` pour un BL
 * sans jamais préciser son type. */
export function PageBl(): ReactElement {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: moi } = useQuery({ queryKey: CLE_MOI, queryFn: recupererMoi, staleTime: DUREE_CACHE_MOI });
  const estAdmin = moi?.role === "admin";

  const document = useQuery({
    queryKey: id !== undefined ? cleDocument(id) : ["document", "sans-identifiant"],
    queryFn: () => lireDocument(id ?? ""),
    enabled: id !== undefined,
    // Un 404 ici est un signal normal (« ce n'est pas un document, tenter
    // une facture »), pas une panne réseau — jamais de nouvelle tentative
    // (la politique par défaut de `main.tsx` réessaierait 3 fois avant de
    // basculer sur `FactureDetail`, retardant l'affichage pour rien).
    retry: false,
  });

  const estBl = document.data?.type === "bl";
  const comparaison = useQuery({
    queryKey: id !== undefined ? cleComparaisonBl(id) : ["document", "sans-identifiant", "comparaison"],
    queryFn: () => obtenirComparaisonBl(id ?? ""),
    enabled: id !== undefined && estAdmin && estBl,
  });

  // Constat de revue (tour de correction 1) : la carte « Livré et facturé »
  // restait périmée après une correction faite dans la section du bas
  // (`SectionCorrection`/`DocumentDetail`, même page) — `surEcriture` (dans
  // `DocumentDetail.tsx`, logique non touchée ici) met à jour le cache de
  // `["document", id]` et invalide `["documents"]`, mais ne sait rien de
  // `["document", id, "comparaison"]`, propre à cette page. On invalide
  // donc ici, dès que le document affiché change (`dataUpdatedAt`,
  // horodatage interne de TanStack Query à chaque écriture réussie) — sauf
  // au tout premier rendu (`premierRendu`), où `comparaison` vient de toute
  // façon de se charger elle-même.
  const premierRendu = useRef(true);
  useEffect(() => {
    if (premierRendu.current) {
      premierRendu.current = false;
      return;
    }
    if (id !== undefined) {
      void queryClient.invalidateQueries({ queryKey: cleComparaisonBl(id) });
    }
  }, [document.dataUpdatedAt, id, queryClient]);

  if (id === undefined) {
    return (
      <p role="alert" className="text-sm text-alerte">
        Document introuvable.
      </p>
    );
  }

  if (document.isPending) {
    return (
      <p role="status" className="text-sm text-encre-2">
        Chargement…
      </p>
    );
  }

  if (document.isError) {
    if (document.error instanceof ErreurApi && document.error.status === 404) {
      // Documents (BL/enlèvement) et factures ne partagent ni table ni
      // route : un identifiant qui n'est pas un document est peut-être
      // celui d'une facture — `FactureDetail` relit `id` via `useParams`
      // et affiche « Facture introuvable. » si ce n'en est pas une non
      // plus (dispatch décrit au commentaire de tête de fichier).
      return <FactureDetail />;
    }
    return (
      <p role="alert" className="text-sm text-alerte">
        Impossible de charger ce document.
      </p>
    );
  }

  const donnees = document.data;
  const numero = donnees.champs.numero.valeur ?? "non détecté";
  // Constat de revue corrigé au tour de correction 1 : `nb_problemes`
  // vient du serveur (`ComparaisonBl`, `ingest/comparaison_bl.py`), jamais
  // recalculé ici — une somme de `regles_ouvertes` ne comptait ni un
  // problème porté par une ligne de facture jamais appariée, ni un
  // problème porté par le groupe facturé ou par le bon eux-mêmes, toujours
  // absents de `lignes` (voir le docstring de `ComparaisonBl` côté
  // serveur).
  const nbProblemes = comparaison.data?.nb_problemes ?? 0;
  const factureConnue = comparaison.data !== undefined && comparaison.data.facture_id !== null;

  return (
    <div className="space-y-6">
      <FilAriane elements={construireFilAriane(donnees, numero)} />

      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-titre text-2xl font-medium text-encre sm:text-3xl">
            {libelleTypePage(donnees.type)}{" "}
            <span className="font-mono text-xl text-encre sm:text-2xl">{numero}</span>
          </h1>
          <p className="text-xs text-encre-2">Document n° {donnees.numero_interne}</p>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-encre">
            <span>
              Livré le <strong>{formaterDate(donnees.champs.date_doc.valeur)}</strong>
            </span>
            <span>{donnees.champs.fournisseur.valeur ?? TIRET}</span>
            <span>{donnees.chantier ?? "Chantier à rattacher"}</span>
          </div>
        </div>
        <PastilleDocument
          statut={donnees.statut}
          nbProblemes={nbProblemes}
          comparaisonChargee={comparaison.data !== undefined}
          factureConnue={factureConnue}
        />
      </header>

      <div className="grid grid-cols-1 gap-5 md:grid-cols-5">
        <section
          aria-label="Photo du bon"
          className="flex flex-col gap-4 rounded-carte border border-bordure bg-surface p-5 md:col-span-2"
        >
          <PhotoBl id={donnees.id} numero={numero} />
          <div className="flex gap-2">
            <a
              href={urlTelechargement(donnees.id)}
              download
              className="inline-flex min-h-[44px] flex-1 items-center justify-center rounded-lg bg-accent px-3 text-center text-sm font-medium text-white outline-none hover:bg-accent-fonce focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2"
            >
              Télécharger la photo
            </a>
            <a
              href={`/api/documents/${donnees.id}/fichier`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-[44px] flex-1 items-center justify-center rounded-lg border border-bordure px-3 text-center text-sm font-medium text-encre outline-none hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent"
            >
              Ouvrir en grand
            </a>
          </div>
          {donnees.photo_compressee === true && (
            <span className="inline-flex w-fit shrink-0 items-center rounded-full bg-bordure px-2 py-0.5 text-xs font-medium text-encre">
              Photo compressée
            </span>
          )}
          <div className="flex flex-col gap-1 text-sm text-encre">
            <p>
              Déposé par <strong>{donnees.deposant ?? TIRET}</strong> via Telegram, le{" "}
              {formaterDateHeure(donnees.cree_le)}
            </p>
            <p>
              Quantités vérifiées par l'équipe :{" "}
              <strong className={classesConfirmation(donnees.confirmation)}>
                {texteConfirmation(donnees.confirmation)}
              </strong>
              {donnees.confirmation !== null && (
                <span className="text-encre-2">
                  {" "}
                  — {donnees.confirme_par ?? TIRET}, {formaterDateHeure(donnees.confirme_le)}
                </span>
              )}
            </p>
          </div>
        </section>

        {estAdmin && estBl && (
          <div className="md:col-span-3">
            <CarteLivreFacture documentId={donnees.id} comparaison={comparaison} nbProblemes={nbProblemes} />
          </div>
        )}
      </div>

      {/* Pleine largeur (pas dans la grille ci-dessus) : le tableau
          d'édition des lignes (`TableauLignesEdition`, `DocumentDetail.tsx`)
          a besoin de place — le coincer dans la colonne de 3/5 le forçait à
          défiler horizontalement dès l'ouverture (constat de la vérification
          visuelle, Task 8). */}
      {donnees.modifiable && <SectionCorrection titre="Corriger la lecture du bon" />}
      {/* Document non modifiable (archivé) consulté par un admin : constat
          de revue (tour de correction 1) — plus aucun champ ni ligne
          n'était visible dans ce cas, faute d'être monté du tout. Jamais
          pour un agent (`estAdmin`) : le brief Task 8 ne lui réserve que
          l'image, le téléchargement et le statut de confirmation. */}
      {!donnees.modifiable && estAdmin && <SectionCorrection titre="Lecture du bon" ouvertParDefaut />}
    </div>
  );
}
