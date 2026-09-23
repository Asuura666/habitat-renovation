import type { QueryClient } from "@tanstack/react-query";

import { CLE_ANOMALIES } from "./anomalies";
import { CLE_A_TRAITER } from "./aTraiter";
import { CLE_DOCUMENTS } from "./documents";
import { CLE_FACTURES } from "./factures";
import { CLE_TABLEAU_DE_BORD } from "./tableauDeBord";

/**
 * À appeler après toute écriture qui peut ouvrir, fermer ou déplacer des
 * problèmes côté serveur (revue finale de la refonte du front, constat
 * LIENS-4) : traiter ou ignorer un problème, valider/archiver/relire un bon
 * (le serveur relance le rapprochement), déposer une facture (idem),
 * rattacher un chantier (réécrit le chantier des livraisons), valider un
 * article. Avant ce correctif, seul le traitement d'un problème invalidait
 * ces données : la pastille « À régler » (montée sur toutes les routes), la
 * vue d'ensemble, les chiffres des chantiers et la comparaison d'un bon
 * restaient faux jusqu'au prochain retour de focus sur la fenêtre.
 *
 * Invalide : les anomalies (toutes les listes), la liste « À régler » et
 * son compte unique (`CLE_A_TRAITER`, préfixe de `CLE_COMPTE_A_REGLER` :
 * pastille, « … en tout » de la vue d'ensemble, en-tête d'« À régler »), le
 * tableau de bord de tous les mois, tout le bilan (chantiers, fournisseurs,
 * livraisons), les factures (état de réception de chaque livraison), la
 * liste des documents et le détail/la comparaison des documents
 * (`["document", id]` et `["document", id, "comparaison"]`).
 */
export async function invaliderApresChangementAnomalies(queryClient: QueryClient): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: CLE_ANOMALIES }),
    queryClient.invalidateQueries({ queryKey: CLE_A_TRAITER }),
    queryClient.invalidateQueries({ queryKey: CLE_TABLEAU_DE_BORD }),
    queryClient.invalidateQueries({ queryKey: ["bilan"] }),
    queryClient.invalidateQueries({ queryKey: CLE_FACTURES }),
    queryClient.invalidateQueries({ queryKey: CLE_DOCUMENTS }),
    queryClient.invalidateQueries({ queryKey: ["document"] }),
  ]);
}
