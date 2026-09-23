import { type ReactElement, useEffect, useRef, useState } from "react";
import { type UseQueryResult, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "react-router";

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
import { CHANTIER_A_RATTACHER, lienFacture } from "../lib/liens";
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
 * seul, jamais un lien mort.
 *
 * Revue finale (constats LIENS-9, DROITS-1, TELEPHONE-10) : pour un agent,
 * « Mes dépôts › n° BL » — les écrans « Chantiers » et fiche chantier lui
 * sont réservés (`GardeAdmin`), un lien vers eux le renvoyait sans
 * explication vers ses dépôts. */
function construireFilAriane(donnees: DonneesDocument, numero: string, estAdmin: boolean): ElementFilAriane[] {
  if (!estAdmin) {
    return [{ libelle: "Mes dépôts", vers: "/documents" }, { libelle: numero }];
  }
  const elements: ElementFilAriane[] = [{ libelle: "Chantiers", vers: "/chantiers" }];
  if (donnees.chantier !== null) {
    elements.push(
      donnees.chantier_id !== null
        ? { libelle: donnees.chantier, vers: `/chantiers/${donnees.chantier_id}` }
        : { libelle: donnees.chantier },
    );
  } else {
    elements.push({ libelle: CHANTIER_A_RATTACHER });
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

/** Colonne « Contrôle » d'une ligne comparée (maquette `BL`) : le verdict
 * vient du serveur (`controle`, revue finale, constats SERVEUR-6/ECRAN-3) —
 * avant, la page concluait « Conforme » dès qu'aucun problème n'était
 * ouvert sur la ligne, y compris pour une ligne jamais retrouvée sur la
 * facture (« Facturé — », « Prix — », « Conforme » en vert). Les codes de
 * `regles_ouvertes` sont traduits par `titreRegle`, jamais affichés bruts
 * (spec §5). Toujours un libellé, jamais la couleur seule. */
function ControleLigne({ ligne }: { ligne: LigneComparee }): ReactElement {
  switch (ligne.controle) {
    case "ecart":
      return (
        <span className="inline-flex items-center gap-2 text-ecart-texte">
          <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full bg-ecart" />
          {ligne.regles_ouvertes.map((code) => titreRegle(code)).join(", ")}
        </span>
      );
    case "conforme":
      return (
        <span className="inline-flex items-center gap-2 text-conforme">
          <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full bg-conforme" />
          Conforme
        </span>
      );
    case "non_facture":
      return (
        <span className="inline-flex items-center gap-2 text-encre-2">
          <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full bg-encre-2" />
          Non retrouvé sur la facture
        </span>
      );
    case "non_controle":
      // Ligne retrouvée sur la facture, mais facturée au seul montant (ex.
      // éco-participation) : rien à comparer — le montant est montré tel
      // quel, jamais un « Conforme » qui n'a rien vérifié.
      return (
        <span className="inline-flex items-center gap-2 text-encre-2">
          <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full bg-encre-2" />
          Facturé {formaterMontant(ligne.montant_facture)}, sans quantité à comparer
        </span>
      );
    case "pas_encore_facture":
      return (
        <span className="inline-flex items-center gap-2 text-encre-2">
          <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full bg-encre-2" />
          Pas encore facturé
        </span>
      );
  }
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
function TableauLivreFacture({ lignes }: { lignes: LigneComparee[] }): ReactElement {
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
              <ControleLigne ligne={ligne} />
            </div>
          </li>
        ))}
      </ul>

      {/* Tableau : ordinateur (>= md) */}
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[500px] text-sm">
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
                  <ControleLigne ligne={ligne} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

/** Carte « Livré et facturé » (admin ; un bon d'enlèvement a aussi la
 * sienne depuis la revue finale, constat SERVEUR-5 — CDC §4.5) : contenu de
 * `comparaison`, lien « Voir la facture » (ouverte sur la livraison de ce
 * bon, constat LIENS-13) et bouton « Régler les N problèmes » vers
 * `/a-regler?document=` — l'écran « À régler » lit désormais ce paramètre et
 * n'affiche que les problèmes de ce bon, exactement ceux comptés ici
 * (constats LIENS-1, ECRAN-2, COUVERTURE-1). */
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
            to={lienFacture(donnees.facture_id, donnees.bloc_id)}
            className="inline-flex min-h-[44px] items-center text-sm font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
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
          <TableauLivreFacture lignes={donnees.lignes} />
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
                {nbProblemes > 1 ? `Régler les ${nbProblemes} problèmes` : "Régler le problème"}
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
 * directement plutôt que de rester repliée sans raison.
 *
 * Revue finale : un chevron qui pivote signale que la section se déplie
 * (constat ECRAN-11 — sans lui, le titre ressemblait à une carte vide) ;
 * l'ancre `#corriger` (lien « Corriger le bon » de l'écran « À régler »)
 * cible la section, ouverte d'office pour un bon « à vérifier » (constat
 * COUVERTURE-17). */
