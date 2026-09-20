# Recette du lot 5 (Restitution) — Contrôle BL & factures

Branche `lot-5-restitution`, créée depuis `main` à `c9f51a5`. Les tâches
techniques L5-T1 à L5-T11 sont commitées jusqu'à `d770654`; L5-T12 est
constituée par la présente livraison documentaire. Le lot
est **techniquement terminé sur la branche**, mais la revue finale de
l'ensemble `main..lot-5-restitution` et la fusion dans `main` n'ont pas encore
eu lieu. Aucun push ni déploiement n'a été fait.

Aucune donnée client n'est reproduite ici : ni montant, ni nom, ni numéro de
client ou de document. Les seuls résultats d'août repris sont des comptes déjà
documentés au lot 4. Les vérifications visuelles du lot 5 ont utilisé des
données inventées.

## À lire d'abord (Ilane)

- **Livré sur la branche** : bilan à trois niveaux et vue inverse, export CSV,
  navigation jusqu'aux documents et anomalies, écran Chantiers & fournisseurs,
  journal consultable, réglage des neuf seuils et synchronisation Google Drive
  par commande planifiable. Détail tâche par tâche en §1.
- **État Git** : avant le commit documentaire de L5-T12,
  `lot-5-restitution` pointe sur `d770654`, soit 26 commits au-dessus de
  `main` (`c9f51a5`). Rien n'est fusionné, poussé ni déployé. La revue finale
  complète reste à faire après L5-T12.
- **Bilan réel d'août** : seuls les comptes déjà établis au lot 4 sont repris
  en §4. Le classement n'est toujours pas confirmé par Ilane. Aucun montant
  réel n'est écrit dans cette recette, et les quatre définitions monétaires de
  L5-D3 restent provisoires (Q2).
- **Drive** : le client, l'orchestration, les migrations et la CLI sont testés
  sans réseau. En l'absence de compte de service et de dossier cible réels, la
  commande refuse de démarrer avec le code 2 et un message clair. Aucun fichier
  n'a été téléversé vers un Drive réel.
- **Visuel** : les écrans Bilan, navigation et Réglages ont été capturés à 375
  px et 1280 px avec des données fictives; les parcours de Chantiers ont aussi
  été vérifiés par navigateur sur une base isolée fictive. Ces preuves sont
  sous `var/captures/`, hors dépôt, et ne constituent pas une validation par le
  client.
- **Contrôles connus** : suite complète et contrôles qualité verts avant L5-T12
  (§3). Ils ne sont pas rejoués par cette tâche documentaire, conformément à
  son périmètre.

## 1. État tâche par tâche

| Tâche | Commit(s) de la branche | Résultat et revue |
| --- | --- | --- |
| L5-T1 | `d697fb5`, corrections `d56cdc0`, `04c8ce1`, `327720c`; ajustement de plan `8bb1323`; corrections de revue globale `c1a6fb7`, `b3edd51` | Agrégats du bilan par chantier, quatre montants de L5-D3, compte de toutes les anomalies ouvertes, mois parisien, tri déterministe. Deux tours de correction ont ajouté le bloc d'origine aux anomalies de ligne et la migration de données 0008 pour préserver l'identité des anomalies déjà enregistrées. La revue globale a ensuite corrigé l'audit des agrégats/exports et borné les comptes d'anomalies. Re-revues fermées. |
| L5-T2 | `1baffd1` | Niveaux fournisseur et BL, vue inverse fournisseur → chantiers, expressions d'agrégat partagées et chantier non résolu conservé. Revue de tâche fermée sans commit correctif distinct. |
| L5-T3 | `157d33c`, ajustement de plan `188f29b`, correction `a50ce4b` | Quatre routes JSON admin, filtres mois/agence, décimaux sérialisés en chaînes, identifiants inconnus rendus en listes vides. La revue a demandé la couverture du mois calendaire et des filtres/identifiants; tests ajoutés. Une seule route d'agences est conservée, côté référentiels. |
| L5-T4 | `0c6bca5`, correction `37f8fe7`; corrections de revue globale `c1a6fb7`, `b3edd51` | Exports CSV serveur aux mêmes niveaux et filtres que le JSON, BOM UTF-8, séparateur `;`, décimale française et noms de fichiers explicites. Revue complétée par le cas d'échappement combinant séparateur, guillemet et retour à la ligne; la revue globale a corrigé l'audit et les bornes partagés avec le bilan. |
| L5-T5 | `1360783` | Écran Bilan par chantier, filtres dans l'URL, tableau ordinateur, cartes téléphone, avertissement que les montants ne s'additionnent pas et export à partir de `md`. Revue fermée; captures fictives à 375 px et 1280 px. |
| L5-T6 | `5ed9e2a` | Niveaux fournisseur et BL, fil d'Ariane, liens document/facture/anomalies et vue inverse. Revue fermée; parcours complet et trois niveaux vérifiés sur données fictives aux deux largeurs. |
| L5-T7 | `8e82ce9`, corrections `9bea4ed`, `38bd039` | Dépôts sur 30 jours, chantiers silencieux et agences connues, routes admin. La revue a corrigé un dépôt administrateur qui pouvait disparaître de la vue, rendu le rôle du déposant explicite, resserré le test de frontière de jour parisien et stabilisé le tri. Re-revue fermée. |
| L5-T8 | `96fbaa1`, corrections `300c42a`, `a4fd383`, `4286ffc` | Écran Chantiers & fournisseurs, création de chantier, agences des fournisseurs, alias en attente, activité et chantiers silencieux. Trois tours ont supprimé une note technique de l'interface en exposant réellement les agences, puis corrigé les invalidations de cache après création, validation d'alias, correction ou ré-extraction d'un document. Parcours navigateur fictifs validés. |
| L5-T9 | `4f539c7` | Lecture paginée et filtrée du journal, route et écran admin; auteur automatique rendu explicitement, valeurs avant/après affichées sans logique métier. Revue de tâche fermée sans commit correctif distinct. |
| L5-T10 | `3103e6f` | Lecture et modification des neuf seuils connus, bornes validées dans `ingest`, journalisation avant/après, écran Réglages. Revue fermée; captures fictives à 375 px et 1280 px. |
| L5-T11 | `d770654` | Migration 0009, protocole et client Google Drive, synchronisation idempotente, petits et gros fichiers, état d'échec/réessai, alerte de supervision au plus une fois, CLI et exploitation. Plusieurs passes de revue ont corrigé les constats critiques/importants; l'ultime verdict est `passed=true`. Google réel non testé faute d'accès. |
| L5-T12 | présent commit documentaire | Présente recette, `docs/passation-lot-5.md`, section Lot 5 de `docs/dette.md` et mise à jour de l'état du projet dans `CLAUDE.md`. Aucun code applicatif n'est modifié et aucun push ou merge n'est effectué dans cette tâche. La revue finale de branche doit suivre. |

