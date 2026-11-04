# CLAUDE.md

Consignes pour Claude Code sur ce dépôt : projet « Contrôle BL & factures »
pour Habitat & Rénovation. Le cahier des charges complet est dans
`docs/cahier-des-charges.md` et fait foi : si quelque chose n'y est pas, on
ne le construit pas.

## Contexte

Système qui collecte des bons de livraison (photos via Telegram) et des
factures fournisseurs (PDF), extrait leur contenu, les rapproche et signale
des anomalies via des règles déterministes. L'IA extrait et normalise, elle
ne décide jamais. Chaque anomalie porte le nom de sa règle et une
justification chiffrée. Un seul client, une seule instance, un VPS OVH.

## Stack imposée — ne pas discuter, ne pas remplacer

- Python 3.11, uv, FastAPI, Uvicorn, SQLAlchemy 2 async + asyncpg, Alembic,
  PostgreSQL 18
- fastapi-users en transport cookie (argon2), slowapi sur `/login`
- pdfplumber pour les PDF ; OCR via l'API Mistral OCR
- Telegram Bot API en webhook via httpx ; pas de framework de bot
- Front : React 18 + TypeScript + Vite, React Router, TanStack Query,
  Tailwind (extend), types générés par openapi-typescript depuis
  `/openapi.json`. Build copié dans l'image API, servi en StaticFiles. Même
  origine, pas de CORS, pas de JWT.
