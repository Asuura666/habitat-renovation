import type { ReactElement } from "react";
import { Link } from "react-router";

export type TonChiffre = "neutre" | "conforme" | "ecart" | "alerte";

const CLASSES_TON: Record<TonChiffre, string> = {
  neutre: "text-encre",
  conforme: "text-conforme",
  ecart: "text-ecart-texte",
  alerte: "text-alerte",
};

const CLASSES_TUILE = "rounded-carte border border-bordure bg-surface p-5";
// Cible cliquable (Task 13, spec §4.3, « bons conformes cliquables ») :
// mêmes couleurs qu'une carte cliquable ailleurs dans la charte (fond
// `hover:bg-fond`, anneau de focus visible) — jamais la couleur seule pour
// signaler que la tuile mène quelque part (accessibilité, CLAUDE.md), le
// contenu (libellé/sous-texte) reste identique à la tuile non cliquable.
const CLASSES_TUILE_CLIQUABLE =
  "block rounded-carte border border-bordure bg-surface p-5 text-left outline-none transition-colors hover:bg-fond focus-visible:ring-2 focus-visible:ring-accent";

/**
 * Tuile chiffrée (spec §2/§4) : libellé discret, grand chiffre en Fraunces
 * (couleur selon `ton` — jamais la seule couleur : `libelle`/`sousTexte`
 * portent toujours le sens en mots), sous-texte optionnel. Autonome
 * (bordure, fond, coin arrondi) : s'utilise directement dans une grille,
 * sans `Carte` autour (mêmes tuiles que les maquettes `Main`/
 * `FicheChantier`).
 *
 * `vers` (Task 13, spec §4.3) : rend toute la tuile cliquable (un vrai
 * `<Link>`, jamais un `onClick` sur un `<div>`) vers la liste des bons du
 * même périmètre — utilisé par la tuile « Conforme » de l'accueil, de la
 * fiche chantier et de la fiche fournisseur. Absent (défaut), la tuile
 * reste un simple conteneur, comme avant cette tâche.
 */
export function Chiffre({
  libelle,
  valeur,
  sousTexte,
  ton = "neutre",
  vers,
}: {
  libelle: string;
  valeur: string;
  sousTexte?: string;
  ton?: TonChiffre;
  vers?: string;
}): ReactElement {
  const contenu = (
    <dl>
      <dt className="text-sm text-encre-2">{libelle}</dt>
      <dd
        // `xl:text-xl` (revue finale, constat COUVERTURE-25) : entre 1280
        // et 1535 px, six tuiles se partagent la ligne de la vue
        // d'ensemble — un montant réel à 5 chiffres (« 12 345,00 € »,
        // insécable) débordait de sa tuile en `text-2xl`.
        className={`mt-1 whitespace-nowrap font-titre text-2xl font-semibold xl:text-xl 2xl:text-2xl ${CLASSES_TON[ton]}`}
      >
        {valeur}
      </dd>
    </dl>
  );
  if (vers !== undefined) {
    return (
      <Link to={vers} className={CLASSES_TUILE_CLIQUABLE}>
        {contenu}
        {sousTexte !== undefined && <p className="mt-2 text-sm text-encre">{sousTexte}</p>}
      </Link>
    );
  }
  return (
    <div className={CLASSES_TUILE}>
      {contenu}
      {sousTexte !== undefined && <p className="mt-2 text-sm text-encre">{sousTexte}</p>}
    </div>
  );
}
