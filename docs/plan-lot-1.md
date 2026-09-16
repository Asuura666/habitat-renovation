# Plan — Lot 1 (Socle)

**Objectif :** à la fin du lot, `python -m app.cli bl-non-recus <facture.pdf>` liste les blocs BL d'une facture Unikalo avec « photo reçue : oui/non », d'après les photos reçues par le bot Telegram et stockées en base. Autour : sauvegarde et restauration testées, `/health` prêt à superviser.

**Architecture :** monolithe modulaire FastAPI. `extract` est pur (dataclasses, sans base ni réseau). `messaging` encapsule Telegram derrière `base.py`. `ingest/service.py` est le seul orchestrateur. Un conteneur `api`, un `postgres:18`, `traefik` devant.

**Stack :** Python 3.11, uv, FastAPI, Uvicorn, SQLAlchemy 2 async + asyncpg, Alembic, PostgreSQL 18, httpx, pdfplumber, Docker Compose, Traefik, restic, ruff, mypy strict, pytest.

**Spec :** `docs/cahier-des-charges.md` (fait foi).

---

## 1. Contraintes globales (valables pour chaque tâche)

- Rien qui ne soit pas dans le cahier des charges. Ni front, ni OCR, ni règles, ni Drive, ni auth dans ce lot.
- Interdits : n8n, Redis, Celery/RQ, MinIO/S3, Neo4j, Keycloak, LangChain, autre ORM, localStorage pour l'auth.
- `extract`, `normalize`, `rules` n'importent ni `fastapi`, ni `sqlalchemy`, ni `httpx`. Aucun module métier n'importe un autre module métier, sauf `ingest`.
- Config fail-fast : une variable manquante empêche le démarrage.
- Aucun secret et aucune fixture dans git. Aucune donnée de fixture dans un log ou un message d'assertion.
- Une tâche = un commit en français, préfixé du module. Avant chaque commit : `uv run pytest`, `uv run ruff check`, `uv run mypy` au vert.
- Montants et quantités en `Decimal`, jamais en `float`.

## 2. Constats avant de commencer

