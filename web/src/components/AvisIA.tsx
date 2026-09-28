import { type ReactElement } from "react";
import { useQuery } from "@tanstack/react-query";

import { cleAvisIA, lireAvisIA, type PrixInternet } from "../api/ia";
import { formaterJourMois, TIRET } from "../lib/formats";
import { domaineSource, texteMontantPrixInternet } from "../lib/prixInternet";

/**
 * Encart « Avis de l'IA — à titre indicatif » (T7, phase 4 IA, spec §6.4) :
 * explication de l'alerte et prix trouvé sur internet (T6, `GET /api/ia
 * /anomalies/{id}`), montré sous la phrase du problème dans
 * `pages/ProblemeDetail.tsx` -- **seulement** pour un problème de catégorie
 * « prix » (même critère que celui déjà utilisé pour la catégorie
 * affichée, `categorieFiltreProbleme`), monté par une seule ligne.
 *
 * Un bonus, jamais un blocage (brief T7) : pendant le chargement, en cas
 * d'erreur, ou si l'IA n'a encore rien produit pour cette anomalie
 * (`ia_active` faux, ou ni explication ni prix), ce composant ne rend
 * rien -- jamais un message d'attente ni une alerte, à la différence du
 * reste de l'écran « À régler ». Sa propre requête TanStack Query, isolée
 * du reste du panneau (même principe que `SyntheseCommentaires`, T5) :
 * une panne ici n'empêche jamais de traiter le problème.
 *
 * Aucun jargon (brief T7) : ni « OpenCode », ni « modèle », ni
 * « confiance » (le champ `confiance` de `PrixInternetReponse` n'est même
 * pas lu ici), ni aucun identifiant.
 */
export function AvisIA({ anomalieId }: { anomalieId: string }): ReactElement | null {
  const avis = useQuery({
    queryKey: cleAvisIA(anomalieId),
    queryFn: () => lireAvisIA(anomalieId),
  });

  if (avis.isPending || avis.isError || avis.data === undefined) {
    return null;
  }

  const { ia_active: iaActive, explication, prix_internet: prixInternet } = avis.data;
  if (!iaActive || (explication === null && prixInternet === null)) {
    return null;
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-bordure bg-fond p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-encre-2">
        Avis de l'IA — à titre indicatif
      </p>
      {explication !== null && <p className="text-sm text-encre">{explication.texte}</p>}
      {prixInternet !== null && <LignePrixInternet prixInternet={prixInternet} />}
    </div>
  );
}

function LignePrixInternet({ prixInternet }: { prixInternet: PrixInternet }): ReactElement | null {
  if (prixInternet.statut === "trouve" && prixInternet.prix !== null) {
    const sourceDomaine =
      prixInternet.source_url !== null ? domaineSource(prixInternet.source_url) : null;
    return (
      <p className="text-sm text-encre">
        {`Prix trouvé sur internet : ${texteMontantPrixInternet(prixInternet)} — consulté le ${formaterJourMois(prixInternet.consulte_le)}`}
        {sourceDomaine !== null && prixInternet.source_url !== null && (
          <>
            {" "}
            <a
              href={prixInternet.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              {`Voir la source (${sourceDomaine})`}
            </a>
          </>
        )}
      </p>
    );
  }

  if (prixInternet.statut === "non_verifiable") {
    return (
      <p className="text-sm text-encre-2">
        {`Prix introuvable sur internet : ${prixInternet.raison ?? TIRET}`}
      </p>
    );
  }

  // Statut inconnu (`echec`, en principe jamais renvoyé par `avis_ia_
  // anomalie` -- une ligne `echec` n'est jamais montrée, `ia_prix.py`) :
  // rien plutôt qu'un texte incohérent, même discipline que le reste de ce
  // composant (l'avis est un bonus, jamais un blocage).
  return null;
}
