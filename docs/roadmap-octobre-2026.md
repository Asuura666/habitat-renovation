# Roadmap — demandes d'octobre 2026

Rédigée le 27/09/2026 à partir de la liste de la réunion client (rapportée par
Ilane le même jour) et de ses décisions. Ce document fait foi pour
l'organisation du travail d'octobre ; le détail de chaque lot vit dans sa
propre spec et son propre plan (`docs/superpowers/`). Ilane fait foi avec le
CDC (`docs/cahier-des-charges.md`, avenant §14).

---

## 0. En bref

| Phase | Contenu | Qui | Quand | Durée estimée |
| --- | --- | --- | --- | --- |
| **Socle commun** | Prérequis minimum de la phase 3, pris dans la phase 1 : migration 0011, calcul de ressemblance, règle R18, sérialisation des tests | Session A | 27/09, en premier | ≈ 2 h |
| **1** | Mise en production du 1er octobre : points 1 et 2, comptes, photos rangées | Session A | 27/09 → 30/09 | ≈ 10 h |
| **2** | Socle d'exploitation : sauvegardes, tâches planifiées, clés | Session A | semaine du 5/10 | ≈ 4 h |
| **3** | Commentaires (point 6) et lot Prix (points 3, 4, 5, sans internet) | **Session B** (autre worktree) | dès le socle commun fusionné dans `dev` | ≈ 18 h |
| **4** | Contrôle des prix à la facture, IA (prix sur internet, synthèse des commentaires) — IA faite sur `feature/phase-4-ia`, éteinte ; contrôle à la facture non commencé | à décider | novembre | ≈ 12 h |

Session A = la session Claude Code principale (`/home/debian/habitat_reno`).
Session B = une seconde session Claude Code lancée par Ilane dans un autre
worktree (§2.2).

---

## 1. La demande

### 1.1 Liste de la réunion (verbatim)

**Calendrier**
- **1er octobre** : mise en production, pour suivre les BL du mois et les rapprocher des factures. Corrections de l'application incluses.
- **Courant octobre** : contrôle des prix (grilles, alertes, page de suivi) et commentaires.

**1. Corrections de l'application**
- Fiche fournisseur : pouvoir filtrer sur un mois.
- Documents conformes : voir aussi les bons conformes (pas seulement les problèmes), et pouvoir cliquer dessus pour ouvrir le document.
- Chantiers : le champ « Confirmé par » affiche un identifiant au lieu du nom → afficher le nom.
- Fournisseur : même problème, afficher le nom au lieu de l'identifiant.

**2. Identification des chantiers**
- Le nom du chantier est toujours écrit sur le BL : il est lu automatiquement et ajouté au tableau de bord de suivi.
- L'employé qui envoie la photo indique aussi le nom du chantier : sert de confirmation.
- Quand l'OCR récupère le nom du chantier sur le BL, on cherche un chantier existant avec une ressemblance d'au moins 90 % : trouvé → le BL est rattaché à ce chantier ; pas trouvé → un nouveau chantier est créé et l'utilisateur est prévenu sur le site.

**3. Grilles de prix fournisseurs**
- Chaque fournisseur a sa grille de prix.
- Mise à jour manuelle possible.
- Import d'une grille depuis un fichier Excel, avec un modèle fourni.
- Mise à jour automatique à partir des derniers prix, après validation manuelle par un représentant.

**4. Contrôle des prix (à la réception du BL)** — quand un BL est pris en photo : on l'analyse, on récupère les informations, puis on contrôle les prix de chaque produit.
- Historique des factures : chercher le produit dans toutes les factures, regarder les prix payés et l'écart avec le prix actuel.
- Grille de prix : si le produit existe dans la grille du fournisseur, comparer avec ce prix, en tenant compte de la date de dernière mise à jour de la grille.
- Internet : si le produit n'existe ni dans les factures ni dans les grilles, une IA cherche le prix du produit sur internet (à titre indicatif).
- Déclenchement de l'alerte : l'écart est comparé à un seuil en pourcentage réglable. C'est la règle de seuil qui déclenche l'alerte ; l'IA ajoute un commentaire pour expliquer l'écart mais ne décide pas.
- Si un problème de prix existe → alerte.

