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
 *
 * Tour 2 de la revue de la Task 10 (23/09/2026) : le recensement des clés
 * de détail (`avant`/`apres`) était incomplet (`nb_articles`, `numero`,
 * `total_ht`, `nb_mis_a_jour`… affichées brutes sur la base de démo) et une
 * valeur objet ou liste passait par `JSON.stringify` (JSON brut à l'écran
 * sur un « Problème disparu », les motifs à vérifier, les lignes
 * corrigées). Recensement complété, chaque forme connue a maintenant sa
 * propre mise en forme (montant, date, liste, phrase chiffrée) — plus
 * aucun `JSON.stringify` dans ce fichier, la clé/valeur technique brute
 * reste le seul repli pour une forme que ce fichier ne connaît pas encore.
 */

import { formaterDate, formaterDateHeure, formaterMontant, TIRET } from "./formats";
import { type Anomalie, phraseProbleme, titreRegle, urgence } from "../ui/libelles";

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

/** Libellés des réglages administrables (`ingest/parametres.py
 * ::DEFINITIONS_PARAMETRES`, neuf clés) dupliqués ici en présentation
 * uniquement (ni borne, ni valeur par défaut) : l'écran Réglages les tient
 * de l'API elle-même à chaque chargement, mais une entrée « Réglage
 * modifié » du journal ne porte que la clé technique dans `cible_id`
 * (`parametres.py::modifier_parametre`) — affichée brute sans cette table
 * (constat de la revue, tour 2 de la Task 10). Un dixième réglage ajouté
 * côté serveur sans mise à jour de cette liste retombe sur sa clé
 * technique (repli défensif, documenté dans `docs/dette.md`). */
const LIBELLES_PARAMETRE: Record<string, string> = {
  tolerance_total_ht: "Tolérance sur le total HT",
  seuil_prix_pct: "Écart de prix",
  seuil_prix_fort_pct: "Écart de prix important",
  occurrences_prix_min: "Occurrences minimales pour l'historique",
  delai_ligne_bl_non_facturee_j: "Délai avant alerte d'une ligne de BL non facturée",
  delai_alias_non_resolu_h: "Délai avant alerte d'un chantier non reconnu",
  delai_confirmation_bl_h: "Délai de confirmation d'un BL",
  delai_chantier_silencieux_j: "Délai d'inactivité d'un chantier",
  duree_ignorance_j: "Durée d'ignorance d'un problème",
};

/** Libellé de la cible (`cible_id`) d'une entrée : pour un réglage
 * (`cible_table === "parametre"`), la clé technique brute n'a aucun sens
 * pour le dirigeant — remplacée par le nom du réglage. Pour toute autre
 * table, `cible_id` reste affiché tel quel (un identifiant, jamais un mot
 * de jargon). */
export function libelleCibleId(cibleTable: string | null, cibleId: string): string {
  if (cibleTable === "parametre") {
    return LIBELLES_PARAMETRE[cibleId] ?? cibleId;
  }
  return cibleId;
}

/** Libellé court d'un code de motif de mise « à vérifier »
 * (`extract/verification.py::CodeMotif`) : le journal ne porte que la
 * liste des codes bruts (`extraction_bl.py`/`factures.py`,
 * `[m.code.value for m in motifs]`), jamais le motif complet avec son
 * `detail` — contrairement à `lib/motifs.ts::libelleMotif`, qui construit
 * la phrase chiffrée complète pour l'écran « À traiter ». Un code inconnu
 * affiche le code brut (défense en profondeur, même principe que le reste
 * de ce fichier) ; jamais le mot « OCR » dans un libellé (constat de la
 * revue, tour 2 : `ocr_echec` afficherait « ocr » à l'écran sans cette
 * table). */
const LIBELLES_CODE_MOTIF: Record<string, string> = {
  champ_absent: "Champ manquant",
  valeur_illisible: "Valeur illisible",
  confiance_faible: "Confiance insuffisante",
  somme_incoherente: "Somme incohérente",
  total_absent: "Total manquant",
  lignes_absentes: "Aucune ligne détectée",
  numero_incoherent: "Numéro incohérent",
  ocr_echec: "Échec de la lecture",
  annotation_illisible: "Annotation illisible",
  fournisseur_inconnu: "Fournisseur inconnu du référentiel",
  numero_en_double: "Numéro en double",
};

