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

**Doit tourner en root**, ou avec un accès en lecture donné explicitement
sur `DOCS_HOST_DIR` au compte qui exécute le cron (voir l'avertissement
« Permissions de `DOCS_HOST_DIR` » ci-dessous) — jamais un simple
« utilisateur propriétaire du dépôt » depuis le durcissement des
permissions des documents (tâche T3, `a59daa3`).

```cron
0 3 * * * cd /home/debian/habitat_reno && ./deploy/backup.sh >> /home/debian/habitat_reno/logs/backup.log 2>&1
```

`backup.sh` s'arrête avec un code non nul à la moindre erreur (dump,
sauvegarde restic ou rotation) : surveiller le code de sortie du cron
(`MAILTO=` ou une supervision externe), pas seulement le contenu du log.

### Attention — permissions de `DOCS_HOST_DIR` (à vérifier avant de poser ce cron)

Les documents dans `DOCS_HOST_DIR` sont écrits par le conteneur `api` en
0640 (dossier 0750), appartenant à l'uid 10001 (`Dockerfile`, `USER
10001`) — aucun droit de lecture pour « other » (défense en profondeur,
tâche T3). `backup.sh` monte ce dossier en lecture seule dans le conteneur
restic lancé avec `-u "$(id -u):$(id -g)"`, c'est-à-dire l'**uid/gid de
l'utilisateur hôte qui invoque le script**, jamais l'uid 10001 (interne au
conteneur, absent de `/etc/passwd` sur l'hôte). Concrètement : tout compte
hôte autre que root n'a plus accès en lecture à ces fichiers, et
`restic backup` échouera (`permission denied`) dès que le cron tournera
sous un compte non-root (ex. `debian`).

Avant de poser ce cron : soit l'exécuter en root (qui contourne les
vérifications de permissions Unix), soit donner au compte qui l'exécute un
accès en lecture au groupe/uid 10001 sur `DOCS_HOST_DIR`, par exemple :

```bash
setfacl -R -m g:10001:rX -m d:g:10001:rX "$DOCS_HOST_DIR"
```

`deploy/test-restauration.sh` ne détecte pas cette régression : il dépose
son fichier de test directement en bash (`echo ... > "$DOCS_DIR_TEST/..."`)
sous l'utilisateur courant, jamais via l'API/uid 10001, donc jamais avec un
fichier 0640 appartenant à un autre uid.

La rotation (`restic forget --keep-daily 30 --keep-monthly 12 --prune`) est
effectuée par `backup.sh` lui-même après chaque sauvegarde : aucune tâche
cron séparée n'est nécessaire pour la purge.

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
7. Lancer la restauration avec un identifiant de snapshot précis :
   `./deploy/restore.sh <identifiant-snapshot> --confirmer`.
   `latest` est refusé par le script : consigner ensemble,
   avant chaque déploiement, le SHA Git, la révision Alembic et l'identifiant
   du snapshot créé (voir
   `docker run --rm -e RESTIC_REPOSITORY -e RESTIC_PASSWORD [...]
   restic/restic:0.19.1 snapshots`). Le script ne migre pas une sauvegarde
   ancienne vers un code plus récent : le SHA préparé doit être compatible
   avec le schéma du snapshot. Il arrête l'API si elle tourne,
   recrée la base, restaure le dump et les originaux, redémarre l'API et
   vérifie `/health`.
   **Les documents existants ne sont jamais supprimés** : le contenu
   restauré est d'abord préparé dans un dossier frère
   `<DOCS_HOST_DIR>.restaure-<horodatage>`, puis la bascule se fait par
   deux renommages : l'ancien `DOCS_HOST_DIR` devient
   `<DOCS_HOST_DIR>.avant-restauration-<horodatage>` (conservé tel quel),
   et le dossier restauré prend la place de `DOCS_HOST_DIR`. Vérifier le
   résultat puis **supprimer à la main** le dossier
   `.avant-restauration-*` une fois satisfait (il n'est jamais nettoyé
   automatiquement).
   **Espace disque** : la préparation (`cp -a` du contenu restauré dans le
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
  l'ancienne base) ; `DOCS_HOST_DIR` inchangé si l'échec est survenu avant
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