1. Le cahier des charges n'est pas à `docs/cahier-des-charges.md` : il est à la racine sous le nom `Cahier des charges — Contrôle BL & factures fournisseurs (Habitat & Rénovation).md`. Je le déplace (`git mv`) dans le commit T1.
2. Le dossier n'est pas un dépôt git (`git init` en T1). Il ne contient aucune fixture.
3. Ce VPS de développement a déjà nginx sur 80/443. Traefik ne peut donc pas y démarrer : j'y valide sa configuration (`docker compose config`), mais il ne tournera réellement que sur le VPS-4 du client.
4. Docker Engine 29.4 est installé. Les Traefik antérieurs à v3.6 ne parlent plus à son API, d'où `traefik:v3.6` épinglé.
5. Hors lot 1, pour mémoire : l'arborescence du CDC cite `R01..R18`, mais le catalogue s'arrête à R17 (la règle semi-remorque n'a pas encore de déclencheur). À trancher au lot 4.

## 3. Questions et réponses

| # | Question | Réponse (2026-09-16) |
| --- | --- | --- |
| Q1 | Comment une photo de BL obtient-elle son numéro au lot 1 ? | **Le numéro doit être détecté dans le BL.** Aucune saisie manuelle, aucune légende. |
| Q2 | Fixtures et lecture de leur contenu dans la session | Fichiers transmis dans la session : facture Unikalo d'août (PDF) et 4 photos de BL (3 Unikalo, 1 Point.P). **Manque la facture de septembre.** |
| Q3 | Sécurisation du VPS, `deploy.sh`, test Telegram | La sécurisation du VPS est **hors lot 1** (faite à part par Ilane). `deploy.sh` est hors lot 1. **Le test Telegram de bout en bout est à faire.** |
| Q4 | Identité git | `Shiro <shiro@openclaw>`, validée. |

**Q5 — option (a), confirmée par Ilane le 2026-09-16 :** « le numéro de BL est écrit tout en haut », « on testera avec l'OCR de Mistral ».
**Question d'origine : conséquence de Q1, l'OCR entre-t-il au lot 1 ?**
Une photo n'a pas de couche texte : détecter le numéro de BL exige l'OCR, prévu au lot 3. Options :
- (a) **Recommandé :** un OCR minimal au lot 1, limité au **numéro de BL et au type** (livraison / enlèvement). Il ajoute une tâche **T6b** (détaillée plus bas). La normalisation, les lignes et les scores de confiance restent au lot 3.
- (b) Pas d'OCR au lot 1. `bl-non-recus` répond alors « non » partout jusqu'au lot 3, et le livrable « photo reçue oui/non » n'est pas atteint.

**Test Telegram de bout en bout (Q3).** Il faut une URL HTTPS publique et un bot de test (token dans `.env`, jamais dans la conversation). Avant T6, je demande sur quelle machine le faire. Si le VPS client n'est pas prêt, je propose un vhost nginx temporaire sur ce VPS, et je ne touche pas à nginx sans ton accord.

Si la facture de septembre manque quand j'arrive à T5, je fais le parseur et ses tests sur août, et septembre est ajouté dès réception.

## 4. Décisions prises (à valider avec le plan)

| # | Décision | Pourquoi |
| --- | --- | --- |
| D1 | Config via `pydantic-settings` | Extension officielle de pydantic (déjà dans la stack via FastAPI). Évite de réécrire la lecture d'environnement. |
| D2 | Tous les `id` en UUID (`gen_random_uuid()`). `telegram_update` a pour clé `update_id`, `parametre` a pour clé `cle`. `chantier_alias` et `rapprochement_ligne` reçoivent aussi un `id` | Le fichier est nommé `<uuid>.<ext>`. Le CDC ne liste que les « colonnes principales ». |
| D3 | Montants et quantités en `numeric` sans précision imposée | Aucun arrondi deviné avant d'avoir vu les factures. |
| D4 | Listes fermées du CDC en `text` + `CHECK`, pas d'`ENUM` Postgres : `role`, `document.type`, `source`, `type_ligne`, `methode`, `gravite`, `anomalie.statut`, `statut_rapprochement` (recu/non_recu/pas_de_bon, nullable). `document.statut` ∈ (recu, a_verifier, archive), étendu par migration aux lots suivants. `agence` en texte libre | Un `CHECK` se modifie simplement en migration, pas un `ENUM`. Le CDC n'a pas de table agence. |
| D5 | `created_at` partout. `updated_at` + `updated_by` partout sauf dans `journal` et `telegram_update` (append-only). `parametre` garde `modifie_par`/`modifie_le` | Section 6 du CDC. |
| D6 | Unicité `chantier_alias (fournisseur_id, libelle_brut, code_brut)` en `NULLS NOT DISTINCT` | Sinon, deux alias identiques sans code passeraient. |
| D7 | `anomalie.detail` : `NOT NULL` + `CHECK (detail <> '{}'::jsonb)` | Invariant « contient toujours les valeurs chiffrées ». |
| D8 | Modèles ORM de toutes les tables dans `app/modules/ingest/models.py`. Migration 0001 autogénérée puis relue ; un test vérifie qu'il n'y a pas de dérive (`alembic check`) | Arborescence du prompt. Une seule source de vérité, contrôlée. |
| D9 | `utilisateur` telle que dans le CDC. L'adaptation fastapi-users (`mdp_hash` ↔ `hashed_password`, `actif` ↔ `is_active`, champs manquants) est reportée au lot 2 | Pas d'auth au lot 1. |
| D10 | La route `POST /tg/webhook` vit dans `ingest/router.py`, pas dans `messaging` | `messaging` ne peut pas importer `ingest`. Il fournit le parsing et le client, `ingest` orchestre. |
| D11 | Réponse Telegram via `reply_parameters.message_id` | Remplaçant officiel de `reply_to_message_id` depuis la Bot API 7.0, même effet. |
| D12 | Tests async via le plugin pytest d'`anyio` (déjà une dépendance), mocks HTTP via `httpx.MockTransport` | Ni pytest-asyncio ni respx à ajouter. |
| D13 | Tests DB sur un vrai `postgres:18` local (`127.0.0.1:5450`, bases `bl_test` et `bl_test_migrations`). Base injoignable = échec explicite, jamais skip. Tests sur vraies fixtures = skip avec raison si les fichiers sont absents (clone neuf), et le nombre de skips est rapporté en recette | Pas d'erreur silencieuse. |
| D14 | La CLI utilise `argparse` (stdlib) et reste en lecture seule : elle parse le PDF sans enregistrer la facture | L'upload de facture est au lot 2. |
| D15 | Au lot 1, le bot accepte tout expéditeur (whitelist au lot 2). `deposant_id` est rempli si `utilisateur.telegram_user_id` correspond, sinon NULL | Seul le lot 2 définit le rattachement. |
| D16 | Dockerfile mono-étage Python (pas de `web/` avant le lot 2), utilisateur non-root. Migration via `docker compose run --rm api alembic upgrade head` | Le multi-étage Node arrive avec le front. |
| D17 | `restic` via l'image `restic/restic` épinglée, sans installation sur l'hôte. La sauvegarde couvre le dump **et** `/srv/docs` | Les originaux font partie des données à restituer (CDC §8). |
| D18 | Un seul `.env` à la racine, lu par l'app (hôte) et par compose (`--env-file .env`). Dans le conteneur, compose reconstruit `DATABASE_URL` vers l'hôte `postgres` | Un seul fichier à maintenir. |

## 5. Structure des fichiers

```
CLAUDE.md                         T1  contraintes du projet
pyproject.toml, uv.lock           T1  deps ajoutées par la tâche qui en a besoin
.python-version, .gitignore       T1
.pre-commit-config.yaml           T1
.env.example                      T2  complété en T3, T6, T8
Dockerfile, .dockerignore         T2
alembic.ini                       T3
app/__init__.py                   T1
app/main.py                       T2 (vide) → T4 (/health) → T6 (routeur)
app/cli.py                        T7
app/core/config.py                T3 (+ vars Telegram en T6)
app/core/db.py                    T3 (+ ping en T4)
app/core/tests/                   T3, T4
app/modules/ingest/models.py      T3
app/modules/ingest/router.py      T6
app/modules/ingest/service.py     T6, T7
app/modules/ingest/tests/         T3, T6, T7
app/modules/extract/pdf.py        T5
app/modules/extract/tests/        T5
app/modules/messaging/base.py     T6
app/modules/messaging/telegram.py T6
app/modules/messaging/tests/      T6
migrations/env.py, versions/0001_schema_initial.py   T3
tests/conftest.py                 T3  fixtures DB partagées
tests/test_frontieres.py          T1  garde des règles d'import
tests/fixtures/README.md          T1  seul fichier suivi du dossier
deploy/docker-compose.yml         T2
deploy/docker-compose.dev.yml     T2  ports 127.0.0.1 pour le dev
deploy/backup.sh, restore.sh      T8
deploy/test-restauration.sh       T8  aller-retour complet en local
deploy/RESTAURATION.md            T8
docs/cahier-des-charges.md        T1  (déplacé)
docs/dette.md                     T1, complété au fil de l'eau
docs/lot-1-recette.md             T9
```

---

## 6. Tâches

### T1 — `outillage: CLAUDE.md, pyproject uv, ruff, mypy strict, pytest, pre-commit`

**Contenu**
- `git init`, `git mv` du CDC vers `docs/cahier-des-charges.md`, ajout de ce plan.
- `CLAUDE.md` : stack imposée, interdits, architecture, règles de frontière, méthode (commits, tests, dette), règles sur les données, commandes usuelles.
- `pyproject.toml` (uv, `requires-python = "==3.11.*"`). Dépendances de dev uniquement : `ruff`, `mypy`, `pytest`, `pre-commit`. Les dépendances runtime arrivent avec la tâche qui s'en sert.
- ruff : `target-version = "py311"`, règles `E F W I B UP SIM RUF ASYNC S`, `S101` autorisé dans les tests.
- mypy : `strict = true`, `files = ["app", "tests"]`.
- pytest : `testpaths = ["app", "tests"]`, marqueur `db`.
- `.gitignore` : `.env`, `tests/fixtures/*` sauf `README.md`, `.venv`, caches.
- `.pre-commit-config.yaml`, hooks locaux via `uv run` : `ruff check`, `ruff format --check`, `mypy`, `pytest`. Deux hooks `language: fail` : l'un bloque tout fichier sous `tests/fixtures/` (hors README), l'autre tout `.env`.
- `docs/dette.md` avec son en-tête.

**Tests**
- `tests/test_frontieres.py`, qui lit les imports de chaque `.py` via `ast` :
  - aucun fichier de `extract/`, `normalize/`, `rules/` n'importe `fastapi`, `starlette`, `sqlalchemy`, `httpx` ou `asyncpg` ;
  - aucun module métier sauf `ingest` n'importe `app.modules.<autre>` ;
  - test négatif du garde : un source synthétique fautif est bien détecté.
- `pre-commit run --all-files` passe. Un `git add` forcé d'un fichier sous `tests/fixtures/` est refusé.

---

### T2 — `deploy: docker-compose traefik, api, postgres 18, .env.example`

**Contenu**
- `deploy/docker-compose.yml`, trois services :
  - `traefik:v3.6` : ports 80/443, redirection HTTP→HTTPS, résolveur Let's Encrypt (`ACME_EMAIL`), provider Docker `exposedByDefault=false`, socket monté en lecture seule, volume pour `acme.json`.
  - `api` : build du `Dockerfile` racine, labels Traefik `Host(${DOMAIN})`, aucun port publié, volume `/srv/docs:/srv/docs`, `depends_on: postgres (service_healthy)`.
  - `postgres:18` : volume nommé monté sur `/var/lib/postgresql` (nouvelle arborescence de l'image 18), healthcheck `pg_isready`, aucun port publié.
- `deploy/docker-compose.dev.yml` : publie `postgres` sur `127.0.0.1:5450` et `api` sur `127.0.0.1:8450`. Sur ce VPS, on lance `up -d postgres` sans Traefik.
- `Dockerfile` : `python:3.11-slim`, uv copié depuis `ghcr.io/astral-sh/uv`, `uv sync --frozen --no-dev`, utilisateur non-root (uid 10001), `uvicorn app.main:app --proxy-headers`.
- `app/main.py` minimal (`FastAPI()`) pour que l'image démarre.
- `.env.example` documenté (rôle, exemple, obligatoire ou non) : `DOMAIN`, `ACME_EMAIL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`.
- Deps ajoutées : `fastapi`, `uvicorn`.

**Tests**
- `docker compose --env-file .env.example -f deploy/docker-compose.yml config` : valide.
- `docker compose ... -f deploy/docker-compose.dev.yml up -d postgres` : `healthy`.
- `docker compose ... build api` : l'image se construit. `docker run` de l'image répond sur `/docs`.
- `grep` : aucun `ports:` sur `postgres`/`api` dans le compose de prod.

---

### T3 — `core: configuration fail-fast, base de données, Alembic et migration 0001`

**Interfaces produites**
```python
# app/core/config.py
class Settings(BaseSettings):          # env_file=".env", aucune valeur par défaut
    database_url: str                  # postgresql+asyncpg://...
    docs_dir: Path
def get_settings() -> Settings         # functools.cache

# app/core/db.py
class Base(DeclarativeBase): ...
def creer_engine(url: str) -> AsyncEngine
def creer_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]
async def get_session(request: Request) -> AsyncIterator[AsyncSession]   # dépendance FastAPI
```
- `app/main.py` appelle `get_settings()` à l'import : sans configuration, uvicorn refuse de démarrer.
- `app/modules/ingest/models.py` décrit les 14 tables de la section 6, avec les décisions D2 à D7.
- `migrations/env.py` en mode async ; l'URL vient de `get_settings()`.
- `migrations/versions/0001_schema_initial.py` : autogénérée, relue, complétée à la main (`CHECK`, `NULLS NOT DISTINCT`) et nommée explicitement.
- `tests/conftest.py` : lit `TEST_DATABASE_URL` (échec explicite si absente ou base injoignable), crée les bases de test si besoin, `alembic upgrade head` une fois par session, `TRUNCATE` de toutes les tables entre les tests.
- `.env.example` : `DATABASE_URL`, `DOCS_DIR`, `TEST_DATABASE_URL`.
- Deps : `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `pydantic-settings`, `anyio` (plugin pytest).

**Tests**
- Config : toutes les variables présentes → OK. Chaque variable manquante → `ValidationError` qui la nomme.
- Démarrage : `python -c "import app.main"` dans un sous-processus à environnement vide → code ≠ 0, le nom de la variable dans stderr.
- Migration (base `bl_test_migrations`) : `upgrade head` → les 14 tables existent. `alembic check` → aucune dérive modèles/base. `downgrade base` → plus aucune table. `upgrade head` repasse.
- Invariants en base :
  - deux `document` de même (fournisseur_id, numero) → `IntegrityError` ; deux avec `numero` NULL → accepté ;
  - deux `chantier_alias` identiques avec `code_brut` NULL → `IntegrityError` ;
  - deux `article` de même (fournisseur_id, code) → `IntegrityError` ;
  - `document.type = 'xyz'` → violation de `CHECK` ;
  - `anomalie.detail = '{}'` → violation de `CHECK`.

---

### T4 — `core: GET /health vérifie la base`

**Interfaces**
```python
# app/core/db.py
async def base_joignable(engine: AsyncEngine, timeout_s: float = 2.0) -> bool   # SELECT 1
```
- `GET /health` → 200 `{"statut": "ok", "base": "ok"}`, ou 503 `{"statut": "ko", "base": "injoignable"}`. Aucun texte d'exception n'est renvoyé.
- Healthcheck du service `api` dans le compose : appel de `/health` en Python via `urllib`.

**Tests**
- Base de test up → 200 et corps attendu.
- Engine pointé vers un port fermé → 503 en moins de 3 s, corps sans détail d'exception.

---

### T5 — `extract: parseur Unikalo, blocs BL et lignes` (attend Q2)

**Interfaces produites**
```python
# app/modules/extract/pdf.py  — n'importe ni fastapi, ni sqlalchemy, ni httpx
class TypeLigne(StrEnum):
    ARTICLE = "article"; ECO = "eco"; COMMENTAIRE = "commentaire"

@dataclass(frozen=True)
class LigneFacture:
    ordre: int
    type_ligne: TypeLigne
    code_article: str | None
    designation: str
    qte_livree: Decimal | None
    qte_totale: Decimal | None
    unite: str | None
    pu_ht: Decimal | None
    pu_cdt: Decimal | None
    remise_pct: Decimal | None
    montant_ht: Decimal | None      # négatif pour un avoir, None pour un commentaire
    tva: Decimal | None

@dataclass(frozen=True)
class BlocBL:
    numero_bl: str
    date_bl: date | None
    numero_commande: str | None
    chantier_brut: str | None
    lignes: tuple[LigneFacture, ...]
    @property
    def montant_ht(self) -> Decimal: ...          # somme des montants non nuls
    @property
    def commentaires(self) -> tuple[str, ...]: ...  # désignations des lignes COMMENTAIRE

@dataclass(frozen=True)
class Facture:
    fournisseur_brut: str
    numero: str
    date_facture: date
    client: str | None
    echeance: date | None
    total_ht: Decimal
    blocs: tuple[BlocBL, ...]

class FactureIllisible(Exception): ...   # pas de couche texte ou structure non reconnue

def extraire_facture_unikalo(chemin: Path) -> Facture
```
La découpe interne sera fixée après lecture des fixtures : texte ligne à ligne ou mots positionnés (`extract_words`) si les colonnes l'exigent. Dans les deux cas, j'isole une fonction d'analyse pure qui prend le texte ou les mots en entrée, pour la tester sur des données inventées. Le module ne journalise rien.

**Tests**
- Synthétiques, avec données inventées (tournent toujours) :
  - nombre au format français `1 234,56` → `Decimal("1234.56")`, et négatif → `Decimal("-…")` ;
  - ligne d'éco-participation → `ECO` ;
  - ligne négative → `ARTICLE` avec montant négatif ;
  - ligne « RETRAIT … PAS DE BON » → `COMMENTAIRE`, sans montant, et présente dans `bloc.commentaires` ;
  - deux blocs « Concerne le B.L. » → deux `BlocBL` avec leurs lignes respectives ;
  - total HT absent → `FactureIllisible` ;
  - PDF sans couche texte → `FactureIllisible`.
- Sur les vraies fixtures (`tests/fixtures/unikalo/*.pdf`, skip si absentes) :
  - par facture, |somme des `montant_ht` de toutes les lignes − `total_ht`| ≤ 0,05 € ;
  - nombre de blocs = nombre d'occurrences de « Concerne le B.L. » dans le texte brut (comptage indépendant) ;
  - chaque bloc a un `numero_bl` non vide et une `date_bl` ;
  - sur l'ensemble des fixtures, au moins une ligne `ECO`, une ligne à montant négatif et une ligne `COMMENTAIRE`.
  - Assertions sur des comptes et des booléens, sans valeur de document dans les messages.
- Deps : `pdfplumber`.

---

### T6 — `messaging: webhook Telegram, dédoublonnage, stockage des documents`

**Interfaces produites**
```python
# app/modules/messaging/base.py
@dataclass(frozen=True)
class FichierEntrant:
    update_id: int
    chat_id: int
    message_id: int
    expediteur_id: int | None
    fichier_id: str
    mime_type: str | None
    nom_fichier: str | None
    compresse: bool                  # True pour une photo Telegram (photo[-1])

@dataclass(frozen=True)
class FichierTelecharge:
    contenu: bytes
    extension: str                   # "jpg", "png", "heic", "pdf", ...

class Messagerie(Protocol):
    async def telecharger(self, fichier: FichierEntrant) -> FichierTelecharge: ...
    async def repondre(self, chat_id: int, message_id: int, texte: str) -> None: ...

# app/modules/messaging/telegram.py
class ErreurTelegram(Exception): ...           # message sans le token
def secret_valide(recu: str | None, attendu: str) -> bool        # hmac.compare_digest
def lire_update(update: dict[str, Any]) -> FichierEntrant | None # None = rien à traiter
class TelegramClient:                           # implémente Messagerie
    def __init__(self, token: str, http: httpx.AsyncClient) -> None
    async def telecharger(self, fichier: FichierEntrant) -> FichierTelecharge  # getFile + /file/bot…
    async def repondre(self, chat_id: int, message_id: int, texte: str) -> None # sendMessage + reply_parameters

# app/modules/ingest/service.py
async def enregistrer_update(session: AsyncSession, update_id: int) -> bool     # INSERT … ON CONFLICT DO NOTHING
async def traiter_fichier(entrant: FichierEntrant, messagerie: Messagerie,
                          sessions: async_sessionmaker[AsyncSession], docs_dir: Path) -> None

# app/modules/ingest/router.py
POST /tg/webhook
```
**Déroulé de `POST /tg/webhook`**
1. En-tête `X-Telegram-Bot-Api-Secret-Token` invalide ou absent → 403.
2. `lire_update` renvoie `None` (texte, sticker, document ni image ni PDF, update sans `message`) → 200, rien n'est écrit.
3. `enregistrer_update` renvoie `False` (update déjà vu) → 200.
4. Sinon, `traiter_fichier` part en `BackgroundTasks` → 200.

**`traiter_fichier`**
1. Télécharge le fichier.
2. Écrit `docs_dir/<uuid4>.<ext>` via un fichier temporaire puis un renommage atomique.
3. Insère le `document` : type `bl`, source `telegram`, statut `recu`, `telegram_message_id`, `deposant_id` selon D15.
4. Commit.
5. Répond « reçu » au message.

En cas d'erreur, aucun document n'est inséré et aucun fichier partiel ne reste. Le log contient l'`update_id` et le type d'erreur, jamais le token ni le contenu.

- Config (T3 complétée) : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` en `SecretStr`, obligatoires.
- Deps : `httpx`.

**Tests `messaging`** (sans base, `httpx.MockTransport`)
- `secret_valide` : bon → True ; mauvais → False ; absent → False.
- `lire_update` :
  - photo en plusieurs tailles → `fichier_id` de `photo[-1]`, `compresse=True` ;
  - document `image/jpeg` → `compresse=False` ; document `application/pdf` → accepté ;
  - document `text/plain` → None ; message texte → None ; update sans `message` → None.
- `telecharger` : appelle `getFile` puis l'URL de fichier attendue, renvoie les octets, extension déduite du type MIME ou du chemin ; `getFile` à `ok=false` → `ErreurTelegram`.
- `repondre` : POST `sendMessage` avec `chat_id`, `text="reçu"`, `reply_parameters.message_id`.
- Erreur HTTP pendant le téléchargement → `str(exception)` ne contient pas le token.

**Tests `ingest`** (base de test, `docs_dir` temporaire, fausse `Messagerie`)
- Secret faux ou absent → 403, aucune ligne en base.
- Update photo valide → 200. Ensuite :
  - 1 `telegram_update` et 1 `document` (telegram, bl, recu, `telegram_message_id`) ;
  - le fichier `docs_dir/<id>.jpg` existe, avec les mêmes octets et `fichier_path` cohérent ;
  - une réponse « reçu » au bon `chat_id`/`message_id`.
- Même `update_id` envoyé deux fois → 1 document, 1 réponse.
- Message texte → 200, aucune ligne, aucune réponse.
- `telegram_user_id` connu d'un `utilisateur` → `deposant_id` rempli ; inconnu → NULL.
- Téléchargement en échec → aucun `document`, aucun fichier dans `docs_dir`, log sans token.

**Test de bout en bout** (exigé par Q3) : `setWebhook` avec `secret_token`, puis une photo, une photo « fichier » et un texte envoyés dans un groupe de test. Vérifications : fichiers présents dans `docs_dir`, lignes en base, réponse « reçu », aucune réponse au texte. Résultat consigné en recette.

---

### T6b — `extract: détection du numéro de BL sur photo (OCR Mistral minimal)` (si Q5 = a)

**Interfaces produites**
```python
# app/modules/extract/ocr.py  — PUR : reçoit le texte OCR, ne fait aucun appel réseau
class TypeBL(StrEnum):
    LIVRAISON = "bl"; ENLEVEMENT = "enlevement"

@dataclass(frozen=True)
class NumeroBL:
    numero: str          # ex. "L200939075589" (Unikalo) ou "9296589304" (Point.P)
    type_bl: TypeBL

def detecter_numero_bl(texte_ocr: str) -> NumeroBL | None

# app/modules/ingest/mistral.py  — client httpx, appelé seulement par ingest/service.py
class ErreurOCR(Exception): ...                                   # message sans la clé API
async def ocr_image(http: httpx.AsyncClient, cle_api: str, contenu: bytes, mime: str) -> dict[str, Any]
def texte_ocr(reponse: dict[str, Any]) -> str                     # concatène pages[].markdown
```
**Complément à `traiter_fichier`, après l'insertion du document**
1. Appel OCR sur le fichier.
2. `ocr_brut` = réponse complète.
3. `detecter_numero_bl` :
   - numéro trouvé → `numero` et `type` remplis, statut `recu` ;
   - non trouvé → `numero` NULL, statut `a_verifier` ;
   - OCR en échec → document gardé en `recu` sans numéro, erreur loguée sans contenu ni clé.

La réponse « reçu » part dans tous les cas : le dépôt est acquis.
- Config : `MISTRAL_API_KEY` obligatoire.

**Tests**
- `detecter_numero_bl` (pur, textes inventés au format observé) :
  - `LIVRAISON N°L…` → type `bl`, numéro avec le `L` ;
  - `Bon d'enlèvement N° …` → type `enlevement` ;
  - espaces ou `°` mal lus (`N°L`, `N° L`, `No L`) → même numéro ;
  - aucun motif → None ;
  - deux numéros différents dans le texte → None (ambigu, donc « à vérifier », jamais deviné).
- `ocr_image` (`httpx.MockTransport`) : bon endpoint, modèle, image en data URI base64, en-tête d'auth ; erreur HTTP → `ErreurOCR` sans la clé dans le message.
- `traiter_fichier` (base de test, faux OCR) : numéro détecté → rempli ; non détecté → `a_verifier` ; OCR en échec → document conservé et réponse « reçu » envoyée.
- Manuel : les 4 photos transmises passent par le vrai OCR, et le numéro attendu est retrouvé pour chacune (comparaison locale, sans afficher le texte OCR).

---

### T7 — `ingest: commande bl-non-recus` (attend Q5 et T5)

**Interfaces**
```python
# app/modules/ingest/service.py
@dataclass(frozen=True)
class BlocReception:
    numero_bl: str
    date_bl: date | None
    chantier_brut: str | None
    montant_ht: Decimal
    photo_recue: bool
async def blocs_avec_reception(session: AsyncSession, facture: Facture) -> list[BlocReception]
def formater_blocs(blocs: list[BlocReception]) -> str     # tableau aligné + ligne de synthèse

# app/cli.py — argparse
python -m app.cli bl-non-recus <facture.pdf>
```
- « Photo reçue » veut dire qu'il existe un `document` de type `bl` ou `enlevement`, de statut différent de `archive`, dont le `numero` vaut `numero_bl` (comparaison exacte après `strip`). La normalisation éventuelle des numéros (zéros de tête, etc.) sera décidée sur les fixtures ; sinon elle relève du lot 3.
- Sortie : `N° BL | Date | Chantier brut | Montant HT | Photo reçue`, puis `N blocs — X reçus — Y non reçus`.
- Codes de sortie : 0 si OK ; 2 si le PDF est illisible (message sur stderr) ; échec fail-fast si la config manque.

**Tests**
- `blocs_avec_reception` (base) :
  - document au bon numéro → oui ;
  - document `archive` → non ;
  - aucun document → non ;
  - document de type `enlevement` → oui ;
  - document de même numéro mais de type `facture` → non.
- `formater_blocs` (pur) : colonnes, « oui »/« non », synthèse exacte.
- CLI : fichier inexistant ou PDF illisible → code 2 ; vraie fixture (skip si absente) → code 0 et une ligne par bloc.

---

### T8 — `deploy: sauvegarde pg_dump + restic, restauration`

**Contenu**
- `deploy/backup.sh` (`set -euo pipefail`) :
  1. charge `.env` ;
  2. `pg_dump -Fc` via `docker run --rm postgres:18` sur le réseau compose ;
  3. `restic backup` (image `restic/restic` épinglée) du dump et de `/srv/docs`, avec tag `nocturne` ;
  4. `restic forget --keep-daily 30 --keep-monthly 12 --prune` ;
  5. suppression du dump temporaire.

  Toute erreur donne un code ≠ 0.
- `deploy/restore.sh <snapshot|latest>` :
  1. refuse de tourner sans `--confirmer` ;
  2. `restic restore` vers un dossier temporaire ;
  3. `docker compose stop api` ;
  4. recrée la base puis `pg_restore` via `postgres:18` ;
  5. restaure `/srv/docs` ;
  6. `docker compose start api` ;
  7. vérifie `/health`.
- `deploy/test-restauration.sh` : aller-retour complet sur ce VPS, dans un projet compose isolé (`-p bl_restore_test`), avec un dépôt restic local et un `docs_dir` temporaire.
- `deploy/RESTAURATION.md`, pas à pas :
  - prérequis, `restic init` (une fois), entrée cron nocturne ;
  - restauration sur un VPS neuf : Docker, dépôt, `.env`, `restore.sh`, vérifications ;
  - rotation du mot de passe restic.
- `.env.example` : `RESTIC_REPOSITORY`, `RESTIC_PASSWORD`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (Object Storage OVH, compatible S3), `DOCS_HOST_DIR`.

**Tests**
- `bash -n` sur les trois scripts.
- `deploy/test-restauration.sh` :
  1. migration ;
  2. insertion de lignes connues et d'un fichier dans `docs` ;
  3. `backup.sh` ;
  4. destruction de la base et des fichiers ;
  5. `restore.sh latest --confirmer` ;
  6. contrôles : mêmes comptes de lignes par table, même sha256 du fichier, `/health` à 200.

  Exécuté une fois, résultat consigné dans la recette.
- `restore.sh` sans `--confirmer` → code ≠ 0, rien n'est modifié.
- Hors de portée du lot sur ce VPS : sauvegarde réelle vers l'Object Storage OVH et restauration sur un VPS jetable. Ce sont des opérations sur l'infra client, consignées en recette quand elles seront faites.

---

### T9 — `docs: recette du lot 1`

- `docs/lot-1-recette.md` :
  - ce qui est fait ;
  - la vérification commande par commande (install, tests, compose, migration, `/health`, webhook, CLI sur les factures d'août et septembre, restauration) ;
  - le nombre de tests skippés et pourquoi ;
  - ce qui manque par rapport au lot Socle du CDC : sécurisation du VPS (faite à part par Ilane), `deploy.sh`, UptimeRobot, restauration sur VPS jetable.
- `docs/dette.md` à jour. Entrées déjà prévisibles :
  - une tâche de fond perdue si le process meurt après le 200 (Telegram ne renverra pas l'update) ;
  - fichiers de plus de 20 Mo non téléchargeables par la Bot API ;
  - bot ouvert à tout expéditeur jusqu'au lot 2 ;
  - photo compressée non marquée en base (aucune colonne prévue dans la section 6).

## 7. Récapitulatif de ce qui est testé

| Zone | Sans base ni réseau | Avec base de test | Manuel / infra |
| --- | --- | --- | --- |
| Frontières d'import | T1 | | |
| Config fail-fast | T3 | | |
| Schéma et invariants | | T3 | |
| `/health` | | T4 | supervision UptimeRobot (hors lot) |
| Parseur Unikalo | T5 synthétique | | T5 vraies fixtures (local) |
| Telegram | T6 (MockTransport) | T6 webhook complet | T6 bout en bout (Q3) |
| CLI `bl-non-recus` | T7 formatage | T7 correspondance | T7 sur août/septembre |
| Sauvegarde / restauration | `bash -n` | T8 aller-retour local | restauration VPS jetable |
