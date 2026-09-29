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
    rules/     engine.py, rules/R01.py … R17.py, tests           ← PUR
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

**État au 29/09/2026.** Lire d'abord `README.md` (documentation globale à
jour : périmètre livré, état exact des demandes du client, audit, limites),
puis `docs/roadmap-octobre-2026.md` (demandes de la réunion du 26/09,
organisation git, phases 1 à 4, suivi), `docs/dette.md` et, avant de toucher
l'IA, `docs/phase-4-ia.md`.

- **Livré et en production (28/09/2026, étiquette `mise-en-prod-octobre-2026`,
  migration `0014`)** : lots 1 à 5, refonte du front (23/09), optimisations de
  sécurité (25/09), phases 1 à 4 d'octobre (chantiers rattachés
  automatiquement, R18, comptes, photos rangées, commentaires sur les lignes,
  grilles de prix, contrôle des prix des bons R19-R25, IA). En production,
  l'IA est **éteinte** (`IA_ACTIVE=false`) et le contrôle des prix des bons
  est **éteint** (interrupteur `prix_controle_bl_actif`) tant que les grilles
  ne sont pas chargées. R06 à R09 restent désactivées côté serveur.
- **Dans `dev`, pas encore en production** : Laboratoire IA (`/ia`), correctifs
  de l'IA, Entrée enregistre un commentaire, prix internet par marque, nom et
  format, jusqu'à cinq sources en HT (migration `0015`), dépendances à jour
  (PR #9 à #14). La démo porte `dev` jusqu'à la PR #13, IA allumée.
- **IA gelée par Ilane le 29/09** : aucune évolution de l'IA sans son accord ;
  OpenCode reste en 1.18.32, modèle `gpt-5.6-sol`, compte ChatGPT d'Ilane.
- **Audit complet du 29/09** : 0 critique, 13 importants confirmés, les autres
  mineurs ou latents (README §20 ; mineurs dans `docs/dette.md`). Décisions
  d'Ilane : « Conforme » strict partout, facture à somme incohérente comptée
  avec mention et R10 dans « À régler », chantiers ne différant que par un
  numéro jamais rattachés automatiquement. **Corrections en cours** sur
  `feature/corrections-audit` (groupe 1, rejeu des recalculs, en relecture ;
  groupes 2 à 5 à faire) ; puis PR vers `dev`, démo, et passage de `dev` en
  production avec l'accord d'Ilane (sauvegarde, migration `0015`, image
  OpenCode, API).
- **Pas fait** : lot 6 (recette sur deux mois, formation, procès-verbal),
  lecteur de factures Point.P, mesure de l'OCR sur 30 photos (4 disponibles),
  Drive (bloqué : Drive partagé Workspace ou OAuth), contrôle des prix à la
  facture, sauvegardes hors du serveur (dépôts restic locaux), serveur dédié
  au client (le serveur actuel est provisoire), supervision (canal Telegram
  supprimé le 28/09 ; scripts de `feature/exploitation-2` non validés).
- **Organisation** : plus aucun commit direct sur `main` ; branches
  `feature/…` → PR vers `dev` ; `dev` → `main` seulement avec l'accord
  d'Ilane ; déploiements depuis l'arbre dédié `habitat_reno-prod`. Détail :
  `docs/roadmap-octobre-2026.md` §2.
- **Tests** : 2 699 collectés le 29/09/2026 ; ruff, mypy strict, typecheck et
  build du front verts à chaque commit (hooks pre-commit, ne jamais utiliser
  `--no-verify`, ne jamais lancer `pre-commit install` depuis un worktree).
- **Décisions d'Ilane qui font foi** : `docs/roadmap-octobre-2026.md` §1.2, avenants
  du cahier des charges §14 et §15 (le §15, IA, reste « à confirmer »), README
  §20.3 pour l'audit.

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
