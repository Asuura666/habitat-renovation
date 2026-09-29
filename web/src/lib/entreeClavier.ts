import type { KeyboardEvent } from "react";

/** Ordinateur = souris ou pavé tactile (pointeur fin qui survole). Un
 * téléphone ou une tablette n'est jamais concerné : Entrée y passe à la
 * ligne et le bouton reste le seul moyen d'enregistrer. */
function surOrdinateur(): boolean {
  return window.matchMedia?.("(hover: hover) and (pointer: fine)").matches ?? false;
}

/** Touche Entrée dans un champ de commentaire (demande d'Ilane du
 * 29/09/2026) : sur ordinateur, Entrée enregistre (`enregistrer`, qui
 * vérifie lui-même que l'envoi est permis) ; Maj+Entrée ou Alt+Entrée passe
 * à la ligne. Alt+Entrée n'insère rien de lui-même dans un `<textarea>` : le
 * saut de ligne est inséré à la place du curseur (`changerTexte`). Une
 * saisie en cours de composition (accents composés, clavier asiatique)
 * n'est jamais interrompue. */
export function gererEntreeCommentaire(
  evenement: KeyboardEvent<HTMLTextAreaElement>,
  enregistrer: () => void,
  changerTexte: (texte: string) => void,
): void {
  if (evenement.key !== "Enter" || evenement.nativeEvent.isComposing || !surOrdinateur()) {
    return;
  }
  if (evenement.shiftKey) {
    return;
  }
  evenement.preventDefault();
  if (evenement.altKey) {
    const champ = evenement.currentTarget;
    const debut = champ.selectionStart;
    const texte = champ.value.slice(0, debut) + "\n" + champ.value.slice(champ.selectionEnd);
    // `maxLength` vaut -1 quand le champ n'a pas de limite.
    if (champ.maxLength >= 0 && texte.length > champ.maxLength) {
      return;
    }
    changerTexte(texte);
    requestAnimationFrame(() => champ.setSelectionRange(debut + 1, debut + 1));
    return;
  }
  enregistrer();
}