function libelleCodeMotif(code: string): string {
  return LIBELLES_CODE_MOTIF[code] ?? code;
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
  // Complété au tour 2 (constat de la revue) : mêmes entrées
  // `facture_deposee` (`factures.py::deposer_facture`) que ci-dessus,
  // trois clés qui s'affichaient brutes sur les 4 entrées « Facture
  // déposée » de la base de démo.
  nb_articles: "Articles",
  numero: "Numéro",
  total_ht: "Total HT",
  total_tva: "Total TVA",
  total_ttc: "Total TTC",
  // `document_corrige`/`extraction_relancee`
  // (`corrections.py::_valeurs_document_pour_journal`, mêmes clés que
  // `CHAMPS_CORRIGEABLES`) — même libellé que le tableau `CHAMPS_AFFICHES`
  // de `pages/DocumentDetail.tsx` pour chaque champ partagé.
  type: "Type",
  date_doc: "Date",
  chantier_brut: "Chantier (brut)",
  numero_commande: "Commande",
  enleve_par: "Enlevé par",
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
  // `alias_valide` (`referentiels.py::valider_alias`) : nombre de documents
  // et blocs de facture déjà déposés rattachés au chantier en même temps
  // que l'alias — s'affichait brut sur les 4 entrées « Nom de chantier
  // fournisseur reconnu » de la base de démo (constat de la revue, tour 2).
  nb_mis_a_jour: "Documents mis à jour",
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
  // Même libellé que `libelleTypeDocument` (`pages/ATraiter.tsx`) et
  // `libelleType` (`pages/BlDeposes.tsx`) pour `document.type`
  // (`document_corrige`/`extraction_relancee`, `models.py` : contrainte
  // `type IN ('bl', 'enlevement', 'facture', 'avoir')`).
  type: {
    bl: "Livraison",
    enlevement: "Enlèvement",
    facture: "Facture",
    avoir: "Avoir",
  },
};

/** Libellé d'une valeur déjà mise en forme (chaîne) : `regle`/`gravite`
 * passent par le langage courant déjà utilisé par l'écran « À régler »
 * (`titreRegle`/`urgence`, `ui/libelles.ts`), quelques autres clés connues
 * par une table de correspondance (`LIBELLES_VALEUR_PAR_CLE`), la valeur
 * telle quelle sinon (jamais un calcul, uniquement de la présentation). */
function libelleValeurDetail(cle: string, formatee: string): string {
  if (cle === "regle") {
    return titreRegle(formatee);
  }
  if (cle === "gravite") {
    return urgence(formatee);
  }
  const parCle = LIBELLES_VALEUR_PAR_CLE[cle];
  const valeurConnue = parCle?.[formatee];
  return valeurConnue !== undefined ? valeurConnue : formatee;
}

function estObjet(valeur: unknown): valeur is Record<string, unknown> {
  return typeof valeur === "object" && valeur !== null && !Array.isArray(valeur);
}

/** Repli pour une valeur imprévue (ni chaîne, ni l'une des formes de liste
 * ou d'objet traitées explicitement plus bas) : une liste `clé : valeur` à
 * plat, jamais du JSON brut (`JSON.stringify` affichait « {"date_bl":… } »
 * ou « ["confiance_faible",…] » à l'écran — constat de la revue, tour 2).
 * Aucune forme rencontrée aujourd'hui ne passe par ici ; défense en
 * profondeur si le serveur journalise un jour une forme que ce fichier ne
 * connaît pas encore. */
function formaterObjetGenerique(valeur: Record<string, unknown>): string {
  const entrees = Object.entries(valeur);
  if (entrees.length === 0) {
    return "Aucun détail.";
  }
  return entrees.map(([cle, v]) => `${cle} : ${typeof v === "string" ? v : String(v)}`).join(" · ");
}

/** Une liste de chaînes (`aliases`, `agences_ajoutees`) — jointe par une
 * virgule, jamais `JSON.stringify` (qui produirait `["a","b"]`, du JSON
 * brut à l'écran). */
function formaterListeChaines(valeurs: unknown[]): string {
  if (valeurs.length === 0) {
    return "Aucun.";
  }
  return valeurs.map((v) => (typeof v === "string" ? v : String(v))).join(", ");
}

/** `motifs` (`extraction_bl.py`/`factures.py`) : liste de codes bruts,
 * traduite code par code (`libelleCodeMotif`) plutôt qu'affichée telle
 * quelle. */
function formaterMotifs(codes: unknown[]): string {
  if (codes.length === 0) {
    return "Aucun.";
  }
  return codes.map((code) => libelleCodeMotif(typeof code === "string" ? code : String(code))).join(", ");
}

