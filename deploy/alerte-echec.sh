#!/usr/bin/env bash
# Alerte d'échec d'une tâche planifiée (phase 2, 27/09/2026) : lancé par
# systemd (`OnFailure=habitat-<instance>-alerte@%n.service`, voir
# deploy/installer-taches.sh), envoie un message dans le canal Telegram de
# supervision de l'instance (CDC §9 : « alerte dans le groupe Telegram de
# supervision »).
#
# Usage : deploy/alerte-echec.sh <instance> <unité en échec>
#
# Le jeton du bot est lu dans `.env.<instance>` (ou HABITAT_RENO_ENV_FILE)
# et passé à curl par sa configuration sur l'entrée standard : il n'apparaît
# jamais dans la ligne de commande (liste des processus), ni dans une sortie.
set -euo pipefail

INSTANCE="${1:?Usage : alerte-echec.sh <instance> <unité>}"
UNITE="${2:?Usage : alerte-echec.sh <instance> <unité>}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
ENV_FILE="${HABITAT_RENO_ENV_FILE:-$ROOT_DIR/.env.$INSTANCE}"

valeur() {
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -n 1 | cut -d= -f2- || true
}

JETON="$(valeur TELEGRAM_BOT_TOKEN)"
CANAL="$(valeur TELEGRAM_CHAT_SUPERVISION_ID)"
if [[ -z "$JETON" || -z "$CANAL" ]]; then
  echo "alerte-echec.sh : jeton ou canal de supervision absent de $ENV_FILE, alerte non envoyée ($UNITE)" >&2
  exit 1
fi

HEURE="$(TZ=Europe/Paris date '+%d/%m/%Y à %H:%M')"
TEXTE="⚠️ Habitat (${INSTANCE}) : la tâche planifiée « ${UNITE} » a échoué le ${HEURE}. Détail : journalctl --user -u ${UNITE}"

CODE="$(printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$JETON" \
  | curl --silent --show-error --max-time 20 --output /dev/null --write-out '%{http_code}' \
      --config - --data-urlencode "chat_id=${CANAL}" --data-urlencode "text=${TEXTE}")" || CODE="000"
if [[ "$CODE" != "200" ]]; then
  echo "alerte-echec.sh : envoi Telegram refusé (HTTP $CODE) pour $UNITE" >&2
  exit 1
fi
echo "alerte-echec.sh : alerte envoyée pour $UNITE"
