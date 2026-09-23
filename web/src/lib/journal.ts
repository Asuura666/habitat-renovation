/**
 * Lecture du journal (`ingest/journal.py`, L5-T9) : libellés français des
 * actions journalisées et mise en forme lisible de `avant`/`apres` — même
 * principe que `lib/regles.ts` (mise en forme uniquement, aucun calcul,
 * aucune interprétation métier).
 *
 * Liste des actions recensée dans le code (`grep -rn 'action=' app/modules
 * /ingest/`, hors tests), pas inventée : `extraction_bl.py`,
 * `corrections.py`, `anomalies.py`, `factures.py`, `depot_telegram.py`,
 * `rapprochement.py`, `referentiels.py`. Complétée par les deux actions de
 * gestion de compte d'`app/core/auth.py` (`utilisateur_cree`,
 * `utilisateur_desactive`) — trouvées pendant la vérification visuelle : la
 * consigne bornait le recensement à `app/modules/ingest/`, mais le journal
 * est alimenté par `app.core` aussi (`creer_utilisateur`/
 * `desactiver_utilisateur`, CLI `utilisateur-creer`/`utilisateur-
 * desactiver`), et la première capture d'écran les a montrées avec leur
 * code brut faute d'entrée ici — corrigé plutôt que laissé tel quel,
 * puisque le mécanisme de repli (défensif) n'a pas besoin d'un code brut
 * quand un libellé est trivial à ajouter. Une action absente de cette table
 * affiche malgré tout son code brut (`libelleAction`) — défense en
 * profondeur, comme `libelleRegle` dans `lib/regles.ts`, si un lot futur en
 * ajoute une que ce fichier ne connaît pas encore.
 */

import { TIRET } from "./formats";

const LIBELLES_ACTION: Record<string, string> = {
  extraction_bl: "Extraction du BL",
  document_corrige: "Document corrigé",
  lignes_corrigees: "Lignes corrigées",
  document_valide: "Document validé",
  document_archive: "Document archivé",
  extraction_relancee: "Extraction relancée",
  anomalie_levee: "Anomalie levée",
  anomalie_traitee: "Anomalie traitée",
  anomalie_ignoree: "Anomalie ignorée",
  facture_deposee: "Facture déposée",
  quantites_verifiees: "Quantités confirmées (BL)",
  ecart_constate: "Écart constaté (BL)",
  facture_rapprochee: "Facture rapprochée",
  fournisseur_defini: "Fournisseur défini",
  chantier_cree: "Chantier créé",
  // Ajoutée par la Task 1 de la refonte du front (`app/modules/ingest/
  // chantiers.py` ou équivalent) : édition du nom/client/agence/actif
  // d'un chantier depuis la fiche chantier — trouvée en relisant la
  // consigne de la Task 10, pas encore recensée par le grep de tête de
  // fichier au moment où ce libellé a été ajouté.
  chantier_modifie: "Chantier modifié",
  alias_valide: "Alias de chantier validé",
  article_valide: "Article validé",
  utilisateur_cree: "Compte utilisateur créé",
  utilisateur_desactive: "Compte utilisateur désactivé",
  parametre_modifie: "Paramètre modifié",
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
 * affichées telles quelles (ce sont déjà des noms de table lisibles),
 * uniquement pour peupler le sélecteur de filtre. */
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
  avant: string;
  apres: string;
}

/** Reconstruit, clé par clé, la comparaison `avant`/`apres` d'une entrée de
 * journal — deux instantanés JSON indépendants (`ingest/journal.py`) :
 * une clé présente d'un côté et absente de l'autre est un fait à afficher
 * explicitement (`"absent"`), jamais un vide ambigu (décision du
 * contrôleur, L5-T9 : « si une valeur est absente d'un côté, dis-le
 * explicitement »). Aucune traduction, aucun calcul d'écart : uniquement
 * une mise en forme lisible du JSON brut, clés triées pour un affichage
 * stable. */
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
    avant: avant !== null && cle in avant ? formaterValeurBrute(avant[cle]) : ABSENT,
    apres: apres !== null && cle in apres ? formaterValeurBrute(apres[cle]) : ABSENT,
  }));
}
