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
# Rotation : les instantanés sont taggés avec --host <COMPOSE_PROJECT_NAME>
# et sauvegardent toujours les mêmes chemins (/dump, DOCS_HOST_DIR), ce qui
# les range dans un seul groupe restic : les 30 quotidiennes et 12
# mensuelles s'appliquent. Les instantanés antérieurs à ce changement (hôte
# aléatoire) restent chacun leur groupe : voir docs/dette.md.
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
# Un dépôt par instance, un nom d'hôte restic stable par instance.
RESTIC_HOST="$PROJECT_NAME"

DUMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$DUMP_DIR"
}
trap cleanup EXIT
# Chemin du dump VU DES CONTENEURS : fixe (/dump), jamais le dossier
# temporaire de l'hôte. restic regroupe les instantanés par (hôte, chemins)
# pour appliquer `forget --keep-*` : avec un chemin différent à chaque
# passage (mktemp) et un nom d'hôte aléatoire (celui du conteneur), chaque
# instantané formait son propre groupe et rien n'était jamais supprimé
# (audit F-01). Le nom d'hôte est fixé par instance (--host, plus bas).
DUMP_CONTENEUR_DIR="/dump"
DUMP_CONTENEUR="$DUMP_CONTENEUR_DIR/bl.dump"

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
  -v "$DUMP_DIR:$DUMP_CONTENEUR_DIR" \
  "$POSTGRES_IMAGE" \
  pg_dump -Fc -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$DUMP_CONTENEUR"

# -u : le conteneur restic écrit alors les fichiers du dépôt local (le cas
# échéant) avec l'uid/gid de l'appelant, jamais en root (sinon les fichiers
# root ne seraient plus supprimables/relisibles par l'utilisateur normal).
# --no-cache : conteneur jetable, un cache persistant n'apporterait rien et
# éviterait de devoir gérer HOME pour un uid arbitraire.
RESTIC_USER_ARGS=(-u "$(id -u):$(id -g)")

# Groupe supplémentaire pour lire DOCS_HOST_DIR (constat R1 de la revue
# finale du 25/09/2026) : les documents y sont écrits par le conteneur api
# en 0640 (dossier 0750), appartenant à l'uid ET au gid 10001 (Dockerfile,
# "useradd --uid 10001 ... appuser", sans "-g" : Debian crée un groupe de
# même nom avec le même gid -- vérifié, "id" dans l'image donne
# "uid=10001(appuser) gid=10001(appuser)") -- jamais l'uid/gid de
# l'utilisateur hôte qui invoque ce script (RESTIC_USER_ARGS ci-dessus).
# Sans ce groupe, tout compte hôte différent de celui qui a écrit
# DOCS_HOST_DIR (root excepté) perdrait l'accès en lecture aux documents à
# sauvegarder. `--group-add` ajoute ce gid comme groupe supplémentaire du
# conteneur restic : le mode 0640/0750 déjà en place suffit alors (bit de
# lecture du groupe déjà positionné), sans exiger que le compte hôte qui
# lance ce script soit root ni qu'une ACL (setfacl, paquet `acl`, absent de
# ce VPS) soit posée à part sur DOCS_HOST_DIR. Gid **fixe** (10001), jamais
# déduit de `stat` sur DOCS_HOST_DIR : le dossier peut avoir été créé à la
# main par un compte différent avant le premier démarrage du conteneur api
# (`_creer_dossier_documents` ne fait jamais de `chown` sur un dossier déjà
# présent, voir `ingest/commun.py`) -- seul le gid effectivement utilisé
# par le conteneur api pour écrire les *fichiers* compte ici. Docker
# accepte un gid numérique même absent du /etc/group du conteneur restic.
DOCS_GID_APPUSER=10001
RESTIC_BACKUP_ARGS=("${RESTIC_USER_ARGS[@]}" --group-add "$DOCS_GID_APPUSER")

RESTIC_ENV=(-e RESTIC_REPOSITORY -e RESTIC_PASSWORD)
if [[ -n "${AWS_ACCESS_KEY_ID:-}" ]]; then
  RESTIC_ENV+=(-e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY)
fi

RESTIC_MOUNTS=(-v "$DUMP_DIR:$DUMP_CONTENEUR_DIR:ro" -v "$DOCS_HOST_DIR:$DOCS_HOST_DIR:ro")
if [[ "$DEPOT_LOCAL" -eq 1 ]]; then
  RESTIC_MOUNTS+=(-v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY")
fi

echo "backup.sh : restic backup (tag nocturne)…"
docker run --rm \
  "${RESTIC_BACKUP_ARGS[@]}" \
  "${RESTIC_ENV[@]}" \
  "${RESTIC_MOUNTS[@]}" \
  "$RESTIC_IMAGE" \
  backup "$DUMP_CONTENEUR_DIR" "$DOCS_HOST_DIR" --host "$RESTIC_HOST" --tag nocturne --no-cache

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
  forget --host "$RESTIC_HOST" --keep-daily 30 --keep-monthly 12 --prune --no-cache

echo "backup.sh : terminé."
