/**
 * Langage courant de la refonte du front (spec §5) : un seul module associe
 * chaque code de règle à un titre sans jargon et construit la phrase
 * chiffrée à partir des valeurs de `detail` déjà calculées par le serveur —
 * aucun calcul métier ici (somme, écart, pourcentage), seulement de la mise
 * en forme. A remplacé l'ancien `lib/regles.ts` (supprimé à la revue finale,
 * plus aucun écran ne l'importait).
 *
 * Un code de règle inconnu affiche « Problème à vérifier » (repli, défense
 * en profondeur si le back-end ajoute une règle que ce fichier ne connaît
 * pas encore) et une phrase générique renvoyant au document.
 *
 * Revue finale de la refonte du front :
 * - la catégorie d'un problème (filtres de l'écran « À régler ») vient du
 *   serveur (`AnomalieReponse.categorie`, table unique
 *   `ingest.anomalies.CATEGORIES_REGLE`) — plus jamais une seconde table
 *   ici, qui contredisait l'état d'un chantier (constats SERVEUR-3,
 *   COUVERTURE-14) ;
 * - les gardes de mise en forme (`montantOuTiret`, `quantiteOuTiret`…) sont
 *   exportées et partagées par « À régler » plutôt que recopiées (constat
 *   LIENS-12) ;
 * - pourcentages au format français (« 30,6 % »), unité omise quand elle
 *   est inconnue (plus de « (—) »), tournures sans « (s) » (constats
 *   ECRAN-1, ECRAN-9, COUVERTURE-5, TELEPHONE-8).
 */

import {
  formaterDate,
  formaterDateHeure,
  formaterMontant,
  formaterPoints,
  formaterQuantite,
  TIRET,
} from "../lib/formats";
import type { components } from "../api/schema";

export type Anomalie = components["schemas"]["AnomalieReponse"];
export type Urgence = "Urgent" | "À voir" | "Info";
export type CategorieRegle = Anomalie["categorie"];

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
  // Revue finale (constat COUVERTURE-20) : le délai est un réglage
  // (`delai_chantier_silencieux_j`) — le titre de la spec §5 (« depuis
  // 7 jours ») devenait faux dès qu'on le changeait. Le nombre de jours
  // réel figure dans la phrase ci-dessous. À signaler à Ilane.
  R16: "Chantier sans bon déposé récemment",
  R17: "Quantité inhabituelle pour le conditionnement",
  R18: "Chantier à confirmer",
  // Phase 3 (prix des bons, spec §5.2, §8.3) : R19-R25 ne sont pas encore
  // produites par le serveur (`evaluer_prix_bl` n'est pas encore câblée),
  // ajoutées ici en même temps que les règles pour ne pas retarder ce
  // fichier à leur câblage (même principe que R18, avenant du 27/09/2026).
  R19: "Plus cher que la grille",
  R20: "Plus cher que la dernière fois",
  R21: "Moins cher que la grille",
  R22: "Produit absent de la grille",
  R23: "Produit reconnu seulement par son nom",
  R24: "Unités différentes",
  R25: "Grille ancienne",
};

/** Titre affiché pour un problème (« règle » en interne) — jamais le code
 * brut : un code inconnu affiche un repli générique plutôt qu'un `R99`
 * technique. */
export function titreRegle(code: string): string {
  return TITRES_REGLE[code] ?? "Problème à vérifier";
}

const URGENCES: Record<string, Urgence> = {
  haute: "Urgent",
  moyenne: "À voir",
  basse: "Info",
};

/** Traduit la gravité technique (`haute`/`moyenne`/`basse`, calculée par le
 * moteur de règles) en mot d'urgence compris de tous — une gravité inconnue
 * retombe sur « Info » plutôt que de planter l'affichage. */
export function urgence(gravite: string): Urgence {
  return URGENCES[gravite] ?? "Info";
}

/** Catégorie de filtre de l'écran « À régler » (spec §4) : lue telle
 * quelle sur l'anomalie, calculée par le serveur (voir l'en-tête). */
export function categorieProbleme(anomalie: Anomalie): CategorieRegle {
  return anomalie.categorie;
}

