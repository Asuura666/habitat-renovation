/**
 * Langage courant de la refonte du front (spec §5) : un seul module associe
 * chaque code de règle à un titre sans jargon et construit la phrase
 * chiffrée à partir des valeurs de `detail` déjà calculées par le serveur —
 * aucun calcul métier ici (somme, écart, pourcentage), seulement de la mise
 * en forme. Remplace `lib/regles.ts` (Task 4, plan de la refonte du front) :
 * `titreRegle`/`phraseProbleme` reprennent les phrases chiffrées de
 * `justification`/`libelleRegle` de ce fichier, débarrassées du code
 * (« R01 — … ») et de la casse technique — `lib/regles.ts` devient un
 * simple ré-export de ce module pour les deux écrans pas encore migrés
 * (`ATraiter`, `Anomalies`).
 *
 * Un code de règle inconnu affiche « Problème à vérifier » (repli, défense
 * en profondeur si le back-end ajoute une règle que ce fichier ne connaît
 * pas encore) et la liste brute `clé : valeur` de son détail.
 */

import { formaterDate, formaterDateHeure, formaterMontant, formaterQuantite, TIRET } from "../lib/formats";
import type { components } from "../api/schema";

export type Anomalie = components["schemas"]["AnomalieReponse"];

const TITRES_REGLE: Record<string, string> = {
  R01: "Bon de livraison jamais reçu",
  R02: "Livré sans bon",
  R03: "Facturé plus que livré",
  R04: "Facturé moins que livré",
  R05: "Facturé mais absent du bon",
  R06: "Livré mais pas facturé",
  R07: "Prix un peu plus cher",
  R08: "Prix plus cher que d'habitude",
  R09: "Remise habituelle oubliée",
  R10: "Erreur de calcul sur la facture",
  R11: "Erreur de calcul sur le bon",
  R12: "Bon facturé deux fois",
  R13: "Avoir sans achat d'origine",
  R14: "Chantier à rattacher",
  R15: "Quantités non confirmées par l'équipe",
  R16: "Chantier sans bon déposé depuis 7 jours",
  R17: "Quantité inhabituelle pour le conditionnement",
};

/** Titre affiché pour un problème (« règle » en interne) — jamais le code
 * brut : un code inconnu affiche un repli générique plutôt qu'un `R99`
 * technique. */
export function titreRegle(code: string): string {
  return TITRES_REGLE[code] ?? "Problème à vérifier";
}

const URGENCES: Record<string, "Urgent" | "À voir" | "Info"> = {
  haute: "Urgent",
  moyenne: "À voir",
  basse: "Info",
};

/** Traduit la gravité technique (`haute`/`moyenne`/`basse`, calculée par le
 * moteur de règles) en mot d'urgence compris de tous — une gravité inconnue
 * retombe sur « Info » plutôt que de planter l'affichage. */
export function urgence(gravite: string): "Urgent" | "À voir" | "Info" {
  return URGENCES[gravite] ?? "Info";
}

/** Catégorie de filtre de l'écran « À régler » (spec §4) : dérivée du seul
 * code de règle, jamais recalculée. Assignation du contrôleur, faute d'un
 * jeu de règles fourni côté serveur — R01/R02/R16 partagent la même racine
 * (« un bon manque ou n'a jamais été vu »), R07-R09 sont des écarts de prix,
 * R03/R04/R15/R17 des écarts de quantité, R14 le seul cas de rattachement ;
 * le reste (erreurs de calcul, doublons, avoirs sans origine) n'a pas de
 * case dédiée dans les filtres de la maquette `ARegler` et tombe dans
 * « autre ». */
const CATEGORIES_REGLE: Record<string, "bl" | "prix" | "quantites" | "rattacher" | "autre"> = {
  R01: "bl",
  R02: "bl",
  R03: "quantites",
  R04: "quantites",
  R05: "autre",
  R06: "autre",
  R07: "prix",
  R08: "prix",
  R09: "prix",
  R10: "autre",
  R11: "autre",
  R12: "autre",
  R13: "autre",
  R14: "rattacher",
  R15: "quantites",
  R16: "bl",
  R17: "quantites",
};

export function categorieProbleme(regle: string): "bl" | "prix" | "quantites" | "rattacher" | "autre" {
  return CATEGORIES_REGLE[regle] ?? "autre";
}

/** Une valeur de `detail` absente ne doit jamais faire planter l'affichage
 * (les clés sont garanties par le back-end pour chaque règle connue, jamais
 * vérifiées ici). */
function valeur(detail: Record<string, string>, cle: string): string {
  return detail[cle] ?? "?";
}

/** `R05`/`R13` posent le tiret cadratin sur `montant` quand `montant_ht` est
 * absent (`app/modules/rules/rules/R05.py`, `R13.py`) — jamais passé à
 * `formaterMontant`, qui suppose une chaîne décimale valide. */
function montant(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? brute : formaterMontant(brute);
}

/** `cle` porte une quantité, un écart de quantité ou un ratio (chaîne
 * décimale), ou le tiret cadratin de `detail` quand la règle n'en a pas
 * trouvé (ex. `R05`/`R06` sans quantité) : le tiret est rendu tel quel,
 * jamais passé à `formaterQuantite`, qui rendrait « NaN » sur toute chaîne
 * non numérique. */
function quantite(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? brute : formaterQuantite(brute);
}

/** `cle` porte une date ISO, ou le tiret cadratin de `detail` quand la règle
 * n'en a pas trouvé (ex. `R01`/`R02`, `bloc.date_bl` absent) : le tiret est
 * rendu tel quel, jamais passé à `formaterDate`, qui plante sur toute
 * chaîne non convertible en date. */
