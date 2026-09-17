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
  pour le service `postgres` : `backup.sh` et `restore.sh` rejoignent son
  réseau compose (`<projet>_default`, `habitat_reno_default` par défaut)
  pour parler au service `postgres` par son nom.

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

Exemple (root ou l'utilisateur propriétaire du dépôt, à adapter au chemin
réel) :

```cron
0 3 * * * cd /home/debian/habitat_reno && ./deploy/backup.sh >> /home/debian/habitat_reno/logs/backup.log 2>&1
```

`backup.sh` s'arrête avec un code non nul à la moindre erreur (dump,
sauvegarde restic ou rotation) : surveiller le code de sortie du cron
(`MAILTO=` ou une supervision externe), pas seulement le contenu du log.

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
6. Construire l'image API sans la démarrer :
   `docker compose --env-file .env -f deploy/docker-compose.yml build api`
7. Lancer la restauration :
   `./deploy/restore.sh latest --confirmer`
   (ou un identifiant de snapshot précis à la place de `latest`, voir
   `docker run --rm -e RESTIC_REPOSITORY -e RESTIC_PASSWORD [...]
   restic/restic:0.19.1 snapshots`). Le script arrête l'API si elle tourne,
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
8. Vérifier manuellement `/health` depuis l'extérieur (Traefik/HTTPS) et
   contrôler que Traefik démarre correctement (ports 80/443 libres sur ce
   VPS neuf — voir la mise en garde plus bas, propre au VPS de
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
  recréée depuis zéro à chaque tentative, et la bascule des documents
  refuse de s'exécuter si un `.avant-restauration-*`/`.restaure-*`
  résiduel du run précédent traîne encore (supprimer ce résidu à la main
  après l'avoir inspecté avant de relancer).

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
