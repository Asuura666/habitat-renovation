# Passation — lots 1 et 2 (nuit du 16 au 17 septembre 2026)

Document de reprise pour la session suivante, qui continuera les lots dans le même mode : autonomie, sous-agents Sonnet, jusqu'au maximum de lots. **À lire en entier avant de toucher au code**, avec `CLAUDE.md`, `docs/cahier-des-charges.md` (qui fait foi), `docs/lot-1-recette.md`, `docs/lot-2-recette.md` et `docs/dette.md`.

---

## 1. État au 17/09/2026, 08 h UTC

- **Branche `main`** @ `88080a8` : lots 1 et 2 fusionnés en avance rapide depuis `lot-2-collecte`. Les branches et worktrees de travail sont supprimés. Aucun remote, rien de déployé.
- **Vérifié sur `main` après fusion** : `uv run pytest -q` → 359 passés ; `ruff check`, `mypy` strict (66 fichiers), `npm --prefix web run typecheck` et `build`, `docker compose --env-file .env.example -f deploy/docker-compose.yml config` : tous verts.
- **Environnement de dev sur ce VPS** (machine partagée avec d'autres projets) :
  - Postgres de dev : conteneur `habitat_reno-postgres-1`, `127.0.0.1:5450` ; base `bl` migrée à `head` (0004), vide. Les bases `bl_test` et `bl_test_migrations` sont recréées automatiquement par `tests/conftest.py`.
  - `.env` à la racine (mode 600, jamais commité) : valeurs de dev factices, **sauf `MISTRAL_API_KEY` qui est réelle**. Elle a été transmise en clair dans la conversation : **rotation à faire**.
  - Fixtures réelles ignorées par git dans `tests/fixtures/unikalo/` :
    - `facture_2026-08.pdf` : un **scan** de 9 pages images ;
    - `facture_2026-08.mistral-ocr.json` : réponse Mistral OCR de ce scan ;
    - `facture_2026-08.attendu.json` : référence établie à la main, soit l'en-tête plus les 28 blocs (numéro, date, chantier brut, montant), dont la somme est égale au total HT.
  - `web/node_modules` installé ; `web/dist` n'est pas construit.
- **Journaux détaillés de la nuit** (ignorés par git, supprimables) : `.superpowers/sdd/plan-lot-1/` et `.superpowers/sdd/plan-lot-2/`. Ils contiennent `progress.md` (journal et décisions), les fiches de tâche et les rapports.

---

## 2. Ce qui a été fait

### Lot 1 — Socle (plan : `docs/plan-lot-1.md`, recette : `docs/lot-1-recette.md`)

| Tâche | Commits | Contenu |
| --- | --- | --- |
| T1 | `d80fffc` | Outillage uv, ruff, mypy strict, pytest (`--import-mode=importlib`), pre-commit, `CLAUDE.md`, garde de frontières d'import `tests/test_frontieres.py` (analyse `ast`) |
| T2 | `fbc5285` | Compose : `traefik:v3.6`, `api`, `postgres:18` ; `Dockerfile` non-root ; `.env.example` ; override de dev (5450/8450) |
| T3 | `692352b` | Config fail-fast (pydantic-settings), `core/db.py`, Alembic, migration 0001 : les 14 tables du CDC §6, avec CHECK et `NULLS NOT DISTINCT` |
| T4 | `2c500f3`, `ce565d0` | `GET /health` (base joignable, délai borné, testé sur connexion qui pend) |
| T5 | `bb86259` | Parseur de facture Unikalo **sur réponse OCR** (`extract/facture.py`, `ocr.py`, `unikalo.py`) ; 28/28 blocs conformes à la référence |
| T6 | `e2cfe14` | Webhook Telegram `POST /tg/webhook` : secret, dédoublonnage `update_id`, téléchargement, stockage `<uuid>.<ext>`, réponse |
| T6b | `3f34fbe`, `41ab6d8` | Détection du n° de BL sur photo par OCR Mistral (`ingest/mistral.py`, `extract/ocr.py::detecter_numero_bl`) |
| T7 | `e5c3717` | CLI `python -m app.cli bl-non-recus <facture.pdf>` (livrable du lot) |
| T8 | `fee9b77` | `deploy/backup.sh` (pg_dump + restic), `restore.sh`, `test-restauration.sh`, `RESTAURATION.md` |
| T9 | `66dd624` | Recette du lot 1 |
| Vague finale | `9cfaac5`, `768bf66` | Nommage des contraintes uniques composites ; script de restauration réparé et rejoué ; test CLI isolé sur `bl_test` ; garde anti-résidu de `restore.sh` |

### Lot 2 — Collecte (plan : `docs/plan-lot-2.md`, recette : `docs/lot-2-recette.md`)

| Tâche | Commits | Contenu |
| --- | --- | --- |
| L2-T1 | `d850bdb` | Auth fastapi-users : cookie `bl_session`, sessions en base (`jeton_session`, migration 0002), expiration glissante de 12 h, slowapi 5/min sur le login, `GET /api/moi` |
| L2-T1b | `f1b672e`, `170f905` | CLI `utilisateur-creer` / `utilisateur-desactiver` (argon2id, e-mail insensible à la casse) |
| L2-T2 | `3ae3d11` | Liste blanche Telegram, filtre du groupe BL, supervision (ligne par dépôt, expéditeur inconnu, échecs) ; migration 0003 (`numero_interne`, `photo_compressee`, `total_ht`) |
| L2-T3 | `4dc290f`, `0da4928` | Réponse « Reçu — document n° N » + boutons « Quantités vérifiées » / « Écart constaté » ; premier clic atomique ; journal ; validation stricte de `callback_data` ; documents archivés protégés |
| L2-T4 | `66458fb`, `c273084` | `POST /api/factures` (admin) : OCR + parseur, doublon 409, transaction unique, écriture disque protégée |
| L2-T5 | `ffe94b6` | `GET /api/factures`, `/api/factures/{id}`, `/fichier`, `GET /api/documents`, `/api/documents/{id}/fichier` ; droits dans le service ; migration 0004 (`bloc_facture.ordre`) |
| L2-T6 | `7a24c67` | Socle React 18 (Vite, React Router 7, TanStack Query 5, Tailwind 3), connexion, service statique par l'API, Dockerfile multi-étage |
| L2-T7 | `e76eeac`, `b0cc8e6`, `f4f3b11` | Écran Factures (liste, dépôt, détail) et onglet BL déposés ; champ `confirmation` explicite exposé par l'API |
| L2-T8 | `1b17f8d` | Recette du lot 2 |
| Vague finale | `acaf86a`, `ead7605`, `fc689f8`, `88080a8` | `ingest/service.py` découpé en `commun.py`, `depot_telegram.py`, `factures.py`, `lecture.py` ; contrôle d'origine anti-CSRF + `Cache-Control` sur `index.html` ; en-têtes de sécurité Traefik ; correspondance des numéros de BL insensible aux espaces insécables |

---

## 3. Décisions

### 3.1 Validées par Ilane (16/09/2026)

- Le numéro de BL est **détecté dans le BL** (imprimé tout en haut) → OCR Mistral dès le lot 1 (« on testera avec l'OCR de Mistral »).
- La sécurisation du VPS est **hors lot 1**, faite à part par Ilane. `deploy.sh` est hors lot 1.
- Le test Telegram de bout en bout est à faire (reporté : pas de bot ni d'URL publique la nuit).
- Identité git : `Shiro <shiro@openclaw>`.
- Mode de travail : carte blanche la nuit, sous-agents **Sonnet uniquement (Haiku interdit)**, enchaîner les lots, contourner les blocages. Le 17/09 : fusion dans `main` demandée.

### 3.2 Prises en autonomie — lot 1 (format : décision — coût si c'est faux)

Les décisions de conception D1 à D18 sont dans `docs/plan-lot-1.md` §4 (UUID, `numeric`, `text` + CHECK plutôt qu'ENUM, pydantic-settings, route webhook dans `ingest`, anyio + `httpx.MockTransport`, etc.). Décisions prises en cours d'exécution :

- **R1** Travail sur une branche depuis un commit vide — aucun coût.
- **R2** Fiches de tâche construites par awk (titres « T<n> ») — aucun coût.
- **R3** pytest en `--import-mode=importlib` (tests colocalisés) — un réglage.
- **R4** Compose `name: habitat_reno` et `${DOCS_HOST_DIR:?}` obligatoire — une ligne.
- **R5** Une ligne texte sans code ni montant devient un COMMENTAIRE, jamais fusionnée dans la désignation (indiscernable par la mise en page) — désignations sur deux lignes tronquées (le texte reste dans la ligne suivante).
- **R6** `tva` = taux résolu via le récapitulatif code → taux — champ à renommer.
- **R7** Montant non imprimé (remise 100 %) → `None` — 0 au lieu de None.
- **R8** En-têtes de page ignorés, bloc continu d'une page à l'autre, rien après « Conditions de règlement » — parseur à ajuster sur septembre.
- **R9** Test Telegram de bout en bout reporté à la recette avec Ilane — report.
- **R10** Test réel de l'OCR sur les photos abandonné (photos absentes du disque) — détection non prouvée sur vraie photo.
- **R11** Tours de correction par `--amend` quand rien n'est au-dessus, sinon commit séparé — historique moins granulaire.
- **R12** Tâche suivante lancée en parallèle d'une re-revue triviale — un commit de correction en plus.
- **R13** `journal.cible_id` en `text` — colonne à retyper.
- **R14 (révisée)** `created_at` sur toutes les tables, y compris `journal` et `telegram_update` (CDC §6) — deux colonnes redondantes.
- **R15 / R18** T5 et T8 exécutées dans des worktrees parallèles avec leur propre Postgres, intégrées par cherry-pick — dérive d'intégration (elle s'est produite : voir §5).
- **R16** **Factures lues via la réponse Mistral OCR** (parseur pur sur le JSON), pas de parseur pdfplumber tant qu'aucun PDF natif réel n'existe — si Ilane fournit des PDF natifs, ajouter un parseur natif.
- **R17** Plus aucun envoi de document client à l'extérieur la nuit ; la réponse OCR sauvegardée sert de fixture hors ligne — vérifications réelles reportées.
- **R19** Test générique « blocs = fichier `.attendu.json` » (critère de recette 100 % des blocs) — aucun.
- **R20** La restauration ne supprime jamais les documents : bascule par renommage, ancien dossier conservé — espace disque doublé jusqu'au nettoyage.
- **R21** Un parseur par fournisseur : `extract/unikalo.py` ; aides génériques dans `extract/ocr.py` — un renommage.
- **R22** Accusé Telegram avant persistance garantie non modifié au lot 1 ; échecs notifiés au lot 2 — sans alerte jusqu'au lot 2 (fait en L2-T2).
- **R23** Migration 0001 modifiée en place (rien de déployé) — une migration de renommage sinon.
- **R24** Parallélisme réduit (swap du VPS saturé) — nuit plus lente.

### 3.3 Prises en autonomie — lot 2

Les décisions de conception L2-D1 à L2-D18 sont dans `docs/plan-lot-2.md` §4. En résumé :
- mapping fastapi-users sur les colonnes du CDC ;
- sessions en base glissantes ;
- `api`/`jobs` n'importent que `ingest` ;
- migrations 0002 à 0003 ;
- bot limité au groupe configuré ;
- expéditeur inconnu signalé en supervision ;
- formats des messages ;
- premier clic qui fait foi ;
- dépôt de facture synchrone ;
- BL reçu calculé à la lecture ;
- onglet « BL déposés » ;
- utilisateurs créés en CLI ;
- types front générés sans serveur ;
- service statique ;
- pas de tests unitaires front ;
- CSRF par contrôle d'origine (L2-D18).

Décisions prises en cours d'exécution :

- **L2-R1** Export OpenAPI par un script npm (`uv run --env-file`), pas une sous-commande CLI — ajouter la sous-commande plus tard.
- **L2-R2** Ne jamais lancer `pre-commit install` depuis un worktree (hooks partagés) — commits bloqués après suppression du worktree.
- **L2-R3** Proxy Vite de dev vers 8450 — une ligne.
- **L2-R4** Migration 0003 avancée dans L2-T2 — aucun.
- **L2-R5** « Confiance réduite » (CDC §4.2) et avoirs **non implémentés**, documentés en dette — à faire au lot 3 ou à réception d'un exemple d'avoir.
- **L2-R6** Un seul agent lance pytest sur une même base de test — plus lent.
- **L2-R7** Migration 0004 `bloc_facture.ordre` (même `created_at` pour tous les blocs d'une transaction) — une colonne.
- **L2-R8** État « vérifié / écart » exposé par l'API à partir du journal (`confirmation`), jamais dérivé dans le front — un champ API.
- **L2-R9** Vague finale : découpage du service sans façade, contrôle d'origine sans jeton CSRF, en-têtes Traefik, alignement trim/strip ; purge des jetons expirés seulement documentée — refactor à ajuster.
- **L2-R10 (point ouvert)** Le contrôle d'origine (`app/core/origine.py`) **bloque la connexion et les POST via `npm run dev`** : le proxy Vite garde l'`Origin` du serveur Vite alors que l'hôte est réécrit. La production et le front servi par l'API ne sont pas touchés. **À corriger avant tout travail front du lot 3**, par l'une de ces deux voies : accepter `Sec-Fetch-Site: same-origin`, ou réécrire `Origin` dans le proxy de `web/vite.config.mts` ; ajouter alors un test derrière proxy.

---

## 4. À faire avec Ilane / questions ouvertes

1. **Valider la lecture des factures par OCR** (R16). Demander s'il existe des factures Unikalo en PDF natif (envoi e-mail du fournisseur).
2. **Rotation de la clé Mistral.**
3. **Fichiers manquants** :
   - facture Unikalo de **septembre** ;
   - **exemple d'avoir** Unikalo ;
   - les **4 photos de BL** (3 Unikalo, 1 Point.P), envoyées dans la conversation mais absentes du disque, à déposer dans `tests/fixtures/bl/` ;
   - pour le lot 3 : **30 photos de BL réelles** dont 10 dégradées, avec le chantier réel de chacune (CDC §12) ;
   - liste des chantiers actifs et libellés fournisseurs ;
   - factures et BL **Point.P**.
4. **Telegram réel** : créer le bot et les deux groupes (BL et supervision), récupérer les identifiants de chat, `setWebhook` avec `secret_token`, fournir une URL HTTPS publique. Toucher au nginx partagé de ce VPS demande l'accord d'Ilane. Dérouler les procédures des recettes (20 dépôts, expéditeur inconnu, boutons).
5. **Tests réels non faits** : `bl-non-recus` sur la facture d'août avec le vrai OCR ; dépôt de facture depuis l'écran ; rendu navigateur et mobile (375 px) ; sauvegarde vers OVH Object Storage et restauration sur VPS jetable.
6. **Questions du plan lot 2** (§3) :
   - Q1 : qui peut cliquer les boutons ?
   - Q2 : que déclenche « Écart constaté » ?
   - Q3 : écran de gestion des utilisateurs ?
   - Q4 : identifiants des groupes Telegram.
   - Q5 : format d'un avoir.
7. **Semi-remorque** (CDC §5) : déclencheur à définir avec le client avant le lot 4.
8. Hors code : sécurisation du VPS client (Ilane), `deploy.sh`, UptimeRobot, information des salariés (RGPD).

---

## 5. Méthode qui a fonctionné (à reproduire)

- **Un plan par lot** `docs/plan-lot-N.md`, écrit par le contrôleur puis exécuté sans attendre de validation. Il contient :
  - objectif et critères du CDC ;
  - contraintes globales ;
  - constats ;
  - questions (non bloquantes, avec décision provisoire) ;
  - tableau des décisions (pourquoi / coût si faux) ;
  - structure des fichiers ;
  - tâches avec interfaces exactes et tests exigés ;
  - récapitulatif des tests.
- **Skill `superpowers:subagent-driven-development`**. Par tâche :
  1. le contrôleur écrit une fiche : sections communes du plan, section de la tâche, « Décisions du contrôleur » ;
  2. un implémenteur **Sonnet** la réalise (tests d'abord, un commit, rapport dans un fichier) ;
  3. un relecteur **Sonnet** vérifie la conformité puis la qualité, sur un paquet de diff (`scripts/review-package`), avec des « risques nommés » explicites ;
  4. les constats Critical/Important passent en tours de correction (reprise du même implémenteur), suivis d'une re-revue ciblée ;
  5. les mineurs sont consignés.
- **Fin de lot** : revue globale de la branche → **une** vague de correction → re-revue → recette `docs/lot-N-recette.md` avec encart « À lire d'abord », liste complète des décisions et honnêteté sur ce qui n'a pas été vérifié réellement.
- **Journal** `.superpowers/sdd/plan-lot-N/progress.md` : chaque dispatch, chaque verdict, chaque « Ruling: décision — pourquoi — coût si faux ». C'est lui qui permet de reprendre après une compaction ou une interruption.
- **Fichier de règles d'exécution commun** transmis à chaque sous-agent, à recréer (l'ancien est dans `.superpowers/sdd/plan-lot-1/execution.md`) :
  - dépôt, branche et format de commit (français, préfixe du module, lignes de fin) ;
  - interdiction de `git add -A` ;
  - interdiction d'afficher `.env` ;
  - valeurs de dev ;
  - machine partagée : ne toucher à aucun autre conteneur, pas de Traefik (80/443 pris par nginx), pas de `docker system prune` ;
  - tests anyio et `httpx.MockTransport` ;
  - aucun sous-agent lancé par un sous-agent.
- Les relecteurs trouvent de vrais défauts à presque chaque tâche. Exemples réels :
  - secrets visibles par `ps` ;
  - `rm -rf` sans garde ;
  - `callback_data` forgé qui provoquait un 500 ;
  - e-mails en double selon la casse ;
  - en-tête de facture mal extrait ;
  - script de restauration cassé par l'intégration.

  **Ne jamais sauter les revues.**

---

## 6. Pièges rencontrés (à éviter)

- **Filtre de sécurité du mode auto** : lancer un script qui lit la facture client, ou envoyer un document client à Mistral, est signalé « Data Exfiltration ». Il faut :
  - travailler hors ligne sur la réponse OCR sauvegardée ;
  - ne jamais afficher le contenu brut des fixtures ;
  - n'afficher que des comptes et des booléens dans les tests et les scripts ;
  - n'utiliser que des données inventées dans le code commité.
- **Mémoire du VPS** (8 Go, swap de 4 Go quasi plein) : jamais deux builds Docker simultanés, deux ou trois agents au plus. Préférer les vérifications sans Docker (uvicorn local + `curl`) quand c'est possible.
- **Base de test partagée** : deux suites pytest simultanées sur la même base (`TRUNCATE`, nom fixe `bl_test_migrations`) se marchent dessus. Un seul agent teste par base, et un worktree parallèle a son propre conteneur Postgres.
- **Worktrees** :
  - les hooks git sont communs à tous les worktrees : `pre-commit install` depuis un worktree casse les commits de l'arbre principal ;
  - l'intégration par cherry-pick crée des dérives : une variable obligatoire ajoutée par une tâche a cassé le script de test d'une autre, et seule la revue globale l'a vu ;
  - générer les `.env` de test à partir de `.env.example`.
- **Après une modification de migration en place** : supprimer `bl_test` et `bl_test_migrations`, sinon le schéma est périmé et `created_at` est introuvable.
- **Consignes du contrôleur fausses** : un port de dev erroné et une dérivation « vérifié / écart » dans le front ont été attrapés par les revues. Les corriger par un Ruling, sans les défendre.
- **`cat >> fichier` sans heredoc** bloque le shell (il attend l'entrée standard).
- **Limite de session API** : des agents s'arrêtent net. Vérifier `git status` du worktree, puis relancer la même consigne.
- **Imports** : `app/core/auth.py` appelle `get_settings()` à l'import, d'où l'import différé dans `app/cli.py` (dette).
- Les commits des sous-agents portent la ligne d'attribution de leur propre modèle (« Claude Sonnet 5 »).

---

## 7. Prochain lot : lot 3 — Extraction (CDC §11)

**Contenu** :
- OCR des BL ;
- contrôle de cohérence (somme des lignes = total HT à 0,05 € → « à vérifier ») ;
- écran « À traiter » avec correction tracée (valeur OCR d'origine conservée) ;
- normalisation fournisseur / chantier (alias validés par l'admin) / article (unités, ratio) ;
- parseur Point.P ;
- score de confiance par champ.

**Livrable** : rapport du taux d'erreur OCR sur 30 BL réels (CDC §10 : au moins 95 % sur n° de BL, fournisseur, date et chantier brut ; au moins 90 % des lignes ; aucune erreur silencieuse).

**Point de départ dans le code** :
- `extract/ocr.py` (`texte_ocr`, `detecter_numero_bl`) ;
- `extract/unikalo.py` (modèle de parseur par fournisseur) ;
- `ingest/mistral.py` (`ocr_document`) ;
- `ingest/depot_telegram.py` (`traiter_fichier` : le document est commité avant l'OCR, `ocr_brut` est stocké) ;
- colonnes déjà présentes : `document.confiance_min`, `chantier_alias`, `article`, `ligne.qte_fact` ;
- dossiers `normalize/` et `rules/` prévus par l'architecture mais pas encore créés ;
- dette à reprendre dans `docs/dette.md` (confiance réduite, avoirs, normalisation des numéros de BL, tâche de fond perdue si le process meurt après le 200).

**Avant de commencer le lot 3** :
1. corriger L2-R10 ;
2. relire `docs/dette.md` ;
3. vérifier la disponibilité des 30 photos réelles.

Sans elles, le livrable du lot 3 ne peut pas être mesuré : construire tout ce qui ne dépend pas d'elles et consigner le blocage.

**Lots suivants** (CDC §11) :
- 4 — Rapprochement : blocs et lignes, unités, avoirs, règles R01 à R17, écran Anomalies (le trim/strip des numéros est déjà aligné) ;
- 5 — Restitution : Chantiers & fournisseurs, Bilan mobile, CSV, Drive, journal, seuils ;
- 6 — Livraison.
