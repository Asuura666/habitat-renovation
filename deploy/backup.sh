#!/usr/bin/env bash
# Sauvegarde nocturne : dump PostgreSQL (pg_dump -Fc) + originaux
# (DOCS_HOST_DIR), envoyés dans un dépôt restic taggé "nocturne", puis
# rotation (--keep-daily 30 --keep-monthly 12 --prune).
#
# Usage : deploy/backup.sh
#
# Variables lues dans le .env à la racine du dépôt (chemin résolu depuis cet
# emplacement, sauf surcharge via HABITAT_RENO_ENV_FILE) :
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, DOCS_HOST_DIR,
#   RESTIC_REPOSITORY, RESTIC_PASSWORD
#   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (seulement si RESTIC_REPOSITORY
#   ne désigne pas un chemin local, c'est-à-dire ne commence pas par "/")
#
# COMPOSE_PROJECT_NAME (optionnel, défaut "habitat_reno") : nom du projet
# compose dont on rejoint le réseau `<projet>_default` pour joindre le
# service "postgres" par son nom.
set -euo pipefail

RESTIC_IMAGE="restic/restic:0.19.1"
POSTGRES_IMAGE="postgres:18"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
ENV_FILE="${HABITAT_RENO_ENV_FILE:-$ROOT_DIR/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "backup.sh : fichier .env introuvable ($ENV_FILE)" >&2
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

if [[ ! -d "$DOCS_HOST_DIR" ]]; then
  echo "backup.sh : DOCS_HOST_DIR introuvable ($DOCS_HOST_DIR)" >&2
  exit 1
fi

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-habitat_reno}"
NETWORK="${PROJECT_NAME}_default"

DUMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$DUMP_DIR"
}
trap cleanup EXIT
DUMP_FILE="$DUMP_DIR/bl.dump"

# Secrets jamais en argument de `docker run` (visible via `ps`/
# /proc/<pid>/cmdline pour tout utilisateur du VPS) : `-e VAR` sans
# `=valeur` fait lire à docker la valeur dans l'environnement du process
# appelant (déjà exporté ci-dessus par `set -a; source ...`, ou juste en
# dessous pour PGPASSWORD qui n'existe pas sous ce nom dans le .env).
export PGPASSWORD="$POSTGRES_PASSWORD"

echo "backup.sh : export pg_dump (projet $PROJECT_NAME, réseau $NETWORK)…"
docker run --rm \
  --network "$NETWORK" \
  -e PGPASSWORD \
  -v "$DUMP_DIR:$DUMP_DIR" \
  "$POSTGRES_IMAGE" \
  pg_dump -Fc -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$DUMP_FILE"

# -u : le conteneur restic écrit alors les fichiers du dépôt local (le cas
# échéant) avec l'uid/gid de l'appelant, jamais en root (sinon les fichiers
# root ne seraient plus supprimables/relisibles par l'utilisateur normal).
# --no-cache : conteneur jetable, un cache persistant n'apporterait rien et
# éviterait de devoir gérer HOME pour un uid arbitraire.
RESTIC_USER_ARGS=(-u "$(id -u):$(id -g)")

RESTIC_ENV=(-e RESTIC_REPOSITORY -e RESTIC_PASSWORD)
if [[ -n "${AWS_ACCESS_KEY_ID:-}" ]]; then
  RESTIC_ENV+=(-e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY)
fi

RESTIC_MOUNTS=(-v "$DUMP_DIR:$DUMP_DIR:ro" -v "$DOCS_HOST_DIR:$DOCS_HOST_DIR:ro")
if [[ "$DEPOT_LOCAL" -eq 1 ]]; then
  RESTIC_MOUNTS+=(-v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY")
fi

echo "backup.sh : restic backup (tag nocturne)…"
docker run --rm \
  "${RESTIC_USER_ARGS[@]}" \
  "${RESTIC_ENV[@]}" \
  "${RESTIC_MOUNTS[@]}" \
  "$RESTIC_IMAGE" \
  backup "$DUMP_DIR" "$DOCS_HOST_DIR" --tag nocturne --no-cache

FORGET_MOUNTS=()
if [[ "$DEPOT_LOCAL" -eq 1 ]]; then
  FORGET_MOUNTS+=(-v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY")
fi

echo "backup.sh : rotation (restic forget --keep-daily 30 --keep-monthly 12 --prune)…"
docker run --rm \
  "${RESTIC_USER_ARGS[@]}" \
  "${RESTIC_ENV[@]}" \
  "${FORGET_MOUNTS[@]}" \
  "$RESTIC_IMAGE" \
  forget --keep-daily 30 --keep-monthly 12 --prune --no-cache

echo "backup.sh : terminé."
