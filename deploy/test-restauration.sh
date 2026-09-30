#!/usr/bin/env bash
# Aller-retour complet de backup.sh / restore.sh sur un projet compose
# isolé (bl_restore_test, ports 127.0.0.1:5459 postgres / 127.0.0.1:8459
# api) et un dépôt restic local jetable.
#
# Ne touche jamais au projet compose "habitat_reno" ni à son .env : un .env
# de test et un dossier docs temporaires sont générés dans un dossier de
# travail (mktemp -d, sous $TMPDIR si défini), détruits en fin d'exécution
# (docker compose down -v) même en cas d'échec.
#
# Usage : deploy/test-restauration.sh
set -euo pipefail

RESTIC_IMAGE="restic/restic:0.19.1"
POSTGRES_IMAGE="postgres:18"
PROJECT_NAME="bl_restore_test"
POSTGRES_PORT="5459"
# 8450/8451 sont pris par la production et la démo sur le VPS actuel.
API_PORT="8459"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"

WORK_DIR="$(mktemp -d)"
ENV_FILE="$WORK_DIR/.env"
OVERRIDE_FILE="$WORK_DIR/docker-compose.override.yml"
DOCS_DIR_TEST="$WORK_DIR/docs"
RESTIC_REPO_TEST="$WORK_DIR/restic-repo"
SAUVEGARDES_TEST="$WORK_DIR/sauvegardes"

COMPOSE_ARGS=(-p "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$ROOT_DIR/deploy/docker-compose.yml" -f "$OVERRIDE_FILE")

cleanup() {
  local statut=$?
  echo "test-restauration.sh : nettoyage (projet $PROJECT_NAME, down -v)…"
  # --rmi local : supprime aussi l'image construite pour ce test
  # (bl_restore_test-api), jamais une image tierce nommée (postgres:18).
  docker compose "${COMPOSE_ARGS[@]}" down -v --remove-orphans --rmi local >/dev/null 2>&1 || true
  # Depuis la correction F-02, les documents restaurés appartiennent à
  # l'uid 10001 (dossiers 0750) : l'utilisateur courant ne peut plus les
  # supprimer, un conteneur root jetable s'en charge.
  docker run --rm --entrypoint sh -v "$WORK_DIR:$WORK_DIR" "$POSTGRES_IMAGE" \
    -c "rm -rf '$WORK_DIR'/*  '$WORK_DIR'/.[!.]*" >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
  exit "$statut"
}
trap cleanup EXIT

echo "test-restauration.sh : dossier de travail temporaire : $WORK_DIR"
mkdir -p "$DOCS_DIR_TEST" "$RESTIC_REPO_TEST" "$SAUVEGARDES_TEST"

POSTGRES_PASSWORD_TEST="$(openssl rand -hex 20)"
RESTIC_PASSWORD_TEST="$(openssl rand -hex 20)"

# `.env` de test généré à partir de `.env.example` : ce fichier contient déjà
# des valeurs factices valides pour TOUTES les variables obligatoires du
# service `api` (y compris celles ajoutées après ce script, comme
# TELEGRAM_BOT_TOKEN/TELEGRAM_WEBHOOK_SECRET/MISTRAL_API_KEY — leur absence
# ici a fait échouer `docker compose ... up` immédiatement, cf.
# docs/lot-1-recette.md). Seules les clés qui doivent être propres à ce test
# isolé sont surchargées ci-dessous (`docker compose --env-file` : la
# dernière occurrence d'une clé dans le fichier l'emporte, vérifié), pour
# que ce script n'ait plus besoin d'être mis à jour à chaque nouvelle
# variable obligatoire ajoutée à `docker-compose.yml`.
cp "$ROOT_DIR/.env.example" "$ENV_FILE"
cat >> "$ENV_FILE" <<EOF

# --- Surcharges propres à test-restauration.sh (projet compose isolé) ---
DOMAIN=bl-restore-test.invalid
ACME_EMAIL=test@invalid.example
POSTGRES_USER=bl_restore_test
POSTGRES_PASSWORD=$POSTGRES_PASSWORD_TEST
POSTGRES_DB=bl_restore_test
DOCS_HOST_DIR=$DOCS_DIR_TEST
DOCS_DIR=/srv/docs
RESTIC_REPOSITORY=$RESTIC_REPO_TEST
RESTIC_PASSWORD=$RESTIC_PASSWORD_TEST
EOF
chmod 600 "$ENV_FILE"

