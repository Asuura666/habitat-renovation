import type { ReactElement } from "react";

/**
 * États calculés côté serveur (spec §6.2, `GET /api/tableau-de-bord` —
 * Task 2) plus `a_voir`, utilisé hors tableau de bord (repli d'urgence
 * générique). Définis ici en attendant que la Task 2 expose son propre
 * type : les deux doivent porter exactement ces six valeurs.
 */
export const ETATS = [
  "a_rattacher",
  "bl_manquant",
  "prix",
  "quantites",
  "a_voir",
  "conforme",
] as const;

export type Etat = (typeof ETATS)[number];

const LIBELLES_ETAT: Record<Etat, string> = {
  a_rattacher: "À rattacher",
  bl_manquant: "BL manquant",
  prix: "Prix à contester",
  quantites: "Quantités à vérifier",
  a_voir: "À voir",
  conforme: "Tout est conforme",
};

// Teintes reprises des maquettes (`ARegler`/`FicheChantier.dc.html`) : pas
// de jeton Tailwind dédié pour ces fonds clairs (hors de la liste imposée
// par la Task 4), valeurs arbitraires assumées ici seulement.
const CLASSES_ETAT: Record<Etat, string> = {
  a_rattacher: "bg-[#f9dedc] text-[#8c1d18]",
  bl_manquant: "bg-[#f9dedc] text-[#8c1d18]",
  prix: "bg-[#fbe9c6] text-[#7a4a00]",
  quantites: "bg-[#fbe9c6] text-[#7a4a00]",
  a_voir: "bg-[#fbe9c6] text-[#7a4a00]",
  // Texte en encre neutre plutôt qu'en vert (même choix que les maquettes,
  // ex. Main.dc.html : `couleurTexte: '#3d3a33'` pour l'état « conforme »,
  // `couleur: vert` réservé au point) — meilleur contraste qu'un vert clair
  // sur fond vert clair.
  conforme: "bg-[#e4f1ea] text-encre",
};

const CLASSES_POINT: Record<Etat, string> = {
  a_rattacher: "bg-alerte",
  bl_manquant: "bg-alerte",
  prix: "bg-ecart",
  quantites: "bg-ecart",
  a_voir: "bg-ecart",
  conforme: "bg-conforme",
};

/** Pastille d'état : point de couleur + libellé en toutes lettres — jamais
 * la couleur seule (spec §2, contrainte d'accessibilité). */
export function PastilleEtat({ etat }: { etat: Etat }): ReactElement {
  return (
    <span
      className={`inline-flex items-center gap-2 whitespace-nowrap rounded-full px-3 py-1 text-sm font-medium ${CLASSES_ETAT[etat]}`}
    >
      <span aria-hidden="true" className={`h-2.5 w-2.5 shrink-0 rounded-full ${CLASSES_POINT[etat]}`} />
      {LIBELLES_ETAT[etat]}
    </span>
  );
}
