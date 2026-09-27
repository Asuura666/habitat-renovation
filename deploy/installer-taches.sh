#!/usr/bin/env bash
# Tâches planifiées d'une instance (phase 2, 27/09/2026) : timers systemd
# utilisateur (le compte hôte a `Linger=yes`, et `cron` n'est pas installé
# sur le VPS). Trois tâches, chacune avec une alerte Telegram en cas
# d'échec (`OnFailure=` → `deploy/alerte-echec.sh`, canal de supervision de
# l'instance) :
#   - sauvegarde : `deploy/backup.sh` (dump + documents, restic) ;
#   - controles : `python -m app.cli controles-differes` (rappels R14-R16 ;
#     R06 reste désactivée tant que CONTROLE_LIVRE_NON_FACTURE_ACTIF est faux) ;
#   - photos : `python -m app.cli ranger-photos` (rattrapage du rangement des
#     photos, notamment après la propagation d'un nom de chantier appris).
# La synchronisation Drive n'est pas planifiée (bloquée, voir docs/dette.md).
# Les sorties vont dans journald (`journalctl --user -u <unité>`, taille
# plafonnée par /etc/systemd/journald.conf.d) : pas de fichier de log ni de
# logrotate.
#
# Usage :
#   deploy/installer-taches.sh <prod|demo> [--taches sauvegarde,controles,photos]
#                                          [--dossier <dir>] [--sans-activer]
#   deploy/installer-taches.sh <prod|demo> --desinstaller
#
# <instance> : projet compose `habitat_<instance>`, fichier `.env.<instance>`
# à la racine du dépôt, surcouche `deploy/docker-compose.vps.yml`.
# --taches : sous-ensemble à installer (défaut : les trois). La sauvegarde
#   exige RESTIC_REPOSITORY et RESTIC_PASSWORD dans le fichier .env.
# --dossier : écrit les unités ailleurs que dans ~/.config/systemd/user
#   (tests) ; implique --sans-activer.
# --sans-activer : écrit les unités sans appeler systemctl.
# Horaires (heure de Paris) décalés entre les instances pour ne jamais faire
# tourner deux sauvegardes ou deux rangements en même temps (mémoire du VPS).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
DOCKER="/usr/bin/docker"

usage() {
  echo "Usage : deploy/installer-taches.sh <prod|demo> [--taches sauvegarde,controles,photos] [--dossier <dir>] [--sans-activer]" >&2
  echo "        deploy/installer-taches.sh <prod|demo> --desinstaller" >&2
  exit 2
}

[[ $# -ge 1 ]] || usage
INSTANCE="$1"
shift
case "$INSTANCE" in
  prod)
    HEURE_PHOTOS="02:30"
    HEURE_SAUVEGARDE="03:00"
    HEURE_CONTROLES="06:15"
    ;;
  demo)
    HEURE_PHOTOS="02:45"
    HEURE_SAUVEGARDE="03:40"
    HEURE_CONTROLES="06:30"
    ;;
  *)
    echo "installer-taches.sh : instance inconnue « $INSTANCE » (prod ou demo)" >&2
    exit 2
    ;;
esac

TACHES="sauvegarde,controles,photos"
DOSSIER="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
ACTIVER=1
DESINSTALLER=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --taches) TACHES="${2:?--taches demande une liste}"; shift 2 ;;
    --dossier) DOSSIER="${2:?--dossier demande un chemin}"; ACTIVER=0; shift 2 ;;
    --sans-activer) ACTIVER=0; shift ;;
    --desinstaller) DESINSTALLER=1; shift ;;
    *) usage ;;
  esac
done

PREFIXE="habitat-${INSTANCE}"
PROJET="habitat_${INSTANCE}"
# HABITAT_RENO_ENV_FILE : surcharge (tests, clone sans les .env réels).
ENV_FILE="${HABITAT_RENO_ENV_FILE:-$ROOT_DIR/.env.${INSTANCE}}"
COMPOSE="$DOCKER compose -p $PROJET --env-file $ENV_FILE -f $ROOT_DIR/deploy/docker-compose.yml -f $ROOT_DIR/deploy/docker-compose.vps.yml"

