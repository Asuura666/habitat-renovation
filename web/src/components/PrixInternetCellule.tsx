import type { ReactElement } from "react";

import type { PrixInternet, RecherchePrix } from "../api/ia";
import { formaterJourMois } from "../lib/formats";
import { domaineSource, texteMontantPrixInternet, texteResumeOffres } from "../lib/prixInternet";
import { Bouton } from "../ui";
import { OffresPrixInternet } from "./OffresPrixInternet";

export interface ProprietesInternet {
  prixInternet: PrixInternet | null | undefined;
  recherche: RecherchePrix | undefined;
  lancementEnCours: boolean;
  erreurLancement: string | null;
  onRechercher: () => void;
}

/**
 * Cellule de la colonne « Internet » de la page « Prix à vérifier » (T10b,
 * phase 4 IA, spec §6.4 ; bouton « Chercher sur internet » : spec
 * 2026-10-01 §3) : dernier prix indicatif trouvé sur internet pour une
 * alerte de prix -- toutes les alertes de prix sont couvertes (décision D1),
 * plus seulement « Produit absent de la grille ». Montée à la fois dans le
 * tableau (`<td>`) et dans la carte téléphone (`<dd>`, `pages/Prix.tsx`), la
 * colonne/ligne elle-même n'existant que quand l'IA est active
 * (`ia_active`, décision prise en amont par `Prix.tsx` -- jamais relue ici).
 * Réutilise la logique d'affichage partagée avec l'encart
 * `components/AvisIA.tsx` (`lib/prixInternet.ts`) pour ne jamais dupliquer
 * la garde https-only du lien source.
 *
 * Ordre d'affichage :
 * - recherche en cours (clic en train de partir, ou état du serveur) ->
 *   « Recherche en cours… » ;
 * - `statut === "trouve"` -> montant, taxes, conditionnement, date de
 *   consultation et lien vers la source (domaine seul, `https:` seulement,
 *   `rel="noopener noreferrer"`), puis « Relancer » ;
 * - `statut === "non_verifiable"` -> « introuvable », raison en `title`,
 *   puis « Relancer » ;
 * - un message (refus du clic : IA éteinte, plafond atteint ; ou échec de la
 *   recherche) s'affiche dans la cellule de la rangée, avec « Réessayer » ;
 * - sinon (rien de cherché) -> le bouton « Chercher sur internet ».
 */
export function PrixInternetCellule({
  prixInternet,
  recherche,
  lancementEnCours,
  erreurLancement,
  onRechercher,
}: ProprietesInternet): ReactElement {
  const lienAction = (libelle: string): ReactElement => (
    <button
      type="button"
      onClick={onRechercher}
      className="ml-1 font-medium text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-accent"
    >
      {libelle}
    </button>
  );

  if (lancementEnCours || recherche?.etat === "en_cours") {
    return <span role="status" className="text-encre-2">
        Recherche en cours…
      </span>;
  }

  const message =
    erreurLancement ??
    (recherche?.etat === "echec" ? (recherche.message ?? "La recherche a échoué") : null);
  const resultat = resultatPrixInternet(prixInternet);

  if (resultat !== null) {
    return (
      <>
        {resultat}
        {message !== null && <p role="alert" className="text-xs text-alerte">
            {message}
          </p>}
        {lienAction(message !== null ? "Réessayer" : "Relancer")}
      </>
    );
  }
  if (message !== null) {
    return (
      <>
        <span role="alert" className="text-alerte">
          {message}
        </span>
        {lienAction("Réessayer")}
      </>
    );
  }
  return (
    <Bouton variante="secondaire" className="whitespace-nowrap" onClick={onRechercher}>
      Chercher sur internet
    </Bouton>
  );
}

/** Affichage d'un résultat déjà enregistré (`trouve`, `non_verifiable`) ;
 * `null` s'il n'y en a pas (rien cherché, ou statut sans résultat exploitable
 * comme `echec`, jamais renvoyé en principe). */
function resultatPrixInternet(prixInternet: PrixInternet | null | undefined): ReactElement | null {
  if (prixInternet === undefined || prixInternet === null) {
    return null;
  }

  if (prixInternet.statut === "trouve" && prixInternet.prix !== null) {
    const resume = texteResumeOffres(prixInternet);
    if (resume !== null) {
      return (
        <>
          <span className="font-mono">{resume}</span>
          {` · ${formaterJourMois(prixInternet.consulte_le)}`}
          <OffresPrixInternet offres={prixInternet.offres} />
        </>
      );
    }
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

  return null;
}
