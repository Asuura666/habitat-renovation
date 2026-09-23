import type { ReactElement, ReactNode } from "react";

/**
 * Brique de base de la charte « Registre » (spec §2) : surface blanche,
 * bordure claire, coin arrondi à 14 px (`rounded-carte`). `titre` et
 * `action` sont optionnels — une carte peut être un simple conteneur (ex.
 * liste de lignes) ou porter un titre Fraunces avec une action alignée à
 * droite (ex. bouton d'export, lien « Voir tout »).
 */
export function Carte({
  titre,
  action,
  children,
  className = "",
}: {
  titre?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}): ReactElement {
  return (
    <div className={`rounded-carte border border-bordure bg-surface p-5 ${className}`}>
      {(titre !== undefined || action !== undefined) && (
        <div className="mb-4 flex items-center justify-between gap-4">
          {titre !== undefined && (
            <h2 className="font-titre text-xl font-medium text-encre">{titre}</h2>
          )}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