**5. Page de suivi des alertes prix**
- Chaque jour, une page liste tous les produits en alerte de prix.
- Pour chaque produit : comparaison entre le prix facturé, le prix de la grille et le prix trouvé sur internet.
- Quand un prix est validé → la grille de prix est mise à jour.

**6. Commentaires**
- Pouvoir ajouter un commentaire sur chaque ligne de BL.
- Chaque semaine, une IA lit tous les commentaires et envoie une synthèse à l'accueil, avec les actions à mener.
- La synthèse ne modifie rien toute seule : les actions sont appliquées par un humain.

### 1.2 Décisions d'Ilane (27/09/2026)

- Priorité au 1er octobre : points 1 et 2.
- Ajouts : **gestion des comptes par un admin** (créer, modifier, supprimer, changer le mot de passe — il n'y aura qu'Ilane et les dirigeants, mais ils la veulent « au cas où ») ; **photos rangées sur le serveur** dans `bl/<année>/<mois>/`, nommées avec le jour, le déposant et le chantier.
- Chantiers : légende de la photo Telegram = nom tapé par l'employé ; si nom lu et légende désignent deux chantiers différents → **alerte, l'humain décide** ; bouton de fusion contre les doublons ; seuil 90 % réglable ; chantier créé « à compléter » (sans agence ni client) ; pas d'import de la liste des chantiers (le client complétera) ; une seule règle pour les bons et les factures.
- Point 3 : **historique complet de toutes les modifications de prix en base** (jamais écrasé), non affiché mais facilement retraçable, par fournisseur.
- Points 3-4-5 : la **page de prix doit rester simple**, peu d'informations d'un coup, directement utiles. On affiche le prix du BL à côté du prix de la grille et de l'historique **avec la date de chaque prix**, plus le **taux de ressemblance** ; **l'humain décide**. Les fournisseurs publient une nouvelle grille chaque année ; notre système construit la grille propre du client avec tout l'historique.
- Unités : **tout garder**, avec les différences selon l'unité (seau/kg…), prix catalogue, remise, net.
- Contrôle des prix : **au BL d'abord** ; à la facture ensuite, quand le contrôle au BL fonctionne.
- Internet : **plus tard**, en même temps que la synthèse IA des commentaires.
- Commentaires : la possibilité d'en ajouter tout de suite ; la synthèse IA plus tard. « À l'accueil » = **page d'accueil de l'application**.
- Ilane enverra des **grilles réelles**.
- Organisation : branche `dev`, branches de fonctionnalité, PR vers `dev`, deux sessions Claude Code en parallèle (§2).

---

## 2. Organisation du travail

### 2.1 Git

