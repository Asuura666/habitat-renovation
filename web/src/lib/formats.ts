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

/** Séparateur des milliers produit par `Intl` en français : l'espace fine
 * insécable (U+202F), presque invisible dans les grands chiffres en
 * Fraunces (« 1310,00 € » à l'écran). Remplacée à l'affichage par l'espace
 * insécable ordinaire (U+00A0), aussi insécable mais bien visible (revue
 * finale de la refonte du front, constats ECRAN-7/COUVERTURE-25) — pure
 * présentation, aucun calcul. */
const ESPACE_FINE_INSECABLE = /\u202f/g;
const ESPACE_INSECABLE = "\u00a0";

function espacesVisibles(texte: string): string {
  return texte.replace(ESPACE_FINE_INSECABLE, ESPACE_INSECABLE);
}

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
  return espacesVisibles(FORMATEUR_MONTANT.format(valeur as unknown as number));
}

/** `true` quand un montant renvoyé par l'API vaut zéro (« 0 », « 0.00 »,
 * « -0.00 ») — sert seulement à choisir une couleur neutre plutôt qu'une
 * couleur d'alerte pour un montant nul (revue finale, constats
 * ECRAN-15/TELEPHONE-11) : une comparaison de chaîne, jamais un calcul. */
export function estMontantNul(valeur: string | null): boolean {
  return valeur !== null && /^-?0+(?:\.0+)?$/.test(valeur);
}

/** Mention « dont X € sur des factures à vérifier » à côté de « Facturé »
 * (décision d'Ilane du 29/09/2026) : une facture dont la somme est
 * incohérente reste comptée dans « Facturé » tant qu'elle n'est pas
 * corrigée. Le montant vient du serveur (`facture_a_verifier`) ; `undefined`
 * quand il est nul, pour ne rien afficher. */
export function mentionFactureAVerifier(valeur: string | null | undefined): string | undefined {
  if (valeur === null || valeur === undefined || estMontantNul(valeur)) {
    return undefined;
  }
  return `dont ${formaterMontant(valeur)} sur des factures à vérifier`;
}

/** Pourcentage déjà exprimé en points par le serveur (`"30.56"` =
 * 30,56 %), au format français et arrondi au dixième (« 30,6 % », maquette
 * `ARegler`) — revue finale, constats ECRAN-1/COUVERTURE-5 : la chaîne brute
 * s'affichait « 30.56 % ». Même technique que `formaterQuantite` (chaîne
 * décimale passée telle quelle à `Intl`, aucune arithmétique). */
const FORMATEUR_POINTS = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 0,
});

export function formaterPoints(valeur: string): string {
  return `${espacesVisibles(FORMATEUR_POINTS.format(valeur as unknown as number))}${ESPACE_INSECABLE}%`;
}

/** Mois d'une URL (`?mois=`), au format `AAAA-MM` (convention unique de
 * l'application depuis la revue finale, constat LIENS-5) — accepte aussi
 * `AAAA-MM-01`, la forme des anciens liens déjà envoyés. Toute autre valeur
 * (vide, `2026-13`, texte) donne `undefined` : jamais une date invalide
 * transmise à `Intl.DateTimeFormat`, qui lève et laisse un écran blanc. */
const REGEX_MOIS_URL = /^(\d{4})-(0[1-9]|1[0-2])(?:-01)?$/;

export function lireMois(valeur: string | null | undefined): string | undefined {
  if (valeur === null || valeur === undefined) {
    return undefined;
  }
  const correspondance = REGEX_MOIS_URL.exec(valeur);
  return correspondance === null ? undefined : `${correspondance[1]}-${correspondance[2]}`;
}

/** Mois courant au format `AAAA-MM`, en heure de Paris (jamais l'UTC : entre
 * minuit et 2 h à Paris, l'UTC est encore la veille, voire le mois d'avant). */
export function moisCourantParis(): string {
  const parties = FORMATEUR_MOIS_PARIS.formatToParts(new Date());
  const annee = parties.find((partie) => partie.type === "year")?.value ?? "0000";
  const mois = parties.find((partie) => partie.type === "month")?.value ?? "01";
  return `${annee}-${mois}`;
}

