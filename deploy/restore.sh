#!/usr/bin/env bash
# Restauration : restic restore -> recrée la base PostgreSQL (pg_restore) et
# bascule DOCS_HOST_DIR vers le contenu restauré (par renommages, sans
# jamais supprimer l'existant), puis redémarre l'API et vérifie /health.
#
# Usage : deploy/restore.sh <snapshot|latest> --confirmer
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
# COMPOSE_OVERRIDE_FILE (optionnel) : fichier compose additionnel (-f) pour
# adapter les ports publiés (utilisé par test-restauration.sh).
set -euo pipefail

usage() {
  echo "Usage : $0 <snapshot|latest> --confirmer" >&2
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

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-habitat_reno}"
NETWORK="${PROJECT_NAME}_default"

COMPOSE_ARGS=(-p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$ROOT_DIR/deploy/docker-compose.yml")
if [[ -n "${COMPOSE_OVERRIDE_FILE:-}" ]]; then
  COMPOSE_ARGS+=(-f "$COMPOSE_OVERRIDE_FILE")
fi

# Horodatage et noms des dossiers frères utilisés par la bascule de
# DOCS_HOST_DIR (voir plus bas) : calculés dès maintenant pour que le
# gestionnaire d'erreurs (ci-dessous) puisse toujours s'y référer.
HORODATAGE="$(date -u +%Y%m%d-%H%M%S)"
DOCS_HOST_DIR_ANCIEN="${DOCS_HOST_DIR}.avant-restauration-${HORODATAGE}"
DOCS_HOST_DIR_NOUVEAU="${DOCS_HOST_DIR}.restaure-${HORODATAGE}"

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
  echo "restore.sh :   script) ; API arrêtée si l'étape « arrêt de l'API » ou une étape suivante" >&2
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

DUMP_FILE="$(find "$RESTORE_DIR" -type f -name '*.dump' -print -quit)"
if [[ -z "$DUMP_FILE" ]]; then
  echo "restore.sh : aucun fichier .dump trouvé dans le snapshot restauré." >&2
  exit 1
fi

RESTORED_DOCS_DIR="$RESTORE_DIR$DOCS_HOST_DIR"
if [[ ! -d "$RESTORED_DOCS_DIR" ]]; then
  echo "restore.sh : dossier docs absent du snapshot restauré ($RESTORED_DOCS_DIR)." >&2
  exit 1
fi

if [[ -e "$DOCS_HOST_DIR_ANCIEN" || -e "$DOCS_HOST_DIR_NOUVEAU" ]]; then
  echo "restore.sh : $DOCS_HOST_DIR_ANCIEN ou $DOCS_HOST_DIR_NOUVEAU existe déjà (restauration précédente non nettoyée ?). Rien n'a été modifié." >&2
  exit 1
fi

ETAPE_COURANTE="arrêt de l'API"
echo "restore.sh : arrêt de l'API…"
docker compose "${COMPOSE_ARGS[@]}" stop api

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
# DOCS_HOST_DIR.
ETAPE_COURANTE="bascule des documents (voir $DOCS_HOST_DIR_ANCIEN / $DOCS_HOST_DIR_NOUVEAU)"
echo "restore.sh : préparation du contenu restauré dans $DOCS_HOST_DIR_NOUVEAU…"
cp -a "$RESTORED_DOCS_DIR" "$DOCS_HOST_DIR_NOUVEAU"

echo "restore.sh : bascule de $DOCS_HOST_DIR (ancien contenu conservé dans $DOCS_HOST_DIR_ANCIEN)…"
if [[ -e "$DOCS_HOST_DIR" ]]; then
  mv -- "$DOCS_HOST_DIR" "$DOCS_HOST_DIR_ANCIEN"
fi
mv -- "$DOCS_HOST_DIR_NOUVEAU" "$DOCS_HOST_DIR"

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
