#!/usr/bin/env bash
# Restauration : restic restore -> recrée la base PostgreSQL (pg_restore) et
# bascule DOCS_HOST_DIR vers le contenu restauré (par renommages, sans
# jamais supprimer l'existant), puis redémarre l'API et vérifie /health.
#
# Ordre (audit F-02, C-02, C-03) : TOUS les contrôles ont lieu avant la
# première destruction : dossier des sauvegardes utilisable, parent de
# DOCS_HOST_DIR présent, snapshot lisible (restic restore), dump et documents
# présents dans le snapshot, dump valide (`pg_restore --list` dans un
# conteneur jetable). Puis : arrêt de l'API, copie de sécurité de la base
# COURANTE (pg_dump -Fc horodaté, droits 600, dans le dossier des
# sauvegardes), et seulement ensuite DROP DATABASE. La bascule des
# documents se fait dans un conteneur root jetable (deploy/basculer-
# documents.sh) : documents rendus à l'uid/gid 10001 de l'API (dossiers
# 0750, fichiers 0640), sans exiger que l'opérateur soit root.
#
# Usage : deploy/restore.sh <identifiant-snapshot> --confirmer
#
# Opération destructive pour la base (recréée) : refuse de s'exécuter sans
# --confirmer, et dans ce cas ne modifie rien. Les documents existants ne
# sont jamais supprimés : l'ancien DOCS_HOST_DIR est conservé à côté sous
# <DOCS_HOST_DIR>.avant-restauration-<horodatage> (voir RESTAURATION.md).
#
# Sécurité : aucun secret (PGPASSWORD, RESTIC_PASSWORD, AWS_*) n'est jamais
# passé en argument à `docker run` (visible via `ps`/`/proc/<pid>/cmdline`
# pour tout utilisateur du VPS) : `-e VAR` sans `=valeur` fait lire à docker
# la valeur dans l'environnement du process appelant (exportée par
# `set -a; source ...`, ou explicitement pour PGPASSWORD).
#
# Variables lues dans le .env à la racine du dépôt (chemin résolu depuis cet
# emplacement, sauf surcharge via HABITAT_RENO_ENV_FILE) :
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, DOCS_HOST_DIR,
#   RESTIC_REPOSITORY, RESTIC_PASSWORD
#   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (seulement si RESTIC_REPOSITORY
#   ne désigne pas un chemin local, c'est-à-dire ne commence pas par "/")
#
# COMPOSE_PROJECT_NAME (optionnel, défaut "habitat_reno") : nom du projet
# compose à arrêter/redémarrer (service "api") et dont on rejoint le réseau
# `<projet>_default`.
# HABITAT_RENO_SAUVEGARDES_DIR (optionnel, défaut $HOME/sauvegardes-habitat) :
# dossier des copies de sécurité de la base courante, créé au besoin (0700).
# COMPOSE_OVERRIDE_FILE (optionnel) : fichier compose additionnel (-f) pour
# adapter les ports publiés (utilisé par test-restauration.sh).
set -euo pipefail

usage() {
  echo "Usage : $0 <identifiant-snapshot> --confirmer" >&2
}

if [[ $# -eq 0 ]]; then
  usage
  exit 1
fi

SNAPSHOT="$1"
shift
CONFIRME=0
for arg in "$@"; do
  case "$arg" in
    --confirmer)
      CONFIRME=1
      ;;
    *)
      echo "restore.sh : argument inconnu ($arg)" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "$SNAPSHOT" == "latest" ]]; then
  echo "restore.sh : identifiant de snapshot précis obligatoire ; 'latest' est refusé. Rien n'a été modifié." >&2
  exit 1
fi

if [[ "$CONFIRME" -ne 1 ]]; then
  echo "restore.sh : opération destructive, relancer avec --confirmer. Rien n'a été modifié." >&2
  exit 1
fi

RESTIC_IMAGE="restic/restic:0.19.1"
POSTGRES_IMAGE="postgres:18"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
ENV_FILE="${HABITAT_RENO_ENV_FILE:-$ROOT_DIR/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "restore.sh : fichier .env introuvable ($ENV_FILE)" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${POSTGRES_USER:?POSTGRES_USER manquant dans $ENV_FILE}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD manquant dans $ENV_FILE}"
: "${POSTGRES_DB:?POSTGRES_DB manquant dans $ENV_FILE}"
: "${DOCS_HOST_DIR:?DOCS_HOST_DIR manquant dans $ENV_FILE}"
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY manquant dans $ENV_FILE}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD manquant dans $ENV_FILE}"

