# Recette du lot 1 (Socle) — Contrôle BL & factures

Branche `lot-1-socle`, commits `88825b5..ae63c37` (T1 à T6b, corrections
comprises). Aucune donnée réelle (numéro, chantier, montant, nom) dans ce
document : les résultats sont donnés en comptes et en écarts, jamais en
valeurs.

## 1. Ce qui est fait

| Tâche | Commit(s) | Contenu |
| --- | --- | --- |
| T1 | 911ad55 | Outillage : `pyproject.toml` (uv), ruff, mypy strict, pytest, pre-commit, `tests/test_frontieres.py` (garde des règles d'import). |
| T2 | f8993c0 | `deploy/docker-compose.yml` (traefik/api/postgres 18), `docker-compose.dev.yml`, `Dockerfile`, `.env.example`. |
| T3 | 6b501ff | Config fail-fast (`pydantic-settings`), `app/core/db.py`, 14 tables (`ingest/models.py`), migration Alembic `0001`. |
| T4 | 4a9f0cb + 1876e03 | `GET /health` (vérifie la base, timeout prouvé), healthcheck compose. |
| T5 | b988efa | **Parseur de facture Unikalo** (`extract/unikalo.py`) sur réponse OCR Mistral (voir §2 — écart R16). |
| T6 | d0c8e80 | Webhook Telegram (`POST /tg/webhook`), dédoublonnage des updates, stockage des documents sur disque. |
| T6b | 1e825c9 + ae63c37 | Détection du numéro de BL sur photo (OCR Mistral minimal), branchée dans `traiter_fichier`. |
| T7 | 8db6485 | **Livrable du lot** : `python -m app.cli bl-non-recus <facture.pdf>` — liste les blocs BL d'une facture avec « photo reçue : oui/non ». |
| T8 | cc343e0 | Sauvegarde (`pg_dump` + restic) et restauration, testées en aller-retour local. |
| T9 | (ce commit) | Cette recette. |

**Résultat mesuré sur la facture d'août** (`tests/fixtures/unikalo/facture_2026-08.pdf`, 9 pages scannées) :
- **28 blocs BL sur 28** conformes à une référence établie indépendamment
  (fixture `.attendu.json`, comptée à la main sur le PDF, ignorée par git) :
  numéro de BL, date, chantier brut (après normalisation des espaces) et
  montant HT du bloc identiques à la référence.
- **En-tête de facture conforme** à la même référence (fournisseur, numéro
  de facture, date, client, échéance, total HT).
- Aucune valeur de ces champs n'apparaît dans le code, les tests commités,
  un message de commit ou ce document — seuls les comptes ci-dessus sont
  publics.

## 2. Écarts par rapport au plan et décisions prises en autonomie

**La facture fournie est un scan** (aucune couche texte) : `pdfplumber`,
prévu au plan, ne peut rien en extraire. Deux écarts en découlent, tous deux
validés par Ilane le 2026-09-16 :

- **R16 — lecture par OCR Mistral au lieu de pdfplumber.** Le parseur T5 lit
  la réponse déjà obtenue de l'API Mistral OCR (`table_format: markdown`),
  pas le PDF directement. `pdfplumber` n'a pas été ajouté aux dépendances.
  Si une facture Unikalo en PDF natif arrive (export direct du logiciel de
  facturation), un parseur `pdfplumber` dédié restera à écrire ; le parseur
  OCR reste utile pour les scans.
- **Q5 — l'OCR entre au lot 1**, mais limité à la détection du numéro de BL
  et du type (livraison/enlèvement) sur les photos (tâche T6b, ajoutée au
  plan). La normalisation, les lignes et les scores de confiance restent au
  lot 3.

**Aucun envoi de document client à un service externe cette nuit**, sauf un
unique appel OCR Mistral sur la facture d'août, fait pendant l'exploration
de faisabilité de T5 (Ruling R17) — nécessaire pour trancher entre pdfplumber
et OCR avant de coder le parseur. Ce point a été signalé par le
classificateur de sécurité du harnais (« Data Exfiltration ») ; audité par
le contrôleur : seule destination `api.mistral.ai` (déjà dans la stack
imposée), clé API jamais écrite sur disque, réponse OCR sauvegardée en
fixture locale passée en permissions `600` et ignorée par git. Depuis, plus
aucun appel réseau vers un service externe n'a été fait avec un document
client (le test réel prévu pour T6b sur les 4 photos de BL a été abandonné
cette nuit, reporté ci-dessous en §4).

### Liste des « Ruling » du journal (`progress.md`)

| # | Décision | Coût si faux |
| --- | --- | --- |
| R1 | Travail sur `lot-1-socle` sans worktree dédié (dépôt neuf, aucune autre activité) | Rebase trivial |
| R2 | Briefs construits par `awk` plutôt que par l'outil `task-brief` | Aucun |
| R3 | pytest en `--import-mode=importlib` (tests colocalisés, noms de fichiers pouvant coïncider) | Un réglage à changer dans `pyproject.toml` |
| R4 | Compose T2 : `name: habitat_reno` fixe, `DOCS_HOST_DIR` paramétrable pour T8 | Une ligne de compose à ajouter |
| R5 | Ligne de texte sans code article ni montant → toujours `COMMENTAIRE`, jamais fusionnée à la désignation précédente | Désignations tronquées pour un article réellement coupé sur deux lignes (déjà dans `docs/dette.md`) |
| R6 | `LigneFacture.tva` = taux résolu via le récapitulatif code→taux de la facture | Champ à renommer si la facture n'imprime pas ce récapitulatif |
| R7 | Remise 100 % sans montant imprimé → `montant_ht=None` (pas 0) | Lecture `0` au lieu de `None` à corriger |
| R8 | En-têtes de page répétés ignorés, un bloc continue d'une page à l'autre, tout après « Conditions de règlement » est hors bloc | Parseur à ajuster si septembre a une mise en page différente |
| R9 | Test Telegram de bout en bout **reporté** (pas de vrai bot ni d'URL publique cette nuit) | Aucun — c'est un report, pas une hypothèse |
| R10 | Test OCR réel fait sur une page de la facture PDF (intégration validée : auth, endpoint, parsing) ; test sur les 4 photos de BL **abandonné** cette nuit (R17) | Détection sur vraie photo de BL non prouvée avant le test du matin (§4) |
| R11 | Les tours de correction amendent le commit de la tâche (`git commit --amend`) | Historique moins granulaire, aucun autre coût |
| R12 | Un correctif trivial démarre la tâche suivante en parallèle de sa re-revue ; correction en commit séparé si la re-revue trouve un problème | Un commit « fixup » de plus dans l'historique |
| R13 | `journal.cible_id` en `text` (cible à clé UUID, texte ou bigint selon la table) | Colonne à retyper (`journal` est vide au lot 1) |
| R14 | *(révisé — annulé)* `created_at` ajouté à `journal` et `telegram_update` en plus de `horodatage`/`recu_le`, conformément au CDC §6 | Coût déjà payé : deux colonnes redondantes |
| R15 | T5 exécutée dans un worktree dédié avec son propre Postgres de test, intégrée par cherry-pick | Cherry-pick manuel plus long |
| R16 | Voir ci-dessus (lecture des factures par OCR Mistral) | Parseur natif à ajouter si PDF natif fourni |
| R17 | Voir ci-dessus (aucun autre envoi externe cette nuit) | Vérifications réelles reportées à cette recette (fait, §3/§4) |
| R18 | T8 exécutée dans un worktree dédié avec son propre Postgres de test, intégrée par cherry-pick | Conflit `.env.example` à résoudre à la main |
| R19 | Test de non-régression ajouté sur fixture `<facture>.attendu.json` (critère de recette : 100 % des blocs) | Aucun — test en plus |
| R20 | La restauration ne supprime jamais les documents existants (bascule par renommage) | Espace disque doublé jusqu'au nettoyage manuel du dossier `.avant-restauration-*` |
| R21 | Parseur spécifique Unikalo déplacé dans `extract/unikalo.py` (un parseur par fournisseur, CDC §13) | Un renommage |

## 3. Vérification commande par commande

### Installation

```bash
uv sync
uv run pre-commit install
```

### Configuration

```bash
cp .env.example .env
chmod 600 .env
# éditer .env : remplacer les valeurs "change-me"/"..." par les valeurs de dev
# (voir .superpowers/sdd/plan-lot-1/execution.md pour les valeurs factices
# utilisées cette nuit — jamais affichées ni copiées ici).
```

### Postgres de dev

```bash
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d postgres
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml ps postgres
```

Vérifié aujourd'hui (2026-09-17) : conteneur `Healthy`.

### Migrations

```bash
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml build api
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml run --rm api alembic upgrade head
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml run --rm api alembic check
```

Résultat réel obtenu ce jour : `upgrade head` ne produit aucune opération
(déjà à jour), `alembic check` répond « No new upgrade operations
detected. » — schéma et modèles alignés, pas de dérive.

**Remarque de recette** : une image `api` construite avant l'ajout de
`alembic.ini`/`migrations/` au `Dockerfile` (T8) ne contient pas ces
fichiers ; `docker compose ... up -d api` sans `--build` réutilise alors une
image obsolète et `alembic upgrade head` échoue avec « No 'script_location'
key found in configuration. » (constaté aujourd'hui, corrigé par un
`build api` avant de relancer). Toujours reconstruire l'image après un
changement de code.

### Tests

```bash
uv run pytest -q
```

**Résultat réel, relancé ce jour (2026-09-17), Postgres de dev démarré,
fixtures `facture_2026-08.{pdf,mistral-ocr.json,attendu.json}` présentes :**

```
148 passed in 16.38s
```

**0 skip.** Les seuls tests conditionnés par une fixture réelle
(`pytest.skip` explicite dans `app/modules/extract/tests/test_unikalo.py`
et `tests/test_cli.py`) portent sur la facture d'août, déjà déposée dans
`tests/fixtures/unikalo/` : ils s'exécutent donc, ils ne sont pas skippés
dans ce clone. Sur un clone neuf sans ces fixtures, ces tests skipperaient
avec une raison explicite affichée (jamais un échec silencieux). Aucun test
commité ne dépend des 4 photos de BL (`tests/fixtures/bl/`, absent de ce
clone) : la vérification de la détection OCR sur ces photos est manuelle,
pas automatisée (voir §4).

```bash
uv run ruff check
uv run ruff format --check
uv run mypy
```

Tous verts ce jour (« All checks passed! », formatage conforme, « Success:
no issues found in 45 source files »).

### `/health`

```bash
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d --build api
curl -i http://127.0.0.1:8450/health
```

Résultat réel : `HTTP/1.1 200 OK`, corps `{"statut":"ok","base":"ok"}`.

Arrêt propre après vérification (ne laisse pas tourner l'API de dev en
continu) :

```bash
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml stop api
docker compose --env-file .env -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml rm -f api
```

### CLI `bl-non-recus` sur la facture d'août

```bash
uv run python -m app.cli bl-non-recus tests/fixtures/unikalo/facture_2026-08.pdf
```

**Cette commande appelle réellement l'API Mistral OCR** (clé lue dans
`.env`) : conformément à la Ruling R17 (plus d'appel externe automatique
cette nuit), **elle n'a pas été relancée ici et doit être exécutée par
Ilane**. Sortie attendue : code 0, un tableau `N° BL | Date | Chantier brut
| Montant HT | Photo reçue`, puis `N blocs — X reçus — Y non reçus`. Le
sous-ensemble de tests commité (`tests/test_cli.py`, inclus dans les 148
tests ci-dessus) exécute déjà ce chemin avec la réponse OCR **rejouée**
depuis la fixture locale (aucun appel réseau dans les tests) et vérifie le
code 0 et la cohérence de la synthèse — l'intégration Mistral elle-même
(auth, endpoint, format) a été validée une fois pendant l'exploration de
T5 (R17).

Dès réception de la **facture de septembre**, même commande avec son
chemin :

```bash
uv run python -m app.cli bl-non-recus tests/fixtures/unikalo/facture_2026-09.pdf
```

Aucun test de non-régression n'existe encore pour septembre (pas de
fixture) : à écrire au lot 3 ou dès réception si un ajustement du parseur
est nécessaire (cf. Ruling R8).

