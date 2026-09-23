/**
 * Liens entre écrans (revue finale de la refonte du front, constats
 * LIENS-5, LIENS-12 et LIENS-13) : une seule fonction par destination, qui
 * reporte le contexte utile (mois affiché, livraison précise dans une
 * facture) plutôt qu'une URL recodée à la main dans chaque écran — avant ce
 * correctif, la même destination était construite de trois façons
 * différentes, et certaines perdaient le mois ou l'ancre en route.
 *
 * Convention d'URL du mois : `?mois=AAAA-MM` partout (voir `lireMois`,
 * `lib/formats.ts`, qui accepte aussi l'ancien `AAAA-MM-01` des liens déjà
 * envoyés), converti en `AAAA-MM-01` au seul moment de l'appel à l'API.
 */

/** Nom affiché d'un chantier que la lecture n'a pas su rattacher à la
 * liste des chantiers — même libellé sur tous les écrans. */
export const CHANTIER_A_RATTACHER = "Chantier à rattacher";

/** Destination d'un chantier non rattaché : l'écran « À régler » filtré
 * sur les chantiers à rattacher (seule action possible). */
export const LIEN_CHANTIERS_A_RATTACHER = "/a-regler?filtre=rattacher";

function avecMois(chemin: string, mois: string | undefined): string {
  return mois === undefined ? chemin : `${chemin}?${new URLSearchParams({ mois }).toString()}`;
}

/** Fiche d'un chantier, au mois affiché par l'écran d'origine (`AAAA-MM`)
 * quand il y en a un ; « à rattacher » quand le chantier est inconnu. */
export function lienChantier(chantierId: string | null, mois?: string): string {
  return chantierId === null ? LIEN_CHANTIERS_A_RATTACHER : avecMois(`/chantiers/${chantierId}`, mois);
}

/** Facture, ouverte directement sur la livraison concernée quand elle est
 * connue (ancre posée par `FactureDetail`, qui y fait défiler la page). */
export function lienFacture(factureId: string, livraisonId?: string | null): string {
  return livraisonId === undefined || livraisonId === null
    ? `/documents/${factureId}`
    : `/documents/${factureId}#bloc-${livraisonId}`;
}

/** Page d'un bon de livraison (ou d'enlèvement). */
export function lienBon(documentId: string): string {
  return `/bl/${documentId}`;
}

/** Documents d'un chantier, au mois affiché quand il y en a un. */
export function lienDocumentsChantier(chantierId: string, mois?: string): string {
  const parametres = new URLSearchParams({ chantier: chantierId });
  if (mois !== undefined) {
    parametres.set("mois", mois);
  }
  return `/documents?${parametres.toString()}`;
}
