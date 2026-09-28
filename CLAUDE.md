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

**Depuis le 27/09/2026 : lire d'abord `docs/roadmap-octobre-2026.md`.**
Demandes d'octobre du client (phases 1 à 4), organisation git (plus aucun
commit direct sur `main` : branches `feature/…` → PR vers `dev` ; `dev` →
`main` seulement avec l'accord d'Ilane), deux sessions Claude Code en
parallèle (worktrees, base de test par session, verrou commun sur les tests),
numéros réservés (migrations, règles, réglages) et zones de conflit.

**Phase 1 (mise en production du 1er octobre)** faite sur `feature/mise-en-prod-1-octobre` le 27/09/2026 (rattachement automatique des chantiers, R18, fusion, reprise, photos rangées, comptes, journal, livraisons conformes) : recette et procédure de déploiement dans `docs/mise-en-production-1er-octobre-recette.md` (ordre : migration 0011, `rattacher-chantiers`, puis `ranger-photos`).

Lots 1 (Socle), 2 (Collecte), 3 (Extraction), 4 (Rapprochement) et 5
(Restitution) faits et **fusionnés dans `main`** (lot 4 le 18/09/2026, lot 5
le 20/09/2026 par avance rapide jusqu'à `a550e8f`). L5-T1 à L5-T12 sont
commitées et relues.

**Refonte du front fusionnée dans `main` le 23/09/2026** (branche
`refonte-front`, 48 commits) : les 14 écrans techniques sont remplacés par
cinq écrans (Vue d'ensemble, À régler, Chantiers, Fournisseurs, Documents +
page BL) plus Réglages/Journal, navigation téléphone à barre basse, aucun
jargon visible. Quatre ajouts serveur seulement (client du chantier,
tableau de bord du mois, téléchargement nommé + comparaison d'un BL, compte
unique des problèmes à régler). Construite en une journée, relue tâche par
tâche puis par une revue finale à 6 angles (85 constats, 19 confirmés, tous
corrigés et revérifiés). **Déployée le jour même sur les deux instances**
(démo et production, migration `0010`). Détail complet, décisions à valider
par Ilane et points ouverts (Drive, secrets à tourner, sauvegardes/crons à
poser) : `docs/refonte-front-recette.md`.

Les derniers contrôles connus sur le lot 5 (après L5-T11) étaient verts
après les corrections finales : 1 362 tests, Ruff, formatage, mypy,
typecheck et build front. La revue finale et la relecture des corrections ont
rendu un verdict vert. **Avant tout
travail, lire
`docs/passation-lot-5.md`** (état, décisions, questions ouvertes, méthode et
point de départ suivant), `docs/refonte-front-recette.md`, `docs/lot-5-recette.md`
et `docs/dette.md`, puis les passations précédentes si nécessaire. Recettes :
`docs/lot-1-recette.md` à `docs/lot-5-recette.md`, puis
`docs/refonte-front-recette.md`.

Points à retenir :
- La facture fournie est un scan : les factures sont lues via l'OCR Mistral
  puis `extract/unikalo.py` (décision R16 du lot 3, à valider par Ilane).
- **Lot 3 bloqué sur des fichiers manquants**, toujours vrai au lot 4 :
  seules 4 photos réelles de BL sont disponibles (30 dont 10 dégradées
  exigées par le CDC §10) ; le parseur de facture Point.P n'est pas
  construit (aucun document disponible) — bloque aussi tout rapprochement
  avec ce fournisseur. Marche à suivre dès réception des photos :
  `docs/protocole-mesure-ocr.md`.
- **Lot 4 : rapprochement, moteur de règles (R01 à R17) et écran Anomalies
  faits.** Verdicts réels sur la facture d'août (28 blocs : 3 reçus, 4
  « pas de bon », 21 non reçus ; 25 anomalies), **non confirmés par Ilane**
  (Q6, détail `docs/lot-4-recette.md` §4) ; semi-remorque non construite,
  aucun déclencheur défini (Q1) ; historique de prix jamais exercé sur des
  données réelles (un seul mois disponible).
- **Lot 5 : Bilan, export CSV, navigation, référentiels, journal, réglages et
  synchronisation Drive fusionnés dans `main`.** Les quatre définitions
  monétaires et le classement d'août restent à confirmer par Ilane. Drive
  reste bloqué : le compte de service ne peut pas écrire sur un Drive
  personnel, il faut un Drive partagé Google Workspace ou basculer en OAuth
  (détail `docs/refonte-front-recette.md` §6). L'application est déployée
  depuis le 23/09/2026 (démo et production), mais aucun cron ni sauvegarde
  restic n'est encore posé sur ces deux instances.
- L2-R10 (contrôle d'origine bloquant les POST via `npm run dev`) est
  résolu depuis le lot 3 (L3-D21, proxy Vite qui réécrit `Origin`).
- Ne jamais lancer `pre-commit install` depuis un worktree (hooks partagés).
- **Contrôles de prix R07/R08/R09 et R06 (« Livré mais pas facturé »)
  désactivés côté serveur depuis le 24/09/2026** (décisions d'Ilane, même
  jour) — `CONTROLE_PRIX_ACTIF` et `CONTROLE_LIVRE_NON_FACTURE_ACTIF`,
  détail `docs/dette.md` et `docs/refonte-front-recette.md`.
- **Optimisations rapidité et sécurité du 25/09/2026 fusionnées dans `main`
  et déployées le jour même** (nginx, démo puis production, dumps
  `avant-optimisations-*` dans `~/sauvegardes-habitat/`) : documents en
  0640/0750, signature et taille des fichiers Telegram vérifiées, en-têtes
  nginx complétés et zone `login`, conteneurs durcis, cache immutable des
  `/assets`, `staleTime` de 30 s côté front, N+1 des alias corrigé, suite de
  tests accélérée. Reporté et contexte : `docs/dette.md` (« Optimisations du
  25/09/2026 »). Le serveur actuel est un serveur perso/de dev provisoire ;
  la cible est un serveur dédié au client (seul Ilane y aura un compte).
- **Phase 4 IA construite sur `feature/phase-4-ia`, IA éteinte** (T1 à T9,
  27-28/09/2026) : synthèse hebdomadaire des commentaires, explication des
  alertes prix et prix trouvé sur internet, conteneur OpenCode (client
  `ingest/opencode.py`) connecté à l'abonnement ChatGPT personnel d'Ilane —
  tout est construit et testé sans lui, `IA_ACTIVE=false` par défaut.
  Explication et prix internet restent sans objet tant que le lot Prix
  n'est pas fusionné (R07-R09 masquées, R22 pas encore fusionnée dans `dev`
  — elle existe sur la branche du lot Prix) ; la 3ᵉ colonne « Internet » de
  `/prix` attend cette fusion (T10). Avenant CDC §15 à confirmer par Ilane.
  Guide d'exploitation, connexion de l'abonnement, essai avant de se fier
  au prix internet : `docs/phase-4-ia.md`.

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