### 1.1 Revues et corrections transverses

Les revues n'ont pas été limitées à l'absence d'erreur de test : elles ont
notamment vérifié l'identité et le rattachement des anomalies, l'absence de
double comptage SQL, la cohérence JSON/CSV, les droits admin, les frontières de
jour en Europe/Paris, l'invalidation du cache front et les frontières de panne
Drive. Les commits correctifs visibles sont listés dans le tableau ci-dessus.

La dernière revue de L5-T11 s'est terminée avec `passed=true`, après correction
des constats critiques/importants. En revanche, **la revue finale de toute la
branche n'est pas encore faite** : aucune conclusion de fusion ne peut être
tirée avant cette étape.

## 2. Décisions L5-D1 à L5-D12

| # | Décision appliquée | Coût si l'hypothèse est fausse / validation |
| --- | --- | --- |
| L5-D1 | Les agrégats sont produits par `ingest`; API et front ne font que sérialiser/présenter. | Code à déplacer, pas de donnée à migrer. |
| L5-D2 | Calcul à la demande, sans table d'agrégat ni cache. | Ajouter un index ou une vue matérialisée seulement après mesure d'une lenteur réelle. |
| L5-D3 | `facturé HT` = lignes article/éco; `rapproché` = mêmes lignes des blocs reçus; `en écart` = blocs avec anomalie ouverte R03–R09; `non justifié` = blocs non reçus ou sans bon. Ces montants ne forment pas une partition. | Quatre expressions à revoir. **Q2, à valider en priorité.** |
| L5-D4 | Le mois est celui de la facture (`date_doc`, sinon `created_at` en Europe/Paris). | Modifier le regroupement si le client attend le mois du BL. |
| L5-D5 | Le CSV exporte le niveau affiché, mêmes colonnes/filtres, BOM UTF-8, `;` et virgule décimale. | Ajouter ou modifier les colonnes. **Q3.** |
| L5-D6 | Le filtre agence liste les valeurs distinctes existantes de `chantier.agence`. | Créer un référentiel dédié si nécessaire. **Q6.** |
| L5-D7 | Drive est une commande `drive-sync` appelée par cron, sans worker. | Transformer l'entrée d'exécution, modèle d'état réutilisable. **Q1.** |
| L5-D8 | Le client Drive est derrière un protocole minimal afin de tester sans réseau. | Retirer une indirection si inutile. |
| L5-D9 | Seules les neuf clés de seuil connues sont modifiables; validation dans le service et journalisation. | Ajuster bornes/libellés, sans clé libre. |
| L5-D10 | Journal en pagination simple avec filtres auteur/action/table/période, sans plein texte JSONB. | Ajouter un filtre si l'usage le justifie. **Q4.** |
| L5-D11 | Navigation portée par les URL et filtres en paramètres de requête. | Réorganiser les routes front. |
| L5-D12 | Sur téléphone, un niveau par écran en cartes; tableau complet et export à partir de `md`. | Refaire la présentation si le client préfère une autre densité. |

## 3. Vérification commande par commande

Les résultats ci-dessous sont les derniers contrôles réels connus sur
`lot-5-restitution` après L5-T11. L5-T12 ne les a pas rejoués, puisqu'elle ne
modifie que la documentation.

```bash
uv run pytest -q
```

