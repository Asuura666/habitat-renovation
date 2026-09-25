# Déployer et tester « Contrôle BL & factures »

Guide opérationnel pour le projet Habitat & Rénovation. Il couvre :

- la préparation d'un environnement local de test ;
- les contrôles qualité et la suite automatisée ;
- un premier déploiement avec Docker Compose ;
- la mise à jour d'une installation existante ;
- les vérifications après déploiement ;
- les tâches planifiées, la sauvegarde et le retour arrière.

Le cahier des charges reste la référence fonctionnelle. Les procédures
spécialisées restent dans :

- `deploy/RESTAURATION.md` pour les sauvegardes et restaurations ;
- `docs/exploitation-lot-4.md` pour les contrôles différés ;
- `docs/exploitation-lot-5.md` pour Google Drive.

## 1. Point de sécurité important sur le VPS actuel

Le fichier `deploy/docker-compose.yml` est conçu pour un hôte où Traefik peut
écouter directement sur les ports **80 et 443**.

Sur le VPS multi-applications actuel, nginx occupe déjà ces ports. Il ne faut
donc **pas** lancer la stack de production telle quelle sur ce VPS : Traefik
échouerait ou entrerait en conflit avec le frontal existant.

Deux scénarios sont possibles :

1. **VPS dédié ou neuf** : utiliser la procédure de production de ce guide ;
2. **VPS actuel avec nginx partagé** : surcouche `deploy/docker-compose.vps.yml`
   (Traefik désactivé, API publiée sur `127.0.0.1:${API_HOST_PORT}`) et virtual
   host `deploy/nginx/habitat.conf` (HTTPS certbot, en-têtes de sécurité repris
   des labels Traefik, `client_max_body_size 25m`). Voir §1.1.

`deploy/docker-compose.dev.yml` publie l'API sur `127.0.0.1:8450` pour le
développement ; ce n'est pas une configuration de production.

### 1.1 Instances en place sur le VPS actuel (depuis le 23/09/2026)

| Instance | Projet compose | Fichier d'env | Port local | URL | Données |
| --- | --- | --- | --- | --- | --- |
| Production | `habitat_prod` | `.env.prod` | 8450 | https://habitat.ellumena.fr | réelles |
| Démonstration | `habitat_demo` | `.env.demo` | 8451 | https://demo.habitat.ellumena.fr | fictives |