function date(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? brute : formaterDate(brute);
}

function dateHeure(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? brute : formaterDateHeure(brute);
}

/** `cle` porte un pourcentage déjà exprimé en points (`"5.23"` = 5,23 %),
 * jamais une fraction entre 0 et 1. */
function pointsPourcent(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  return brute !== undefined ? `${brute} %` : "?";
}

/** Comme `pointsPourcent`, avec un mot au lieu de « — % » quand la valeur
 * vaut le tiret cadratin de `detail` (R09 : `remise_appliquee` porte le
 * tiret quand la ligne n'a aucune remise). */
function pointsPourcentOuAucun(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? "aucune" : `${brute} %`;
}

/** `article` suivi de son `code` entre parenthèses quand il est connu
 * (identification sans ambiguïté d'un article dont le libellé peut être
 * partagé par plusieurs codes fournisseur). */
function articleAvecCode(detail: Record<string, string>): string {
  const article = valeur(detail, "article");
  const code = detail.code;
  return code !== undefined && code !== TIRET ? `${article} (code ${code})` : article;
}

/** Repli pour une règle inconnue : liste brute `clé : valeur` du `detail`. */
function detailBrut(detail: Record<string, string>): string {
  const entrees = Object.entries(detail);
  if (entrees.length === 0) {
    return "Aucun détail.";
  }
  return entrees.map(([cle, val]) => `${cle} : ${val}`).join(" · ");
}

/** Phrase chiffrée justifiant un problème (jamais de code de règle ni de
 * jargon dans le texte — seulement des valeurs déjà calculées par le
 * serveur, mises en forme). */
export function phraseProbleme(anomalie: Anomalie): string {
  const detail = anomalie.detail;
  switch (anomalie.regle) {
    case "R01":
      return (
        `BL n° ${valeur(detail, "numero_bl")}, chantier ${valeur(detail, "chantier")}, ` +
        `daté du ${date(detail, "date_bl")}, montant HT ${montant(detail, "montant_ht")}.`
      );
    case "R02":
      return (
        `BL n° ${valeur(detail, "numero_bl")}, chantier ${valeur(detail, "chantier")}, ` +
        `daté du ${date(detail, "date_bl")}, montant HT ${montant(detail, "montant_ht")} — ` +
        `mention lue : « ${valeur(detail, "mention")} ».`
      );
    case "R03":
    case "R04":
      return (
        `${articleAvecCode(detail)} : ${quantite(detail, "qte_facture")} facturé(s) contre ` +
        `${quantite(detail, "qte_bl")} sur le BL (${valeur(detail, "unite")}), ` +
        `écart ${quantite(detail, "ecart")}.`
      );
    case "R05":
      return (
        `${articleAvecCode(detail)} : quantité ${quantite(detail, "qte")}, ` +
        `montant HT ${montant(detail, "montant")}, sans ligne correspondante sur le BL.`
      );
    case "R06":
      return (
        `${articleAvecCode(detail)} : quantité ${quantite(detail, "qte")}, sur le BL du ` +
        `${date(detail, "date_bl")} (${valeur(detail, "jours")} jours), jamais facturée.`
      );
    case "R07":
    case "R08":
      return (
        `${articleAvecCode(detail)} : PU facturé ${montant(detail, "pu_facture")}, médiane ` +
        `${montant(detail, "mediane")} sur ${valeur(detail, "occurrences")} occurrence(s), ` +
        `écart ${pointsPourcent(detail, "ecart_pct")}.`
      );
    case "R09":
      return (
        `${articleAvecCode(detail)} : remise habituelle ${pointsPourcent(detail, "remise_habituelle")} ` +
        `(${valeur(detail, "occurrences")} occurrence(s)), remise appliquée ` +
        `${pointsPourcentOuAucun(detail, "remise_appliquee")}.`
      );
    case "R10":
    case "R11":
      return (
        `Somme des lignes ${montant(detail, "somme")}, total ${montant(detail, "total")}, ` +
        `écart ${montant(detail, "ecart")} (tolérance ${montant(detail, "tolerance")}).`
      );
    case "R12":
      return (
        `BL n° ${valeur(detail, "numero_bl")} déjà rapproché par la facture ` +
        `${valeur(detail, "autre_facture")}, revu ici sur la facture ${valeur(detail, "facture")}, ` +
        `montant HT ${montant(detail, "montant_ht")}.`
      );
    case "R13":
      return (
        `${articleAvecCode(detail)} : montant ${montant(detail, "montant")}, aucune ligne ` +
        `positive antérieure trouvée sur le chantier ${valeur(detail, "chantier")}.`
      );
    case "R14":
      return (
        `Libellé « ${valeur(detail, "libelle")} » du fournisseur ${valeur(detail, "fournisseur")}, ` +
        `non résolu depuis ${valeur(detail, "heures")} heures.`
      );
    case "R15":
      return (
        `Déposé par ${valeur(detail, "deposant")} le ${dateHeure(detail, "depose_le")}, ` +
        `jamais confirmé (${valeur(detail, "heures")} heures).`
      );
    case "R16":
      return (
        `Chantier ${valeur(detail, "chantier")} : dernier dépôt le ` +
        `${dateHeure(detail, "dernier_depot")} (${valeur(detail, "jours")} jours), ` +
        `${valeur(detail, "bl_factures_depuis")} BL facturé(s) depuis.`
      );
    case "R17":
      return (
        `${articleAvecCode(detail)} : quantité ${quantite(detail, "qte")} ` +
        `${valeur(detail, "conditionnement")}, ratio ${quantite(detail, "ratio")}.`
      );
    default:
      return detailBrut(detail);
  }
}