### Webhook Telegram — procédure de bout en bout (repris du rapport T6, à faire avec Ilane)

Non exécuté cette nuit (Ruling R9 : pas de vrai bot, pas d'URL HTTPS
publique). Procédure complète pour la matinée :

1. Créer un bot de test via **@BotFather** (`/newbot`), récupérer le token,
   le mettre dans `.env` (`TELEGRAM_BOT_TOKEN`) — jamais dans une
   conversation.
2. Choisir/générer `TELEGRAM_WEBHOOK_SECRET` (chaîne aléatoire), le mettre
   dans `.env`.
3. Démarrer l'API derrière une URL HTTPS publique (VPS client déjà prêt, ou
   vhost nginx temporaire sur ce VPS — **soumis à l'accord préalable
   d'Ilane**, aucune modification nginx faite sans validation).
4. Déclarer le webhook :
   ```bash
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://<domaine>/tg/webhook" \
     -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
   ```
   Vérifier `{"ok": true}` dans la réponse.
5. Créer un **groupe de test** avec le bot ajouté dedans (ou un chat privé).
6. Envoyer, dans ce groupe/chat :
   a. une **photo** (compressée, `photo[]`) ;
   b. la **même image « en fichier »** (document `image/jpeg`/`png`, non
      compressée) ;
   c. un **message texte**.
