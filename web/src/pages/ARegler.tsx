import { type ReactElement, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import {
  type AliasEnAttente,
  type ArticleAValider,
  type ATraiter,
  type ChantierACompleter,
  CLE_A_TRAITER,
  CLE_COMPTE_A_REGLER,
  type DocumentATraiter,
  obtenirATraiter,
  obtenirCompteARegler,
  problemes,
} from "../api/aTraiter";
import { type Anomalie, cleAnomalies, type FiltresAnomalies, listerAnomalies } from "../api/anomalies";
import { CLE_CHANTIERS, CLE_FOURNISSEURS, listerChantiers, listerFournisseurs } from "../api/referentiels";
import {
  Carte,
  categorieProbleme as categorieRegle,
  EnTetePage,
  EtatVide,
  Filtres,
  montantOuTiret,
  type OptionFiltre,
  PastilleUrgence,
  phraseProbleme,
  quantiteOuTiret,
  titreRegle,
  type Urgence,
  urgence,
} from "../ui";
import { formaterDate, TIRET } from "../lib/formats";
import { CHANTIER_A_RATTACHER } from "../lib/liens";
import { libelleMotif } from "../lib/motifs";
import { ProblemeDetail } from "./ProblemeDetail";

/**
 * Écran « À régler » (Task 6, refonte du front, spec §3/§4) : file unique
 * des anomalies ouvertes et des documents/alias/articles en attente de
 * `GET /api/a-traiter`, en langage courant. Remplace les anciens écrans
 * « Anomalies » et « À traiter » — voir `App.tsx` : `/anomalies` et
 * `/a-traiter` redirigent vers `/a-regler`.
 *
 * `ProblemeDetail.tsx` (panneau de droite en `lg+`, page plein écran
 * `/a-regler/:id` en dessous) importe les types et fonctions ci-dessous :
 * les deux fichiers forment un seul écran.
 */

// ---------------------------------------------------------------------------
// Modèle d'un « problème » de la liste — anomalie, ou pseudo-problème tiré
// de `GET /api/a-traiter` (document à vérifier, alias en attente, article à
// valider). `id` d'une anomalie est son uuid brut, jamais préfixé (fix
// round 1, finding 3) : les fiches chantier et fournisseur lient vers
// `/a-regler/${anomalie.id}` avec cet uuid tel quel. Seuls les trois
// pseudo-problèmes (`document:<uuid>`, `alias:<uuid>`, `article:<uuid>`),
// qui ne partagent aucun espace d'identifiants garanti avec les anomalies
// ni entre eux, restent préfixés — stable pour la route `/a-regler/:id`.
// ---------------------------------------------------------------------------

export type { Urgence };
export type CategorieFiltre = "bl" | "prix" | "quantites" | "rattacher" | "illisible" | "autre";

export type Probleme =
  | { kind: "anomalie"; id: string; anomalie: Anomalie }
  | { kind: "document"; id: string; document: DocumentATraiter }
  | { kind: "alias"; id: string; alias: AliasEnAttente }
  | { kind: "article"; id: string; article: ArticleAValider }
  | { kind: "chantier"; id: string; chantier: ChantierACompleter };

export function urgenceProbleme(probleme: Probleme): Urgence {
  return probleme.kind === "anomalie" ? urgence(probleme.anomalie.gravite) : "À voir";
}

/** Catégorie de filtre : celle calculée par le serveur pour une anomalie
 * (revue finale, constat SERVEUR-3 — table unique, la même que l'état d'un
 * chantier), fixe pour les trois pseudo-problèmes. */
export function categorieFiltreProbleme(probleme: Probleme): CategorieFiltre {
  switch (probleme.kind) {
    case "anomalie":
      return categorieRegle(probleme.anomalie);
    case "document":
      return "illisible";
    case "alias":
      return "rattacher";
    case "article":
      return "autre";
    case "chantier":
      return "rattacher";
  }
}

/** Titre d'un document « à vérifier » (fix round 1, finding 5) : distingue
 * une facture (« Facture à vérifier ») d'un bon de livraison (« Bon
 * illisible à corriger »), et un écart signalé par l'équipe au dépôt
 * (bouton Telegram « Écart constaté », `confirmation === "ecart"`) d'un bon
 * réellement illisible. */
export function titreDocument(document: DocumentATraiter): string {
  if (document.confirmation === "ecart") {
    return "Écart signalé par l'équipe";
  }
  return document.type === "facture" ? "Facture à vérifier" : "Bon illisible à corriger";
}

export function titreProbleme(probleme: Probleme): string {
  switch (probleme.kind) {
    case "anomalie":
      return titreRegle(probleme.anomalie.regle);
    case "document":
      return titreDocument(probleme.document);
    case "alias":
      return "Chantier à rattacher";
    case "article":
      return "Article à valider";
    case "chantier":
      return probleme.chantier.nom;
  }
}

/** Quantité toujours accompagnée d'une unité nommée quand `detail` la
 * porte (fix round 1, finding 8) : une quantité nue dans la colonne
 * « montant en jeu » ressemble à un montant sans en être un. Rendu au tiret
 * cadratin quand l'unité est absente ou vaut le tiret (fix round 2,
 * finding 2) : jamais une unité inventée, jamais une quantité seule. Les
 * gardes (`quantiteOuTiret`, `montantOuTiret`…) viennent de `ui/libelles.ts`
 * (revue finale, constat LIENS-12 : elles y étaient recopiées). */
export function quantiteAvecUnite(detail: Record<string, string>, cleQuantite: string, cleUnite: string): string {
  const quantite = quantiteOuTiret(detail, cleQuantite);
  if (quantite === "?" || quantite === TIRET) {
    return quantite;
  }
  const unite = detail[cleUnite];
  return unite !== undefined && unite !== TIRET ? `${quantite} ${unite}` : TIRET;
}

const REGLES_MONTANT_HT = new Set(["R01", "R02", "R12"]);
const REGLES_MONTANT = new Set(["R05", "R13"]);
const REGLES_ECART_MONTANT = new Set(["R10", "R11"]);
const REGLES_ECART_QUANTITE_AVEC_UNITE = new Set(["R03", "R04"]);

/** « Montant en jeu » de la liste (maquette `ARegler`) : une seule valeur
 * déjà présente dans `detail`, mise en forme (jamais une somme, un écart ou
 * un pourcentage recalculé ici). Seuls R01/R02/R12 (`montant_ht`), R05/R13
 * (`montant`, signé comme sur l'accueil — revue finale, constat ECRAN-8),
 * R10/R11 (`ecart`, déjà en euros) et R03/R04 (`ecart` de quantité,
 * accompagné de son unité) affichent une valeur ; tout le reste affiche le
 * tiret cadratin. */
export function valeurEnJeu(anomalie: Anomalie): string {
  const { detail, regle } = anomalie;
  if (REGLES_MONTANT_HT.has(regle)) return montantOuTiret(detail, "montant_ht");
  if (REGLES_MONTANT.has(regle)) return montantOuTiret(detail, "montant");
  if (REGLES_ECART_MONTANT.has(regle)) return montantOuTiret(detail, "ecart");
  if (REGLES_ECART_QUANTITE_AVEC_UNITE.has(regle)) return quantiteAvecUnite(detail, "ecart", "unite");
  return TIRET;
}

export function valeurProbleme(probleme: Probleme): string {
  return probleme.kind === "anomalie" ? valeurEnJeu(probleme.anomalie) : TIRET;
}

export function phraseAffichee(probleme: Probleme): string {
  switch (probleme.kind) {
    case "anomalie":
      return phraseProbleme(probleme.anomalie);
    case "document": {
      const motifs = probleme.document.motifs;
      if (motifs.length === 0) {
        return "À vérifier avant traitement.";
      }
      // Résumé court sur la ligne de liste (le détail affiche tous les
      // motifs) : au delà de deux, une ligne trop longue nuit à la liste.
      const libelles = motifs.slice(0, 2).map((motif) => libelleMotif(motif));
      const reste = motifs.length - libelles.length;
      return reste > 0 ? `${libelles.join(" · ")} — et ${reste} de plus.` : libelles.join(" · ");
    }
    case "alias":
      return `Libellé lu : « ${probleme.alias.libelle} » — ${probleme.alias.nb_documents} document${
        probleme.alias.nb_documents > 1 ? "s" : ""
      }.`;
    case "article":
      return probleme.article.libelle ?? "Unités et conditionnement à confirmer.";
    case "chantier": {
      const c = probleme.chantier;
      return `Créé automatiquement le ${formaterDate(c.cree_le)} — ${c.nb_bons} bon${
        c.nb_bons > 1 ? "s" : ""
      }.`;
    }
  }
}

export function contexteProbleme(probleme: Probleme): string {
  switch (probleme.kind) {
    case "anomalie": {
      const a = probleme.anomalie;
      // Revue finale (constat COUVERTURE-5) : un chantier non rattaché
      // s'appelle « Chantier à rattacher », comme partout ailleurs.
      const morceaux = [a.chantier ?? CHANTIER_A_RATTACHER, a.fournisseur ?? TIRET];
      if (a.numero_bl !== null) {
        morceaux.push(a.numero_bl);
      }
      return morceaux.join(" · ");
    }
    case "document":
      return [
        probleme.document.chantier_brut ?? TIRET,
        probleme.document.fournisseur ?? TIRET,
        probleme.document.numero ?? TIRET,
      ].join(" · ");
    case "alias":
      return probleme.alias.fournisseur;
    case "article":
      return probleme.article.fournisseur;
    case "chantier":
      return "Nouveau chantier à compléter";
  }
}

/** `true` pour un problème déjà contesté ou ignoré (filtre « Déjà
 * réglés ») — sa ligne montre alors l'issue plutôt que l'urgence (revue
 * finale, constats ECRAN-16/TELEPHONE-12). */
export function estDejaRegle(probleme: Probleme): boolean {
  return probleme.kind === "anomalie" && probleme.anomalie.statut !== "ouverte";
}

// ---------------------------------------------------------------------------
// Périmètre de la liste (revue finale, constats LIENS-1, ECRAN-2,
// COUVERTURE-1, LIENS-14) : un écran peut ouvrir « À régler » restreint à un
// bon (`?document=`, bouton « Régler les N problèmes » de la page du bon), à
// une livraison (`?blocId=`, anciens liens), à un chantier (`?chantier=`) ou
// à un fournisseur (`?fournisseur=`, liens « Voir l'historique » des
// fiches). Chaque périmètre est transmis tel quel au serveur, qui sait déjà
// filtrer (`GET /api/anomalies?bl_document_id=|bloc_id=|chantier_id=|
// fournisseur_id=`) — jamais un tri refait ici. Avant ce correctif,
// `?document=` était ignoré : « Régler les 2 problèmes » ouvrait la file
// complète.
// ---------------------------------------------------------------------------

type Portee =
  | { type: "document"; id: string }
  | { type: "bloc"; id: string }
  | { type: "chantier"; id: string }
  | { type: "fournisseur"; id: string };

/** Périmètre dit dans l'en-tête quand la liste est restreinte (« 2
 * problèmes ouverts sur ce bon ») : jamais un nombre sans son périmètre à
 * côté de la pastille de navigation, qui compte tout. */
const PERIMETRE_EN_TETE: Record<Portee["type"], string> = {
  document: "sur ce bon",
  bloc: "sur cette livraison",
  chantier: "sur ce chantier",
  fournisseur: "chez ce fournisseur",
};

function lirePortee(parametres: URLSearchParams): Portee | undefined {
  const document = parametres.get("document");
  if (document) return { type: "document", id: document };
  const blocId = parametres.get("blocId");
  if (blocId) return { type: "bloc", id: blocId };
  const chantier = parametres.get("chantier");
  if (chantier) return { type: "chantier", id: chantier };
  const fournisseur = parametres.get("fournisseur");
  if (fournisseur) return { type: "fournisseur", id: fournisseur };
  return undefined;
}

function filtresPortee(portee: Portee | undefined): FiltresAnomalies {
  switch (portee?.type) {
    case "document":
      return { blDocumentId: portee.id };
    case "bloc":
      return { blocId: portee.id };
    case "chantier":
      return { chantierId: portee.id };
    case "fournisseur":
      return { fournisseurId: portee.id };
    default:
      return {};
  }
}

/** Pseudo-problèmes (`GET /api/a-traiter`) retenus pour un périmètre : tous
 * sans périmètre ; pour un bon, seulement ce bon s'il est lui-même « à
 * vérifier » ; aucun pour une livraison, un chantier ou un fournisseur (ces
 * éléments ne portent pas d'identifiant de chantier ou de fournisseur
 * fiable) — jamais des données d'une visite précédente sans rapport avec le
 * périmètre (fix round 1, finding 10 : la requête peut être désactivée mais
 * son cache encore présent). */
function aTraiterDuPerimetre(aTraiter: ATraiter | undefined, portee: Portee | undefined): ATraiter | undefined {
  if (aTraiter === undefined || portee === undefined) {
    return aTraiter;
  }
  if (portee.type === "document") {
    return {
      ...aTraiter,
      documents: aTraiter.documents.filter((document) => document.id === portee.id),
      alias: [],
      articles: [],
      chantiers_a_completer: [],
    };
  }
  return undefined;
}

/** Combine les anomalies ouvertes (déjà filtrées par le serveur) et le
 * contenu de `GET /api/a-traiter` en une seule liste de problèmes —
 * composition d'affichage pure, aucune donnée recalculée. */
function construireProblemes(anomaliesOuvertes: Anomalie[], aTraiter: ATraiter | undefined): Probleme[] {
  const problemes: Probleme[] = anomaliesOuvertes.map((anomalie) => ({
    kind: "anomalie",
    id: anomalie.id,
    anomalie,
  }));
  if (aTraiter !== undefined) {
    for (const document of aTraiter.documents) {
      problemes.push({ kind: "document", id: `document:${document.id}`, document });
    }
    for (const alias of aTraiter.alias) {
      problemes.push({ kind: "alias", id: `alias:${alias.id}`, alias });
    }
    for (const article of aTraiter.articles) {
      problemes.push({ kind: "article", id: `article:${article.id}`, article });
    }
    for (const chantier of aTraiter.chantiers_a_completer) {
      problemes.push({ kind: "chantier", id: `chantier:${chantier.id}`, chantier });
    }
  }
  return problemes;
}

function compterCategorie(problemes: Probleme[], categorie: CategorieFiltre): number {
  return problemes.filter((probleme) => categorieFiltreProbleme(probleme) === categorie).length;
}

// Le maximum accepté par `GET /api/anomalies` (`_LIMITE_MAX`,
// `app/modules/api/anomalies.py`) : cet écran affiche tous les problèmes
// ouverts d'un coup, jamais paginés, donc jamais le défaut de 100.
const LIMITE_ANOMALIES_ECRAN = 500;

/** Issue d'un problème déjà réglé, en lieu et place de son urgence (revue
 * finale, constats ECRAN-16/TELEPHONE-12) : couleur neutre, date du
 * traitement. */
function PastilleIssue({ anomalie }: { anomalie: Anomalie }): ReactElement {
  const issue = anomalie.statut === "traitee" ? "Contesté" : "Ignoré";
  return (
    <span className="inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-full bg-bordure px-2.5 py-1 text-xs font-semibold text-encre">
      {anomalie.traitee_le !== null ? `${issue} le ${formaterDate(anomalie.traitee_le)}` : issue}
    </span>
  );
}

function LigneProbleme({
  probleme,
  actif,
  href,
}: {
  probleme: Probleme;
  actif: boolean;
  href: string;
}): ReactElement {
  return (
    <Link
      to={href}
      className={`block min-h-[44px] px-5 py-4 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent ${
        actif ? "bg-fond" : "hover:bg-fond"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        {probleme.kind === "anomalie" && estDejaRegle(probleme) ? (
          <PastilleIssue anomalie={probleme.anomalie} />
        ) : (
          <PastilleUrgence urgence={urgenceProbleme(probleme)} />
        )}
        <span className="whitespace-nowrap font-mono text-sm font-medium text-encre">
          {valeurProbleme(probleme)}
        </span>
      </div>
      <p className="mt-2 text-sm font-semibold text-encre">{titreProbleme(probleme)}</p>
      <p className="mt-0.5 text-sm text-encre">{phraseAffichee(probleme)}</p>
      <p className="mt-0.5 truncate text-xs text-encre-2">{contexteProbleme(probleme)}</p>
    </Link>
  );
}

export function ARegler(): ReactElement {
  const { id } = useParams<{ id?: string }>();
  const [parametres, setParametres] = useSearchParams();
  const navigate = useNavigate();

  const filtreActif = parametres.get("filtre") || "tous";
  const portee = lirePortee(parametres);

  const filtreRegles = filtreActif === "regles";

  // Fix round 1, finding 9 : file des problèmes ouverts et historique
  // « Déjà réglés » (traitées/ignorées) séparés en deux appels distincts,
  // jamais un seul `statut=toutes` filtré côté client (qui tronquait
  // silencieusement les problèmes ouverts). L'historique n'est demandé que
  // si le filtre « Déjà réglés » est actif.
  const filtresOuvertes = { statut: "ouverte" as const, ...filtresPortee(portee), limite: LIMITE_ANOMALIES_ECRAN };
  const anomaliesOuvertes = useQuery({
    queryKey: cleAnomalies(filtresOuvertes),
    queryFn: () => listerAnomalies(filtresOuvertes),
  });
  const filtresReglees = { statut: "toutes" as const, ...filtresPortee(portee), limite: LIMITE_ANOMALIES_ECRAN };
  const anomaliesReglees = useQuery({
    queryKey: cleAnomalies(filtresReglees),
    queryFn: () => listerAnomalies(filtresReglees),
    enabled: filtreRegles,
  });
  // Pseudo-problèmes utiles seulement sans périmètre ou pour un bon (voir
  // `aTraiterDuPerimetre`) : pas d'appel réseau inutile sinon.
  const aTraiterUtile = portee === undefined || portee.type === "document";
  const aTraiter = useQuery({
    queryKey: CLE_A_TRAITER,
    queryFn: obtenirATraiter,
    refetchInterval: 30_000,
    enabled: aTraiterUtile,
  });
  const chantiers = useQuery({ queryKey: CLE_CHANTIERS, queryFn: listerChantiers });
  const fournisseurs = useQuery({
    queryKey: CLE_FOURNISSEURS,
    queryFn: listerFournisseurs,
    enabled: portee?.type === "fournisseur",
  });

  const chargement =
    anomaliesOuvertes.isPending || (aTraiterUtile && aTraiter.isPending) || (filtreRegles && anomaliesReglees.isPending);
  const enErreur =
    anomaliesOuvertes.isError || (aTraiterUtile && aTraiter.isError) || (filtreRegles && anomaliesReglees.isError);

  // Composition simple à chaque rendu (quelques dizaines d'éléments) :
  // `portee` est un nouvel objet à chaque lecture de l'URL.
  const problemesOuverts = construireProblemes(
    anomaliesOuvertes.data ?? [],
    aTraiterUtile ? aTraiterDuPerimetre(aTraiter.data, portee) : undefined,
  );
  const problemesRegles = useMemo<Probleme[]>(
    () =>
      (anomaliesReglees.data ?? [])
        .filter((a) => a.statut !== "ouverte")
        .map((a) => ({ kind: "anomalie" as const, id: a.id, anomalie: a })),
    [anomaliesReglees.data],
  );

  // Fix round 1, finding 9 (suite) : jamais une troncature silencieuse.
  const troncature = filtreRegles
    ? (anomaliesReglees.data?.length ?? 0) >= LIMITE_ANOMALIES_ECRAN
    : (anomaliesOuvertes.data?.length ?? 0) >= LIMITE_ANOMALIES_ECRAN;

  const nbOuverts = problemesOuverts.length;
  const nbUrgents = problemesOuverts.filter((p) => urgenceProbleme(p) === "Urgent").length;

  // En-tête (revue finale, constats LIENS-2, ECRAN-6, TELEPHONE-2,
  // COUVERTURE-2) : sans périmètre, le compte unique du serveur — le même
  // nombre que la pastille de navigation et que le « … en tout » de la vue
  // d'ensemble (même clé de requête, un seul appel) ; restreint à un bon, un
  // chantier ou un fournisseur, le nombre de la liste affichée, dit comme
  // tel.
  const compteARegler = useQuery({
    queryKey: CLE_COMPTE_A_REGLER,
    queryFn: obtenirCompteARegler,
    // Même rythme que la liste des documents/chantiers à rattacher
    // ci-dessus : un dépôt Telegram arrivé entre-temps compte aussitôt.
    // Toujours actif (fix round 1, décision d'Ilane du 24/09/2026,
    // `docs/dette.md`) : même restreint à un périmètre, le filtre « Prix »
    // ci-dessous a besoin de `controle_prix_actif` — même clé que `Gabarit`,
    // donc jamais un second appel réseau pour l'écran non restreint.
    refetchInterval: 30_000,
  });
  const urgentsAffiches = (nombre: number): string => `${nombre} urgent${nombre > 1 ? "s" : ""}`;
  const surtitre =
    portee === undefined
      ? `${problemes(compteARegler.data?.nb_problemes ?? nbOuverts)} à régler en tout · ${urgentsAffiches(
          compteARegler.data?.nb_urgents ?? nbUrgents,
        )}`
      : `${problemes(nbOuverts)} ouvert${nbOuverts > 1 ? "s" : ""} ${PERIMETRE_EN_TETE[portee.type]} · ${urgentsAffiches(
          nbUrgents,
        )}`;

  // Constat mineur 2 de la revue des contrôles de prix : le repli est
  // `false`, même valeur que le défaut serveur (`CONTROLE_PRIX_ACTIF`
  // absente -> désactivé) -- jamais l'inverse, qui ferait flasher le
  // filtre « Prix » et la puce « Prix » d'une anomalie (`ProblemeDetail`)
  // le temps que la requête réponde.
  const controlePrixActif = compteARegler.data?.controle_prix_actif ?? false;
  const options: OptionFiltre[] = [
    { valeur: "tous", libelle: "Tous", compte: nbOuverts },
    { valeur: "urgents", libelle: "Urgents", compte: nbUrgents },
    { valeur: "bl", libelle: "BL manquants", compte: compterCategorie(problemesOuverts, "bl") },
    ...(controlePrixActif
      ? [{ valeur: "prix", libelle: "Prix", compte: compterCategorie(problemesOuverts, "prix") }]
      : []),
    { valeur: "quantites", libelle: "Quantités", compte: compterCategorie(problemesOuverts, "quantites") },
    { valeur: "rattacher", libelle: "À rattacher", compte: compterCategorie(problemesOuverts, "rattacher") },
    { valeur: "illisible", libelle: "Bons illisibles", compte: compterCategorie(problemesOuverts, "illisible") },
    { valeur: "regles", libelle: "Déjà réglés" },
  ];

  // Constat mineur 6 de la revue des contrôles de prix : un ancien lien
  // `?filtre=prix` (partagé avant la désactivation, ou simplement tapé)
  // revient au filtre « tous » tant que le contrôle de prix reste
  // désactivé -- le filtre lui-même n'apparaît plus dans `options`
  // ci-dessus, mais sans ce repli la liste resterait filtrée sur une
  // catégorie qu'aucune anomalie ouverte ne peut plus porter, une liste
  // vide sans explication plutôt qu'un retour silencieux à « tous ».
  const filtreEffectif = filtreActif === "prix" && !controlePrixActif ? "tous" : filtreActif;

  const listeAffichee = useMemo(() => {
    if (filtreEffectif === "regles") return problemesRegles;
    if (filtreEffectif === "urgents") return problemesOuverts.filter((p) => urgenceProbleme(p) === "Urgent");
    if (filtreEffectif === "tous") return problemesOuverts;
    return problemesOuverts.filter((p) => categorieFiltreProbleme(p) === (filtreEffectif as CategorieFiltre));
  }, [filtreEffectif, problemesOuverts, problemesRegles]);

  const indexActuel = id !== undefined ? listeAffichee.findIndex((p) => p.id === id) : -1;
  const problemeActuel = indexActuel >= 0 ? listeAffichee[indexActuel] : undefined;
  const idSuivant = indexActuel >= 0 && indexActuel + 1 < listeAffichee.length ? listeAffichee[indexActuel + 1]!.id : null;
  const modeDetail = id !== undefined;

  function suffixeRecherche(): string {
    const chaine = parametres.toString();
    return chaine === "" ? "" : `?${chaine}`;
  }

  function changerFiltre(valeur: string): void {
    const suivants = new URLSearchParams(parametres);
    if (valeur === "tous") {
      suivants.delete("filtre");
    } else {
      suivants.set("filtre", valeur);
    }
    setParametres(suivants, { replace: true });
  }

  function allerAuProblemeSuivant(): void {
    navigate(idSuivant !== null ? `/a-regler/${idSuivant}${suffixeRecherche()}` : `/a-regler${suffixeRecherche()}`);
  }

  function libellePortee(p: Portee): string {
    switch (p.type) {
      case "document":
        return "Problèmes de ce bon de livraison uniquement.";
      case "bloc":
        return "Problèmes de cette livraison uniquement.";
      case "chantier": {
        const nom = chantiers.data?.find((chantier) => chantier.id === p.id)?.nom_canonique;
        return nom !== undefined ? `Problèmes du chantier ${nom} uniquement.` : "Problèmes de ce chantier uniquement.";
      }
      case "fournisseur": {
        const nom = fournisseurs.data?.find((fournisseur) => fournisseur.id === p.id)?.nom;
        return nom !== undefined
          ? `Problèmes du fournisseur ${nom} uniquement.`
          : "Problèmes de ce fournisseur uniquement.";
      }
    }
  }

  return (
    <div className="space-y-6">
      <div className={modeDetail ? "hidden lg:block" : ""}>
        <EnTetePage
          surtitre={surtitre}
          titre="À régler"
          actions={<Filtres options={options} valeur={filtreEffectif} onChange={changerFiltre} />}
        />
      </div>

      {portee !== undefined && !modeDetail && (
        <p className="rounded-lg border border-bordure bg-surface p-3 text-sm text-encre-2">
          {libellePortee(portee)}{" "}
          <Link
            to="/a-regler"
            className="inline-flex min-h-[44px] items-center font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Afficher tous les problèmes
          </Link>
        </p>
      )}

      {chargement && (
        <p role="status" className="text-sm text-encre-2">
          Chargement…
        </p>
      )}
      {enErreur && (
        <p role="alert" className="text-sm text-alerte">
          Impossible de charger les problèmes.
        </p>
      )}
      {!chargement && !enErreur && troncature && (
        <p role="alert" className="rounded-lg border border-bordure bg-surface p-3 text-sm text-[#7a4a00]">
          Plus de {LIMITE_ANOMALIES_ECRAN} problèmes trouvés : la liste peut être incomplète.
        </p>
      )}

      {!chargement && !enErreur && (
        <div className="lg:grid lg:grid-cols-5 lg:gap-5">
          <section
            aria-label="Liste des problèmes"
            className={modeDetail ? "hidden lg:col-span-3 lg:block" : "lg:col-span-3"}
          >
            <Carte className="!p-0">
              {listeAffichee.length === 0 ? (
                <div className="p-5">
                  <EtatVide message="Aucun problème pour ce filtre." />
                </div>
              ) : (
                <ul className="divide-y divide-bordure">
                  {listeAffichee.map((probleme) => (
                    <li key={probleme.id}>
                      <LigneProbleme
                        probleme={probleme}
                        actif={probleme.id === id}
                        href={`/a-regler/${probleme.id}${suffixeRecherche()}`}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </Carte>
          </section>

          <aside
            aria-label="Détail du problème sélectionné"
            className={`${
              modeDetail ? "lg:col-span-2" : "hidden lg:col-span-2 lg:block"
            } lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:self-start lg:overflow-y-auto`}
          >
            {modeDetail && problemeActuel !== undefined && (
              // `key={problemeActuel.id}` (fix round 1, finding 4) : une clé
              // différente par problème force React à remonter
              // `ProblemeDetail` (et ses enfants) — jamais le commentaire ou
              // le chantier choisi d'un problème collé au suivant.
              <ProblemeDetail
                key={problemeActuel.id}
                probleme={problemeActuel}
                chantiers={chantiers.data ?? []}
                lienRetour={`/a-regler${suffixeRecherche()}`}
                onTraitementReussi={allerAuProblemeSuivant}
              />
            )}
            {modeDetail && problemeActuel === undefined && (
              <Carte>
                <p className="text-sm text-encre-2">
                  Ce problème n'est plus dans la liste : il a déjà été réglé, ou ne correspond pas au filtre
                  choisi.
                </p>
                <Link
                  to={`/a-regler${suffixeRecherche()}`}
                  className="mt-3 inline-flex min-h-[44px] items-center text-sm font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  Retour à la liste
                </Link>
              </Carte>
            )}
            {!modeDetail && (
              <Carte>
                <EtatVide message="Sélectionnez un problème dans la liste." />
              </Carte>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
