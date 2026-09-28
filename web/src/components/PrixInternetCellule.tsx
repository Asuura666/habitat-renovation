import type { ReactElement } from "react";

import type { PrixInternet } from "../api/ia";
import type { AlerteProduit } from "../api/prix";
import { formaterJourMois, TIRET } from "../lib/formats";
import { domaineSource, texteMontantPrixInternet } from "../lib/prixInternet";

/**
 * Cellule de la colonne « Internet » de la page « Prix à vérifier » (T10b,
 * phase 4 IA, spec §6.4) : dernier prix indicatif trouvé sur internet pour
 * une alerte « Produit absent de la grille » (R22, lot Prix) -- montée à la
 * fois dans le tableau (`<td>`) et dans la carte téléphone (`<dd>`,
 * `pages/Prix.tsx`), la colonne/ligne elle-même n'existant que quand l'IA
 * est active (`ia_active`, décision prise en amont par `Prix.tsx` -- jamais
 * relue ici). Réutilise la logique d'affichage partagée avec l'encart
 * `components/AvisIA.tsx` (`lib/prixInternet.ts`) pour ne jamais dupliquer
 * la garde https-only du lien source.
 *
 * `prixInternet` :
 * - `undefined` (rangée R22 absente de la réponse groupée) ou `null`
 *   (recherchée, sans résultat `trouve`/`non_verifiable` de moins de 30
 *   jours, `ingest/ia_prix.py`) -> « en attente » dans les deux cas (même
 *   texte, même conclusion pour l'utilisateur : rien à montrer pour
 *   l'instant) ;
 * - `statut === "trouve"` -> montant, taxes, conditionnement, date de
 *   consultation et lien vers la source (domaine seul, `https:` seulement,
 *   `rel="noopener noreferrer"`) ;
 * - `statut === "non_verifiable"` -> « introuvable », raison en `title`
 *   (brief T10b -- la cellule reste courte, la raison n'est jamais affichée
 *   en clair).
 *
 * Une rangée sans alerte R22 (autre alerte de prix) affiche un tiret --
 * jamais interrogée par `Prix.tsx` (`prixInternet` y vaut donc toujours
 * `undefined`), mais ce composant vérifie `produit.regles` lui-même plutôt
 * que de déduire ce cas de la seule absence de valeur, qui a une autre
 * signification ci-dessus (« pas encore cherché »).
 */
export function PrixInternetCellule({
  produit,
  prixInternet,
}: {
  produit: AlerteProduit;
  prixInternet: PrixInternet | null | undefined;
}): ReactElement {
  if (!produit.regles.includes("R22")) {
    return <>{TIRET}</>;
  }

  if (prixInternet === undefined || prixInternet === null) {
    return <span className="text-encre-2">en attente</span>;
  }

  if (prixInternet.statut === "trouve" && prixInternet.prix !== null) {
    const sourceDomaine =
      prixInternet.source_url !== null ? domaineSource(prixInternet.source_url) : null;
    return (
      <>
        <span className="font-mono">{texteMontantPrixInternet(prixInternet)}</span>
        {` · ${formaterJourMois(prixInternet.consulte_le)}`}
        {sourceDomaine !== null && prixInternet.source_url !== null && (
          <>
            {" "}
            <a
              href={prixInternet.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {`source (${sourceDomaine})`}
            </a>
          </>
        )}
      </>
    );
  }

  if (prixInternet.statut === "non_verifiable") {
    return (
      <span className="text-encre-2" title={prixInternet.raison ?? undefined}>
        introuvable
      </span>
    );
  }

  // Statut inconnu (`echec`, en principe jamais renvoyé -- même garde que
  // `AvisIA.tsx::LignePrixInternet`) : « en attente » plutôt qu'un texte
  // incohérent.
  return <span className="text-encre-2">en attente</span>;
}