DEPOT_LOCAL=0
if [[ "$RESTIC_REPOSITORY" == /* ]]; then
  DEPOT_LOCAL=1
else
  : "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID manquant dans $ENV_FILE (dépôt restic distant)}"
  : "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY manquant dans $ENV_FILE (dépôt restic distant)}"
fi

# Garde-fous sur DOCS_HOST_DIR avant tout effet de bord : un chemin mal
# configuré (racine, dossier système, chemin relatif) ne doit jamais mener
# à une bascule/suppression catastrophique. Refuse et ne touche à rien.
if [[ "$DOCS_HOST_DIR" != /* ]]; then
  echo "restore.sh : DOCS_HOST_DIR doit être un chemin absolu ($DOCS_HOST_DIR). Rien n'a été modifié." >&2
  exit 1
fi
DOCS_HOST_DIR_INTERDITS=(/ /home /srv /etc /usr /var /root /tmp)
if [[ -n "${HOME:-}" ]]; then
  DOCS_HOST_DIR_INTERDITS+=("$HOME")
fi
for interdit in "${DOCS_HOST_DIR_INTERDITS[@]}"; do
  if [[ "$DOCS_HOST_DIR" == "$interdit" ]]; then
    echo "restore.sh : DOCS_HOST_DIR ne peut pas être un chemin système ($DOCS_HOST_DIR). Rien n'a été modifié." >&2
    exit 1
  fi
done
DOCS_HOST_DIR_PARENT="$(dirname -- "$DOCS_HOST_DIR")"
if [[ ! -d "$DOCS_HOST_DIR_PARENT" ]]; then
  echo "restore.sh : dossier parent de DOCS_HOST_DIR introuvable ($DOCS_HOST_DIR_PARENT). Rien n'a été modifié." >&2
  exit 1
fi

# Dossier des copies de sécurité de la base courante : vérifié ici, avant
# tout appel à docker, pour ne jamais découvrir après le DROP qu'il n'est pas
# utilisable.
SAUVEGARDES_DIR="${HABITAT_RENO_SAUVEGARDES_DIR:-}"
if [[ -z "$SAUVEGARDES_DIR" ]]; then
  if [[ -z "${HOME:-}" ]]; then
    echo "restore.sh : dossier des sauvegardes indéterminé (HOME et HABITAT_RENO_SAUVEGARDES_DIR absents). Rien n'a été modifié." >&2
    exit 1
  fi
  SAUVEGARDES_DIR="$HOME/sauvegardes-habitat"
fi
if [[ "$SAUVEGARDES_DIR" != /* ]]; then
  echo "restore.sh : le dossier des sauvegardes doit être un chemin absolu ($SAUVEGARDES_DIR). Rien n'a été modifié." >&2
  exit 1
fi
if [[ ! -e "$SAUVEGARDES_DIR" ]]; then
  (umask 077 && mkdir -p -- "$SAUVEGARDES_DIR") || true
fi
if [[ ! -d "$SAUVEGARDES_DIR" || ! -w "$SAUVEGARDES_DIR" ]]; then
  echo "restore.sh : dossier des sauvegardes inutilisable ($SAUVEGARDES_DIR : absent ou non inscriptible), la copie de sécurité de la base ne pourrait pas être écrite. Rien n'a été modifié." >&2
  exit 1
fi

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-habitat_reno}"
NETWORK="${PROJECT_NAME}_default"

COMPOSE_ARGS=(-p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$ROOT_DIR/deploy/docker-compose.yml")
if [[ -n "${COMPOSE_OVERRIDE_FILE:-}" ]]; then
  COMPOSE_ARGS+=(-f "$COMPOSE_OVERRIDE_FILE")
fi

# `ps -a` : un conteneur api ARRÊTÉ compte aussi (la procédure arrête
# l'API avant de restaurer) ; sans `-a`, compose ne listait que les
# conteneurs en marche et la restauration était refusée à tort (bogue
# consigné le 25/09/2026, corrigé en phase 2 le 27/09/2026).
if [[ -z "$(docker compose "${COMPOSE_ARGS[@]}" ps -a -q api)" ]]; then
  echo "restore.sh : conteneur api introuvable pour le projet compose '$PROJECT_NAME'. Le créer avant la restauration. Rien n'a été modifié." >&2
  exit 1
fi

# Horodatage et noms des dossiers frères utilisés par la bascule de
# DOCS_HOST_DIR (voir plus bas) : calculés dès maintenant pour que le
# gestionnaire d'erreurs (ci-dessous) puisse toujours s'y référer.
HORODATAGE="$(date -u +%Y%m%d-%H%M%S)"
DOCS_HOST_DIR_ANCIEN="${DOCS_HOST_DIR}.avant-restauration-${HORODATAGE}"
DOCS_HOST_DIR_NOUVEAU="${DOCS_HOST_DIR}.restaure-${HORODATAGE}"
COPIE_SECURITE="$SAUVEGARDES_DIR/avant-restauration-${POSTGRES_DB}-${HORODATAGE}.dump"

# Diagnostic clair en cas d'échec à mi-parcours (ex. pg_restore) : affiche
# l'étape en cours (ETAPE_COURANTE, mise à jour juste avant chaque section
# ci-dessous), la commande fautive, l'état qu'elle implique et la commande
# de reprise. Se combine avec le trap EXIT (nettoyage de RESTORE_DIR) déjà
# en place : l'un ne remplace pas l'autre, les deux s'exécutent.
ETAPE_COURANTE="préparation (avant tout effet de bord)"
on_error() {
  local code=$? ligne="${1:-?}"
  echo "" >&2
  echo "restore.sh : ÉCHEC pendant l'étape « $ETAPE_COURANTE » (ligne $ligne, code $code) :" >&2
  echo "restore.sh :   ${BASH_COMMAND:-?}" >&2
  echo "restore.sh : état laissé : base '$POSTGRES_DB' possiblement vide/partielle si l'étape" >&2
  echo "restore.sh :   « recréation de la base » ou une étape suivante a été atteinte (elle est" >&2
  echo "restore.sh :   recréée AVANT pg_restore, donc jamais restaurée à l'ancien état par ce" >&2
  echo "restore.sh :   script ; l'ancienne base est dans la copie de sécurité $COPIE_SECURITE" >&2
  echo "restore.sh :   si elle a pu être écrite) ; API arrêtée si l'étape « arrêt de l'API » ou une étape suivante" >&2
  echo "restore.sh :   a été atteinte ; documents inchangés sauf si l'étape « bascule des" >&2
  echo "restore.sh :   documents » a été atteinte ou est en cours (vérifier alors l'existence de" >&2
  echo "restore.sh :   $DOCS_HOST_DIR_ANCIEN et $DOCS_HOST_DIR_NOUVEAU, résidus possibles d'une" >&2
  echo "restore.sh :   bascule interrompue)." >&2
  echo "restore.sh : reprise : corriger la cause puis relancer : $0 $SNAPSHOT --confirmer" >&2
  echo "restore.sh :   (idempotent : recrée la base depuis zéro à chaque tentative ; supprimer" >&2
  echo "restore.sh :   d'abord un éventuel résidu .avant-restauration-*/.restaure-* du run" >&2
  echo "restore.sh :   précédent, sans quoi la bascule des documents refusera de s'exécuter)." >&2
}
trap 'on_error "$LINENO"' ERR

RESTORE_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$RESTORE_DIR"
}
trap cleanup EXIT