function SectionCorrection({
  titre,
  ouvertParDefaut = false,
}: {
  titre: string;
  ouvertParDefaut?: boolean;
}): ReactElement {
  return (
    <details
      id="corriger"
      className="group scroll-mt-4 rounded-carte border border-bordure bg-surface p-5"
      open={ouvertParDefaut}
    >
      <summary className="inline-flex min-h-[44px] w-full cursor-pointer list-none items-center gap-2 text-sm font-semibold text-encre outline-none focus-visible:ring-2 focus-visible:ring-accent">
        <span aria-hidden="true" className="inline-block transition-transform group-open:rotate-90">
          ▸
        </span>
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

  // Revue finale (constat SERVEUR-5) : un bon d'enlèvement est traité comme
  // un BL (CDC §4.5) — le serveur accepte désormais sa comparaison. Cette
  // page ne reçoit jamais une facture (404 -> `FactureDetail`, plus bas).
  const estBl = document.data !== undefined && document.data.type !== "facture";
  const location = useLocation();
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

  // Ancre `#corriger` (lien « Corriger le bon » de l'écran « À régler ») :
  // la section n'existe qu'une fois le document chargé, le navigateur ne
  // peut donc pas y défiler seul (revue finale, constat COUVERTURE-17).
  const documentCharge = document.data !== undefined;
  useEffect(() => {
    if (documentCharge && location.hash === "#corriger") {
      window.document.getElementById("corriger")?.scrollIntoView({ block: "start" });
    }
  }, [documentCharge, location.hash]);

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
      <FilAriane elements={construireFilAriane(donnees, numero, estAdmin)} />

      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-titre text-2xl font-medium text-encre sm:text-3xl">
            {libelleTypePage(donnees.type)}{" "}
            <span className="font-mono text-xl text-encre sm:text-2xl">{numero}</span>
          </h1>
          {/* Numéro de dépôt, cité par chaque message Telegram (tour de
              correction 1 de la Task 8) — gardé pour retrouver un bon. */}
          <p className="text-xs text-encre-2">Document n° {donnees.numero_interne}</p>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-encre">
            <span>
              {donnees.type === "enlevement" ? "Enlevé le" : "Livré le"}{" "}
              <strong>{formaterDate(donnees.champs.date_doc.valeur)}</strong>
            </span>
            <span>{donnees.champs.fournisseur.valeur ?? TIRET}</span>
            <span>{donnees.chantier ?? CHANTIER_A_RATTACHER}</span>
          </div>
        </div>
        <PastilleDocument
          statut={donnees.statut}
          nbProblemes={nbProblemes}
          comparaisonChargee={comparaison.data !== undefined}
          factureConnue={factureConnue}
        />
      </header>

      {/* Deux colonnes seulement à partir de `lg` (revue finale, constat
          ECRAN-12) : entre 768 et 1023 px, le tableau « Livré et facturé »
          n'avait pas la place de ses cinq colonnes dans 3/5 de la largeur. */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
        <section
          aria-label="Photo du bon"
          className="flex flex-col gap-4 rounded-carte border border-bordure bg-surface p-5 lg:col-span-2"
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
            // CDC : une photo compressée par Telegram est acceptée mais
            // marquée comme telle — libellé en français courant (revue
            // finale, constats ECRAN-13/TELEPHONE-13).
            <span className="inline-flex w-fit shrink-0 items-center rounded-full bg-bordure px-2 py-0.5 text-xs font-medium text-encre">
              Photo envoyée en qualité réduite
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
          <div className="lg:col-span-3">
            <CarteLivreFacture documentId={donnees.id} comparaison={comparaison} nbProblemes={nbProblemes} />
          </div>
        )}
      </div>

      {/* Pleine largeur (pas dans la grille ci-dessus) : le tableau
          d'édition des lignes (`TableauLignesEdition`, `DocumentDetail.tsx`)
          a besoin de place — le coincer dans la colonne de 3/5 le forçait à
          défiler horizontalement dès l'ouverture (constat de la vérification
          visuelle, Task 8). Ouverte d'office pour un bon « à vérifier » ou
          quand on arrive par l'ancre `#corriger` (revue finale, constat
          COUVERTURE-17). */}
      {donnees.modifiable && (
        <SectionCorrection
          titre="Corriger la lecture du bon"
          ouvertParDefaut={donnees.statut === "a_verifier" || location.hash === "#corriger"}
        />
      )}
      {/* Document non modifiable : admin consultant un document archivé
          (tour de correction 1), ou agent consultant son propre dépôt —
          revue finale (constat COUVERTURE-15) : l'agent voyait, avant la
          refonte, les champs et lignes lus sur son bon ; il les retrouve ici
          en lecture seule (`DocumentDetail` n'affiche aucun bouton quand
          `modifiable` vaut `false`), section repliée par défaut. */}
      {!donnees.modifiable && <SectionCorrection titre="Lecture du bon" ouvertParDefaut={estAdmin} />}
    </div>
  );
}
