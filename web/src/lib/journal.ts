/**
 * Lecture du journal (`ingest/journal.py`, L5-T9) : libellés français des
 * actions et des éléments journalisés, et mise en forme lisible de
 * `avant`/`apres` — même principe que `lib/regles.ts` (mise en forme
 * uniquement, aucun calcul, aucune interprétation métier). Langage courant
 * de la refonte du front (spec §1/§5, fix round 1 de la revue de la Task
 * 10) : aucun code de règle ni mot d'architecture interne (« bloc »,
 * « alias », « rapprochement », « OCR », « UUID ») dans un libellé affiché
 * — la clé/valeur technique brute reste le repli défensif pour tout ce que
 * ce fichier ne connaît pas encore (même principe que `libelleRegle` dans
 * `lib/regles.ts`).
 *
 * Liste des actions recensée dans le code (`grep -rn 'action=' app/modules
 * /ingest/`, hors tests), pas inventée : `extraction_bl.py`,
 * `corrections.py`, `anomalies.py`, `factures.py`, `depot_telegram.py`,
 * `rapprochement.py`, `referentiels.py`. Complétée par les deux actions de
 * gestion de compte d'`app/core/auth.py` (`utilisateur_cree`,
 * `utilisateur_desactive`).
 */

import { titreRegle, urgence } from "../ui/libelles";
import { TIRET } from "./formats";

const LIBELLES_ACTION: Record<string, string> = {
  extraction_bl: "Lecture du BL",
  document_corrige: "Document corrigé",
  lignes_corrigees: "Lignes corrigées",
  document_valide: "Document validé",
  document_archive: "Document archivé",
  extraction_relancee: "Lecture relancée",
  // « Levée » (`ingest/anomalies.py::synchroniser_anomalies`) : un problème
  // encore ouvert que le rejeu des règles ne retrouve plus est supprimé,
  // pas créé — l'entrée journalisée constate sa disparition, jamais son
  // apparition (L4-D12).
  anomalie_levee: "Problème disparu",
  anomalie_traitee: "Problème réglé",
  anomalie_ignoree: "Problème ignoré",
  facture_deposee: "Facture déposée",
  quantites_verifiees: "Quantités confirmées (BL)",
  ecart_constate: "Écart constaté (BL)",
  facture_rapprochee: "Facture comparée aux bons",
  fournisseur_defini: "Fournisseur défini",
  chantier_cree: "Chantier créé",
  // Édition du nom/client/agence/actif d'un chantier depuis sa fiche
  // (`app/modules/ingest/referentiels.py::modifier_chantier`).
  chantier_modifie: "Chantier modifié",
  alias_valide: "Nom de chantier fournisseur reconnu",
  article_valide: "Article validé",
  utilisateur_cree: "Compte utilisateur créé",
  utilisateur_desactive: "Compte utilisateur désactivé",
  parametre_modifie: "Réglage modifié",
};

export function libelleAction(action: string): string {
  return LIBELLES_ACTION[action] ?? action;
}

/** Options du sélecteur d'action (décision du contrôleur : liste figée,
 * comme `CODES_REGLE` dans `pages/Anomalies.tsx` — pas de valeur inventée,
 * uniquement celles recensées ci-dessus, triées sur leur libellé). */
export const ACTIONS_CONNUES = Object.keys(LIBELLES_ACTION).sort((a, b) =>
  libelleAction(a).localeCompare(libelleAction(b), "fr"),
);

/** Tables cibles recensées dans le code (mêmes fichiers que ci-dessus) —
 * code technique interne, uniquement pour peupler le sélecteur de filtre :
 * voir `libelleCible` pour leur libellé affiché. */
export const CIBLES_CONNUES = [
  "document",
  "anomalie",
  "fournisseur",
  "chantier",
  "chantier_alias",
  "article",
  "utilisateur",
  "parametre",
] as const;

const LIBELLES_CIBLE: Record<string, string> = {
  document: "Document",
  anomalie: "Problème",
  fournisseur: "Fournisseur",
  chantier: "Chantier",
  chantier_alias: "Nom de chantier fournisseur",
  article: "Article",
  utilisateur: "Compte utilisateur",
  parametre: "Réglage",
};