export PGPASSWORD="$POSTGRES_PASSWORD"

# -u : le conteneur restaure alors avec l'uid/gid de l'appelant (jamais en
# root), sans quoi les fichiers/dossiers recréés par restic sous
# RESTORE_DIR ne seraient plus supprimables par le nettoyage ci-dessous.
# --no-cache : conteneur jetable.
RESTIC_USER_ARGS=(-u "$(id -u):$(id -g)")

RESTIC_ENV=(-e RESTIC_REPOSITORY -e RESTIC_PASSWORD)
if [[ -n "${AWS_ACCESS_KEY_ID:-}" ]]; then
  RESTIC_ENV+=(-e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY)
fi

RESTIC_MOUNTS=(-v "$RESTORE_DIR:$RESTORE_DIR")
if [[ "$DEPOT_LOCAL" -eq 1 ]]; then
  RESTIC_MOUNTS+=(-v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY")
fi

ETAPE_COURANTE="restauration restic (rien touché sur la base/les documents en place)"
echo "restore.sh : restic restore $SNAPSHOT -> $RESTORE_DIR…"
docker run --rm \
  "${RESTIC_USER_ARGS[@]}" \
  "${RESTIC_ENV[@]}" \
  "${RESTIC_MOUNTS[@]}" \
  "$RESTIC_IMAGE" \
  restore "$SNAPSHOT" --target "$RESTORE_DIR" --no-cache

# Dump : emplacement fixe des sauvegardes récentes (/dump/bl.dump), sinon
# recherche dans l'ancien format (dossier temporaire aléatoire), en ignorant
# le dossier des documents : un document nommé « *.dump » ne doit pas être
# pris pour la base.
DUMP_FILE="$RESTORE_DIR/dump/bl.dump"
if [[ ! -f "$DUMP_FILE" ]]; then
  DUMP_FILE="$(find "$RESTORE_DIR" -path "$RESTORE_DIR$DOCS_HOST_DIR" -prune -o -type f -name '*.dump' -print -quit)"
fi
if [[ -z "$DUMP_FILE" ]]; then
  echo "restore.sh : aucun fichier .dump trouvé dans le snapshot restauré. Rien n'a été modifié." >&2
  exit 1
fi

RESTORED_DOCS_DIR="$RESTORE_DIR$DOCS_HOST_DIR"
if [[ ! -d "$RESTORED_DOCS_DIR" ]]; then
  echo "restore.sh : dossier docs absent du snapshot restauré ($RESTORED_DOCS_DIR). Rien n'a été modifié." >&2
  exit 1
fi

# Garde par motif (pas par nom horodaté exact, qui ne matcherait quasiment
# jamais puisque HORODATAGE est calculé à chaque exécution) : un résidu
# ".restaure-*" témoigne d'une bascule interrompue en cours de
# copie/renommage (état incertain, jamais sûr de reprendre dessus) et
# bloque toujours la restauration. Un résidu ".avant-restauration-*" est
# l'ancien contenu d'une restauration précédente déjà réussie (conservé
# volontairement, cf. RESTAURATION.md) : il n'empêche pas de relancer, mais
# est signalé pour rappeler qu'il reste à supprimer à la main.
if compgen -G "${DOCS_HOST_DIR}.restaure-*" >/dev/null; then
  echo "restore.sh : résidu ${DOCS_HOST_DIR}.restaure-* détecté (bascule d'une restauration précédente interrompue en cours de copie/renommage) : à inspecter puis supprimer avant de relancer. Rien n'a été modifié." >&2
  exit 1
fi
if compgen -G "${DOCS_HOST_DIR}.avant-restauration-*" >/dev/null; then
  echo "restore.sh : ancien(s) contenu(s) ${DOCS_HOST_DIR}.avant-restauration-* d'une restauration précédente déjà présents (non bloquant ; à supprimer à la main une fois vérifiés, cf. RESTAURATION.md)." >&2
fi

# Dernier contrôle avant destruction : le dump du snapshot est lisible par
# pg_restore (`--list` ne touche à aucune base).
ETAPE_COURANTE="validation du dump (rien touché sur la base/les documents en place)"
echo "restore.sh : validation du dump (pg_restore --list)…"
docker run --rm \
  -v "$RESTORE_DIR:$RESTORE_DIR:ro" \
  "$POSTGRES_IMAGE" \
  pg_restore --list "$DUMP_FILE" >/dev/null

ETAPE_COURANTE="arrêt de l'API (base et documents encore intacts)"
echo "restore.sh : arrêt de l'API…"
docker compose "${COMPOSE_ARGS[@]}" stop api

# Copie de sécurité de la base COURANTE avant de la supprimer : si la
# restauration tourne mal, ou si le mauvais snapshot a été choisi, l'état
# précédent reste récupérable. Le dump sort sur stdout et est redirigé côté
# hôte sous `umask 077` : le fichier naît en 0600 (jamais lisible par un
# autre utilisateur, même un instant). Il est ensuite validé
# (`pg_restore --list`) ; en cas d'échec il est supprimé (jamais laissé
# partiel) et rien n'est détruit. Une copie existante n'est jamais écrasée
# ni supprimée. Base absente (reprise après un échec entre DROP et CREATE) :
# pas de copie, message clair.
ETAPE_COURANTE="copie de sécurité de la base courante (base encore intacte, API arrêtée)"
BASE_EXISTE="$(
  docker run --rm \
    --network "$NETWORK" \
    -e PGPASSWORD \
    "$POSTGRES_IMAGE" \
    psql -h postgres -U "$POSTGRES_USER" -d postgres -tA -v ON_ERROR_STOP=1 \
    -c "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB';"
)"
if [[ "$BASE_EXISTE" == "1" ]]; then
  if [[ -e "$COPIE_SECURITE" ]]; then
    echo "restore.sh : la copie de sécurité $COPIE_SECURITE existe déjà ; elle n'est jamais écrasée. Relancer dans une seconde. Base non touchée." >&2
    exit 1
  fi
  echo "restore.sh : copie de sécurité de la base courante -> $COPIE_SECURITE…"
  if ! (
    umask 077
    set -o noclobber
    docker run --rm \
      --network "$NETWORK" \
      -e PGPASSWORD \
      "$POSTGRES_IMAGE" \
      pg_dump -Fc -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$COPIE_SECURITE"
  ); then
    rm -f -- "$COPIE_SECURITE"
    echo "restore.sh : la copie de sécurité a échoué (fichier partiel supprimé). Base non touchée." >&2
    exit 1
  fi
  if ! docker run --rm -i \
    "$POSTGRES_IMAGE" \
    pg_restore --list < "$COPIE_SECURITE" >/dev/null; then
    rm -f -- "$COPIE_SECURITE"
    echo "restore.sh : la copie de sécurité est invalide (supprimée). Base non touchée." >&2
    exit 1
  fi
  chmod 600 -- "$COPIE_SECURITE"