/** Libellé de la tuile « Écart prix ou quantité » (Vue d'ensemble, fiche
 * chantier, fiche fournisseur) : décision d'Ilane du 24/09/2026 (`docs/
 * dette.md`), contrôles de prix désactivés côté serveur — le montant qui
 * alimente cette tuile (`MontantsBilan.en_ecart`) ne peut plus contenir
 * d'écart de prix tant que `controlePrixActif` est faux, le libellé ne
 * doit donc plus l'évoquer. `controlePrixActif` vient de
 * `CompteProblemesReponse.controle_prix_actif` (`GET /api/a-regler/compte`,
 * seul endroit qui porte ce drapeau) ; aucun calcul ici, une simple
 * correspondance texte. */
export function libelleEcart(controlePrixActif: boolean): string {
  return controlePrixActif ? "Écart prix ou quantité" : "Écart de quantité";
}

/** Sous-texte de la tuile « Écart … » (Vue d'ensemble, fiche chantier,
 * fiche fournisseur) : même bascule que `libelleEcart`, avec le même
 * drapeau -- décrit ce que le montant contient plutôt qu'un mot vague
 * (« un écart »), pour rester clair pour un non-technicien même quand les
 * contrôles de prix sont désactivés (Vue d'ensemble affichait « livraisons
 * concernées par un écart », muet sur la nature de l'écart alors que le
 * libellé de la tuile dit déjà « quantité »). */
export function sousTexteEcart(controlePrixActif: boolean): string {
  return controlePrixActif
    ? "livraisons concernées par un écart de prix ou de quantité"
    : "livraisons avec un écart de quantité";
}

// ---------------------------------------------------------------------------
// Gardes de mise en forme d'une valeur de `detail` : une clé absente affiche
// « ? », le tiret cadratin (valeur manquante posée par les règles pures) est
// rendu tel quel, jamais passé à un formateur (`formaterDate` lève sur une
// chaîne non convertible, `formaterQuantite` rendrait « NaN »).
// ---------------------------------------------------------------------------

export function texteOuTiret(detail: Record<string, string>, cle: string): string {
  return detail[cle] ?? "?";
}

function garde(detail: Record<string, string>, cle: string, formater: (brute: string) => string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? brute : formater(brute);
}

export function montantOuTiret(detail: Record<string, string>, cle: string): string {
  return garde(detail, cle, formaterMontant);
}

export function quantiteOuTiret(detail: Record<string, string>, cle: string): string {
  return garde(detail, cle, formaterQuantite);
}

export function dateOuTiret(detail: Record<string, string>, cle: string): string {
  return garde(detail, cle, formaterDate);
}

export function dateHeureOuTiret(detail: Record<string, string>, cle: string): string {
  return garde(detail, cle, formaterDateHeure);
}

/** `cle` porte un pourcentage déjà exprimé en points (`"5.23"` = 5,23 %),
 * jamais une fraction entre 0 et 1. */
export function pointsOuTiret(detail: Record<string, string>, cle: string): string {
  return garde(detail, cle, formaterPoints);
}

/** Comme `pointsOuTiret`, avec un mot au lieu du tiret quand la valeur vaut
 * le tiret cadratin (R09 : `remise_appliquee` porte le tiret quand la ligne
 * n'a aucune remise). */
export function pointsOuAucun(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  if (brute === undefined) {
    return "?";
  }
  return brute === TIRET ? "aucune" : formaterPoints(brute);
}

/** Unité à accoler à une quantité (« 12 m² »), ou rien quand la règle ne
 * la connaît pas (tiret cadratin, cas le plus courant tant que l'article
 * n'a pas d'unité validée) — plus jamais « (—) » dans une phrase. */
function suffixeUnite(detail: Record<string, string>): string {
  const unite = detail.unite;
  return unite !== undefined && unite !== TIRET && unite.trim() !== "" ? ` ${unite}` : "";
}

/** `article` suivi de son `code` entre parenthèses quand il est connu
 * (identification sans ambiguïté d'un article dont le libellé peut être
 * partagé par plusieurs codes fournisseur). */
function articleAvecCode(detail: Record<string, string>): string {
  const article = texteOuTiret(detail, "article");
  const code = detail.code;
  return code !== undefined && code !== TIRET ? `${article} (code ${code})` : article;
}

/** Même principe qu'`articleAvecCode`, pour les règles de prix des bons
 * (phase 3, R19-R25) : leur `detail` porte la clé `produit`, pas `article`
 * (spec §5.2) -- deux tables de règles distinctes, deux clés distinctes,
 * jamais mélangées. */
