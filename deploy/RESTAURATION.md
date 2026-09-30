# Sauvegarde et restauration

Sauvegarde chiffrée (restic) du dump PostgreSQL (`pg_dump -Fc`) et des
originaux (`DOCS_HOST_DIR`, montés dans l'API sur `/srv/docs`). Scripts :
`deploy/backup.sh`, `deploy/restore.sh`. Testés en aller-retour complet par
`deploy/test-restauration.sh` (projet compose isolé, dépôt restic local
jetable — ne touche jamais à la sauvegarde réelle ni à la base de
production).

## Prérequis

- Docker + Docker Compose sur la machine (VPS client).
- `.env` à la racine du dépôt, avec au minimum (voir `.env.example`) :
  `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DOCS_HOST_DIR`,
  `RESTIC_REPOSITORY`, `RESTIC_PASSWORD`, et si `RESTIC_REPOSITORY` est un
  dépôt distant (ne commence pas par `/`) : `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY` (Object Storage OVH, compatible S3).
- La stack `habitat_reno` tourne déjà (`docker compose ... up -d`), au moins
  pour le service `postgres`. Avant une restauration, le conteneur `api` doit
  aussi avoir été créé, même s'il est arrêté : `restore.sh` le vérifie avant
  tout appel à restic, arrêt de service ou modification de la base. Les scripts
  rejoignent le réseau compose (`<projet>_default`, `habitat_reno_default` par
  défaut) pour parler au service `postgres` par son nom.

## Choisir l'instance : développement local, `prod`, `demo`

Les scripts lisent trois variables d'environnement (à passer à l'appel,
jamais dans le `.env`). **Sans elles, ils visent le développement local**
(`.env`, projet `habitat_reno`, sans la surcouche VPS) : sur le VPS, cela
agirait sur la mauvaise base.

| Variable | Rôle |
| --- | --- |
| `HABITAT_RENO_ENV_FILE` | fichier d'environnement de l'instance |
| `COMPOSE_PROJECT_NAME` | projet compose (réseau `<projet>_default`, service `api`) ; sert aussi de nom d'hôte restic |
| `COMPOSE_OVERRIDE_FILE` | `restore.sh` seulement : surcouche VPS (`deploy/docker-compose.vps.yml`), sans laquelle l'API redémarrerait sans son port publié |
| `HABITAT_RENO_SAUVEGARDES_DIR` | `restore.sh` seulement, optionnelle : dossier de la copie de sécurité de la base (défaut `$HOME/sauvegardes-habitat`) |

À lancer depuis `/home/debian/habitat_reno` (ou l'arbre de déploiement de
l'instance), **sans `sudo`** : les scripts n'ont pas besoin d'être root.

```bash
# Production
HABITAT_RENO_ENV_FILE=/home/debian/habitat_reno/.env.prod COMPOSE_PROJECT_NAME=habitat_prod \
  ./deploy/backup.sh
HABITAT_RENO_ENV_FILE=/home/debian/habitat_reno/.env.prod COMPOSE_PROJECT_NAME=habitat_prod \
COMPOSE_OVERRIDE_FILE=deploy/docker-compose.vps.yml \
  ./deploy/restore.sh <identifiant-snapshot> --confirmer

# Démonstration : .env.demo et habitat_demo à la place
# Développement local (installation mono-instance) : aucune variable
./deploy/backup.sh
./deploy/restore.sh <identifiant-snapshot> --confirmer
```

Dans les commandes `docker compose` des étapes ci-dessous, remplacer les
options du développement (`--env-file .env -f deploy/docker-compose.yml`)
par celles de l'instance, comme dans `docs/deploiement-octobre-2026.md` :

```bash
P="-p habitat_prod --env-file .env.prod -f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml"
# démonstration : P="-p habitat_demo --env-file .env.demo -f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml"
# développement local : P="-p habitat_reno --env-file .env -f deploy/docker-compose.yml"
docker compose $P ps
```

## `restic init` (une seule fois, à la création du dépôt)

```bash
set -a; source .env; set +a
docker run --rm \
  -e RESTIC_REPOSITORY -e RESTIC_PASSWORD \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  restic/restic:0.19.1 init
```

Si `RESTIC_REPOSITORY` est un chemin local, ajouter
`-v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY"` (créer le dossier au préalable
avec l'utilisateur courant, sinon Docker le crée en root au premier accès)
et `-u "$(id -u):$(id -g)"` (comme le font `backup.sh`/`restore.sh`, pour
que les fichiers du dépôt restent lisibles/supprimables par un utilisateur
normal) ; les variables `AWS_*` sont alors inutiles.

Ne jamais relancer `init` sur un dépôt déjà initialisé : `restic` refuse et
ne modifie rien, mais autant l'éviter.

## Entrée cron nocturne

Peut tourner sous **n'importe quel compte hôte**, root ou non (voir
« Permissions de `DOCS_HOST_DIR` » ci-dessous — `backup.sh` s'en charge
lui-même depuis le correctif R1 de la revue finale du 25/09/2026).

```cron
0 3 * * * cd /home/debian/habitat_reno && ./deploy/backup.sh >> /home/debian/habitat_reno/logs/backup.log 2>&1
```

`backup.sh` s'arrête avec un code non nul à la moindre erreur (dump,
sauvegarde restic ou rotation) : surveiller le code de sortie du cron
(`MAILTO=` ou une supervision externe), pas seulement le contenu du log.