cat > "$OVERRIDE_FILE" <<EOF
services:
  postgres:
    ports:
      - "127.0.0.1:$POSTGRES_PORT:5432"
  api:
    ports:
      - "127.0.0.1:$API_PORT:8000"
EOF

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

NETWORK="${PROJECT_NAME}_default"

# Dossier des copies de sécurité de restore.sh : jetable, jamais le vrai
# ~/sauvegardes-habitat.
export HABITAT_RENO_SAUVEGARDES_DIR="$SAUVEGARDES_TEST"

# Exécute une commande sh dans un conteneur root jetable qui monte le dossier
# de travail (les documents restaurés appartiennent à l'uid 10001 et ne sont
# plus lisibles par l'utilisateur courant).
sh_root() {
  docker run --rm \
    --entrypoint sh \
    -v "$WORK_DIR:$WORK_DIR" \
    "$POSTGRES_IMAGE" \
    -c "$1"
}

# Secrets jamais en argument de `docker run` (visible via `ps` pour tout
# utilisateur du VPS) : `-e VAR` sans `=valeur` fait lire à docker la
# valeur dans l'environnement de ce script (RESTIC_REPOSITORY/
# RESTIC_PASSWORD déjà exportées ci-dessus par `set -a; source ...`, et
# PGPASSWORD explicitement ici car absente sous ce nom du .env).
export PGPASSWORD="$POSTGRES_PASSWORD"

psql_test() {
  # $1 = base cible, $2 = requête SQL
  docker run --rm \
    --network "$NETWORK" \
    -e PGPASSWORD \
    "$POSTGRES_IMAGE" \
    psql -h postgres -U "$POSTGRES_USER" -d "$1" -v ON_ERROR_STOP=1 -tA -c "$2"
}

echo "test-restauration.sh : démarrage de postgres + api (projet $PROJECT_NAME)…"
docker compose "${COMPOSE_ARGS[@]}" up -d --build postgres api

echo "test-restauration.sh : migration (alembic upgrade head)…"
docker compose "${COMPOSE_ARGS[@]}" run --rm -T api alembic upgrade head

echo "test-restauration.sh : initialisation du dépôt restic local…"
docker run --rm \
  -u "$(id -u):$(id -g)" \
  -e RESTIC_REPOSITORY \
  -e RESTIC_PASSWORD \
  -v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY" \
  "$RESTIC_IMAGE" \
  init --no-cache

echo "test-restauration.sh : insertion de données inventées et d'un fichier docs…"
psql_test "$POSTGRES_DB" "INSERT INTO utilisateur (email, role) VALUES ('test-restauration@example.invalid', 'admin');"
psql_test "$POSTGRES_DB" "INSERT INTO fournisseur (nom) VALUES ('Fournisseur Test Restauration');"
psql_test "$POSTGRES_DB" "INSERT INTO parametre (cle, valeur) VALUES ('test_restauration_cle', 'valeur_inventee');"

echo "contenu inventé pour le test de restauration $(date -u +%FT%TZ)" > "$DOCS_DIR_TEST/test-restauration.txt"
SHA_AVANT="$(sha256sum "$DOCS_DIR_TEST/test-restauration.txt" | awk '{print $1}')"

# Constat R1 de la revue finale du 25/09/2026 : le fichier ci-dessus est
# déposé en bash, sous l'utilisateur courant -- jamais avec les droits réels
# des documents produits par l'API (0640, appartenant à l'uid 10001,
# Dockerfile "USER 10001", tâche T3). Ce second fichier reproduit ces droits
# exacts (uid/gid 10001, mode 0640), via un conteneur root jetable qui n'a
# besoin d'aucune image supplémentaire (réutilise $POSTGRES_IMAGE, déjà
# nécessaire ci-dessus), pour que ce script détecte si "backup.sh" perd
# l'accès en lecture à un document réel du client. Le sha256 « avant » est
# calculé par ce même conteneur root, jamais par l'utilisateur courant du
# script : une fois chown/chmod appliqués, ce fichier n'est plus lisible
# par l'utilisateur courant (c'est exactement le comportement reproduit).
DOCUMENT_UID_10001="$DOCS_DIR_TEST/test-restauration-uid-10001.txt"
SHA_AVANT_10001="$(
  docker run --rm \
    --entrypoint sh \
    -v "$DOCS_DIR_TEST:$DOCS_DIR_TEST" \
    "$POSTGRES_IMAGE" \
    -c "echo 'contenu inventé (uid 10001) pour le test de restauration $(date -u +%FT%TZ)' > '$DOCUMENT_UID_10001' \
        && chown 10001:10001 '$DOCUMENT_UID_10001' \
        && chmod 0640 '$DOCUMENT_UID_10001' \
        && sha256sum '$DOCUMENT_UID_10001' | awk '{print \$1}'"
)"