/** Libellé français de l'élément concerné par une entrée (`cible_table`) —
 * le code technique reste le repli si ce fichier ne le connaît pas
 * encore. */
export function libelleCible(cible: string): string {
  return LIBELLES_CIBLE[cible] ?? cible;
}

export const AUTOMATIQUE = "Automatique";

/** Libellé de l'auteur d'une entrée : convention du projet depuis le lot 1,
 * `utilisateur_id`/`auteur` nuls signifient une décision automatique
 * (`ingest/journal.py`) — jamais une cellule vide qui laisserait croire à
 * une donnée manquante (décision du contrôleur, L5-T9). */
export function libelleAuteur(auteur: string | null): string {
  return auteur ?? AUTOMATIQUE;
}

const ABSENT = "absent";

function formaterValeurBrute(valeur: unknown): string {
  if (valeur === null) {
    return TIRET;
  }
  if (typeof valeur === "string") {
    return valeur;
  }
  return JSON.stringify(valeur);
}

export interface LigneAvantApres {
  cle: string;
  libelle: string;
  avant: string;
  apres: string;
}

/** Libellé des clés de détail (`avant`/`apres`) qui reviennent le plus
 * souvent dans le journal — présentation uniquement, la clé technique brute
 * reste le repli (`libelleCleDetail`) si elle n'est pas listée ici. Clés
 * recensées en lisant les appels `Journal(...)` d'`app/modules/ingest/` et
 * `app/core/auth.py` (mêmes fichiers que `LIBELLES_ACTION`). */
const LIBELLES_CLE_DETAIL: Record<string, string> = {
  statut: "État",
  commentaire: "Commentaire",
  valeur: "Valeur",
  regle: "Problème concerné",
  gravite: "Urgence",
  detail: "Détail du problème",
  nb_blocs: "Livraisons (total)",
  nb_blocs_recus: "Livraisons reçues",
  nb_blocs_pas_de_bon: "Livraisons sans bon",
  nb_lignes_appariees: "Lignes reliées à une facture",
  nb_anomalies: "Problèmes",
  // Nombre de noms de chantier fournisseur non reconnus à la dépose d'une
  // facture, pour lesquels une demande de reconnaissance a été créée
  // (`factures.py::deposer_facture`, `resoudre_chantier`) — sans cette
  // entrée, la clé brute (« nb_demandes_alias ») afficherait le mot
  // interdit « alias » (constat de la revue, fix round 1 de la Task 10).
  nb_demandes_alias: "Noms de chantier fournisseur à confirmer",
  nb_lignes: "Lignes",
  lignes: "Lignes",
  motifs: "Points à vérifier",
  chantier_libelle: "Nom de chantier lu",
  methode_chantier: "Chantier retrouvé via",
  methode_fournisseur: "Fournisseur retrouvé via",
  methode: "Retrouvé via",
  confirme_le: "Confirmé le",
  confirme_par: "Confirmé par",
  nom: "Nom",
  nom_canonique: "Nom",
  agence: "Agence",
  agences_ajoutees: "Agences ajoutées",
  client: "Client",
  actif: "Actif",
  siret: "Siret",
  tva: "TVA",
  aliases: "Autres noms connus",
  libelle: "Nom lu",
  unite_cdt: "Unité de conditionnement",
  unite_fact: "Unité de facturation",
  ratio: "Ratio",
  valide: "Validé",
  email: "E-mail",
  role: "Rôle",
  telegram_user_id: "Identifiant Telegram",
};

/** Un identifiant (`chantier_id`, `fournisseur_id`…) désigne l'élément
 * qu'il nomme — même liste que `libelleCible`, sur le préfixe de la clé. */
const PREFIXES_ID: Record<string, string> = {
  chantier: "Chantier",
  fournisseur: "Fournisseur",
  article: "Article",
  document: "Document",
  utilisateur: "Compte utilisateur",
  alias: "Nom de chantier fournisseur",
};