Chaque instance a sa base, son volume et son dossier de documents
(`/home/debian/habitat-data/<instance>/docs`, propriété de l'uid 10001 de
l'image). Les fichiers `.env.*` ne sont jamais versionnés. Commandes :

```bash
C="-f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml"
docker compose -p habitat_prod --env-file .env.prod $C build api
docker compose -p habitat_prod --env-file .env.prod $C stop api
docker compose -p habitat_prod --env-file .env.prod $C run --rm -T api alembic upgrade head
docker compose -p habitat_prod --env-file .env.prod $C up -d --wait api
```

(idem avec `habitat_demo` / `.env.demo`). Sur ce VPS, remplacer dans les
sections suivantes `-p habitat_reno --env-file .env -f deploy/docker-compose.yml`
par ces options. `DOMAIN` et `ACME_EMAIL` restent exigés par l'interpolation du
compose même si Traefik ne démarre pas.

Les sauvegardes restic ne sont pas encore configurées pour ces instances
(dépôt et crons à poser, voir §9 et §11).

## 2. Architecture déployée

La stack de production contient :

- `traefik` : terminaison HTTPS et certificat Let's Encrypt ;
- `api` : FastAPI, le build React statique et les commandes CLI ;
- `postgres` : PostgreSQL 18 ;
- le volume Docker `postgres-data` ;
- le volume Docker `traefik-acme` ;
- le répertoire hôte `DOCS_HOST_DIR`, monté dans l'API sous `/srv/docs`.

Seuls les ports 80 et 443 sont publiés en production. PostgreSQL et l'API ne
sont accessibles que sur le réseau Docker interne.

## 3. Prérequis

### 3.1 Production

- Linux 64 bits ;
- Docker Engine et le plugin `docker compose` ;
- un domaine dont l'enregistrement DNS pointe vers le serveur ;
- les ports 80 et 443 libres et autorisés par le pare-feu ;
- suffisamment d'espace pour les images, PostgreSQL, les originaux et une
  restauration temporaire ;
- un utilisateur d'exploitation autorisé à utiliser Docker ;
- les secrets Telegram, Mistral et PostgreSQL ;
- un dépôt restic initialisé pour les sauvegardes ;
- facultativement, un compte de service et un dossier Google Drive partagé.

Vérifications rapides :

```bash
docker --version
docker compose version
df -h
```

### 3.2 Développement et tests hors conteneur

En plus de Docker :

- Python **3.11** ;
- `uv` ;
- Node.js compatible avec le projet (l'image de build utilise Node 24) ;
- npm.

```bash
python3.11 --version
uv --version
node --version
npm --version
```

## 4. Préparer les fichiers et les secrets

Depuis la racine du dépôt :

```bash
cd /home/debian/habitat_reno
cp .env.example .env
chmod 600 .env
```

Remplacer toutes les valeurs factices obligatoires. Ne jamais committer `.env`,
le JSON Google, un token Telegram, une clé Mistral ou un mot de passe.

Variables principales :

| Variable | Usage |
| --- | --- |
| `DOMAIN` | domaine public sans `https://` |
| `ACME_EMAIL` | compte Let's Encrypt |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | base PostgreSQL |
| `DOCS_HOST_DIR` | stockage persistant des originaux sur l'hôte |
| `DATABASE_URL` | connexion locale hors conteneur ; Compose la remplace dans `api` |
| `DOCS_DIR` | `/srv/docs` dans le conteneur |
| `TEST_DATABASE_URL` | base réservée à pytest |
| `TELEGRAM_BOT_TOKEN` | token du bot |
| `TELEGRAM_WEBHOOK_SECRET` | secret vérifié sur le webhook |
| `TELEGRAM_CHAT_BL_ID` | groupe de dépôt des BL |
| `TELEGRAM_CHAT_SUPERVISION_ID` | groupe de supervision |
| `MISTRAL_API_KEY` | OCR Mistral |
| `COOKIE_SECURE` | `true` en production HTTPS, `false` en HTTP local |
| `RESTIC_*`, `AWS_*` | sauvegarde chiffrée |
| `GOOGLE_DRIVE_*` | optionnelles pour l'API, requises par `drive-sync` |
| `CONTROLE_PRIX_ACTIF` | optionnelle, défaut `false` ; active R07/R08/R09 (décision d'Ilane du 24/09/2026, `docs/dette.md`) |
| `CONTROLE_LIVRE_NON_FACTURE_ACTIF` | optionnelle, défaut `false` ; active R06 (décision d'Ilane du 24/09/2026, `docs/dette.md`) |
| `API_DOCS_ACTIVES` | optionnelle, défaut `false` ; sert `/docs`, `/redoc` et `/openapi.json` (désactivées par défaut, constat sécurité du 24/09/2026, `docs/dette.md`) |

Créer le répertoire documentaire avec des droits limités :

```bash
sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 750 /srv/habitat-reno/docs
```

Adapter la commande si `DOCS_HOST_DIR` désigne un autre chemin. Ne jamais lui
donner `/`, `/home`, `/srv`, `/var` ou un autre dossier système global.

Valider la configuration Compose sans démarrer de conteneur :

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml config -q
```

Une sortie vide avec un code 0 signifie seulement que la syntaxe Compose est
valide et que les variables exigées existent. Cette commande ne détecte pas un
mot de passe encore égal à `change-me`, un domaine en `.invalid`, un faux token
Telegram ou une clé factice : contrôler manuellement chaque valeur avant tout
déploiement.

## 5. Tester le projet avant déploiement

### 5.1 Installer les dépendances

```bash
uv sync --frozen
npm --prefix web ci
```

### 5.2 Démarrer PostgreSQL de développement

La surcouche de développement publie PostgreSQL uniquement sur
`127.0.0.1:5450` :

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.dev.yml \
  up -d postgres

docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml \
  -f deploy/docker-compose.dev.yml \
  ps
```

Dans `.env`, `TEST_DATABASE_URL` doit viser une base de test distincte, par
exemple `bl_test`, sur ce port. Pytest crée et migre automatiquement cette base
et une seconde base suffixée `_migrations`. Il échoue explicitement si
PostgreSQL est absent ; les tests de base ne sont jamais ignorés silencieusement.

Ne pas lancer plusieurs suites pytest simultanément contre la même base de test.

### 5.3 Contrôles complets

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q
npm --prefix web run typecheck
npm --prefix web run build
```

Il n'existe pas de script `npm test` dans `web/package.json`. Les contrats du
frontend sont couverts par pytest, le typage TypeScript et le build Vite.

État de référence du 20/09/2026 au commit `d5e47df` de `main` :

- 1 362 tests réussis ;
- Ruff réussi ;
- 215 fichiers conformes au format ;
- mypy réussi sur 182 fichiers ;
- typecheck TypeScript réussi ;
- build Vite réussi, 98 modules transformés.

### 5.4 Test isolé de sauvegarde/restauration

Cette commande crée un projet Compose temporaire, une base et un dépôt restic
locaux, détruit les données inventées, les restaure puis nettoie l'ensemble. Elle
ne cible pas la stack `habitat_reno` :

```bash
./deploy/test-restauration.sh
```

Prérequis : ports locaux `5451` et `8451` libres. Le résultat attendu se termine
par `SUCCÈS` avec comptes SQL identiques, SHA-256 identique et `/health` à 200.

## 6. Premier déploiement sur un VPS dédié

### 6.1 Contrôles avant effet de bord

```bash
cd /home/debian/habitat_reno
git status --short
git log -1 --oneline
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml config -q
```

L'arbre Git doit être propre. Vérifier aussi le DNS et la disponibilité des
ports 80/443 avant de démarrer Traefik.

### 6.2 Démarrer PostgreSQL

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml up -d postgres

docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml ps
```

Attendre que `postgres` soit `healthy`.

### 6.3 Construire l'API et appliquer les migrations

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml build api

docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml run --rm -T api alembic upgrade head
```

Ne pas démarrer l'API sur une base non migrée. Ne pas exécuter automatiquement
`alembic downgrade` en production.

### 6.4 Démarrer la stack

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml up -d

docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml ps
```

Les trois services doivent être démarrés ; `api` et `postgres` doivent devenir
`healthy`.

### 6.5 Créer le premier administrateur

La commande demande le mot de passe deux fois de façon interactive. Ne jamais le
mettre dans la ligne de commande :

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml exec api \
  python -m app.cli utilisateur-creer \
  --email admin@example.invalid \
  --nom "Administrateur" \
  --role admin \
  --agence "Agence principale"
```

Remplacer l'adresse, le nom et l'agence. Ajouter `--telegram-id` uniquement si
l'identifiant numérique réel est connu et autorisé.

### 6.6 Configurer Telegram

Le webhook public attendu est :

```text
https://<DOMAIN>/tg/webhook
```

Configurer le bot Telegram avec ce chemin et le même `secret_token` que
`TELEGRAM_WEBHOOK_SECRET`. Manipuler le token uniquement depuis un poste ou un
gestionnaire de secrets de confiance : ne pas le coller dans un ticket, un log
ou une capture.

## 7. Vérifications après déploiement

### 7.1 État et logs

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml ps

docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml logs --tail=100 api postgres traefik
```

Chercher les redémarrages, erreurs de migration, connexions PostgreSQL refusées,
erreurs de certificat et validations de configuration. Ne jamais recopier des
logs contenant des données client dans un outil externe.

### 7.2 Santé interne

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml exec -T api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read().decode())"
```

Résultat attendu :

```json
{"statut":"ok","base":"ok"}
```

Ce point de santé vérifie uniquement que le processus API répond et que
PostgreSQL est joignable. Il ne prouve ni que la révision Alembic attendue est
appliquée, ni que `DOCS_HOST_DIR` est accessible, ni que Telegram, Mistral ou
Drive fonctionnent. Exécuter aussi les contrôles des §7.4 et §7.5.

### 7.3 Santé HTTPS externe

```bash
curl --fail --show-error --silent \
  "https://<DOMAIN>/health"
```

Vérifier également :

- certificat TLS valide ;
- redirection HTTP vers HTTPS ;
- page de connexion accessible ;
- connexion avec le compte administrateur ;
- absence d'accès aux écrans admin avec un compte agent ;
- en-têtes de sécurité présents ;
- aucun port PostgreSQL ou API publié publiquement.

### 7.4 État des migrations

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml exec -T api alembic current
```

La révision affichée doit être la tête courante des migrations.

### 7.5 Recette fonctionnelle minimale

Utiliser uniquement des données inventées pour cette recette technique :

1. créer un agent de test avec `utilisateur-creer` ;
2. vérifier la connexion et les permissions admin/agent ;
3. créer un chantier et un fournisseur fictifs ;
4. vérifier les écrans Factures, À traiter, Anomalies, Bilan, Chantiers,
   Journal et Réglages ;
5. vérifier les mises en page téléphone et ordinateur ;
6. contrôler un export CSV fictif ;
7. tester le webhook Telegram avec un document synthétique autorisé ;
8. vérifier qu'aucun secret ou contenu documentaire n'apparaît dans les logs.

Un test réel Mistral, Telegram ou Google Drive est un test externe distinct : il
ne doit être lancé qu'avec les accès autorisés et des données explicitement
permises.

## 8. Google Drive

La stack peut fonctionner sans Google Drive. Pour l'activer, suivre
`docs/exploitation-lot-5.md`, partager uniquement le dossier cible avec le
compte de service, puis renseigner les deux variables `GOOGLE_DRIVE_*`.

Premier test limité :

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml exec -T api \
  python -m app.cli drive-sync --limite 1
```

Codes de sortie :

- `0` : aucun échec ;
- `1` : au moins un document a échoué ;
- `2` : configuration Drive absente ou invalide.

Sans identifiants, le code 2 est le comportement attendu. Ne jamais fabriquer
de faux identifiants en production.

## 9. Tâches planifiées

Créer d'abord le dossier de logs :

```bash
mkdir -p /home/debian/habitat_reno/logs
```

**Attention** : la ligne « Sauvegarde nocturne » ci-dessous doit tourner en root, ou
avec un accès en lecture donné explicitement sur `DOCS_HOST_DIR` au compte
qui exécute le cron — jamais un compte hôte ordinaire tel quel. Les
documents y sont écrits par le conteneur `api` en 0640 (dossier 0750),
appartenant à l'uid 10001 (`Dockerfile`, `USER 10001`, tâche T3) ; `backup.sh`
monte ce dossier en lecture seule pour restic avec `-u "$(id -u):$(id -g)"`,
c'est-à-dire l'uid/gid de l'utilisateur **hôte** qui invoque le script —
jamais l'uid 10001. Détail et solutions (root, ou `setfacl` sur
`DOCS_HOST_DIR`) : `deploy/RESTAURATION.md` § « Entrée cron nocturne ».

Après validation du déploiement seulement, configurer une adresse
d'exploitation dans la crontab. `MAILTO` nécessite un MTA fonctionnel. Les
blocs d'échec réémettent la fin du log sur la sortie de cron et conservent le
code non nul :

```cron
MAILTO=ops@example.invalid

# Sauvegarde nocturne
0 3 * * * cd /home/debian/habitat_reno && ./deploy/backup.sh >> /home/debian/habitat_reno/logs/backup.log 2>&1 || { code=$?; tail -n 50 /home/debian/habitat_reno/logs/backup.log; exit $code; }

# Règles différées R06, R14, R15, R16
15 6 * * * cd /home/debian/habitat_reno && docker compose -p habitat_reno --env-file .env -f deploy/docker-compose.yml exec -T api python -m app.cli controles-differes >> /home/debian/habitat_reno/logs/controles-differes.log 2>&1 || { code=$?; tail -n 50 /home/debian/habitat_reno/logs/controles-differes.log; exit $code; }

# Synchronisation Drive — uniquement après recette Drive réelle
10 * * * * cd /home/debian/habitat_reno && /usr/bin/flock -n /tmp/habitat-drive-sync.lock docker compose -p habitat_reno --env-file .env -f deploy/docker-compose.yml exec -T api python -m app.cli drive-sync --limite 100 >> /home/debian/habitat_reno/logs/drive-sync.log 2>&1 || { code=$?; tail -n 50 /home/debian/habitat_reno/logs/drive-sync.log; exit $code; }
```

Remplacer l'adresse factice et provoquer un échec contrôlé pour vérifier la
réception de l'alerte. Sans MTA, brancher le code non nul sur la supervision du
VPS ; la seule présence d'un fichier de log n'est pas une alerte.

Installer aussi `/etc/logrotate.d/habitat-reno` :

```text
/home/debian/habitat_reno/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

Tester avec `logrotate --debug /etc/logrotate.d/habitat-reno`. Surveiller les
codes de sortie, l'espace disque et la rotation. Ne pas planifier Drive avant
la recette réelle et le premier téléversement limité.

## 10. Mettre à jour une installation existante

### 10.1 Avant la mise à jour

1. annoncer une fenêtre d'indisponibilité ;
2. vérifier l'état des conteneurs et l'espace disque ;
3. noter le SHA courant et la révision Alembic ;
4. exécuter et vérifier une sauvegarde ;
5. relever dans la sortie restic l'identifiant exact du snapshot créé et
   consigner ensemble : date UTC, SHA, révision Alembic et snapshot.

```bash
git rev-parse HEAD
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml exec -T api alembic current
./deploy/backup.sh
```

Ne pas poursuivre si la sauvegarde, la configuration Compose ou PostgreSQL est
en erreur. `backup.sh` ne place actuellement aucun SHA Git dans le snapshot :
l'association SHA/révision/snapshot dans le journal d'exploitation est donc
obligatoire pour un rollback fiable.

### 10.2 Construire, arrêter, migrer et redémarrer

Après avoir placé la version validée dans le dépôt :

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml config -q

docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml build api

# Début de la fenêtre d'indisponibilité : l'ancien code ne doit pas servir
# pendant que le schéma change.
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml stop api

docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml run --rm -T api alembic upgrade head

docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml up -d api
```

L'arrêt avant migration est volontaire. Les migrations du projet ne sont pas
déclarées compatibles *expand/contract* avec l'ancienne version de l'API ; les
appliquer pendant que l'ancien conteneur traite des requêtes créerait une course
code/schéma. En cas d'échec de migration, laisser l'API arrêtée et appliquer la
procédure de rollback du §11.2. Une mise à jour sans interruption demanderait
une stratégie de migrations spécifiquement conçue et testée pour cela.

Si le fichier Compose ou l'image Traefik/PostgreSQL a changé, utiliser ensuite
`up -d` sur toute la stack, après lecture du diff d'infrastructure.

Rejouer toutes les vérifications du §7.

## 11. Sauvegarde, restauration et retour arrière

### 11.1 Sauvegarde

La sauvegarde comprend :

- un `pg_dump -Fc` de PostgreSQL ;
- les originaux de `DOCS_HOST_DIR` ;
- un envoi chiffré dans restic ;
- une rétention de 30 sauvegardes quotidiennes et 12 mensuelles.

Procédure complète : `deploy/RESTAURATION.md`.

### 11.2 Retour arrière applicatif avec schéma compatible

Utiliser cette procédure uniquement si l'analyse des migrations confirme que le
schéma courant reste compatible avec l'ancien code. Remplacer `<SHA_PRECEDENT>`
par la valeur consignée avant déploiement :

```bash
cd /home/debian/habitat_reno
test -z "$(git status --porcelain)" || { echo "Arbre Git non propre : rollback refusé" >&2; exit 1; }
git switch --detach <SHA_PRECEDENT>

docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml build api
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml stop api
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml up -d api
```

La garde Git refuse explicitement un arbre non propre : ne pas écraser,
déplacer ou masquer des modifications inexpliquées pour forcer un rollback.

Un schéma n'est déclaré compatible avec l'ancien code qu'après lecture des
migrations appliquées depuis ce SHA et vérification qu'aucune table, colonne,
contrainte ou sémantique attendue par l'ancien code n'a été supprimée, renommée
ou rendue incompatible. En cas de doute ou sans test ciblé, considérer le
schéma incompatible et utiliser la restauration complète.

Vérifier ensuite `docker compose ps`, les logs, `/health`, `alembic current` et
les parcours du §7. Le mode Git détaché reproduit exactement l'ancienne version
sans réécrire `main`; consigner ce rollback avant toute intervention suivante.

Ne pas lancer automatiquement un `alembic downgrade`. Une migration descendante
peut supprimer des colonnes ou des données ; elle nécessite une analyse et une
validation explicites. Si le schéma n'est pas compatible avec l'ancien code,
restaurer ensemble code, base et documents selon le §11.3.

### 11.3 Rollback complet ou restauration sur un VPS neuf

La restauration de la base est destructive. Elle doit utiliser un **snapshot
précis**, pas `latest`, et le SHA qui lui a été associé avant le déploiement.
Si cette association n'existe pas ou est douteuse, arrêter et reconstruire le
contexte avant toute restauration.

Préparer la version exacte et s'assurer qu'un conteneur `api` existe. L'étape
`create api` est indispensable sur un VPS neuf : `restore.sh` termine par
`docker compose start api`, qui ne crée pas un conteneur absent.

```bash
cd /home/debian/habitat_reno
test -z "$(git status --porcelain)" || { echo "Arbre Git non propre : restauration refusée" >&2; exit 1; }
git switch --detach <SHA_ASSOCIE_AU_SNAPSHOT>

docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml up -d postgres
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml build api
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml create api

./deploy/restore.sh <IDENTIFIANT_SNAPSHOT> --confirmer
```

Ici aussi, la garde refuse la restauration si l'arbre contient des changements
inexpliqués.

Lire **entièrement** `deploy/RESTAURATION.md` avant cette commande. Vérifier
l'espace disque : l'ancien et le nouveau dossier documentaire coexistent
pendant la bascule. L'ancien contenu est conservé dans un dossier
`.avant-restauration-*` jusqu'à sa suppression manuelle après validation.

Le script restaure le schéma contenu dans le snapshot puis démarre l'image
préparée. Il ne migre pas automatiquement une sauvegarde ancienne vers un code
plus récent. Après restauration, vérifier que le SHA actif correspond bien au
snapshot, contrôler `alembic current`, `/health`, les comptes de lignes et un
échantillon de documents. Pour revenir ensuite au code courant, traiter cela
comme une nouvelle mise à jour : sauvegarde, arrêt de l'API, build, migration et
redémarrage (§10), jamais un simple changement de code à chaud.

## 12. Arrêt et diagnostic

Afficher l'état :

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml ps
```

Suivre les logs :

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml logs -f api
```

Arrêter sans supprimer les volumes :

```bash
docker compose -p habitat_reno --env-file .env \
  -f deploy/docker-compose.yml stop
```

`docker compose down` retire les conteneurs et le réseau. Ne jamais ajouter
`-v` en production sauf opération destructive explicitement approuvée : cette
option supprimerait les volumes nommés, dont PostgreSQL et les certificats ACME.

## 13. Checklist de réception

- [ ] DNS correct et ports 80/443 libres sur un VPS dédié ;
- [ ] `.env` complet, non versionné et mode 600 ;
- [ ] `DOCS_HOST_DIR` absolu, existant et protégé ;
- [ ] `docker compose config -q` réussi ;
- [ ] sauvegarde restic initialisée et testée ;
- [ ] PostgreSQL `healthy` ;
- [ ] migrations à la tête ;
- [ ] API `healthy` ;
- [ ] `/health` interne et HTTPS renvoient 200 ;
- [ ] certificat TLS valide et redirection HTTP → HTTPS ;
- [ ] premier administrateur créé ;
- [ ] permissions admin/agent vérifiées ;
- [ ] parcours fonctionnels testés avec des données fictives ;
- [ ] webhook Telegram validé avec le secret attendu ;
- [ ] sauvegarde nocturne surveillée ;
- [ ] contrôles différés planifiés ;
- [ ] Drive testé puis planifié uniquement si les accès sont disponibles ;
- [ ] aucune donnée client, clé ou capture réelle dans Git ou les logs partagés ;
- [ ] procédure de retour arrière et snapshot utilisable connus de l'opérateur.
