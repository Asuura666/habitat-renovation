import type { ReactElement } from "react";

export type TonChiffre = "neutre" | "conforme" | "ecart" | "alerte";

const CLASSES_TON: Record<TonChiffre, string> = {
  neutre: "text-encre",
  conforme: "text-conforme",
  ecart: "text-ecart-texte",
  alerte: "text-alerte",
};

/**
 * Tuile chiffrée (spec §2/§4) : libellé discret, grand chiffre en Fraunces
 * (couleur selon `ton` — jamais la seule couleur : `libelle`/`sousTexte`
 * portent toujours le sens en mots), sous-texte optionnel. Autonome
 * (bordure, fond, coin arrondi) : s'utilise directement dans une grille,
 * sans `Carte` autour (mêmes tuiles que les maquettes `Main`/
 * `FicheChantier`).
 */
export function Chiffre({
  libelle,
  valeur,
  sousTexte,
  ton = "neutre",
}: {
  libelle: string;
  valeur: string;
  sousTexte?: string;
  ton?: TonChiffre;
}): ReactElement {
  return (
    <div className="rounded-carte border border-bordure bg-surface p-5">
      <dl>
        <dt className="text-sm text-encre-2">{libelle}</dt>
        <dd
          className={`mt-1 whitespace-nowrap font-titre text-2xl font-semibold ${CLASSES_TON[ton]}`}
        >
          {valeur}
        </dd>
      </dl>
      {sousTexte !== undefined && <p className="mt-2 text-sm text-encre">{sousTexte}</p>}
    </div>
  );
}