- `main` = ce qui est en production. **Plus aucun commit ni push direct sur `main`.**
- `dev` = branche d'intégration, créée depuis `main` le 27/09/2026 et poussée sur GitHub (`Asuura666/habitat-renovation`, privé).
- Chaque lot sur une branche `feature/<nom>` **partie de `dev`**, terminée par une **PR vers `dev`** (`gh pr create --base dev`). La session qui a fait le lot fusionne sa PR dans `dev` quand sa relecture finale est verte (fusion avec commit de fusion, `gh pr merge --merge`, pour garder l'historique tâche par tâche), sauf si Ilane demande à valider lui-même.
- `dev` → `main` : **seulement avec l'accord d'Ilane**, avant un déploiement ; le déploiement se fait depuis `main`.
- Avant de commencer une branche ou d'ouvrir une PR : `git fetch origin && git rebase origin/dev` (ou fusion de `dev`) pour partir de l'état le plus récent.
- Jamais pousser les vieilles branches `lot-5-referentiels`, `lot-5-restitution` (ancien historique avec des valeurs réelles) ni le bundle de `~/sauvegardes-habitat/`.

Branches prévues :

| Branche | Contenu | Session |
| --- | --- | --- |
| `feature/socle-commun` | docs (cette roadmap, spec et plan de la phase 1, avenant CDC), sérialisation des tests, tâches 1 à 3 du plan de la phase 1 | A |
| `feature/mise-en-prod-1-octobre` | tâches 4 à 13 du plan de la phase 1 | A |
| `feature/exploitation` | phase 2 | A |
| `feature/phase-3-prix` (nom libre) | phase 3 | B |

### 2.2 Deux sessions en parallèle — lancer la session B

À faire par Ilane **après la fusion de `feature/socle-commun` dans `dev`** :

```bash
cd /home/debian/habitat_reno
git fetch origin
git worktree add ../habitat_reno-prix -b feature/phase-3-prix origin/dev
cd ../habitat_reno-prix
cp ../habitat_reno/.env .env
# Dans .env, donner à la session B SA base de test (créée automatiquement au premier pytest) :
#   TEST_DATABASE_URL=postgresql+asyncpg://<même utilisateur>:<même mot de passe>@127.0.0.1:5450/bl_test_prix
uv sync
npm --prefix web ci
# NE PAS lancer `pre-commit install` : les hooks git sont partagés et déjà installés.
claude
```

Premier message à donner à la session B :

> Lis `CLAUDE.md` puis `docs/roadmap-octobre-2026.md` (surtout §2 et §5). Tu es la session B : tu fais la phase 3 (commentaires et lot Prix) sur la branche `feature/phase-3-prix`, en commençant par le cadrage P0. La session A travaille en parallèle sur les phases 1 et 2 dans `/home/debian/habitat_reno` : ne touche jamais à ce répertoire.

### 2.3 Ressources partagées — règles pour ne pas se gêner

**Mémoire du serveur.** Le VPS est à sa limite (≈ 1 Go disponible, swap de 4 Go plein le 27/09). Une seconde session Claude Code ajoute ≈ 300-500 Mo. Règles :
- les suites `pytest` et le build du front passent par un **verrou commun** (`flock /tmp/habitat_reno-tests.lock`, déjà posé dans `.pre-commit-config.yaml` par le socle commun) : les deux sessions ne font jamais tourner deux suites en même temps, la seconde attend ;
- pour un lancement manuel : `flock /tmp/habitat_reno-tests.lock uv run pytest …` ;
- un seul sous-agent d'implémentation à la fois par session ;
- si la mémoire manque (`free -h`), libérer de la place en arrêtant d'abord ce qui ne sert pas au projet (VS Code Server, conteneurs inutilisés) — **jamais** les conteneurs `habitat_prod-*` / `habitat_demo-*`.

**Base de test.** Une base par session : `bl_test` (A), `bl_test_prix` (B) sur le même Postgres de dev (`habitat_reno-postgres-1`, `127.0.0.1:5450`). Jamais `docker exec` sur les conteneurs de production ou de démo, jamais de connexion à leurs bases.

**Commits.** Le hook pre-commit rejoue toute la suite (≈ 7 min) : commiter en détaché (`nohup git commit -F msg.txt > commit.log 2>&1 &`) et surveiller. Jamais `--no-verify`. Ruff formate aussi le Python des blocs de code Markdown : `uv run ruff format <fichier.md>` après avoir écrit un document qui en contient.

### 2.4 Numéros et noms réservés

| Élément | Session A (phases 1-2) | Session B (phase 3) | Phase 4 |
| --- | --- | --- | --- |
| Migrations Alembic | `0011` (socle commun), aucune autre prévue | à partir de `0012` | `0014` (`down_revision = "0012"` ; la branche qui fusionne dans `dev` en second remet la chaîne en ligne) |
| Règles du moteur | `R18` « Chantier à confirmer » (socle commun) | `R19` à `R29` | `R30`+ |
| Clés de réglage (`parametre`) | `seuil_ressemblance_chantier_pct` | préfixe `prix_` (ex. `prix_seuil_ecart_bl_pct`) | — |
| Actions de journal | `chantier_*`, `alias_*`, `compte_*`, `acces_*`, `mot_de_passe_change` | `grille_*`, `prix_*`, `commentaire_*` | `synthese_*` |
| Routes API | `/api/comptes`, `/api/chantiers/…`, `/api/documents/{id}/chantier`, `/api/bilan/livraisons` | `/api/grilles/…`, `/api/prix/…`, `/api/commentaires/…` | `/api/ia/…` |
| Pages du front | `/comptes`, `/livraisons` | `/prix`, `/fournisseurs/:id/prix` | — |
| Commandes CLI et tâches planifiées | — | — | `synthese-commentaires`, `ia-prix`, `essai-prix-internet` ; timers `synthese` (quotidien) et `ia-prix` (horaire) |

Si une session a besoin d'une migration hors de sa plage : celle qui fusionne dans `dev` **en second** met à jour le `down_revision` de sa migration pour garder une chaîne linéaire (`tests/test_migrations.py` le vérifie).

### 2.5 Fichiers touchés par les deux sessions

Conflits attendus, à résoudre en **gardant les deux ajouts** :

| Fichier | Pourquoi | Conseil |
| --- | --- | --- |
| `web/openapi.json`, `web/src/api/schema.d.ts` | fichiers générés | en cas de conflit, prendre l'une des versions puis `npm --prefix web run api:schema && npm --prefix web run api:types` |
| `app/modules/api/anomalies.py` (`RegleAnomalie`), `app/modules/rules/engine.py` (ensembles de règles), `app/modules/rules/tests/test_engine.py` (invariant « toutes les règles »), `tests/test_regle_anomalie_couverture.py`, `app/modules/ingest/anomalies.py` (`CATEGORIES_REGLE`), `web/src/ui/libelles.ts` | énumérations de règles | ajouter ses règles à la suite ; l'invariant devient l'union de tous les ensembles |
| `app/modules/ingest/parametres.py` (`DEFINITIONS_PARAMETRES`) | réglages | ajouter à la fin |
| `app/modules/api/__init__.py`, `web/src/App.tsx`, `web/src/components/Gabarit.tsx` | nouveaux routeurs, routes, liens | une ligne chacun |
| `app/modules/ingest/extraction_bl.py` | A : rattachement du chantier (bloc chantier et journal) ; B : contrôle des prix du bon | B se branche **après** l'extraction, à côté de `_rapprocher_si_numero` (appels après le commit de `_extraire_et_committer`), dans sa propre transaction, sans jamais faire échouer l'extraction |
| `web/src/pages/FicheFournisseur.tsx`, `web/src/pages/ARegler.tsx` | A : mois, livraisons, chantiers à compléter, alerte R18 | B met ses écrans sur ses propres pages (`/fournisseurs/:id/prix`, `/prix`) et n'ajoute qu'un lien sur ces pages-là |
| `web/src/lib/journal.ts` | libellés des actions | ajouter ses libellés |
| `docs/dette.md`, `CLAUDE.md`, `memory.md` | suivi | chacun écrit dans sa propre section datée |

### 2.6 Méthode (les deux sessions)

- `CLAUDE.md` fait foi pour les frontières et la méthode : `extract`/`normalize`/`rules` purs ; `api` et `jobs` n'importent que `ingest` et `app.core` ; une tâche = un commit en français préfixé du module ; tests avant ou avec le code ; ruff, mypy strict, typecheck et build verts.
- Démarche : cadrage (questions à Ilane), spec écrite, plan, puis exécution tâche par tâche avec des sous-agents **Sonnet** (Haiku interdit ; Opus seulement en escalade), relecture après chaque tâche et relecture finale.
- Données de test **inventées** uniquement. Les grilles réelles, factures et photos du client ne vont jamais dans un commit, un log ni un texte publié (`tests/fixtures/` est ignoré par git).
- Rien en production sans l'accord d'Ilane.

---

## 3. Socle commun (session A, en premier)

Le strict minimum des phases 1-2 dont la phase 3 a besoin pour démarrer sans
se heurter à la phase 1 :

| # | Élément | Pourquoi la phase 3 en a besoin |
| --- | --- | --- |
| S1 | Cette roadmap, spec et plan de la phase 1, avenant CDC §14 | la session B doit connaître les décisions, les zones de conflit et les numéros réservés |
| S2 | Verrou `flock` sur `pytest` et le build dans `.pre-commit-config.yaml` | deux sessions sur un serveur à court de mémoire |
| S3 | Tâche 1 du plan de la phase 1 : migration `0011`, réglage `seuil_ressemblance_chantier_pct` | fixe la chaîne de migrations : la phase 3 part de `0012` sans conflit de numéro |
| S4 | Tâche 2 : `ressemblance(a, b) -> int` dans `app/modules/normalize/texte.py` (0-100, insensible à la casse, aux accents, à la ponctuation et à l'ordre des mots) | le « taux de ressemblance » des produits de la page Prix la réutilise |
| S5 | Tâche 3 : règle R18, ensemble `REGLES_CHANTIER`, énumérations des règles à jour | fixe la numérotation : la phase 3 ajoute ses règles à partir de R19, sur un modèle déjà montré de bout en bout (règle pure → moteur → énumération API → catégorie → libellé du front) |

**Ce dont la phase 3 n'a pas besoin** : la légende Telegram, le rattachement
automatique, la fusion, l'écran des comptes (le compte admin d'Ilane suffit
pour valider des prix), les corrections, le rangement des photos, les
sauvegardes et les tâches planifiées (utiles avant de **déployer** les prix,
pas pour les développer).

Livraison : PR `feature/socle-commun` → `dev`, fusionnée ; Ilane peut alors
lancer la session B (§2.2).

---

## 4. Phase 1 — mise en production du 1er octobre (session A)

Spec : `docs/superpowers/specs/2026-09-27-mise-en-production-1er-octobre-design.md`.
Plan : `docs/superpowers/plans/2026-09-27-mise-en-production-1er-octobre.md`
(tâches 1 à 3 = socle commun ; tâches 4 à 13 sur `feature/mise-en-prod-1-octobre`).

| # | Tâche | Durée |
| --- | --- | --- |
| 4 | Légende Telegram lue, conservée, affichée | 35 min |
| 5 | Rattachement automatique du chantier (bons et factures) : ressemblance ≥ seuil, création « à compléter », apprentissage du nom lu, alerte R18, verrou contre les doublons simultanés | 1 h 30 |
| 6 | « À régler » : nouveaux chantiers à compléter, choix du chantier sur l'alerte ; étiquette « À compléter » ; changer le chantier d'un bon | 1 h 15 |
| 7 | Fusion de deux chantiers | 1 h |
| 8 | Reprise des noms en attente (`rattacher-chantiers`) | 25 min |
| 9 | Photos rangées `bl/<année>/<mois>/<jour>_<déposant>_<chantier>_n<numéro>` (liens physiques) + `ranger-photos` | 50 min |
| 10 | Comptes, serveur | 1 h |
| 11 | Comptes, écran | 45 min |
| 12 | Journal : noms au lieu des identifiants (« Confirmé par », fournisseur…) | 40 min |
| 13 | Fiche fournisseur par mois ; « Conforme » cliquable → livraisons conformes → page du bon | 1 h 15 |
| — | Relecture finale, PR vers `dev` | 1 h 30 |
| — | Déploiement (après `dev` → `main` avec l'accord d'Ilane) : dumps, démo puis production, migration, `rattacher-chantiers`, `ranger-photos` | 45 min |

Exemples du seuil de 90 % : « Villa Test » / « VILLA TEST (123) » = 100
(rattaché) ; « Résidence des Tilleuls » / « tilleuls residence » = 90
(rattaché) ; « Les Pins » / « Les Pins 2 » = 88 (nouveau chantier) ;
« Ormeaux » / « Résidence les Ormeaux » = 50 (nouveau chantier, à fusionner).

---

## 5. Phase 2 — socle d'exploitation (session A, semaine du 5/10)

| Tâche | Détail | Prérequis | Durée |
| --- | --- | --- | --- |
| Sauvegardes | `deploy/backup.sh` (dump + documents, restic) chaque nuit vers un stockage **hors du serveur** (le CDC §9 prévoit OVH Object Storage) ; corriger d'abord le bogue de `restore.sh` (`ps -q` sans `-a`) ; rejouer `deploy/test-restauration.sh` et consigner le résultat | Ilane : un conteneur OVH Object Storage et ses clés S3 (ou une autre destination) | 2 h |
| Tâches planifiées | timers systemd (`cron` absent du VPS) : `controles-differes` (rappels R14-R16), sauvegarde nocturne, `ranger-photos` (rattrapage) ; `drive-sync` quand le Drive sera débloqué | — | 1 h |
| Clés | changer les clés collées dans le chat (Mistral, Telegram, compte de service Google), mettre à jour `.env.prod`/`.env.demo`, recréer les conteneurs | Ilane génère les nouvelles clés | 30 min |
| De son côté, Ilane | groupe Telegram de test avec son propre bot (relié à la démo), comptes des employés et leurs identifiants Telegram | — | — |

---

## 6. Phase 3 — commentaires et lot Prix (session B)

Point de départ : `dev` après fusion du socle commun (§3). Branche :
`feature/phase-3-prix`. Livraison : PR vers `dev`. Le déploiement des prix en
production attend les sauvegardes de la phase 2.

### 6.1 Ce qui existe déjà (à lire avant de concevoir)

- **Lignes** (`app/modules/ingest/models.py`, `Ligne`) : `code_brut`, `article_brut` (désignation), `article_id`, `qte_livree`, `qte_totale`, `unite_brut`, `qte_fact` (convertie), `pu_ht`, `pu_cdt`, `remise_pct`, `montant_ht`, `tva`, `type_ligne` (`article`/`eco`/`commentaire`), `confiance`.
  - Sur un **BL**, l'OCR remplit `code_brut`, `article_brut`, quantités, `unite_brut`, `pu_ht`, `montant_ht` (`extraction_bl.py`, boucle d'insertion des lignes) — **pas de remise** lue. En production au 27/09, toutes les lignes d'articles des bons déposés ont un `pu_ht`.
  - Sur une **facture** Unikalo : `pu_ht`, `pu_cdt` (prix du conditionnement), `remise_pct`, `montant_ht`.
