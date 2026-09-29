/**
 * Logique d'affichage du prix trouvé sur internet, partagée (T10b, phase 4
 * IA, spec §6.4) entre l'encart `components/AvisIA.tsx` (T7, détail d'un
 * problème) et la colonne « Internet » de la page « Prix à vérifier »
 * (`components/PrixInternetCellule.tsx`, T10b) -- montant/HT-TTC/
 * conditionnement et calcul du domaine d'une source, pour ne jamais laisser
 * deux implémentations de la garde https-only diverger (extrait d'ici, brief
 * T10b : « réutilise sa logique d'affichage ... en l'extrayant dans une
 * petite fonction/composant partagé plutôt qu'en la recopiant »).
 */

import type { PrixInternet } from "../api/ia";
import { formaterMontant } from "./formats";

/** Les seuls champs utiles à l'affichage du montant -- aussi fournis par le
 * Laboratoire IA (`pages/LaboIA.tsx`), qui montre le résultat d'un essai
 * exactement comme la page « Prix à vérifier ». */
export type MontantPrixInternet = Pick<PrixInternet, "prix" | "taxes" | "conditionnement" | "unite">;

/** Nom de domaine d'une adresse (« exemple.invalid », jamais l'adresse
 * complète -- rester court à l'écran), `www.` retiré -- `null` si l'adresse
 * ne doit **pas** devenir un lien cliquable : non analysable, protocole
 * autre que `https:` (`new URL("javascript:...")`/`"data:..."` ne lève pas,
 * elles rendent juste un `hostname` vide -- rendre le lien tout de même
 * l'aurait rendu cliquable), ou hôte vide. `source_url` vient d'une réponse
 * de l'IA : cette fonction se défend elle-même, jamais uniquement sur la
 * garde déjà faite côté serveur (`extract/reponses_ia.py`, qui ne garde que
 * des adresses `https://` vérifiées pour le statut `trouve` -- une défense
 * en profondeur, pas une confiance aveugle en amont). */
export function domaineSource(url: string): string | null {
  let analysee: URL;
  try {
    analysee = new URL(url);
  } catch {
    return null;
  }
  if (analysee.protocol !== "https:" || analysee.hostname === "") {
    return null;
  }
  return analysee.hostname.replace(/^www\./, "");
}

/** Unité et conditionnement en un seul groupe entre parenthèses -- le
 * conditionnement (« seau de 15 L », « boîte de 10 ») est déjà la
 * description la plus parlante pour un non-technicien ; l'unité seule
 * (« u », « L ») ne complète l'affichage que lorsque le conditionnement
 * manque, jamais les deux à la fois (redondant, l'un contenant souvent déjà
 * l'autre). Chaîne vide si aucun des deux n'est présent -- jamais une
 * parenthèse vide affichée. */
function parentheseConditionnement(prixInternet: MontantPrixInternet): string {
  const partie = prixInternet.conditionnement ?? prixInternet.unite;
  return partie !== null && partie !== "" ? ` (${partie})` : "";
}

/** Montant, HT/TTC et conditionnement (sinon unité) d'un prix trouvé sur
 * internet, en un seul texte (« 12,34 € TTC (seau 15 L) ») -- à l'appelant
 * de vérifier `statut === "trouve" && prix !== null` avant d'appeler cette
 * fonction (jamais revérifié ici, comme `formaterMontant` : un tiret plutôt
 * qu'une exception si `prix` est tout de même `null`). */
export function texteMontantPrixInternet(prixInternet: MontantPrixInternet): string {
  const taxes = prixInternet.taxes !== null ? ` ${prixInternet.taxes}` : "";
  return `${formaterMontant(prixInternet.prix)}${taxes}${parentheseConditionnement(prixInternet)}`;
}