REQUETE_COMPTES="SELECT c.relname || ':' || (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM public.%I', c.relname), false, true, '')))[1]::text::bigint FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind = 'r' AND n.nspname = 'public' ORDER BY c.relname;"

COMPTES_AVANT_FILE="$WORK_DIR/comptes-avant.txt"
psql_test "$POSTGRES_DB" "$REQUETE_COMPTES" > "$COMPTES_AVANT_FILE"

echo "test-restauration.sh : backup.sh…"
HABITAT_RENO_ENV_FILE="$ENV_FILE" COMPOSE_PROJECT_NAME="$PROJECT_NAME" "$ROOT_DIR/deploy/backup.sh"

echo "test-restauration.sh : récupération de l'identifiant précis du snapshot nocturne…"
SNAPSHOT_ID="$(
  docker run --rm \
    -u "$(id -u):$(id -g)" \
    -e RESTIC_REPOSITORY \
    -e RESTIC_PASSWORD \
    -v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY" \
    "$RESTIC_IMAGE" \
    snapshots --tag nocturne --json --no-cache \
    | python3 -c 'import json, sys; snapshots = json.load(sys.stdin); assert len(snapshots) == 1, "snapshot nocturne introuvable"; print(snapshots[0]["id"])'
)"
echo "test-restauration.sh : snapshot nocturne sélectionné : $SNAPSHOT_ID"

# F-01 : nom d'hôte fixe par instance (sinon la rotation ne supprime rien).
HOTE_SNAPSHOT="$(
  docker run --rm \
    -u "$(id -u):$(id -g)" \
    -e RESTIC_REPOSITORY \
    -e RESTIC_PASSWORD \
    -v "$RESTIC_REPOSITORY:$RESTIC_REPOSITORY" \
    "$RESTIC_IMAGE" \
    snapshots --tag nocturne --json --no-cache \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)[0]["hostname"])'
)"
if [[ "$HOTE_SNAPSHOT" != "$PROJECT_NAME" ]]; then
  echo "test-restauration.sh : hôte du snapshot '$HOTE_SNAPSHOT' au lieu de '$PROJECT_NAME'." >&2
  exit 1
fi

echo "test-restauration.sh : destruction (base + fichiers docs)…"
docker compose "${COMPOSE_ARGS[@]}" stop api
docker run --rm \
  --network "$NETWORK" \
  -e PGPASSWORD \
  "$POSTGRES_IMAGE" \
  psql -h postgres -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE \"$POSTGRES_DB\";" \
  -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"
find "$DOCS_DIR_TEST" -mindepth 1 -maxdepth 1 -exec rm -rf {} +

echo "test-restauration.sh : restore.sh $SNAPSHOT_ID --confirmer…"
HABITAT_RENO_ENV_FILE="$ENV_FILE" COMPOSE_PROJECT_NAME="$PROJECT_NAME" COMPOSE_OVERRIDE_FILE="$OVERRIDE_FILE" \
  "$ROOT_DIR/deploy/restore.sh" "$SNAPSHOT_ID" --confirmer

echo "test-restauration.sh : vérifications…"
COMPTES_APRES_FILE="$WORK_DIR/comptes-apres.txt"
psql_test "$POSTGRES_DB" "$REQUETE_COMPTES" > "$COMPTES_APRES_FILE"

ECHEC=0

if diff -u "$COMPTES_AVANT_FILE" "$COMPTES_APRES_FILE" >/dev/null; then
  echo "  - comptes de lignes par table : identiques."
else
  echo "  - comptes de lignes par table : DIFFÉRENTS" >&2
  diff -u "$COMPTES_AVANT_FILE" "$COMPTES_APRES_FILE" >&2 || true
  ECHEC=1