/** `lignes` (`corrections.py::corriger_lignes`, `_ligne_en_chaine`) : un
 * résumé plutôt que le détail ligne par ligne (code, prix, identifiant
 * technique de chaque ligne — sans intérêt pour retracer *qui* a corrigé
 * *quoi*, le détail complet de chaque ligne reste consultable sur l'écran
 * du document, `pages/DocumentDetail.tsx`). */
function formaterNombreLignes(lignes: unknown[]): string {
  if (lignes.length === 0) {
    return "Aucune ligne.";
  }
  return `${lignes.length} ligne${lignes.length > 1 ? "s" : ""}`;
}

/** `detail` d'un « Problème disparu »
 * (`anomalies.py::synchroniser_anomalies`, `avant={regle, gravite,
 * detail}`) : même phrase chiffrée que l'écran « À régler »
 * (`phraseProbleme`, `ui/libelles.ts`) plutôt que le JSON brut du détail —
 * a besoin de `regle`, posée à côté de `detail` dans le même instantané
 * (`contexte`, jamais l'autre côté avant/après ; sans `regle` à côté,
 * repli générique). `detail` est en réalité `dict[str, str]` côté serveur
 * (`Anomalie.detail`, `app/modules/ingest/models.py`), jamais vérifié ici
 * (même défense en profondeur que partout ailleurs dans ce fichier) ; seuls
 * les deux champs que `phraseProbleme` lit réellement (`regle`, `detail`)
 * sont renseignés sur l'objet reconstruit pour l'appeler. */
function formaterDetailAnomalie(detail: Record<string, unknown>, contexte: Record<string, unknown>): string {
  const regle = contexte.regle;
  if (typeof regle !== "string") {
    return formaterObjetGenerique(detail);
  }
  const anomalie = { regle, detail: detail as Record<string, string> } as unknown as Anomalie;
  return phraseProbleme(anomalie);
}

/** Valeur affichée d'une clé de détail, pour un côté (`avant` ou `apres`)
 * donné — présentation uniquement, aucun calcul : un montant ou une date
 * passe par les mêmes formateurs que le reste du front (`lib/formats.ts`,
 * jamais affiché brut — constat de la revue, tour 2 : `total_ht : 456.30`,
 * `confirme_le` en ISO), une liste ou un objet connu a sa propre mise en
 * forme, la valeur brute reste le repli pour tout le reste (même principe
 * que `libelleCleDetail`). `contexte` est l'instantané complet de ce côté :
 * nécessaire pour `detail`, qui a besoin de la clé voisine `regle`. */
function valeurDetail(cle: string, contexte: Record<string, unknown>): string {
  const brute = contexte[cle];
  if (brute === null) {
    return TIRET;
  }
  if (cle === "detail" && estObjet(brute)) {
    return formaterDetailAnomalie(brute, contexte);
  }
  if (cle === "motifs" && Array.isArray(brute)) {
    return formaterMotifs(brute);
  }
  if (cle === "lignes" && Array.isArray(brute)) {
    return formaterNombreLignes(brute);
  }
  if (Array.isArray(brute)) {
    return formaterListeChaines(brute);
  }
  if (estObjet(brute)) {
    return formaterObjetGenerique(brute);
  }
  if ((cle === "total_ht" || cle === "total_tva" || cle === "total_ttc") && typeof brute === "string") {
    return formaterMontant(brute);
  }
  if (cle === "date_doc" && typeof brute === "string") {
    return formaterDate(brute);
  }
  if (cle === "confirme_le" && typeof brute === "string") {
    return formaterDateHeure(brute);
  }
  return libelleValeurDetail(cle, typeof brute === "string" ? brute : String(brute));
}

/** Reconstruit, clé par clé, la comparaison `avant`/`apres` d'une entrée de
 * journal — deux instantanés JSON indépendants (`ingest/journal.py`) :
 * une clé présente d'un côté et absente de l'autre est un fait à afficher
 * explicitement (`"absent"`), jamais un vide ambigu (décision du
 * contrôleur, L5-T9 : « si une valeur est absente d'un côté, dis-le
 * explicitement »). Aucun calcul d'écart, clés triées pour un affichage
 * stable : `libelle`/`valeurDetail` habillent la clé et la valeur en
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
  return [...cles].sort().map((cle) => ({
    cle,
    libelle: libelleCleDetail(cle),
    avant: avant !== null && cle in avant ? valeurDetail(cle, avant) : ABSENT,
    apres: apres !== null && cle in apres ? valeurDetail(cle, apres) : ABSENT,
  }));
}