Résultat réel : `1359 passed in 369.65s`.

```bash
uv run ruff check
```

Résultat réel : `All checks passed!`.

```bash
uv run ruff format --check
```

Résultat réel : 212 fichiers conformes au format attendu.

```bash
uv run mypy
```

Résultat réel : `Success: no issues found in 181 source files`.

```bash
npm --prefix web run typecheck
npm --prefix web run build
```

Résultats réels : TypeScript sans erreur; build Vite réussi, 98 modules
transformés.

```bash
docker compose -p habitat_reno --env-file .env -f deploy/docker-compose.yml config -q
```

Résultat réel : code 0, configuration Compose valide.

La commande `drive-sync` a aussi été lancée sans identifiants Google : résultat
réel conforme au contrat, code 2 et message explicite signalant la
configuration absente. Elle n'a pas été exécutée avec un compte Google réel.

Les tests ciblés et revues de chaque tâche sont matérialisés par les commits de
correction de §1, mais leurs sorties intermédiaires ne sont pas réinventées ici.
La suite complète ci-dessus est la preuve consolidée disponible.

## 4. Bilan d'août — comptes uniquement

Le lot 5 n'a pas créé une nouvelle vérité métier sur août. Il restitue les
données produites par le rapprochement du lot 4. Les seuls résultats réels
réutilisables sans exposer de donnée client sont :

| Mesure | Compte |
| --- | ---: |
| Blocs de facture | 28 |
| Blocs reçus | 3 |
| Blocs « pas de bon » | 4 |
| Blocs non reçus | 21 |
| Anomalies produites | 25 |
| R01 | 21 |
| R02 | 4 |
| R13 | 3 |
| Lignes de facture | 136 |
| Lignes avec `qte_fact` renseignée | 113 |
| Lignes appariées à une ligne de BL | 3 |

Le nombre d'anomalies par règle n'est pas une partition du total : un même
objet peut porter plusieurs règles. Aucun montant, nom ou numéro réel n'est
repris. Les quatre agrégats monétaires du Bilan ne sont donc pas consignés ici.

**Réserve obligatoire** : ce classement n'a pas été confirmé par Ilane. Il ne
constitue pas une recette métier acceptée. La seule information sûre déjà
consignée au lot 4 est que trois des quatre photos disponibles portent un
numéro présent dans la facture considérée. Q5 reste ouverte.

## 5. Validation visuelle et captures fictives

Toutes les données utilisées dans le navigateur sont inventées, sur une base de
vérification isolée. Les fichiers restent hors dépôt dans `var/captures/` :

- L5-T5 : Bilan chantier à 375 px et 1280 px;
- L5-T6 : niveaux chantier, fournisseur et BL, plus vue inverse, à 375 px et
  1280 px — huit captures;
- L5-T10 : Réglages à 375 px et 1280 px.

Soit 12 captures explicitement nommées L5, auxquelles s'ajoutent les parcours
Playwright de L5-T8 décrits dans les commits de correction. Ces contrôles
établissent la mise en page sur données fictives, pas l'acceptation visuelle du
client ni la justesse des données d'août.

## 6. Questions Q1 à Q6

| Question | État au moment de L5-T12 |
| --- | --- |
| Q1 — accès Google Drive | **Ouverte.** Compte de service et dossier cible non fournis; aucun test réel ni activation. |
| Q2 — définition des quatre montants | **Ouverte et prioritaire.** L5-D3 est implémentée provisoirement; les montants ne s'additionnent pas. |
| Q3 — contenu du CSV | **Ouverte.** L5-D5 exporte le niveau affiché avec les mêmes colonnes. |
| Q4 — visibilité du journal | **Ouverte.** Réservé à l'admin provisoirement. |
| Q5 — verdicts d'août | **Ouverte.** Les comptes de §4 ne sont pas confirmés par Ilane. |
| Q6 — agences | **Ouverte.** Filtre fondé sur le texte libre existant; aucune valeur tant que le champ n'est pas renseigné. |

## 7. Limites externes et critères non vérifiables

- **Google Drive réel** : aucun accès, donc ni téléversement, ni arborescence,
  ni permissions, ni reprise après panne réseau ne sont vérifiés contre Google.
- **Déploiement** : aucun déploiement; les crons lot 4 et lot 5 ne sont pas
  posés. La configuration Compose est valide, mais le comportement sur le VPS
  client n'est pas exercé.
- **Validation métier du Bilan** : définitions L5-D3 et classement d'août non
  confirmés. Une capture fictive ne remplace pas cette validation.
- **Volume et diversité** : toujours seulement quatre photos réelles, aucune
  facture Point.P, un seul mois d'historique et aucun avoir complet. Les limites
  des lots 2 à 4 restent applicables (`docs/dette.md`).
- **Excel réel** : format CSV couvert automatiquement; l'ouverture manuelle dans
  l'environnement Excel du client n'est pas documentée comme effectuée.
- **Revue finale et fusion** : encore à faire. Le lot ne doit pas être présenté
  comme fusionné dans `main` ni prêt au déploiement avant cette revue.
