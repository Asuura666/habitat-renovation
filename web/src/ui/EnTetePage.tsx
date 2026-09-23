import type { ReactElement, ReactNode } from "react";

/**
 * En-tête d'écran (spec §2) : surtitre discret optionnel (ex. « Bonjour
 * Charly · mis à jour ce matin à 7 h 05 »), titre en Fraunces, actions
 * alignées à droite (boutons, filtres).
 */
export function EnTetePage({
  surtitre,
  titre,
  actions,
}: {
  surtitre?: string;
  titre: string;
  actions?: ReactNode;
}): ReactElement {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div>
        {surtitre !== undefined && <p className="text-sm text-encre-2">{surtitre}</p>}
        <h1 className="font-titre text-3xl font-medium text-encre">{titre}</h1>
      </div>
      {actions !== undefined && (
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      )}
    </header>
  );
}
