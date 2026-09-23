import type { QueryClient } from "@tanstack/react-query";

import { CLE_ANOMALIES } from "./anomalies";
import { CLE_TABLEAU_DE_BORD } from "./tableauDeBord";

/**
 * À appeler après toute écriture qui peut ouvrir, fermer ou déplacer des
 * problèmes côté serveur (revue finale de la refonte du front, constat
 * LIENS-4) : traiter ou ignorer un problème, valider/archiver/relire un bon
 * (le serveur relance le rapprochement), déposer une facture (idem),
 * rattacher un chantier (réécrit le chantier des livraisons). Avant ce
 * correctif, seul le traitement d'un problème invalidait ces données : la
 * pastille « À régler » (montée sur toutes les routes), la vue d'ensemble,
 * les chiffres des chantiers et la comparaison d'un bon restaient faux
 * jusqu'au prochain retour de focus sur la fenêtre.
 *
 * Invalide : les anomalies (toutes les listes et la pastille, même
 * préfixe), le tableau de bord de tous les mois, tout le bilan (chantiers,
 * fournisseurs, livraisons) et le détail/la comparaison des documents
 * (`["document", id]` et `["document", id, "comparaison"]`).
 */
export async function invaliderApresChangementAnomalies(queryClient: QueryClient): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: CLE_ANOMALIES }),
    queryClient.invalidateQueries({ queryKey: CLE_TABLEAU_DE_BORD }),
    queryClient.invalidateQueries({ queryKey: ["bilan"] }),
    queryClient.invalidateQueries({ queryKey: ["document"] }),
  ]);
}