function produitAvecCode(detail: Record<string, string>): string {
  const produit = texteOuTiret(detail, "produit");
  const code = detail.code;
  return code !== undefined && code !== TIRET ? `${produit} (code ${code})` : produit;
}

/** Phrase chiffrée justifiant un problème (jamais de code de règle ni de
 * jargon dans le texte — seulement des valeurs déjà calculées par le
 * serveur, mises en forme). */
export function phraseProbleme(anomalie: Anomalie): string {
  const detail = anomalie.detail;
  switch (anomalie.regle) {
    case "R01":
      return (
        `BL n° ${texteOuTiret(detail, "numero_bl")}, chantier ${texteOuTiret(detail, "chantier")}, ` +
        `daté du ${dateOuTiret(detail, "date_bl")}, montant HT ${montantOuTiret(detail, "montant_ht")}.`
      );
    case "R02":
      return (
        `BL n° ${texteOuTiret(detail, "numero_bl")}, chantier ${texteOuTiret(detail, "chantier")}, ` +
        `daté du ${dateOuTiret(detail, "date_bl")}, montant HT ${montantOuTiret(detail, "montant_ht")} — ` +
        `mention lue : « ${texteOuTiret(detail, "mention")} ».`
      );
    case "R03":
    case "R04": {
      const unite = suffixeUnite(detail);
      return (
        `${articleAvecCode(detail)} : quantité facturée ${quantiteOuTiret(detail, "qte_facture")}${unite}, ` +
        `quantité sur le bon ${quantiteOuTiret(detail, "qte_bl")}${unite}, ` +
        `écart ${quantiteOuTiret(detail, "ecart")}${unite}.`
      );
    }
    case "R05":
      return (
        `${articleAvecCode(detail)} : quantité ${quantiteOuTiret(detail, "qte")}, ` +
        `montant HT ${montantOuTiret(detail, "montant")}, sans ligne correspondante sur le bon.`
      );
    case "R06":
      return (
        `${articleAvecCode(detail)} : quantité ${quantiteOuTiret(detail, "qte")}, sur le bon du ` +
        `${dateOuTiret(detail, "date_bl")} (il y a ${texteOuTiret(detail, "jours")} jours), jamais facturée.`
      );
    case "R07":
    case "R08":
      return (
        `${articleAvecCode(detail)} : facturé ${montantOuTiret(detail, "pu_facture")} au lieu de ` +
        `${montantOuTiret(detail, "mediane")} habituellement (+${pointsOuTiret(detail, "ecart_pct")}) — ` +
        `nombre de factures de référence : ${texteOuTiret(detail, "occurrences")}.`
      );
    case "R09":
      return (
        `${articleAvecCode(detail)} : remise habituelle ${pointsOuTiret(detail, "remise_habituelle")} ` +
        `(factures de référence : ${texteOuTiret(detail, "occurrences")}), remise appliquée ` +
        `${pointsOuAucun(detail, "remise_appliquee")}.`
      );
    case "R10":
    case "R11":
      return (
        `Somme des lignes ${montantOuTiret(detail, "somme")}, total ${montantOuTiret(detail, "total")}, ` +
        `écart ${montantOuTiret(detail, "ecart")} (tolérance ${montantOuTiret(detail, "tolerance")}).`
      );
    case "R12":
      return (
        `BL n° ${texteOuTiret(detail, "numero_bl")} déjà facturé sur la facture ` +
        `${texteOuTiret(detail, "autre_facture")}, revu ici sur la facture ${texteOuTiret(detail, "facture")}, ` +
        `montant HT ${montantOuTiret(detail, "montant_ht")}.`
      );
    case "R13":
      return (
        `${articleAvecCode(detail)} : montant ${montantOuTiret(detail, "montant")}, aucune ligne ` +
        `positive antérieure trouvée sur le chantier ${texteOuTiret(detail, "chantier")}.`
      );
    case "R14":
      return (
        `Chantier pas encore identifié : libellé « ${texteOuTiret(detail, "libelle")} » du ` +
        `fournisseur ${texteOuTiret(detail, "fournisseur")}, depuis ${texteOuTiret(detail, "heures")} heures.`
      );
    case "R15":
      return (
        `Déposé par ${texteOuTiret(detail, "deposant")} le ${dateHeureOuTiret(detail, "depose_le")}, ` +
        `jamais confirmé (depuis ${texteOuTiret(detail, "heures")} heures).`
      );
    case "R16":
      return (
        `Chantier ${texteOuTiret(detail, "chantier")} : dernier dépôt le ` +
        `${dateHeureOuTiret(detail, "dernier_depot")} (il y a ${texteOuTiret(detail, "jours")} jours) ; ` +
        `bons facturés depuis : ${texteOuTiret(detail, "bl_factures_depuis")}.`
      );
    case "R17":
      return (
        `${articleAvecCode(detail)} : quantité ${quantiteOuTiret(detail, "qte")} inhabituelle pour ` +
        `un conditionnement de ${texteOuTiret(detail, "conditionnement")}.`
      );
    case "R18":
      return (
        `Le nom lu sur le bon (« ${texteOuTiret(detail, "nom_lu")} ») et le nom indiqué par l'employé ` +
        `(« ${texteOuTiret(detail, "legende")} ») ne désignent pas un seul chantier. ` +
        `Chantiers possibles : ${texteOuTiret(detail, "candidats")}.`
      );
    // Phase 3 (prix des bons, spec §5.2, §8.3) : R19-R25 ne sont pas
    // encore produites par le serveur, voir le commentaire de
    // `TITRES_REGLE` ci-dessus.
    case "R19":
      return (
        `${produitAvecCode(detail)} : ${montantOuTiret(detail, "prix_bon")} sur le bon au lieu de ` +
        `${montantOuTiret(detail, "prix_grille")} dans la grille (du ${dateOuTiret(detail, "date_grille")}), ` +
        `+${pointsOuTiret(detail, "ecart_pct")}.`
      );
    case "R20":
      return (
        `${produitAvecCode(detail)} : ${montantOuTiret(detail, "prix_bon")} sur le bon, ` +
        `${montantOuTiret(detail, "dernier_prix")} sur la facture ${texteOuTiret(detail, "numero_facture")} du ` +
        `${dateOuTiret(detail, "date_dernier_prix")}, +${pointsOuTiret(detail, "ecart_pct")}.`
      );
    case "R21":
      return (
        `${produitAvecCode(detail)} : ${montantOuTiret(detail, "prix_bon")} sur le bon au lieu de ` +
        `${montantOuTiret(detail, "prix_grille")} dans la grille (du ${dateOuTiret(detail, "date_grille")}), ` +
        `${pointsOuTiret(detail, "ecart_pct")}.`
      );
    case "R22":
      return (
        `${produitAvecCode(detail)} : absent de la grille, ${montantOuTiret(detail, "prix_bon")} sur le bon. ` +
        `Produits proches : ${texteOuTiret(detail, "candidats")}.`
      );
    case "R23":
      return (
        `${produitAvecCode(detail)} : reconnu dans la grille comme « ${texteOuTiret(detail, "designation_grille")} » ` +
        `par son nom (ressemblance ${texteOuTiret(detail, "ressemblance")} %).`
      );
    case "R24": {
      const uniteGrille = texteOuTiret(detail, "unite_grille");
      const uniteDernierPrix = texteOuTiret(detail, "unite_dernier_prix");
      const references: string[] = [];
      if (uniteGrille !== TIRET) {
        references.push(`la grille (« ${uniteGrille} »)`);
      }
      if (uniteDernierPrix !== TIRET) {
        references.push(`la dernière facture (« ${uniteDernierPrix} »)`);
      }
      const reference = references.length > 0 ? references.join(" et de ") : "la référence (« — »)";
      const uniteBon = texteOuTiret(detail, "unite_bon");
      return (
        `${produitAvecCode(detail)} : unité du bon « ${uniteBon} », différente de celle de ` +
        `${reference} — comparaison impossible.`
      );
    }
    case "R25":
      return (
        `${produitAvecCode(detail)} : prix de grille du ${dateOuTiret(detail, "date_grille")}, vieux de ` +
        `${texteOuTiret(detail, "age_mois")} mois.`
      );
    default:
      // Revue finale (constat COUVERTURE-19) : plus de liste brute
      // `clé : valeur` (jargon technique) pour une règle inconnue.
      return "Le détail figure sur la facture ou le bon concerné.";
  }
}