/** Mois `AAAA-MM` -> premier jour `AAAA-MM-01`, la forme attendue par
 * l'API (`?mois=` du bilan et du tableau de bord). */
export function moisApi(mois: string): string {
  return `${mois}-01`;
}

const FORMATEUR_LIBELLE_MOIS = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  month: "long",
  year: "numeric",
});

/** « septembre 2026 » à partir d'un mois `AAAA-MM` (ou `AAAA-MM-01`) ;
 * repli sur la valeur brute plutôt qu'une exception si elle n'est pas
 * lisible. */
export function libelleMois(mois: string): string {
  const lu = lireMois(mois);
  if (lu === undefined) {
    return mois;
  }
  return FORMATEUR_LIBELLE_MOIS.format(new Date(`${lu}-01T12:00:00Z`));
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
 * Ruling R18) mais tout aussi faux à l'affichage. L'appelant (`ui/libelles
 * .ts`) doit donc filtrer ce cas **avant** d'appeler cette fonction, comme
 * il le fait déjà pour `formaterDate`/`formaterMontant` — jamais ici, pour
 * rester cohérent avec le contrat `string | null` des fonctions voisines. */
export function formaterQuantite(valeur: string | null): string {
  if (valeur === null) {
    return TIRET;
  }
  return espacesVisibles(FORMATEUR_QUANTITE.format(valeur as unknown as number));
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

const FORMATEUR_JOUR_MOIS_COURT = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  day: "2-digit",
  month: "2-digit",
});

/** Jour et mois seuls, sans année (« 28/09 ») — carte « Commentaires de la
 * semaine » (T5, phase 4 IA, `components/SyntheseCommentaires.tsx`) :
 * semaine d'une action « encore à faire » (« semaine du 14/09 ») et date à
 * laquelle une action a été cochée (« faite par Léa le 28/09 »), jamais
 * l'année complète (`formaterDate`) qui alourdirait ces mentions courtes.
 * Accepte une date seule (`AAAA-MM-JJ`, `ActionSyntheseReponse.
 * semaine_debut`) ou un horodatage complet (`faite_le`) : `new Date` lit les
 * deux formats ; `null` affiche un tiret. */
export function formaterJourMois(valeur: string | null): string {
  if (valeur === null) {
    return TIRET;
  }
  return FORMATEUR_JOUR_MOIS_COURT.format(new Date(valeur));
}

const FORMATEUR_JOUR_SEUL = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  day: "numeric",
});

const FORMATEUR_JOUR_MOIS_LONG = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "Europe/Paris",
  day: "numeric",
  month: "long",
});

/** Période d'une synthèse hebdomadaire des commentaires (T5, phase 4 IA) :
 * « du 21 au 27 septembre » quand les deux dates sont du même mois, « du 28
 * septembre au 4 octobre » quand la semaine civile est à cheval sur deux
 * mois (le mois n'est alors précisé qu'une fois de trop, jamais une fois de
 * trop peu). `semaineDebut`/`semaineFin` : dates seules `AAAA-MM-JJ`
 * (`SyntheseReponse`) ; `getUTCMonth`/`getUTCFullYear` comparent les
 * composants de la date telle qu'écrite (minuit UTC pour une chaîne
 * `AAAA-MM-JJ`), jamais convertis vers un fuseau -- une comparaison de
 * calendrier, pas d'affichage. */
export function periodeSemaine(semaineDebut: string, semaineFin: string): string {
  const debut = new Date(semaineDebut);
  const fin = new Date(semaineFin);
  const memeMois =
    debut.getUTCFullYear() === fin.getUTCFullYear() && debut.getUTCMonth() === fin.getUTCMonth();
  const debutFormate = memeMois
    ? FORMATEUR_JOUR_SEUL.format(debut)
    : FORMATEUR_JOUR_MOIS_LONG.format(debut);
  return `du ${debutFormate} au ${FORMATEUR_JOUR_MOIS_LONG.format(fin)}`;
}