fi

if sh_root "test -f '$DOCS_DIR_TEST/test-restauration.txt'"; then
  SHA_APRES="$(sh_root "sha256sum '$DOCS_DIR_TEST/test-restauration.txt'" | awk '{print $1}')"
  if [[ "$SHA_APRES" == "$SHA_AVANT" ]]; then
    echo "  - sha256 du fichier docs : identique ($SHA_APRES)."
  else
    echo "  - sha256 du fichier docs : DIFFÉRENT (avant=$SHA_AVANT après=$SHA_APRES)" >&2
    ECHEC=1
  fi
else
  echo "  - fichier docs restauré : ABSENT" >&2
  ECHEC=1
fi

# R1 : le fichier 0640/uid 10001 (droits réels d'un document déposé par
# l'API) doit avoir survécu au même aller-retour -- sinon "backup.sh" a
# perdu l'accès en lecture à ce fichier (constat R1 de la revue finale du
# 25/09/2026, régression de "backup.sh --group-add" si elle réapparaît).
# Lu par le même conteneur root que pour SHA_AVANT_10001 : l'utilisateur
# courant du script n'a toujours pas accès à ce fichier 0640/uid 10001.
if sh_root "test -f '$DOCUMENT_UID_10001'"; then
  SHA_APRES_10001="$(
    sh_root "sha256sum '$DOCUMENT_UID_10001'" | awk '{print $1}'
  )"
  if [[ "$SHA_APRES_10001" == "$SHA_AVANT_10001" ]]; then
    echo "  - sha256 du fichier docs (0640, uid 10001) : identique ($SHA_APRES_10001)."
  else
    echo "  - sha256 du fichier docs (0640, uid 10001) : DIFFÉRENT (avant=$SHA_AVANT_10001 après=$SHA_APRES_10001)" >&2
    ECHEC=1
  fi
else
  echo "  - fichier docs restauré (0640, uid 10001) : ABSENT" >&2
  ECHEC=1
fi

# F-02 : documents rendus à l'uid/gid de l'API, dossiers 0750, fichiers 0640.
DROITS_ATTENDUS="10001:10001 750 $DOCS_DIR_TEST
10001:10001 640 $DOCS_DIR_TEST/test-restauration.txt
10001:10001 640 $DOCUMENT_UID_10001"
DROITS_OBSERVES="$(sh_root "stat -c '%u:%g %a %n' '$DOCS_DIR_TEST' '$DOCS_DIR_TEST/test-restauration.txt' '$DOCUMENT_UID_10001'")"
if [[ "$DROITS_OBSERVES" == "$DROITS_ATTENDUS" ]]; then
  echo "  - droits des documents : 10001:10001, 0750 / 0640."
else
  echo "  - droits des documents : DIFFÉRENTS" >&2
  echo "attendus :" >&2; echo "$DROITS_ATTENDUS" >&2
  echo "observés :" >&2; echo "$DROITS_OBSERVES" >&2
  ECHEC=1
fi

# C-03 : copie de sécurité de la base courante, écrite avant le DROP, 600.
COPIE_SECURITE_TEST="$(find "$SAUVEGARDES_TEST" -name 'avant-restauration-*.dump' -print -quit)"
if [[ -n "$COPIE_SECURITE_TEST" && "$(stat -c %a "$COPIE_SECURITE_TEST")" == "600" && -s "$COPIE_SECURITE_TEST" ]]; then
  echo "  - copie de sécurité de la base : présente, non vide, 0600."
else
  echo "  - copie de sécurité de la base : ABSENTE, vide ou droits incorrects (${COPIE_SECURITE_TEST:-aucun fichier})" >&2
  ECHEC=1
fi

CODE_HEALTH="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$API_PORT/health")"
if [[ "$CODE_HEALTH" == "200" ]]; then
  echo "  - /health : 200."
else
  echo "  - /health : $CODE_HEALTH (attendu 200)" >&2
  ECHEC=1
fi

if [[ "$ECHEC" -ne 0 ]]; then
  echo "test-restauration.sh : ÉCHEC." >&2
  exit 1
fi

echo "test-restauration.sh : SUCCÈS — aller-retour complet vérifié (migration, données inventées, backup, destruction, restauration, comptes identiques, sha256 identique, /health 200)."
