import type { ReactElement } from "react";

import type { Urgence } from "./libelles";

// Mêmes teintes que `PastilleEtat` (fonds clairs de la charte, pas de jeton
// Tailwind dédié) : rouge pour « Urgent », ambre pour « À voir », neutre
// pour « Info ».
const CLASSES_URGENCE: Record<Urgence, string> = {
  Urgent: "bg-[#f9dedc] text-[#8c1d18]",
  "À voir": "bg-[#fbe9c6] text-[#7a4a00]",
  Info: "bg-fond text-encre-2",
};

/** Pastille d'urgence d'un problème (« Urgent », « À voir », « Info »),
 * partagée par « À régler », la fiche chantier et la fiche fournisseur
 * (revue finale de la refonte du front, constat LIENS-12 : l'urgence
 * apparaissait en pastille colorée sur deux écrans et en simple texte gris
 * sur le troisième). Toujours le mot en toutes lettres, jamais la couleur
 * seule (spec §2). */
export function PastilleUrgence({ urgence }: { urgence: Urgence }): ReactElement {
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${CLASSES_URGENCE[urgence]}`}
    >
      {urgence}
    </span>
  );
}
