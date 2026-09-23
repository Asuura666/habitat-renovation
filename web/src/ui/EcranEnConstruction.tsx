import type { ReactElement } from "react";

import { EnTetePage } from "./EnTetePage";
import { EtatVide } from "./EtatVide";

/**
 * Repli temporaire posé par la Task 4 sur une route qui n'a pas encore
 * d'écran (plan de la refonte du front §8, ex. `/` Vue d'ensemble) : les
 * Tâches 5 à 10 remplacent ce composant, sur leur route, par l'écran fini —
 * jamais de jargon technique visible en attendant.
 */
export function EcranEnConstruction({ titre }: { titre: string }): ReactElement {
  return (
    <div className="space-y-6">
      <EnTetePage titre={titre} />
      <EtatVide message="Cet écran est en cours de construction." />
    </div>
  );
}