7. Vérifications après chaque envoi :
   - a. et b. : réponse « reçu » en réponse au message ; un nouveau fichier
     dans `docs_dir` (`ls -la var/docs` en dev, ou le point de montage
     `DOCS_HOST_DIR` en prod) ; une ligne `document`
     (`type=bl, source=telegram, statut=recu`) et une ligne
     `telegram_update` en base pour chaque `update_id` ;
   - c. : **aucune** réponse du bot, aucune nouvelle ligne en base, aucun
     fichier.
8. Rejouer un `update_id` déjà traité (renvoyer la même photo, ou un
   `curl` direct sur `/tg/webhook` avec le même corps et le bon en-tête
   secret) → 200, mais **aucun** nouveau document ni nouvelle réponse
   (dédoublonnage).
9. Consigner ici le résultat : nombre de fichiers dans `docs_dir`, lignes
   `document`/`telegram_update` créées, éventuels écarts.

### OCR — numéro de BL sur photo (T6b)

Détection unitaire déjà testée (textes inventés, 124/148 tests couvrent ce
module et les autres). **Reste à prouver sur les 4 vraies photos** (3
Unikalo, 1 Point.P) :

```bash
# une fois les 4 photos déposées dans tests/fixtures/bl/ :
uv run pytest -m db -k detection_bl_fixtures_reelles -q   # nom indicatif : aucun test de ce
                                                            # type n'existe encore, à écrire
```

