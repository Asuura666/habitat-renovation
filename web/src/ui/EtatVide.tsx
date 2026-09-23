import type { ReactElement } from "react";

/** État vide générique (liste sans résultat, filtre trop strict…) — texte
 * en français courant, jamais une case grisée sans explication. */
export function EtatVide({ message }: { message: string }): ReactElement {
  return (
    <p
      role="status"
      className="rounded-carte border border-dashed border-bordure bg-surface p-6 text-center text-sm text-encre-2"
    >
      {message}
    </p>
  );
}
