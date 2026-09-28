import type { ReactElement } from "react";

/**
 * Pastille « À compléter » (Task 6, avenant du 27/09/2026, spec §2.6) : un
 * chantier créé automatiquement (nom lu ou légende Telegram sans
 * ressemblance connue), sans agence ni client renseignés tant qu'un admin
 * n'a pas enregistré sa fiche (`modifier_chantier` le fait sortir de cet
 * état). Couleur écart (même teinte que `PastilleEtat`, catégories
 * « prix »/« quantites »/« a_voir ») — pas de jeton Tailwind dédié pour ce
 * fond clair, même choix assumé que `PastilleEtat`. Toujours doublée du
 * libellé, jamais la couleur seule (contrainte d'accessibilité).
 */
export function PastilleACompleter({ className = "" }: { className?: string }): ReactElement {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full bg-[#fbe9c6] px-2.5 py-1 text-xs font-medium text-[#7a4a00] ${className}`}
    >
      À compléter
    </span>
  );
}
