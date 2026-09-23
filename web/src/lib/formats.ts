/**
 * Formatage d'affichage (décisions du contrôleur, L2-T7) : aucune règle
 * métier ici, uniquement de la présentation.
 *
 * Les montants viennent de l'API sous forme de chaîne décimale (Pydantic
 * sérialise les `Decimal` en `str`, jamais en `float` — voir
 * `app/modules/api/schemas.py`). Cette chaîne décimale est acceptée par
 * `Intl.NumberFormat.format` depuis la spécification « Intl.NumberFormat
 * v3 » (navigateurs récents) : aucune arithmétique en virgule flottante
 * n'est introduite côté front pour la formater (correction de revue L2-T7,
 * tour 1/5 : la mention précédente de ce commentaire sur-évaluait la portée
 * de la garantie ECMA-402).
 */

const FORMATEUR_MONTANT = new Intl.NumberFormat("fr-FR", {
  style: "currency",
  currency: "EUR",
});

/** `maximumFractionDigits: 3` (une quantité de rapprochement peut porter
 * jusqu'à 3 décimales, ex. un ratio ou une conversion d'unité),
 * `minimumFractionDigits: 0` : une quantité s'écrit « 100 », « 2,5 » ou
 * « 0,75 », jamais « 100,00 » — contrairement à un montant, qui affiche
 * toujours deux décimales (fix round 1, revue L4-T10, Ruling R18). */
const FORMATEUR_QUANTITE = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 3,
  minimumFractionDigits: 0,
});

const FORMATEUR_POURCENTAGE = new Intl.NumberFormat("fr-FR", { style: "percent" });

const FORMATEUR_DATE = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  dateStyle: "short",
});

const FORMATEUR_DATE_HEURE = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  dateStyle: "short",
  timeStyle: "short",
});

/** Année et mois seuls, en heure de Paris (`formatToParts`, jamais un
 * gabarit de chaîne dépendant de la locale de l'utilisateur) — utilisé par
 * `DocumentsListe.tsx` (tour de correction 1, Task 8) pour comparer le
 * filtre `?mois=` (`"AAAA-MM"`, valeur d'un `<input type="month">`) à un
 * horodatage de dépôt (`cree_le`), jamais par simple troncature de la
 * chaîne ISO (en UTC) : un dépôt entre minuit et 2 h, heure de Paris,
 * tombe sinon dans le mois suivant — même convention que le mois d'un bloc
 * de facture (L5-D4, `ingest/bilan.py`), qui préfère `date_doc` (une date
 * simple, sans fuseau) et ne retombe sur `created_at` converti qu'à
 * défaut. */
const FORMATEUR_MOIS_PARIS = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  year: "numeric",
  month: "2-digit",
});

export function moisParis(horodatageIso: string): string {
  const parties = FORMATEUR_MOIS_PARIS.formatToParts(new Date(horodatageIso));
  const annee = parties.find((partie) => partie.type === "year")?.value ?? "";
  const mois = parties.find((partie) => partie.type === "month")?.value ?? "";
  return `${annee}-${mois}`;
}

export const TIRET = "—";

/** `valeur` est la chaîne décimale renvoyée par l'API ; `null` (champ
 * absent, ex. facture pas encore reconnue) affiche un tiret. */
export function formaterMontant(valeur: string | null): string {
  if (valeur === null) {
    return TIRET;
  }
  // `as unknown as number` : le paramètre est en réalité une chaîne
  // numérique (voir le commentaire de tête de fichier) ; `Intl.NumberFormat`
  // l'accepte à l'exécution, mais les types de la bibliothèque standard
  // n'exposent cette surcharge que pour un littéral de gabarit `` `${number}` ``,
  // jamais pour un `string` général comme celui renvoyé par l'API.
  return FORMATEUR_MONTANT.format(valeur as unknown as number);
}

/** `valeur` est la chaîne décimale renvoyée par l'API pour une quantité,
 * un écart de quantité ou un ratio (`rules.rules.R*` écrivent `str(<Decimal>)`
 * — même origine que `formaterMontant`, même technique : aucune arithmétique
 * en virgule flottante n'est introduite ici, `Intl.NumberFormat.format`
 * accepte directement la chaîne décimale) ; `null` affiche un tiret.
 *
 * `valeur` ne doit **jamais** être le tiret cadratin (`TIRET`, "—") que
 * certaines règles posent dans `detail` pour une quantité absente (ex.
 * `R05`/`R06` sans quantité) : `Intl.NumberFormat.format("—")` ne lève pas
 * d'exception mais rend la chaîne « NaN », un plantage silencieux moins
 * visible que celui déjà corrigé sur les dates (fix round 1, revue L4-T10,
 * Ruling R18) mais tout aussi faux à l'affichage. L'appelant (`lib/regles
 * .ts`) doit donc filtrer ce cas **avant** d'appeler cette fonction, comme
 * il le fait déjà pour `formaterDate`/`formaterMontant` — jamais ici, pour
 * rester cohérent avec le contrat `string | null` des fonctions voisines. */
export function formaterQuantite(valeur: string | null): string {
  if (valeur === null) {
    return TIRET;
  }
  return FORMATEUR_QUANTITE.format(valeur as unknown as number);
}

/** `valeur` est une chaîne décimale entre 0 et 1 (ex. `"0.80"` : confiance
 * ou seuil OCR, `verifier_bl`) ; `null` affiche un tiret. Même technique que
 * `formaterMontant` (fix round 1, revue L3-T9) : `Intl.NumberFormat` avec
 * `style: "percent"` applique lui-même le facteur 100 sur la représentation
 * décimale — aucune arithmétique en virgule flottante n'est introduite ici. */
export function formaterPourcentage(valeur: string | null): string {
  if (valeur === null) {
    return TIRET;
  }
  return FORMATEUR_POURCENTAGE.format(valeur as unknown as number);
}

/** Date seule (`date_doc`, `date_bl`), au format `JJ/MM/AAAA`. */
export function formaterDate(valeur: string | null): string {
  if (valeur === null) {
    return TIRET;
  }
  return FORMATEUR_DATE.format(new Date(valeur));
}

/** Horodatage complet (`cree_le`, `confirme_le`), au format
 * `JJ/MM/AAAA HH:MM`, fuseau Europe/Paris. */
export function formaterDateHeure(valeur: string | null): string {
  if (valeur === null) {
    return TIRET;
  }
  return FORMATEUR_DATE_HEURE.format(new Date(valeur));
}