### Permissions de `DOCS_HOST_DIR`

Les documents dans `DOCS_HOST_DIR` sont écrits par le conteneur `api` en
0640 (dossier 0750), appartenant à l'uid **et** au gid 10001 (`Dockerfile`,
`USER 10001` — Debian crée un groupe de même nom et même gid que l'uid) —
aucun droit de lecture pour « other » (défense en profondeur, tâche T3),
mais le mode 0640 accorde déjà la lecture au **groupe** propriétaire.
`backup.sh` monte ce dossier en lecture seule dans le conteneur restic
lancé avec `-u "$(id -u):$(id -g)"` (l'uid/gid de l'utilisateur hôte qui
invoque le script, jamais l'uid 10001, interne au conteneur, absent de
`/etc/passwd` sur l'hôte) **et** `--group-add 10001` : ce deuxième réglage
ajoute ce gid (fixe, celui de l'image `Dockerfile`, jamais déduit de
`stat` sur `DOCS_HOST_DIR` — ce dossier a pu être créé à la main par un
compte différent avant le premier démarrage du conteneur `api`) comme
groupe supplémentaire du conteneur restic, quel que soit le compte hôte
qui invoque le script. Le mode 0640/0750 déjà en place suffit alors :
aucune ACL (`setfacl`, paquet `acl`) à poser à part sur `DOCS_HOST_DIR`, et
aucune obligation de faire tourner le cron en root.

`deploy/test-restauration.sh` couvre cette régression (constat R1 de la
revue finale du 25/09/2026) : en plus de son fichier de test déposé
directement en bash sous l'utilisateur courant, il dépose un second
fichier avec les droits réels d'un document produit par l'API (0640,
uid/gid 10001) et vérifie qu'il survit à l'aller-retour sauvegarde/
restauration.

La rotation (`restic forget --keep-daily 30 --keep-monthly 12 --prune`) est
effectuée par `backup.sh` lui-même après chaque sauvegarde : aucune tâche
cron séparée n'est nécessaire pour la purge. Pour qu'elle s'applique
réellement, restic doit voir les instantanés comme un seul groupe (même hôte,
mêmes chemins) : `backup.sh` monte donc le dump sous le chemin fixe `/dump`
et fixe `--host <COMPOSE_PROJECT_NAME>` (un nom par instance). Sans cela, le
nom d'hôte aléatoire du conteneur et le dossier temporaire du dump
séparaient chaque instantané dans son propre groupe et rien n'était jamais
supprimé (audit F-01). Les instantanés antérieurs à ce changement gardent
leur ancien groupe et ne sont pas purgés : les lister avec `restic snapshots`
et supprimer à la main les plus anciens (`restic forget <id> --prune`) quand
plusieurs mois de sauvegardes récentes existent.

## Restauration sur un VPS neuf (reprise après sinistre)

1. Installer Docker + le plugin Compose sur le nouveau VPS.
2. Récupérer le dépôt applicatif (`git clone` ou copie) à l'endroit voulu.
3. Créer `.env` à la racine (copie de `.env.example` complétée avec les
   vraies valeurs), en particulier `RESTIC_REPOSITORY`, `RESTIC_PASSWORD`,
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` — ce sont ceux du dépôt
   restic existant, pas de nouvelles valeurs.
4. Créer `DOCS_HOST_DIR` (dossier vide) s'il n'existe pas déjà. `restore.sh`
   refuse de s'exécuter si `DOCS_HOST_DIR` n'est pas un chemin absolu, s'il
   désigne `/` ou un dossier système évident (`/home`, `/srv`, `/etc`,
   `/usr`, `/var`, `/root`, `/tmp`, `$HOME`), ou si son dossier parent
   n'existe pas — vérifier la valeur avant de lancer la restauration.
5. Démarrer uniquement `postgres` (pas encore l'API, la base est vide) :
   `docker compose --env-file .env -f deploy/docker-compose.yml up -d postgres`
   et attendre qu'il soit `healthy` (`docker compose ps`).
6. Vérifier que l'arbre Git est propre **avant** de changer de SHA, puis
   replacer le dépôt sur le SHA associé au snapshot choisi. Ne pas masquer des
   changements avec `reset`, `clean` ou `stash` pendant une reprise : les
   identifier et les traiter explicitement avant de poursuivre.
   ```bash
   test -z "$(git status --porcelain)" || {
     echo "Arbre Git non propre : restauration refusée" >&2
     exit 1
   }
   git switch --detach <SHA-associé-au-snapshot>
   test "$(git rev-parse HEAD)" = "<SHA-complet-associé-au-snapshot>"
   ```
   Construire ensuite l'image API et **créer son conteneur sans le démarrer** :
   `docker compose --env-file .env -f deploy/docker-compose.yml build api`
   puis
   `docker compose --env-file .env -f deploy/docker-compose.yml create api`.
   Cette création est obligatoire sur un VPS neuf : `restore.sh` termine par
   `docker compose start api`, qui ne crée pas un conteneur absent.
7. Lancer la restauration avec un identifiant de snapshot précis (avec les
   variables de l'instance, voir « Choisir l'instance » plus haut) :
   `./deploy/restore.sh <identifiant-snapshot> --confirmer`.
   `latest` est refusé par le script : consigner ensemble,
   avant chaque déploiement, le SHA Git, la révision Alembic et l'identifiant
   du snapshot créé (voir
   `docker run --rm -e RESTIC_REPOSITORY -e RESTIC_PASSWORD [...]
   restic/restic:0.19.1 snapshots`). Le script ne migre pas une sauvegarde
   ancienne vers un code plus récent : le SHA préparé doit être compatible
   avec le schéma du snapshot. **Tous les contrôles ont lieu avant la
   première destruction** : dossier des copies de sécurité utilisable, parent
   de `DOCS_HOST_DIR` présent, snapshot lisible, dump et documents présents
   dans le snapshot, dump valide (`pg_restore --list` dans un conteneur
   jetable). Puis il arrête l'API, **écrit une copie de sécurité de la base
   courante** (`pg_dump -Fc`, droits 600, dans
   `$HABITAT_RENO_SAUVEGARDES_DIR` ou `~/sauvegardes-habitat`, fichier
   `avant-restauration-<base>-<horodatage>.dump` : à conserver tant que la
   restauration n'est pas validée), recrée la base, restaure le dump et les
   originaux, redémarre l'API et vérifie `/health`.
   **Les documents existants ne sont jamais supprimés** : le contenu
   restauré est d'abord préparé dans un dossier frère
   `<DOCS_HOST_DIR>.restaure-<horodatage>`, puis la bascule se fait par
   deux renommages : l'ancien `DOCS_HOST_DIR` devient
   `<DOCS_HOST_DIR>.avant-restauration-<horodatage>` (conservé tel quel),
   et le dossier restauré prend la place de `DOCS_HOST_DIR`. Vérifier le
   résultat puis **supprimer à la main** le dossier
   `.avant-restauration-*` une fois satisfait (il n'est jamais nettoyé
   automatiquement).
   **Droits** : la copie et les renommages se font dans un conteneur root
   jetable (`deploy/basculer-documents.sh`), pas avec les droits de
   l'opérateur : les documents restaurés sont rendus à l'uid/gid 10001 de
   l'API (dossiers 0750, fichiers 0640) et le parent de `DOCS_HOST_DIR` peut
   appartenir à root. L'ancien dossier `.avant-restauration-*` garde ses
   propriétaires (uid 10001) : le supprimer avec `sudo rm -rf`, ou avec
   `docker run --rm -v <parent>:<parent> postgres:18 rm -rf <dossier>`.
   **Espace disque** : la préparation (copie du contenu restauré dans le
   dossier frère, avant les deux renommages) a besoin, le temps de la
   bascule, de deux fois l'espace occupé par les documents sur le disque
   du parent de `DOCS_HOST_DIR` (l'ancien contenu et la copie restaurée
   coexistent jusqu'à la suppression manuelle du `.avant-restauration-*`) :
   vérifier l'espace disponible avant de lancer une restauration sur un
   volume déjà proche de sa capacité.
8. Effectuer tous les contrôles post-restauration avant de supprimer l'ancien
   dossier documentaire :
   - **SHA actif** : `git rev-parse HEAD` doit être exactement le SHA complet
     associé au snapshot ;
   - **schéma** : comparer
     `docker compose --env-file .env -f deploy/docker-compose.yml exec -T api alembic heads`
     et la révision indiquée par la même commande avec `alembic current` ; la
     révision courante doit être l'unique tête attendue ;
   - **comptes de lignes** : les comparer au relevé consigné avec le snapshot.
     Pour obtenir des comptes exacts sur toutes les tables publiques :
     ```bash
     set -a; source .env; set +a
     docker compose --env-file .env -f deploy/docker-compose.yml exec -T postgres \
       psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
     SELECT format(
       'SELECT %L AS table, count(*) AS lignes FROM %I.%I;',
       schemaname || '.' || tablename, schemaname, tablename
     )
     FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename \gexec
     SQL
     ```
   - **documents** : vérifier la présence, l'ouverture et le SHA-256 d'un
     échantillon consigné avant sinistre (plusieurs formats et fournisseurs),
     par exemple `sha256sum "$DOCS_HOST_DIR/<chemin-consigné>"` ; ne pas se
     limiter au nombre de fichiers ;
   - **recette minimale avec données fictives uniquement** : `/health` interne
     puis HTTPS doivent répondre, la page de connexion doit être accessible,
     les connexions admin/agent et leurs permissions doivent être correctes,
     et les écrans Factures, À traiter, Anomalies, Bilan, Chantiers, Journal et
     Réglages ainsi qu'un export CSV fictif doivent être vérifiés. Suivre
     `docs/deploiement-et-tests.md` §7 pour le détail ; les appels Mistral,
     Telegram ou Drive réels restent des tests externes séparés et autorisés.
   Contrôler aussi que Traefik démarre correctement (ports 80/443 libres sur
   ce VPS neuf — voir la mise en garde plus bas, propre au VPS de
   développement).
9. Reconfigurer la sauvegarde nocturne (cron) sur ce nouveau VPS.

## En cas d'échec pendant la restauration

`restore.sh` installe un gestionnaire d'erreur (`trap ... ERR`) en plus du
nettoyage habituel (`trap ... EXIT`) : si une étape échoue (ex. `pg_restore`
à mi-chemin), le script affiche avant de s'arrêter :

- la ligne et la commande en échec, et son code de sortie ;
- l'état probable laissé : API arrêtée, base `POSTGRES_DB` possiblement
  vide ou partielle (elle a été recréée avant `pg_restore` : un échec de
  `pg_restore` laisse donc une base vide ou partiellement restaurée, pas
  l'ancienne base, qui reste dans la copie de sécurité
  `avant-restauration-<base>-<horodatage>.dump`, restaurable avec
  `pg_restore --no-owner` dans une base recréée : voir « Retour arrière
  avec la copie de sécurité » ci-dessous) ; `DOCS_HOST_DIR` inchangé si l'échec est survenu avant
  la bascule des documents, ou déjà basculé s'il est survenu après ;
- les chemins à vérifier manuellement :
  `<DOCS_HOST_DIR>.avant-restauration-<horodatage>` (ancien contenu,
  présent seulement si la bascule a eu lieu) et
  `<DOCS_HOST_DIR>.restaure-<horodatage>` (résidu possible d'une bascule
  interrompue en cours de copie/renommage) ;
- la commande de reprise : relancer `./deploy/restore.sh <même
  snapshot> --confirmer`. C'est idempotent — la base est de toute façon
  recréée depuis zéro à chaque tentative. La garde anti-résidu compare par
  motif (`.avant-restauration-*`, `.restaure-*`), pas par nom horodaté
  exact : un résidu `.restaure-*` (bascule précédente interrompue en cours
  de copie/renommage, état incertain) **bloque** toujours la relance —
  l'inspecter puis le supprimer à la main avant de relancer. Un résidu
  `.avant-restauration-*` (ancien contenu d'une restauration précédente
  déjà réussie, volontairement conservé) n'empêche pas de relancer ; il est
  seulement signalé, à supprimer à la main une fois vérifié.

### Retour arrière avec la copie de sécurité

Si la restauration a échoué ou si le mauvais snapshot a été choisi, remettre
la base d'AVANT dans l'instance avec la copie
`avant-restauration-<base>-<horodatage>.dump`. **Garder la première copie
de sécurité** : une relance de `restore.sh` après un échec écrit une
nouvelle copie, celle de la base partielle ou vide (si la base est absente,
la relance n'en écrit aucune, et l'affiche). La copie utile est donc la
plus ancienne (`ls -1 "$SAUVEGARDES_DIR"/avant-restauration-<base>-*`), ne
jamais la supprimer avant validation.

```bash
# Depuis /home/debian/habitat_reno, sans sudo. Production ; démonstration :
# ENV=.env.demo et PROJET=habitat_demo à la place.
ENV=/home/debian/habitat_reno/.env.prod
PROJET=habitat_prod
P="-p $PROJET --env-file $ENV -f deploy/docker-compose.yml -f deploy/docker-compose.vps.yml"
COPIE=/home/debian/sauvegardes-habitat/avant-restauration-<base>-<horodatage>.dump
# (ou $HABITAT_RENO_SAUVEGARDES_DIR/... si cette variable était positionnée)

# Le mot de passe est lu par le shell, jamais affiché ni passé en argument :
# `-e PGPASSWORD` sans valeur fait lire la variable de cet environnement.
set -a; source "$ENV"; set +a
export PGPASSWORD="$POSTGRES_PASSWORD"

docker compose $P stop api
docker run --rm --network "${PROJET}_default" -e PGPASSWORD postgres:18 \
  psql -h postgres -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";" \
  -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"
docker run --rm --network "${PROJET}_default" -e PGPASSWORD \
  -v "$COPIE:$COPIE:ro" postgres:18 \
  pg_restore --exit-on-error --no-owner -h postgres -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" "$COPIE"
docker compose $P start api
```

Puis vérifier `/health` et les écrans. Les documents ne sont pas concernés
par ce retour arrière : si la bascule a eu lieu, l'ancien contenu est dans
`<DOCS_HOST_DIR>.avant-restauration-<horodatage>` (le remettre en place par
deux renommages, avec `sudo` ou un conteneur root jetable).

**Suppression d'un résidu** (`.restaure-*` ou `.avant-restauration-*`) :
ces dossiers appartiennent à l'uid 10001 (voire root) et ne sont pas
supprimables par l'opérateur. Après inspection, avec `sudo` :
`sudo rm -rf <dossier>` ; sans `sudo`, avec un conteneur root jetable qui
monte le parent :
`docker run --rm -v <parent>:<parent> postgres:18 rm -rf <parent>/<dossier>`
(par exemple `<parent>/documents.restaure-<horodatage>`). Un résidu
`.restaure-*` bloque la relance tant qu'il existe.

Sur le VPS de développement actuel, Traefik ne démarre jamais (nginx
occupe déjà 80/443) : `restore.sh` ne touche qu'au service `api`
(`stop`/`start`), jamais à `traefik`, donc la restauration s'y teste sans
conflit de port (voir `deploy/test-restauration.sh`, qui ne démarre que
`postgres` et `api`).

## Rotation du mot de passe restic

Un dépôt restic peut avoir plusieurs clés simultanément : on en ajoute une
nouvelle avant de révoquer l'ancienne, jamais l'inverse.

```bash
set -a; source .env; set +a

# 1. Lister les clés existantes (pour retrouver l'identifiant à révoquer).
docker run --rm -e RESTIC_REPOSITORY -e RESTIC_PASSWORD \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  restic/restic:0.19.1 key list

# 2. Ajouter la nouvelle clé (invite interactive : nouveau mot de passe).
docker run --rm -it -e RESTIC_REPOSITORY -e RESTIC_PASSWORD \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  restic/restic:0.19.1 key add

# 3. Mettre à jour RESTIC_PASSWORD dans .env avec le nouveau mot de passe,
#    puis vérifier qu'une sauvegarde fonctionne avec la nouvelle valeur
#    (./deploy/backup.sh).

# 4. Une fois vérifié, révoquer l'ancienne clé avec son identifiant obtenu
#    à l'étape 1 (RESTIC_PASSWORD dans l'environnement est alors la
#    NOUVELLE valeur, déjà mise à jour dans .env) :
docker run --rm -e RESTIC_REPOSITORY -e RESTIC_PASSWORD \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  restic/restic:0.19.1 key remove <identifiant-ancienne-cle>
```

Pour un dépôt local (chemin commençant par `/`), ajouter
`-v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY"` à chacune des commandes
ci-dessus et omettre les variables `AWS_*`.

## Hors périmètre du lot 1 sur ce VPS

La sauvegarde réelle vers l'Object Storage OVH et une restauration sur un
VPS jetable sont des opérations sur l'infrastructure du client : elles ne
sont pas exécutées depuis ce VPS de développement. Seul l'aller-retour
local (`deploy/test-restauration.sh`, dépôt restic local jetable, projet
compose isolé) est vérifié ici ; le résultat est consigné dans
`docs/lot-1-recette.md`.
