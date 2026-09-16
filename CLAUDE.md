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

Interdit : n8n, Redis, Celery/RQ, MinIO/S3, Neo4j, Keycloak, LangChain, tout
ORM autre que SQLAlchemy, tout state manager front autre que TanStack Query,
localStorage pour l'auth.

## Architecture — monolithe modulaire

```
app/
  core/        config (fail-fast : variable manquante = refus de démarrer), db, auth, middleware
  modules/
    ingest/    router, service d'orchestration, models, tests
    extract/   pdf.py, ocr.py, tests            ← PUR
    normalize/ fournisseur, chantier, article, unites, tests   ← PUR
    rules/     engine.py, rules/R01.py … R17.py, tests           ← PUR
    api/       routers JSON consommés par le front
    messaging/ base.py (interface), telegram.py, tests
    jobs/      drive_sync, bilan, rappels
  main.py
web/           front (ne pas créer avant le lot 2)
migrations/    alembic
deploy/        docker-compose.yml, traefik, backup.sh, restore.sh, deploy.sh
docs/
```

## Règles de frontière — non négociables

- `extract`, `normalize`, `rules` n'importent ni FastAPI, ni SQLAlchemy, ni
  httpx. Entrées et sorties en dataclasses. Leurs tests tournent sans base ni
  réseau.
- Aucun module métier n'importe un autre module métier. `ingest/service.py`
  est le seul orchestrateur.
- Aucune règle métier dans le front ni dans les routers : le router valide,
  appelle un service, sérialise.
- Chaque règle `Rxx` est une fonction pure qui reçoit des dataclasses et
  retourne `Optional[Anomalie]` avec un champ `detail` contenant toutes les
  valeurs ayant déclenché la règle. Chaque règle a au minimum un test positif
  et un test négatif.
- Ces règles sont vérifiées par `tests/test_frontieres.py` (analyse statique
  des imports via `ast`).

## Périmètre en cours : lot 1 (Socle) uniquement

Ne pas commencer le front, ni les règles, ni le Drive, ni l'auth. L'OCR
n'entre au lot 1 que pour la détection du numéro de BL (tâche T6b, validée
par Ilane).

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
