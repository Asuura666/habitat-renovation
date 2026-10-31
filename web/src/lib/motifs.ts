/**
 * Libellés français des motifs de mise « à vérifier » (décision du
 * contrôleur, L3-T9). Chaque motif vient tel quel de l'API (`code`, `champ`,
 * `detail` — voir `app/modules/extract/verification.py::CodeMotif` et
 * `app/modules/ingest/extraction_bl.py` pour les quatre motifs posés par
 * `ingest`) : ce fichier ne fait que le mettre en forme, aucun calcul
 * métier. Un code inconnu affiche le code brut (défense en profondeur si le
 * back-end en ajoute un que ce fichier ne connaît pas encore).
 */

import { formaterMontant } from "./formats";
import type { components } from "../api/schema";

export type Motif = components["schemas"]["MotifReponse"];

const LIBELLES_CHAMP: Record<string, string> = {
  fournisseur: "Fournisseur",
  numero: "Numéro",
  date_doc: "Date",
  chantier_brut: "Chantier",
  total_ht: "Total HT",
  lignes: "Lignes",
};

/** `champ` peut valoir `"ligne:<ordre>"` (`verifier_bl`, confiance d'une
 * ligne, `ordre` compté à partir de 0 côté API) : rendu « Ligne <ordre+1> »
 * (fix round 1, revue L3-T9 : un numéro de ligne affiché à l'admin part de
 * 1, une conversion d'affichage `+1`, pas un calcul métier — le brut est
 * gardé tel quel si ce n'est pas un nombre, défense en profondeur). Les
 * autres champs connus sont traduits, un champ inconnu s'affiche tel quel. */
function libelleChamp(champ: string | null): string {
  if (champ === null) {
    return "";
  }
  if (champ.startsWith("ligne:")) {
    const ordreBrut = champ.slice("ligne:".length);
    const ordre = Number(ordreBrut);
    return `Ligne ${Number.isNaN(ordre) ? ordreBrut : ordre + 1}`;
  }
  return LIBELLES_CHAMP[champ] ?? champ;
}

/** Une valeur de `detail` absente ne doit jamais faire planter l'affichage
 * (défense en profondeur : les clés de `detail` sont garanties par le
 * back-end pour chaque code connu, jamais vérifiées ici). */
function valeur(detail: Record<string, string>, cle: string): string {
  return detail[cle] ?? "?";
}

function montant(detail: Record<string, string>, cle: string): string {
  const brute = detail[cle];
  return brute !== undefined ? formaterMontant(brute) : "?";
}


export function libelleMotif(motif: Motif): string {
  const champ = libelleChamp(motif.champ);
  switch (motif.code) {
    case "champ_absent":
      return `${champ || "Champ"} absent`;
    case "valeur_illisible":
      return `${champ || "Champ"} illisible`;
    case "confiance_faible":
      // Revue finale de la refonte du front (constats ECRAN-13,
      // TELEPHONE-13) : plus de pourcentages de confiance et de seuil de
      // lecture, termes techniques — une phrase qui dit quoi faire.
      return `Lecture incertaine de « ${champ || "ce champ"} » — à vérifier sur la photo`;
    case "somme_incoherente":
      return (
        `Somme des lignes (${montant(motif.detail, "somme")}) différente du total ` +
        `(${montant(motif.detail, "total")}), écart ${montant(motif.detail, "ecart")}`
      );
    case "total_absent":
      return `Total absent (somme des lignes : ${montant(motif.detail, "somme")})`;
    case "lignes_absentes":
      return "Aucune ligne détectée";
    case "numero_incoherent":
      return (
        `Numéro lu (${valeur(motif.detail, "lu")}) différent du numéro détecté ` +
        `(${valeur(motif.detail, "detecte")})`
      );
    case "ocr_echec":
      return "Échec de la lecture automatique";
    case "annotation_illisible":
      return "Annotation illisible";
    case "fournisseur_inconnu":
      return "Fournisseur inconnu du référentiel";
    case "numero_en_double":
      return (
        `Numéro « ${valeur(motif.detail, "numero")} » déjà utilisé par le document ` +
        `n° ${valeur(motif.detail, "numero_interne_existant")}`
      );
    case "reference_chantier_inconnue": {
      // Lot 2 du 31/10/2026 : aucun chantier écrit sur le bon, et la
      // référence de commande ne désigne aucun chantier connu (`candidats`
      // seulement si elle ressemble à plusieurs).
      const reference = valeur(motif.detail, "reference");
      const candidats = motif.detail["candidats"];
      return candidats !== undefined
        ? `Pas de chantier écrit sur le bon ; la référence de commande « ${reference} » ressemble à plusieurs chantiers : ${candidats}`
        : `Pas de chantier écrit sur le bon ; la référence de commande « ${reference} » ne correspond à aucun chantier connu`;
    }
    default:
      return motif.code;
  }
}