- **Articles** (`Article`) : clé `(fournisseur_id, code)`, `libelle`, `unite_cdt` (seau, sac…), `unite_fact` (kg, m…), `ratio`, `valide`. Créés automatiquement à la première ligne portant un code (`referentiels.rattacher_article`), unités validées par l'admin.
- **Unités** : `app/modules/normalize/unites.py` (`normaliser_unite`, `convertir_en_unite_fact`) ; propositions d'article et de ratio : `normalize/article.py`.
- **Appariement de lignes** (facture ↔ BL, par code puis désignation normalisée) : `normalize/appariement.py::apparier_lignes`.
- **Ressemblance** (socle commun) : `normalize/texte.py::ressemblance`.
- **Anciens contrôles de prix, sur les factures** : R07 (écart > 5 % à la médiane des 6 derniers mois), R08 (> 15 %), R09 (remise habituelle oubliée) ; historique construit par `ingest/rapprochement.py::_construire_historiques` (médiane des `pu_ht` des factures du fournisseur sur 6 mois). **Désactivés** depuis le 24/09 par `CONTROLE_PRIX_ACTIF=false` (`ingest/commun.py::regles_desactivees`, `REGLES_PRIX`) : leurs anomalies sont masquées, leurs réglages (`seuil_prix_pct`, `seuil_prix_fort_pct`, `occurrences_prix_min`) cachés de Réglages, et le filtre « Prix » d'« À régler » caché (`CompteProblemes.controle_prix_actif`). La nouvelle règle au BL ne doit pas tomber sous ce drapeau par accident.
- **Anomalies** (`ingest/anomalies.py`) : persistance idempotente (`synchroniser_anomalies`, portée obligatoire), cycle `ouverte` → `traitee`/`ignoree` avec commentaire, jamais rouverte ; table unique `CATEGORIES_REGLE` (catégorie `prix` existe) ; « À régler » les compte toutes.
- **Réglages** : `ingest/parametres.py` (`DEFINITIONS_PARAMETRES`, bornes, journalisés).
- **Journal** : table `journal` (auteur, action, cible, `avant`/`apres` JSON).
- **Données réelles disponibles** : une seule facture (août 2026) ; l'historique des prix sera mince au début — la grille servira de référence dès le premier jour.

