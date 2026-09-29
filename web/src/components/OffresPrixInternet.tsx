import type { ReactElement } from "react";

import type { PrixInternet } from "../api/ia";
import { formaterMontant } from "../lib/formats";
import { domaineSource, texteMontantPrixInternet } from "../lib/prixInternet";

/**
 * Liste repliable des offres trouvées sur internet (une par site), dans
 * l'ordre reçu du serveur (la moins chère en HT d'abord, jamais retriée
 * ici). Un lien n'existe que si l'adresse est en `https:`
 * (`domaineSource`). Sur téléphone, les éléments sont empilés.
 */
export function OffresPrixInternet({ offres }: { offres: PrixInternet["offres"] }): ReactElement | null {
  if (offres.length === 0) {
    return null;
  }
  return (
    <details className="mt-1 text-sm">
      <summary
        className={
          "flex min-h-[44px] cursor-pointer items-center font-medium text-accent outline-none " +
          "focus-visible:ring-2 focus-visible:ring-accent sm:min-h-0"
        }
      >
        {`Voir les ${offres.length} offres`}
      </summary>
      <ul className="flex flex-col gap-2 pb-1">
        {offres.map((offre, indice) => {
          const domaine = offre.source_url !== null ? domaineSource(offre.source_url) : null;
          return (
            <li key={indice} className="flex flex-col gap-1 sm:flex-row sm:flex-wrap sm:gap-x-2">
              <span className="font-mono">{texteMontantPrixInternet(offre)}</span>
              {offre.taxes === "TTC" && offre.prix_ht !== null && (
                <span className="text-encre-2">{`soit ${formaterMontant(offre.prix_ht)} HT`}</span>
              )}
              {domaine !== null && offre.source_url !== null && (
                <a
                  href={offre.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={
                    "inline-flex min-h-[44px] items-center font-medium text-accent underline outline-none " +
                    "focus-visible:ring-2 focus-visible:ring-accent sm:min-h-0"
                  }
                >
                  {`source (${domaine})`}
                </a>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