if [[ "$DESINSTALLER" -eq 1 ]]; then
  # Avec --dossier/--sans-activer, systemctl n'est JAMAIS appelé : un essai
  # de désinstallation ne doit pas couper les vraies tâches de l'instance
  # (constat de la relecture de la phase 2).
  for tache in sauvegarde controles photos; do
    if [[ "$ACTIVER" -eq 1 ]]; then
      systemctl --user disable --now "${PREFIXE}-${tache}.timer" 2>/dev/null || true
    fi
    rm -f "$DOSSIER/${PREFIXE}-${tache}.timer" "$DOSSIER/${PREFIXE}-${tache}.service"
  done
  rm -f "$DOSSIER/${PREFIXE}-alerte@.service"
  if [[ "$ACTIVER" -eq 1 ]]; then
    systemctl --user daemon-reload
  fi
  echo "Tâches de l'instance $INSTANCE désinstallées ($DOSSIER)."
  exit 0
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "installer-taches.sh : $ENV_FILE introuvable" >&2
  exit 1
fi
IFS=',' read -r -a LISTE <<< "$TACHES"
for tache in "${LISTE[@]}"; do
  case "$tache" in
    sauvegarde|controles|photos) ;;
    *)
      echo "installer-taches.sh : tâche inconnue « $tache » (sauvegarde, controles, photos)" >&2
      exit 2
      ;;
  esac
done
for cle in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_SUPERVISION_ID; do
  if ! grep -qE "^${cle}=.+" "$ENV_FILE"; then
    echo "installer-taches.sh : attention, $cle absent de $ENV_FILE : les échecs ne seront pas signalés sur Telegram" >&2
  fi
done
if [[ ",$TACHES," == *",sauvegarde,"* ]]; then
  for cle in RESTIC_REPOSITORY RESTIC_PASSWORD; do
    if ! grep -qE "^${cle}=.+" "$ENV_FILE"; then
      echo "installer-taches.sh : $cle absent de $ENV_FILE ; la sauvegarde n'est pas installée (--taches controles,photos pour les autres)" >&2
      exit 1
    fi
  done
fi

mkdir -p "$DOSSIER"

ecrire_alerte() {
  cat > "$DOSSIER/${PREFIXE}-alerte@.service" <<EOF
[Unit]
Description=Habitat ${INSTANCE} : alerte d'échec de %i

[Service]
Type=oneshot
ExecStart=$ROOT_DIR/deploy/alerte-echec.sh ${INSTANCE} %i
EOF
}

# ecrire_tache <nom> <description> <heure> <ExecStart> [lignes Environment=…]
ecrire_tache() {
  local nom="$1" description="$2" heure="$3" commande="$4"
  shift 4
  local environnement=""
  for ligne in "$@"; do
    environnement+="Environment=${ligne}"$'\n'
  done
  cat > "$DOSSIER/${PREFIXE}-${nom}.service" <<EOF
[Unit]
Description=Habitat ${INSTANCE} : ${description}
OnFailure=${PREFIXE}-alerte@%n.service

[Service]
Type=oneshot
WorkingDirectory=$ROOT_DIR
${environnement}ExecStart=${commande}
EOF
  cat > "$DOSSIER/${PREFIXE}-${nom}.timer" <<EOF
[Unit]
Description=Habitat ${INSTANCE} : ${description} (chaque jour à ${heure}, heure de Paris)

[Timer]
OnCalendar=*-*-* ${heure}:00 Europe/Paris
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

ecrire_alerte
TIMERS=()
for tache in "${LISTE[@]}"; do
  case "$tache" in
    sauvegarde)
      ecrire_tache sauvegarde "sauvegarde nocturne (base et documents, restic)" "$HEURE_SAUVEGARDE" \
        "$ROOT_DIR/deploy/backup.sh" \
        "HABITAT_RENO_ENV_FILE=$ENV_FILE" "COMPOSE_PROJECT_NAME=$PROJET"
      ;;
    controles)
      ecrire_tache controles "contrôles différés (rappels)" "$HEURE_CONTROLES" \
        "$COMPOSE exec -T api python -m app.cli controles-differes"
      ;;
    photos)
      ecrire_tache photos "rangement des photos des bons" "$HEURE_PHOTOS" \
        "$COMPOSE exec -T api python -m app.cli ranger-photos"
      ;;
    *)
      echo "installer-taches.sh : tâche inconnue « $tache » (sauvegarde, controles, photos)" >&2
      exit 2
      ;;
  esac
  TIMERS+=("${PREFIXE}-${tache}.timer")
done

if [[ "$ACTIVER" -eq 1 ]]; then
  systemctl --user daemon-reload
  systemctl --user enable --now "${TIMERS[@]}"
  systemctl --user list-timers "${PREFIXE}-*" --no-pager
else
  echo "Unités écrites dans $DOSSIER (non activées) : ${TIMERS[*]}"
fi
