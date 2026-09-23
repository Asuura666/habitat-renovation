import type { ReactElement } from "react";
import { Link } from "react-router";

export interface ElementFilAriane {
  libelle: string;
  vers?: string;
}

/**
 * Fil d'Ariane partagé (remplace la version locale à `BilanFournisseur.tsx`
 * — Task 4 la factorise pour les tâches suivantes). Le dernier élément
 * (sans `vers`) est la page courante, annoncée par `aria-current="page"`.
 */
export function FilAriane({ elements }: { elements: ElementFilAriane[] }): ReactElement {
  return (
    <nav aria-label="Fil d'Ariane" className="text-sm text-encre-2">
      <ol className="flex flex-wrap items-center gap-2">
        {elements.map((element, index) => (
          <li key={`${element.libelle}-${index}`} className="flex items-center gap-2">
            {index > 0 && <span aria-hidden="true">›</span>}
            {element.vers !== undefined ? (
              <Link
                to={element.vers}
                className="font-medium text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-accent"
              >
                {element.libelle}
              </Link>
            ) : (
              <span aria-current="page">{element.libelle}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