### 6.2 Découpage proposé

| # | Tâche | Contenu | Durée |
| --- | --- | --- | --- |
| C | **Commentaires (point 6)** | Table `commentaire` (ligne, auteur, texte, date), ajout depuis la page du bon (une zone par ligne), liste sous la ligne, nombre de commentaires sur le bon ; journalisé (`commentaire_ajoute`). Indépendant du reste : peut passer en premier. | 3 h |
| P0 | **Cadrage** | Avec les grilles réelles d'Ilane : questions §6.3, spec, plan, modèle Excel | 1 h 30 |
| P1 | **Grilles en base** | Tables des prix par fournisseur ; **historique jamais écrasé** : chaque changement = une nouvelle ligne (prix catalogue, remise, prix net, unité, conditionnement, date d'effet, source `saisie`/`import`/`validation`, auteur, fichier importé) ; prix en vigueur = dernière ligne par produit ; **la base refuse UPDATE et DELETE** sur l'historique (déclencheur PostgreSQL) ; historique non affiché mais interrogeable | 1 h 30 |
| P2 | **Saisie manuelle** | Page `/fournisseurs/:id/prix` : prix en vigueur, recherche, ajouter ou modifier un prix (= nouvelle ligne d'historique) ; lien depuis la fiche fournisseur | 2 h |
| P3 | **Import Excel + modèle** | Modèle téléchargeable ; import d'un fichier : aperçu (lignes nouvelles, prix modifiés, erreurs ligne par ligne) puis confirmation ; bibliothèque `openpyxl` (nouvelle dépendance, passe par `pip-audit`) ; taille plafonnée | 3 h |
| P4 | **Retrouver le produit** | Relier une ligne de bon à un produit de la grille et aux lignes de factures passées : code article exact, sinon ressemblance de la désignation (`ressemblance`, avec le taux affiché) ; conversion d'unité (article, ratio) | 2 h |
| P5 | **Contrôle au bon** | Nouvelle règle pure (R19 « Prix hors référence ») : écart en % entre le prix du bon et la grille en vigueur, et entre le prix du bon et le dernier prix facturé ; seuil réglable (`prix_…`) ; justification chiffrée (prix du bon, référence, date de la référence, écart, ressemblance) ; exécutée après l'extraction du bon et après une correction de ses lignes | 2 h |
| P6 | **Page « Prix à vérifier »** | `/prix` : une ligne par produit en alerte, **simple** : produit · prix du bon · prix de la grille (date) · dernier prix facturé (date) · écart · ressemblance ; filtre « du jour » ; actions « Valider ce prix » (nouvelle ligne de grille, source `validation`, auteur, et l'alerte passe « réglée »), « Contester », « Ignorer » | 2 h 30 |
| — | **Relecture finale, PR vers `dev`** | | 2 h |

### 6.3 Questions à trancher en P0 (avec Ilane, grilles en main)

1. **Format des grilles réelles** : colonnes, un fichier par fournisseur ou par agence, fréquence ; en déduire le modèle Excel.
2. **Prix d'un BL** : le prix unitaire imprimé est-il net (remise déduite) ou catalogue ? Dans quelle unité (seau ou kg) ? Comparer toujours en prix net par unité de facturation, après conversion.
3. **Quand grille et historique existent tous les deux** : alerte si l'un **ou** l'autre dépasse le seuil ? Un seuil unique ou un par référence ? (Ilane : « on affiche tout, l'humain décide » ; « c'est la règle de seuil qui déclenche l'alerte ».)
4. **Âge de la grille** : à partir de quel âge l'afficher comme ancienne (les fournisseurs publient une grille par an) ?
5. **« Valider ce prix »** : date d'effet de la nouvelle ligne de grille (date du bon ?), et que faire si plusieurs bons du même produit sont en alerte.
6. **« Contester »** : simple fermeture de l'alerte avec commentaire, ou suivi particulier (réclamation fournisseur — évolution hors demande) ?
7. **Produit introuvable** (ni grille ni facture) : « aucune référence », jamais « conforme » ; plus tard, le prix internet (phase 4).
8. **Commentaires** : qui peut commenter (admins seulement, ou aussi les employés depuis leur accès) ; modifiable ou non après coup (proposition : non modifiable, historisé).
9. Faut-il un **drapeau d'activation** propre au contrôle des prix au BL (comme `CONTROLE_PRIX_ACTIF` pour les factures), pour l'allumer seulement quand les grilles sont chargées ?

### 6.4 Contraintes propres à la phase 3

- L'historique des prix est une donnée de valeur : aucun code ne le modifie ni ne le supprime ; le déclencheur de la base le garantit ; un test le vérifie.
- La règle de prix est **pure et déterministe** (`rules/`), avec test positif et négatif ; aucune IA dans la décision.
- La page Prix ne montre que l'essentiel ; le détail complet reste dans la justification de l'alerte.
- Grilles réelles du client : jamais commitées ; les tests génèrent leurs propres fichiers Excel inventés.
- Après la PR, Ilane décide du déploiement ; les sauvegardes (phase 2) doivent tourner avant que l'historique des prix n'existe en production.

---

## 7. Phase 4 — plus tard (novembre)

À lancer quand le contrôle au BL tourne bien et que les tâches planifiées existent.

| Tâche | Contenu | Durée |
| --- | --- | --- |
| Contrôle des prix à la facture | Même logique qu'au bon, sur le prix réellement payé ; remplace R07-R09 (désactivées) en s'appuyant sur la grille et l'historique | 2 h 30 |
| Prix trouvé sur internet | Une IA (OpenCode + abonnement ChatGPT personnel d'Ilane, pas Mistral, décision D2 de la spec) cherche le prix d'un produit absent des factures et des grilles, **à titre indicatif**, avec source et date (recherche web par le service public gratuit d'Exa) ; 3e colonne de la page Prix, à construire quand le lot Prix sera fusionné (T10) | 4 h |
| Commentaire de l'IA sur les alertes prix | Explique l'écart ; ne décide rien | 1 h 30 |
| Synthèse hebdomadaire des commentaires | Tâche planifiée chaque semaine ; synthèse et actions à mener affichées sur la page d'accueil ; ne modifie rien | 3 h |
| Relecture et déploiement | | 1 h |

**Fait** (27-28/09/2026, `feature/phase-4-ia`, IA éteinte,
`docs/superpowers/specs/2026-09-27-phase-4-ia-design.md`) : synthèse
hebdomadaire des commentaires, commentaire de l'IA sur les alertes prix,
prix trouvé sur internet — moteur OpenCode connecté à l'abonnement ChatGPT
d'Ilane. **Attend le lot Prix** (fusion dans `dev`) : l'explication et le
prix internet n'ont aucune alerte/anomalie R22 à traiter tant qu'il n'est
pas fusionné ; la 3ᵉ colonne « Internet » de la page `/prix` (T10 du plan).
**Attend l'abonnement d'Ilane** : aucun essai de bout en bout n'est possible
avant sa connexion (les modèles gratuits d'OpenCode refusent le mode
serveur). Contrôle des prix à la facture (non IA) : non commencé.

---

## 8. En attente, hors de cette demande

Point.P (parseur de factures, bloque le rapprochement avec ce fournisseur) ;
fournisseurs gérés à l'écran et fournisseur d'une facture reconnu par
SIRET/TVA ; écran de correction d'une facture « à vérifier » ; Drive (Drive
partagé Workspace ou OAuth) ; serveur dédié au client ; lot 6 (recette sur
deux mois, formation, procès-verbal). Voir `memory.md` et `docs/dette.md`.

---

## 9. Calendrier

| Période | Session A | Session B |
| --- | --- | --- |
| 27/09 | Socle commun → PR `dev` | — |
| 27/09 → 30/09 | Phase 1, PR `dev`, puis `dev` → `main` et déploiement avec l'accord d'Ilane | Démarre dès le socle fusionné : commentaires, puis cadrage Prix (grilles reçues) |
| Semaine du 5/10 | Phase 2 | Lot Prix P1 → P3 |
| 12/10 → 23/10 | Appui, corrections de la production | Lot Prix P4 → P6, PR `dev` |
| Novembre | Phase 4 | |

---

## 10. Suivi

- [x] Socle commun fusionné dans `dev` (S1 → S5) — PR #1, 27/09
- [x] Session B lancée (Ilane) — commentaires faits, spec et plan du lot Prix écrits (27/09)
- [ ] Phase 1 : PR vers `dev`
- [ ] Phase 1 : déployée (`dev` → `main`, démo puis production)
- [~] Phase 2 : restauration corrigée et testée, tâches planifiées et alerte, sauvegardes locales posées (27/09) — restent OVH, clés, contrôles/photos après le déploiement de la phase 1 (`docs/phase-2-exploitation-recette.md`)
- [x] Phase 3 : commentaires (session B ; fusionnés dans `feature/phase-4-ia` pour la synthèse IA)
- [x] Phase 3 : lot Prix (P0 → P6), PR vers `dev`
- [~] Phase 4 : IA (synthèse, explication, prix internet) faite sur `feature/phase-4-ia`, éteinte (`IA_ACTIVE=false`) — contrôle des prix à la facture non commencé