Deux façons de fournir les photos : les déposer dans
`tests/fixtures/bl/` (jamais suivi par git, comme le reste de
`tests/fixtures/`), ou les envoyer par Telegram une fois le webhook actif
(procédure ci-dessus) et vérifier `document.numero` en base.

### Sauvegarde / restauration

```bash
./deploy/test-restauration.sh
```

**Relancé réellement ce jour.** Premier essai : échec immédiat —

```
error while interpolating services.api.environment.TELEGRAM_BOT_TOKEN: required variable TELEGRAM_BOT_TOKEN is missing a value: TELEGRAM_BOT_TOKEN manquant
```

**Cause identifiée (anomalie d'intégration, code non modifié dans le cadre
de cette tâche T9) :** `deploy/docker-compose.yml` exige
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_WEBHOOK_SECRET` (ajoutés par T6) et
`MISTRAL_API_KEY` (ajouté par T6b) sur le service `api`, mais
`deploy/test-restauration.sh` a été écrit par T8 dans un worktree branché
**avant** T6/T6b et génère un `.env` de test isolé qui ne fixe que
`DOMAIN`, `ACME_EMAIL`, `POSTGRES_*`, `DOCS_HOST_DIR`, `DOCS_DIR`,
`RESTIC_REPOSITORY`, `RESTIC_PASSWORD`. Le cherry-pick d'intégration (T8 →
`lot-1-socle`, commit `cc343e0`) n'a pas eu de conflit sur ce fichier
(T8 ne touche pas `docker-compose.yml`) et personne n'a rejoué le script
après l'intégration de T6b : la régression est passée inaperçue jusqu'à
cette recette. **À corriger** (hors périmètre de T9 : aucun code touché
ici) : ajouter les trois variables au bloc `cat > "$ENV_FILE"` du script.

**Contournement utilisé pour vérifier réellement le mécanisme aujourd'hui**
(valeurs factices exportées dans le shell, jamais écrites dans le dépôt ;
`docker compose` fait passer les variables déjà exportées avant celles du
`--env-file` généré par le script) :

```bash
export TELEGRAM_BOT_TOKEN="000000:dev-restore-test" \
       TELEGRAM_WEBHOOK_SECRET="dev-restore-test-secret" \
       MISTRAL_API_KEY="dev-restore-test-key"