else
  echo "restore.sh : base $POSTGRES_DB absente (reprise après un échec entre DROP et CREATE ?) : aucune copie de sécurité créée ; conserver la PREMIÈRE copie avant-restauration-* existante."
fi

ETAPE_COURANTE="recréation de la base (base droppée/recréée, pas encore restaurée)"
echo "restore.sh : recréation de la base $POSTGRES_DB…"
docker run --rm \
  --network "$NETWORK" \
  -e PGPASSWORD \
  "$POSTGRES_IMAGE" \
  psql -h postgres -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";" \
  -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"

ETAPE_COURANTE="pg_restore (base vide ou partielle tant que cette étape n'est pas terminée)"
echo "restore.sh : pg_restore…"
docker run --rm \
  --network "$NETWORK" \
  -e PGPASSWORD \
  -v "$RESTORE_DIR:$RESTORE_DIR:ro" \
  "$POSTGRES_IMAGE" \
  pg_restore --exit-on-error --no-owner -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$DUMP_FILE"

# Bascule de DOCS_HOST_DIR sans jamais supprimer l'existant : le contenu
# restauré est d'abord copié dans un dossier frère temporaire
# (DOCS_HOST_DIR_NOUVEAU, même parent que DOCS_HOST_DIR), puis la bascule
# elle-même se fait par deux renommages successifs (rapides, sans copie,
# puisque même système de fichiers que DOCS_HOST_DIR) : l'ancien contenu
# devient DOCS_HOST_DIR_ANCIEN (conservé, à supprimer à la main après
# vérification — voir RESTAURATION.md), le nouveau prend la place de
# DOCS_HOST_DIR. Le tout dans un conteneur root jetable qui monte le
# PARENT de DOCS_HOST_DIR et le dossier restauré (lecture seule) : voir
# basculer-documents.sh (droits 10001, 0750/0640). Le montage du parent
# tient au fait que les renommages se font dans ce dossier.
ETAPE_COURANTE="bascule des documents (voir $DOCS_HOST_DIR_ANCIEN / $DOCS_HOST_DIR_NOUVEAU)"
echo "restore.sh : préparation du contenu restauré dans $DOCS_HOST_DIR_NOUVEAU…"
echo "restore.sh : bascule de $DOCS_HOST_DIR (ancien contenu conservé dans $DOCS_HOST_DIR_ANCIEN, documents rendus à l'uid/gid 10001)…"
docker run --rm \
  --entrypoint sh \
  -v "$DOCS_HOST_DIR_PARENT:$DOCS_HOST_DIR_PARENT" \
  -v "$RESTORE_DIR:$RESTORE_DIR:ro" \
  -v "$SCRIPT_DIR/basculer-documents.sh:/basculer-documents.sh:ro" \
  "$POSTGRES_IMAGE" \
  /basculer-documents.sh "$RESTORED_DOCS_DIR" "$DOCS_HOST_DIR_NOUVEAU" "$DOCS_HOST_DIR" "$DOCS_HOST_DIR_ANCIEN"

ETAPE_COURANTE="redémarrage de l'API (base et documents déjà restaurés/basculés)"
echo "restore.sh : redémarrage de l'API…"
docker compose "${COMPOSE_ARGS[@]}" start api

ETAPE_COURANTE="vérification de /health (base, documents et API déjà en place)"
echo "restore.sh : vérification de /health…"
TENTATIVES=0
until docker compose "${COMPOSE_ARGS[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)" >/dev/null 2>&1; do
  TENTATIVES=$((TENTATIVES + 1))
  if [[ "$TENTATIVES" -ge 30 ]]; then
    echo "restore.sh : /health ne répond pas 30x après redémarrage." >&2
    exit 1
  fi
  sleep 2
done

echo "restore.sh : terminé, /health répond 200. Ancien contenu docs conservé dans $DOCS_HOST_DIR_ANCIEN (à supprimer à la main après vérification)."