/** Libellé d'une clé de détail : la table ci-dessus si elle la connaît,
 * sinon un identifiant reconnu à son suffixe `_id` (`chantier_id` ->
 * « Chantier »), sinon la clé technique brute (défense en profondeur,
 * même principe que `libelleAction`). */
function libelleCleDetail(cle: string): string {
  const connu = LIBELLES_CLE_DETAIL[cle];
  if (connu !== undefined) {
    return connu;
  }
  if (cle.endsWith("_id")) {
    const prefixe = PREFIXES_ID[cle.slice(0, -3)];
    if (prefixe !== undefined) {
      return prefixe;
    }
  }
  return cle;
}

/** Valeurs connues pour certaines clés de détail (présentation uniquement —
 * la valeur brute reste le repli). */
const LIBELLES_VALEUR_PAR_CLE: Record<string, Record<string, string>> = {
  statut: {
    ouverte: "Ouvert",
    traitee: "Réglé",
    ignoree: "Ignoré",
    a_verifier: "À vérifier",
    recu: "Reçu",
    archive: "Archivé",
  },
  methode_chantier: {
    alias: "Nom déjà reconnu",
  },
  methode_fournisseur: {
    siret: "Numéro Siret",
    tva: "Numéro de TVA",
    nom: "Nom",
  },
  methode: {
    validation_humaine: "Validation manuelle",
  },
  actif: {
    true: "Oui",
    false: "Non",
  },
  valide: {
    true: "Oui",
    false: "Non",
  },
};

/** Libellé d'une valeur de détail déjà mise en forme (`formaterValeurBrute`)
 * — `regle`/`gravite` passent par le langage courant déjà utilisé par
 * l'écran « À régler » (`titreRegle`/`urgence`, `ui/libelles.ts`), quelques
 * autres clés connues par une table de correspondance, la valeur brute
 * sinon (jamais un calcul, uniquement de la présentation ; le tiret et
 * « absent » ne sont jamais réinterprétés). */
function libelleValeurDetail(cle: string, formatee: string): string {
  if (formatee === TIRET || formatee === ABSENT) {
    return formatee;
  }
  if (cle === "regle") {
    return titreRegle(formatee);
  }
  if (cle === "gravite") {
    return urgence(formatee);
  }
  const parCle = LIBELLES_VALEUR_PAR_CLE[cle];
  const valeurConnue = parCle?.[formatee];
  if (valeurConnue !== undefined) {
    return valeurConnue;
  }
  return formatee;
}

/** Reconstruit, clé par clé, la comparaison `avant`/`apres` d'une entrée de
 * journal — deux instantanés JSON indépendants (`ingest/journal.py`) :
 * une clé présente d'un côté et absente de l'autre est un fait à afficher
 * explicitement (`"absent"`), jamais un vide ambigu (décision du
 * contrôleur, L5-T9 : « si une valeur est absente d'un côté, dis-le
 * explicitement »). Aucun calcul d'écart, clés triées pour un affichage
 * stable : `libelle`/`libelleValeurDetail` habillent la clé et la valeur en
 * langage courant quand ce fichier les connaît, sans jamais changer la
 * valeur avant/après elle-même. */
export function lignesAvantApres(
  avant: Record<string, unknown> | null,
  apres: Record<string, unknown> | null,
): LigneAvantApres[] {
  const cles = new Set([
    ...(avant !== null ? Object.keys(avant) : []),
    ...(apres !== null ? Object.keys(apres) : []),
  ]);
  return [...cles].sort().map((cle) => {
    const valeurAvant = avant !== null && cle in avant ? formaterValeurBrute(avant[cle]) : ABSENT;
    const valeurApres = apres !== null && cle in apres ? formaterValeurBrute(apres[cle]) : ABSENT;
    return {
      cle,
      libelle: libelleCleDetail(cle),
      avant: libelleValeurDetail(cle, valeurAvant),
      apres: libelleValeurDetail(cle, valeurApres),
    };
  });
}
