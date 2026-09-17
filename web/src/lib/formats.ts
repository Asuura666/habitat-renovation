/**
 * Formatage d'affichage (décisions du contrôleur, L2-T7) : aucune règle
 * métier ici, uniquement de la présentation.
 *
 * Les montants viennent de l'API sous forme de chaîne décimale (Pydantic
 * sérialise les `Decimal` en `str`, jamais en `float` — voir
 * `app/modules/api/schemas.py`). `Intl.NumberFormat.format` accepte cette
 * chaîne directement (ECMA-402 : la valeur est convertie en valeur
 * mathématique exacte, `ToIntlMathematicalValue`) : aucune arithmétique en
 * virgule flottante n'est introduite côté front.
 */

const FORMATEUR_MONTANT = new Intl.NumberFormat("fr-FR", {
  style: "currency",
  currency: "EUR",
});

const FORMATEUR_DATE = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  dateStyle: "short",
});

const FORMATEUR_DATE_HEURE = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  dateStyle: "short",
  timeStyle: "short",
});

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
