# Prix internet : jusqu'à cinq sources par produit — conception

Date : 29/09/2026. Demande d'Ilane (même jour), conception validée en
conversation. Complète le §6 de
`docs/superpowers/specs/2026-09-27-phase-4-ia-design.md` (prix trouvé sur
internet), sans rien changer à ce qui déclenche une recherche (§6.1 : alertes
R22 ouvertes, produit sans dernier prix facturé, cache de 30 jours, plafond
du jour).

## 1. But

Pour un produit absent de la grille, l'IA rapporte **jusqu'à cinq offres**
de sites différents au lieu d'une seule. Chaque offre passe les mêmes
contrôles qu'aujourd'hui. La page Prix montre **le prix le plus bas**,
**l'écart** entre le moins cher et le plus cher, et **les liens** vers les
sources.

Critère de réussite : sur les 20 produits Unikalo de l'essai du 29/09 (11
trouvés avec une source), les produits trouvés affichent en général
plusieurs sources vérifiées, sans aucun prix inventé (chaque offre gardée a
sa page réellement ouverte et son prix présent dans cette page).

## 2. Décisions

| Sujet | Décision |
| --- | --- |
| Nombre d'offres | 1 à 5, de sites différents ; au-delà de 5 offres vérifiées, les 5 premières (ordre de l'IA) |
| Offre en échec | écartée avec sa raison, jamais l'ensemble ; « trouvé » s'il reste au moins une offre |
| Comparaison HT/TTC | **tout ramené en HT** (choix d'Ilane) : TTC ÷ 1,20 (TVA 20 %) ; une offre « inconnu » reste listée mais ne compte ni dans le plus bas ni dans l'écart |
| Stockage | une colonne `offres` (JSONB) dans `prix_internet` ; les colonnes actuelles portent l'offre la moins chère (en HT) |
| Anciennes recherches | reprises par la migration comme une offre unique |

Approches écartées : une table `prix_internet_offre` (plus de code pour des
offres jamais lues sans leur recherche) ; une ligne par offre dans
`prix_internet` (casse « une ligne par recherche », dont dépend le cache).

## 3. Réponse de l'IA (`SCHEMA_PRIX_INTERNET`, remplacé)

```json
{"statut": "trouve | prix_non_verifiable",
 "raison": "… (si non vérifiable)",
 "offres": [
   {"produit_trouve": "…", "prix": 12.34, "devise": "EUR",
    "taxes": "HT | TTC | inconnu", "unite": "…", "conditionnement": "…",
    "source_url": "https://…", "confiance": "faible | moyenne | elevee"}
 ]}
```

Consignes (texte envoyé `_texte_prix` et agent `habitat-prix`) : chercher
jusqu'à cinq offres **de sites différents**, pour **le même produit au même
format**, avec un prix **pour le même conditionnement** (jamais un prix au
mètre à côté d'un prix à la pièce) ; ouvrir chaque page avec `webfetch` ;
au plus 5 recherches et 6 pages ; une seule offre vaut mieux qu'une offre
douteuse. Agent : `steps` 8 → 14 ; délai de l'appel 240 → 300 s.

## 4. Contrôles (`extract/reponses_ia.py`, pur)

- Garde 1 (globale) inchangée : `prix_non_verifiable` → non vérifiable,
  raison gardée.
- Gardes 2 à 4 **par offre**, dans l'ordre actuel : offre complète (prix >
  0, EUR, `https://`, produit, confiance), page réellement ouverte, prix
  présent dans le texte de la page. Une offre en échec est écartée ; deux
  offres sur la même page (à la barre oblique finale et au fragment près,
  même règle que la garde 3) : seule la première compte.
- `PrixInternetLu` garde ses champs actuels, qui décrivent **l'offre la plus
  basse en HT** (à défaut d'offre HT/TTC connue : la première gardée), et
  gagne `offres: tuple[OffreLue, ...]`, triées par prix HT croissant, les
  « inconnu » à la fin. `OffreLue` : les champs d'une offre + `prix_ht`
  (`Decimal | None`).
- `prix_ht(prix, taxes)` : `HT` → prix ; `TTC` → prix ÷ 1,20 arrondi au
  centime ; sinon `None`.
- Aucune offre gardée → non vérifiable, raison = celle de la première offre
  écartée (« source non ouverte », « prix absent de la page », …) ou
  « aucune offre » si la liste est vide.
- `controles_prix_internet` (Laboratoire IA) : le contrôle du statut, puis
  une ligne par offre (« Offre 2 — exemple.fr » : gardée, ou écartée et
  pourquoi). Une seule implémentation des gardes, partagée avec
  `lire_prix_internet`.

## 5. Données (migration `0015`)

- `prix_internet.offres` : JSONB, non nul, défaut `[]` ; chaque offre :
  `prix` (texte décimal), `devise`, `taxes` (`HT`/`TTC`/`null`), `unite`,
  `conditionnement`, `produit_trouve`, `source_url`, `confiance`.
- Reprise : chaque ligne `trouve` existante reçoit `offres` = une offre
  construite depuis ses colonnes actuelles. Aucune autre donnée modifiée ;
  `downgrade` supprime la colonne.
- Écriture (`ingest/ia_prix.py`) : colonnes actuelles = offre la plus basse,
  `offres` = toutes les offres gardées.

## 6. API (`/api/ia/…`, admin)

`PrixInternetReponse` garde ses champs (offre la plus basse) et ajoute
`offres` (liste : champs d'une offre + `prix_ht`), `prix_ht_min`,
`prix_ht_max` (`null` si aucune offre HT/TTC connue) et `nb_sources`.
Routes inchangées ; types front régénérés.

## 7. Écrans

- **Page Prix, colonne « Internet »** (`PrixInternetCellule`) : « dès 11,59 €
  HT · 3 sources » ; « jusqu'à 13,91 € HT » si l'écart existe ; liste
  dépliable des offres (prix d'origine avec HT/TTC, prix HT, conditionnement,
  lien `https:` vers le site). Une seule source : affichage actuel.
- **Encart « Avis de l'IA »** (`AvisIA.tsx`, détail d'un problème) : même
  liste.
- **Laboratoire IA** : les offres gardées et, dans ④, le contrôle de chaque
  offre.
- Téléphone : liste empilée, cibles de 44 px, liens `rel="noopener
  noreferrer"`.

## 8. Commande `essai-prix-internet`

Le CSV de sortie garde ses colonnes (offre la plus basse) et ajoute
`nb_sources`, `prix_ht_min`, `prix_ht_max`.

## 9. Tests

- Purs : chaque garde par offre (positif/négatif), offre écartée sans
  écarter les autres, doublon de page, plus de cinq offres, conversion HT,
  ordre, « inconnu » hors du plus bas, cohérence `lire_`/`controles_`.
- Base : migration (reprise d'une ligne existante, `downgrade`), écriture des
  offres, cache inchangé.
- API et front (tests texte du dépôt), frontières de modules.
- Essai réel sur les 20 produits une fois la démo mise à jour.

## 10. Hors périmètre

Aucun changement du déclenchement (§6.1), du cache, du plafond ni des
contrôles de prix R07-R09 (toujours éteints). Pas d'alerte automatique sur
l'écart entre prix facturé et prix internet.
