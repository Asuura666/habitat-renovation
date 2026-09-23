import type { ReactElement } from "react";

export interface OptionFiltre {
  valeur: string;
  libelle: string;
  compte?: number;
}

/**
 * Groupe de filtres en pastilles (maquette `ARegler`) : vrais `<button>`
 * avec `aria-pressed`, jamais des cases à cocher déguisées. `compte`,
 * quand fourni, s'affiche après le libellé (`Urgents · 5`).
 */
export function Filtres({
  options,
  valeur,
  onChange,
}: {
  options: OptionFiltre[];
  valeur: string;
  onChange: (valeur: string) => void;
}): ReactElement {
  return (
    <div role="group" aria-label="Filtrer" className="flex flex-wrap gap-2">
      {options.map((option) => {
        const actif = option.valeur === valeur;
        return (
          <button
            key={option.valeur}
            type="button"
            aria-pressed={actif}
            onClick={() => onChange(option.valeur)}
            className={`min-h-[44px] rounded-full border px-4 py-2 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 ${
              actif
                ? "border-accent bg-accent text-white"
                : "border-bordure bg-surface text-encre hover:bg-fond"
            }`}
          >
            {option.libelle}
            {option.compte !== undefined && ` · ${option.compte}`}
          </button>
        );
      })}
    </div>
  );
}