./deploy/test-restauration.sh
```

**Résultat réel avec ce contournement : SUCCÈS.**

```
test-restauration.sh : SUCCÈS — aller-retour complet vérifié (migration, données inventées,
  backup, destruction, restauration, comptes identiques, sha256 identique, /health 200).
```

Comptes de lignes par table identiques avant/après, sha256 du fichier
`docs` identique, `/health` à 200 après restauration. Nettoyage automatique
en fin de script (`docker compose down -v`, dossier temporaire supprimé) :
vérifié, aucun résidu (`docker ps` ne montre plus que les conteneurs du
projet principal après coup).

Hors périmètre de ce VPS de développement (voir `deploy/RESTAURATION.md`,
§ « Hors périmètre du lot 1 ») : sauvegarde réelle vers l'Object Storage
OVH et restauration sur un VPS jetable — reportées en §4.

## 4. Ce qui manque / à faire avec Ilane

- **Facture de septembre** : non fournie. Le parseur et ses tests n'ont été
  faits que sur août ; à ajouter dès réception (fixture + `.attendu.json`),
  avec vérification des Rulings R5–R8 sur cette deuxième facture (mise en
  page possiblement différente).
- **Test OCR du numéro de BL sur les 4 vraies photos** (3 Unikalo, 1
  Point.P) : à déposer dans `tests/fixtures/bl/` ou à envoyer par Telegram
  une fois le webhook actif. Non fait cette nuit (Ruling R10/R17).
- **Test Telegram de bout en bout** : procédure prête (§3), jamais exécutée
  (pas de vrai bot ni d'URL HTTPS publique cette nuit).
- **Sécurisation du VPS** : hors lot 1, faite à part par Ilane.
- **`deploy.sh`** : hors lot 1, pas commencé.
- **UptimeRobot** (supervision de `/health`) : hors lot 1, pas configuré.
- **Sauvegarde réelle vers OVH Object Storage et restauration sur un VPS
  jetable** : seul l'aller-retour local (`deploy/test-restauration.sh`,
  dépôt restic jetable) a été vérifié (§3). `RESTIC_REPOSITORY`,
  `RESTIC_PASSWORD`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` ne sont
  pas renseignées dans le vrai `.env` du dépôt (aucune valeur, même
  factice) : à faire avant toute sauvegarde nocturne réelle (voir
  `deploy/RESTAURATION.md`, `restic init`).
- **Anomalie à corriger** (non traitée ici, T9 ne touche pas au code) :
  `deploy/test-restauration.sh` échoue tel quel sur un dépôt propre car son
  `.env` de test généré ne fixe pas `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_WEBHOOK_SECRET`, `MISTRAL_API_KEY` désormais exigées par
  `docker-compose.yml` (détail et contournement en §3). À corriger dans le
  script avant de le remettre en cron ou de le rejouer sans contournement
  manuel.
- **Rotation de la clé Mistral** : la clé actuellement dans `.env` a été
  transmise en clair dans la conversation cette nuit (nécessaire pour
  configurer `.env` sans accès direct au secret manager du client) ; à
  révoquer et régénérer côté compte Mistral, puis à remplacer dans `.env`
  dès que possible.
- **Questions ouvertes** : voir §5 ci-dessous.

## 5. Questions pour Ilane

1. **Facture Unikalo en PDF natif** : existe-t-il des factures Unikalo
   envoyées en PDF natif (export direct du logiciel de facturation, par
   e-mail par exemple), ou seul le scan papier est disponible ? Cela
   déterminerait si un parseur `pdfplumber` natif doit être ajouté en plus
   du parseur OCR (R16), et changerait le coût par facture (l'OCR Mistral
   est facturé à l'appel, un PDF natif ne l'est pas).
2. **Validation de la lecture des factures par OCR** : la lecture des
   factures via l'OCR Mistral (au lieu de `pdfplumber`, prévu au plan
   initial) convient-elle définitivement pour le lot 1, ou faut-il revoir
   ce choix une fois une deuxième facture (septembre) disponible ?
3. **Vhost/URL pour le test Telegram** : sur quelle machine faire le test
   de bout en bout — le VPS client est-il prêt (URL HTTPS + DNS), ou faut-il
   un vhost nginx temporaire sur ce VPS de développement ? Dans ce
   deuxième cas, confirmation explicite requise avant toute modification de
   la configuration nginx partagée.
