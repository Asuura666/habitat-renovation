/**
 * Libellés français des règles de contrôle (CDC §5) et phrase de
 * justification construite à partir du `detail` d'une anomalie (L4-D17,
 * L4-T10) : équivalent de `lib/motifs.ts` (motifs d'extraction) pour les
 * anomalies de rapprochement produites par `app/modules/rules/rules/R01.py`
 * … `R17.py`. Ce fichier ne fait que mettre en forme des valeurs déjà
 * chiffrées par les règles pures : aucun calcul d'écart, de somme ou de
 * pourcentage n'est fait ici. Un code de règle inconnu affiche le code brut
 * (`libelleRegle`) et la liste brute `clé : valeur` de son détail
 * (`justification`) — défense en profondeur si le back-end ajoute une règle
 * que ce fichier ne connaît pas encore.
 */

import { formaterDate, formaterDateHeure, formaterMontant, TIRET } from "./formats";
import type { components } from "../api/schema";

export type Anomalie = components["schemas"]["AnomalieReponse"];

const LIBELLES_REGLE: Record<string, string> = {
  R01: "R01 — BL facturé non reçu",
  R02: "R02 — BL facturé « pas de bon »",
  R03: "R03 — Quantité facturée supérieure à la quantité du BL",
  R04: "R04 — Quantité facturée inférieure à la quantité du BL",
  R05: "R05 — Ligne facturée absente du BL",
  R06: "R06 — Ligne du BL non facturée",
  R07: "R07 — Prix hors historique",
  R08: "R08 — Prix hors historique (écart fort)",
  R09: "R09 — Remise habituelle absente",
  R10: "R10 — Incohérence arithmétique de la facture",
  R11: "R11 — Incohérence arithmétique du BL",
  R12: "R12 — Doublon de facturation",
  R13: "R13 — Avoir sans origine",
  R14: "R14 — Chantier non résolu",
  R15: "R15 — BL sans confirmation",
  R16: "R16 — Chantier silencieux",
  R17: "R17 — Conditionnement inhabituel",
};

export function libelleRegle(code: string): string {
  return LIBELLES_REGLE[code] ?? code;
}

const LIBELLES_GRAVITE: Record<string, string> = {
  haute: "Haute",
  moyenne: "Moyenne",
  basse: "Basse",
};

export function libelleGravite(gravite: string): string {
  return LIBELLES_GRAVITE[gravite] ?? gravite;
}

/** Une valeur de `detail` absente ne doit jamais faire planter l'affichage
 * (même défense en profondeur que `lib/motifs.ts::valeur` : les clés sont
 * garanties par le back-end pour chaque règle connue, jamais vérifiées
 * ici). */
function valeur(detail: Record<string, string>, cle: string): string {
  return detail[cle] ?? "?";
}

/** Même défense que `date` ci-dessous : `R05`/`R13` posent le tiret
 * cadratin sur `montant` quand `montant_ht` est absent
 * (`app/modules/rules/rules/R05.py`, `R13.py`) — jamais passé à
 * `formaterMontant`, qui suppose une chaîne décimale valide. */
function montant(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? brute : formaterMontant(brute);
}

/** `cle` porte une date ISO, ou le tiret cadratin de `detail` quand la
 * règle n'en a pas trouvé (ex. `R01`/`R02`, `bloc.date_bl` absent —
 * `app/modules/rules/rules/R01.py`) : le tiret est rendu tel quel, jamais
 * passé à `formaterDate`, qui plante sur toute chaîne non convertible en
 * date (`new Date("—")` est une date invalide, `Intl.DateTimeFormat.format`
 * lève alors `RangeError: Invalid time value` — trouvé en vérification
 * visuelle, fix round 1). Même défense que `pointsPourcentOuAucun`
 * ci-dessous et que `pourcentage` de `lib/motifs.ts`. */
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
 * jamais une fraction entre 0 et 1 — contrairement à `confiance`/`seuil` de
 * `lib/motifs.ts` : même convention que `remise_pct` dans
 * `FactureDetail.tsx` (`` `${valeur} %` ``), jamais `formaterPourcentage`
 * qui multiplierait par 100 une valeur déjà en points. */
function pointsPourcent(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  return brute !== undefined ? `${brute} %` : "?";
}

/** Comme `pointsPourcent`, avec un mot au lieu de « — % » quand la valeur
 * vaut le tiret cadratin de `detail` (R09 : `remise_appliquee` porte le
 * tiret quand la ligne n'a aucune remise, plutôt qu'un pourcentage nul —
 * voir `app/modules/rules/rules/R09.py`). */
function pointsPourcentOuAucun(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? "aucune" : `${brute} %`;
}

/** `article` suivi de son `code` entre parenthèses quand il est connu
 * (décision du contrôleur : identification sans ambiguïté d'un article
 * dont le libellé peut être partagé par plusieurs codes fournisseur). */
function articleAvecCode(detail: Record<string, string>): string {
  const article = valeur(detail, "article");
  const code = detail.code;
  return code !== undefined && code !== TIRET ? `${article} (code ${code})` : article;
}

/** Repli pour une règle inconnue : liste brute `clé : valeur` du `detail`
 * (décision du contrôleur, même esprit que le code brut de `libelleRegle`). */
function detailBrut(detail: Record<string, string>): string {
  const entrees = Object.entries(detail);
  if (entrees.length === 0) {
    return "Aucun détail.";
  }
  return entrees.map(([cle, val]) => `${cle} : ${val}`).join(" · ");
}

export function justification(anomalie: Anomalie): string {
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
        `${articleAvecCode(detail)} : ${valeur(detail, "qte_facture")} facturé(s) contre ` +
        `${valeur(detail, "qte_bl")} sur le BL (${valeur(detail, "unite")}), ` +
        `écart ${valeur(detail, "ecart")}.`
      );
    case "R05":
      return (
        `${articleAvecCode(detail)} : quantité ${valeur(detail, "qte")}, ` +
        `montant HT ${montant(detail, "montant")}, sans ligne correspondante sur le BL.`
      );
    case "R06":
      return (
        `${articleAvecCode(detail)} : quantité ${valeur(detail, "qte")}, sur le BL du ` +
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
        `${articleAvecCode(detail)} : quantité ${valeur(detail, "qte")} ` +
        `${valeur(detail, "conditionnement")}, ratio ${valeur(detail, "ratio")}.`
      );
    default:
      return detailBrut(detail);
  }
}
