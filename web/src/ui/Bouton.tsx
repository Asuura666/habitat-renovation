import type { ButtonHTMLAttributes, PropsWithChildren, ReactElement } from "react";

export type VarianteBouton = "principal" | "secondaire";

const CLASSES_VARIANTE: Record<VarianteBouton, string> = {
  principal: "border-accent bg-accent text-white hover:bg-accent-fonce",
  secondaire: "border-bordure bg-surface text-encre hover:bg-fond",
};

/**
 * Bouton de la charte (spec §7) : vrai `<button>`, jamais un `<div>`
 * cliquable — cible tactile ≥ 44 px, anneau de focus visible. `type="button"`
 * par défaut (un formulaire qui a besoin de `type="submit"` le passe dans
 * `props`, qui l'emporte).
 */
export function Bouton({
  variante = "principal",
  className = "",
  ...props
}: PropsWithChildren<
  { variante?: VarianteBouton } & ButtonHTMLAttributes<HTMLButtonElement>
>): ReactElement {
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex min-h-[44px] items-center justify-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 ${CLASSES_VARIANTE[variante]} ${className}`}
    />
  );
}