- Docker + Compose, Traefik, restic. ruff, mypy strict, pytest.
- IA (phase 4, décision d'Ilane du 27/09/2026, avenant §15 à confirmer) :
  OpenCode (`opencode serve`, conteneur interne) et l'abonnement ChatGPT
  d'Ilane ; un seul point d'appel, `ingest/opencode.py` ; l'IA ne décide
  jamais.

Interdit : n8n, Redis, Celery/RQ, MinIO/S3, Neo4j, Keycloak, LangChain, tout
ORM autre que SQLAlchemy, tout state manager front autre que TanStack Query,
localStorage pour l'auth.

## Architecture — monolithe modulaire

```
app/
  core/        config (fail-fast : variable manquante = refus de démarrer), db, auth, middleware
  modules/
    ingest/    router, orchestration (commun, depot_telegram, factures, lecture), mistral,
               opencode.py, ia_synthese.py, ia_prix.py (phase 4, IA), models, tests
    extract/   facture.py, ocr.py, unikalo.py (un parseur par fournisseur),
               reponses_ia.py (schémas IA, phase 4), tests   ← PUR
    normalize/ fournisseur, chantier, article, unites, tests   ← PUR
    rules/     engine.py, rules/R01.py … R25.py (R15 retirée), tests   ← PUR
    api/       routers JSON consommés par le front
    messaging/ base.py (interface), telegram.py, tests
    jobs/      drive.py, drive_sync.py (bilan à la demande dans ingest ;
               rappels R14-R16 via ingest/suivi.py, controles-differes)
  main.py
web/           front React (lot 2)
migrations/    alembic
deploy/        docker-compose.yml, traefik, backup.sh, restore.sh, deploy.sh,
               opencode/ (conteneur IA, phase 4)
docs/
infra/         README.md : documentation technique d'ensemble (demande client, architecture, infra et ses choix)
```

## Règles de frontière — non négociables

- `extract`, `normalize`, `rules` n'importent ni FastAPI, ni SQLAlchemy, ni
  httpx. Entrées et sorties en dataclasses. Leurs tests tournent sans base ni
  réseau.
- Aucun module métier n'importe un autre module métier. Le paquet `ingest`
  est le seul orchestrateur ; `api` et `jobs` (couches d'entrée) n'importent
  que `ingest` et `app.core` (décision L2-D3).
- Aucune règle métier dans le front ni dans les routers : le router valide,
  appelle un service, sérialise.
- Chaque règle `Rxx` est une fonction pure qui reçoit des dataclasses et
  retourne `Optional[Anomalie]` avec un champ `detail` contenant toutes les
  valeurs ayant déclenché la règle. Chaque règle a au minimum un test positif
  et un test négatif.
- Ces règles sont vérifiées par `tests/test_frontieres.py` (analyse statique
  des imports via `ast`).

## Où en est le projet

**État au 04/11/2026.** Lire d'abord `README.md` (à jour au 04/11/2026 :
parcours, écrans, lecture des bons, règles, commandes, déploiement ; l'ancien
README, état au 22/10 avec l'histoire détaillée et l'audit, est archivé dans
`docs/readme-octobre-2026.md`), puis
`docs/roadmap-octobre-2026.md` (organisation git, phases 1 à 4),
`docs/dette.md` et, avant de toucher l'IA, `docs/phase-4-ia.md`.

- **En production** (`habitat.ellumena.fr`) : code `3399c6e` (PR #29),
  déployé le 02/11/2026 à 22 h 27 UTC, migration `0018`. `main` aligné sur la
  production le 04/11 (PR #30, `0f533af`, étiquette `mise-en-prod-2026-11-02`).
  `dev` porte en plus la PR #31 (hôte de démonstration retiré de
  `deploy/nginx/habitat.conf`, fichier déjà identique sur le serveur : rien à
  redéployer). Démo supprimée le 29/10. IA **éteinte** (`IA_ACTIVE=false`) ;
  contrôle des prix des bons **allumé** (réglage `prix_controle_bl_actif`) ;
  R06 à R09 toujours désactivées côté serveur.
- **Lots du 31/10 au 02/11 (PR #26 à #29)** :
  - lot 1 : plus de confirmation des quantités (R15 retirée, migration
    `0017`), commande `resoudre-fournisseurs` ;
  - lot 2 : règles de lecture (seuil de ressemblance d'un chantier à 80 %,
    fournisseur reconnu par SIREN ou TVA, chantier confirmé par ressemblance
    ou par la légende, chantier choisi à la main jamais écrasé, référence de
    commande en secours, lignes jugées sur quantité × prix = montant),
    commande `recalculer-bons` (sans nouvel OCR), bons dans « Livraisons »
    avec la colonne « Facturé », archivage d'une facture, recherche de
    chantier, historique d'un produit (migration `0018`, commande
    `importer-historique-prix`), tuile « Montant des bons du mois » ;
  - lot 3 : montant lu du bon affiché même non facturé, suivi des chantiers
    du mois dans la vue d'ensemble, encart « Factures » sur la fiche
    fournisseur ;
  - lot 4 : commande `fournisseur-fusionner` (« Méridionale Bois et
    Matériaux » fusionné dans Point.P : c'est la société qui exploite Point.P
    dans la région, son nom est en pied de page des bons Point.P), prénoms
    des employés retirés du nom de chantier lu.
- **Grilles de prix chargées en production** : Unikalo, Point.P, Rexel,
  Corudo ; historique Point.P importé depuis le fichier de contrôle d'août.
- **Retour arrière des lots du 31/10 au 02/11** : images
  `habitat_prod-api:avant-2026-10-31`, `:avant-lot2-2026-11-01`,
  `:avant-lot3-2026-11-02`, `:avant-lot4-2026-11-02` et dumps
  `~/sauvegardes-habitat/avant-lot{1,2,3,4}-prod-*.dump`.
- **Attendu du client** : les factures fournisseurs d'octobre en PDF
  (demandées le 04/11), sans lesquelles aucun bon d'octobre ne se rapproche
  d'une facture.
- **Décision du client, pas d'Ilane** (Ilane, 04/11/2026) : le serveur dédié
  et les sauvegardes hors du serveur. En attendant, le serveur actuel reste
  provisoire et les sauvegardes restic sont locales (chaque nuit).
- **Proposition en attente d'Ilane** : ne plus lever « Produit absent de la
  grille » (R22) pour un fournisseur qui n'a aucune grille.
- **IA gelée par Ilane le 29/09** : aucune évolution de l'IA sans son accord ;
  OpenCode reste en 1.18.32, modèle `gpt-5.6-sol`, compte ChatGPT d'Ilane.
- **Audit complet du 29/09 : corrigé et déployé le 30/09** (13 importants,
  `docs/readme-octobre-2026.md` §20, mineurs dans `docs/dette.md`). Reste ouvert : F-04 (aucune
  alerte si une sauvegarde ne s'exécute pas).
- **Pas fait** : lot 6 (recette sur deux mois, formation, procès-verbal),
  lecteur de factures Point.P (aucune facture Point.P reçue), mesure de l'OCR
  selon `docs/protocole-mesure-ocr.md`, Drive (bloqué : Drive partagé
  Workspace ou OAuth), contrôle des prix à la facture, supervision (aucune
  alerte ne sort du serveur ; les scripts de `feature/exploitation-2`, datés
  du 27/09, ne sont pas commités et restent dans l'arbre principal
  `~/habitat_reno`).
- **Organisation** : plus aucun commit direct sur `main` ; branches
  `feature/…` → PR vers `dev`, fusionnées par Ilane ; `dev` → `main` par une
  PR avec commit de fusion, seulement avec l'accord d'Ilane, puis étiquette
  `mise-en-prod-AAAA-MM-JJ` sur ce commit. Déploiements sur le GO d'Ilane
  depuis l'arbre dédié `~/habitat_reno-prod` (détaché sur le commit
  déployé), après un dump dans `~/sauvegardes-habitat/` et une image
  `habitat_prod-api:avant-…`. Détail : `docs/roadmap-octobre-2026.md` §2.
- **Tests** : 3 115 au 04/11/2026 ; ruff, mypy strict, typecheck et build du
  front verts à chaque commit (hook pre-commit : suite complète sous
  `flock /tmp/habitat_reno-tests.lock`, 15 à 20 min ; ne jamais utiliser
  `--no-verify`, ne jamais lancer `pre-commit install` depuis un worktree).
- **Décisions d'Ilane qui font foi** : `docs/roadmap-octobre-2026.md` §1.2,
  avenants du cahier des charges §14 et §15 (le §15, IA, reste « à
  confirmer »), `docs/readme-octobre-2026.md` §20.3 pour l'audit.

## Méthode

- Une tâche = un commit, message en français, préfixé du module (ex :
  `extract: parseur Unikalo, blocs BL et lignes`).
- Tests avant ou avec le code, jamais après. `uv run pytest`,
  `uv run ruff check` et `uv run mypy` doivent passer avant chaque commit.
- Simplicité : si une solution trois fois plus simple couvre 80 % du besoin,
  la prendre et noter ce qu'elle ne couvre pas dans `docs/dette.md`. Pas
  d'abstraction « pour plus tard » sauf `messaging/base.py`.
- Ne pas réinventer ce qui existe dans une bibliothèque de la stack. Ne pas
  remplacer un élément de la stack par autre chose.

## Données

Les fixtures (factures PDF, photos de BL) sont des documents réels d'un
client : elles restent dans `tests/fixtures/`, dans `.gitignore`, jamais dans
un commit, jamais dans un message de log, jamais envoyées à un service autre
que ceux de la stack.

## Commandes usuelles

```bash
uv sync                          # installer les dépendances (dev + runtime)
uv run pytest                    # suite de tests complète
uv run pytest -k <expr>          # tests ciblés
uv run pytest -m db              # tests nécessitant Postgres de dev/test
uv run ruff check                # lint
uv run ruff check --fix          # lint avec corrections auto
uv run ruff format               # formatage
uv run ruff format --check       # vérifie le formatage sans modifier
uv run mypy                      # typage strict (app/ et tests/)
uv run pre-commit install        # installe les hooks git (une fois)
uv run pre-commit run --all-files  # rejoue tous les hooks sur tout le dépôt
```
