#!/usr/bin/env bash
# Tâches planifiées d'une instance (phase 2, 27/09/2026 ; IA, phase 4,
# 28/09/2026) : timers systemd utilisateur (le compte hôte a `Linger=yes`,
# et `cron` n'est pas installé sur le VPS). Cinq tâches possibles, chacune
# avec une alerte Telegram en cas d'échec (`OnFailure=` →
# `deploy/alerte-echec.sh`, canal de supervision de l'instance) :
#   - sauvegarde : `deploy/backup.sh` (dump + documents, restic) ;
#   - controles : `python -m app.cli controles-differes` (rappels R14-R16 ;
#     R06 reste désactivée tant que CONTROLE_LIVRE_NON_FACTURE_ACTIF est faux) ;
#   - photos : `python -m app.cli ranger-photos` (rattrapage du rangement des
#     photos, notamment après la propagation d'un nom de chantier appris) ;
#   - synthese : `python -m app.cli synthese-commentaires` (synthèse
#     hebdomadaire des commentaires par l'IA, T8 phase 4) ;
#   - ia-prix : `python -m app.cli ia-prix` (explication des alertes prix et
#     recherche de prix internet par l'IA, T8 phase 4).
# `synthese` et `ia-prix` n'ont de sens qu'une fois le conteneur OpenCode
# installé et l'IA allumée sur l'instance (`docs/phase-4-ia.md`) : elles ne
# sont donc **jamais** installées par défaut (voir `TACHES` ci-dessous) ; tant
# que `IA_ACTIVE` est faux, les commandes qu'elles lancent se terminent tout
# de suite en écrivant « IA éteinte » (code 0, pas une alerte).
# La synchronisation Drive n'est pas planifiée (bloquée, voir docs/dette.md).
# Les sorties vont dans journald (`journalctl --user -u <unité>`, taille
# plafonnée par /etc/systemd/journald.conf.d) : pas de fichier de log ni de
# logrotate.
#
# Usage :
#   deploy/installer-taches.sh <prod|demo> [--taches sauvegarde,controles,photos,synthese,ia-prix]
#                                          [--dossier <dir>] [--sans-activer]
#   deploy/installer-taches.sh <prod|demo> --desinstaller
#
# <instance> : projet compose `habitat_<instance>`, fichier `.env.<instance>`
# à la racine du dépôt, surcouche `deploy/docker-compose.vps.yml`.
# --taches : sous-ensemble à installer (défaut : sauvegarde,controles,photos
#   -- jamais synthese/ia-prix par défaut, voir ci-dessus). La sauvegarde
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
  echo "Usage : deploy/installer-taches.sh <prod|demo> [--taches sauvegarde,controles,photos,synthese,ia-prix] [--dossier <dir>] [--sans-activer]" >&2
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
    HEURE_SYNTHESE="07:00"
    # ia-prix (T8, phase 4 IA) : chaque heure de 07:10 à 20:10, calendrier
    # complet plutôt qu'une heure fixe (brief T8, valeur vérifiée).
    CALENDRIER_IA_PRIX="07..20:10:00"
    PHRASE_IA_PRIX="chaque heure de 07:10 à 20:10"
    ;;
  demo)
    HEURE_PHOTOS="02:45"
    HEURE_SAUVEGARDE="03:40"
    HEURE_CONTROLES="06:30"
    HEURE_SYNTHESE="07:20"
    CALENDRIER_IA_PRIX="07..20:40:00"
    PHRASE_IA_PRIX="chaque heure de 07:40 à 20:40"
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
  for tache in sauvegarde controles photos synthese ia-prix; do
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
    sauvegarde|controles|photos|synthese|ia-prix) ;;
    *)
      echo "installer-taches.sh : tâche inconnue « $tache » (sauvegarde, controles, photos, synthese, ia-prix)" >&2
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

# ecrire_tache <nom> <description> <calendrier> <frequence> <ExecStart>
#              [lignes Environment=…]
# <calendrier> : ce qui suit « *-*-* » et précède « Europe/Paris » dans
#   `OnCalendar=` -- une heure fixe avec ses secondes ("03:00:00") pour une
#   tâche quotidienne, ou un intervalle complet ("07..20:10:00") pour une
#   tâche répétée plusieurs fois par jour (ia-prix, T8 phase 4 IA). Passé
#   textuellement : cette fonction ne connaît aucun format de plus, elle ne
#   fait qu'écrire ce qu'on lui donne après « *-*-* » et avant
#   « Europe/Paris ».
# <frequence> : phrase humaine insérée dans la Description du timer (ex.
#   "chaque jour à 03:00" ou "chaque heure de 07:10 à 20:10") -- calculée par
#   l'appelant plutôt que déduite de <calendrier>, qui n'a pas une forme
#   assez régulière pour ça une fois qu'il porte un intervalle.
ecrire_tache() {
  local nom="$1" description="$2" calendrier="$3" frequence="$4" commande="$5"
  shift 5
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
Description=Habitat ${INSTANCE} : ${description} (${frequence}, heure de Paris)

[Timer]
OnCalendar=*-*-* ${calendrier} Europe/Paris
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
      ecrire_tache sauvegarde "sauvegarde nocturne (base et documents, restic)" \
        "${HEURE_SAUVEGARDE}:00" "chaque jour à ${HEURE_SAUVEGARDE}" \
        "$ROOT_DIR/deploy/backup.sh" \
        "HABITAT_RENO_ENV_FILE=$ENV_FILE" "COMPOSE_PROJECT_NAME=$PROJET"
      ;;
    controles)
      ecrire_tache controles "contrôles différés (rappels)" \
        "${HEURE_CONTROLES}:00" "chaque jour à ${HEURE_CONTROLES}" \
        "$COMPOSE exec -T api python -m app.cli controles-differes"
      ;;
    photos)
      ecrire_tache photos "rangement des photos des bons" \
        "${HEURE_PHOTOS}:00" "chaque jour à ${HEURE_PHOTOS}" \
        "$COMPOSE exec -T api python -m app.cli ranger-photos"
      ;;
    synthese)
      # T8, phase 4 IA : synthèse hebdomadaire des commentaires -- passe tous
      # les jours (idempotente, `docs/superpowers/specs/2026-09-27-phase-4-ia
      # -design.md` §4.1) ; si l'IA est éteinte ou déjà synthétisée, la
      # commande le dit et sort en code 0 (pas d'alerte).
      ecrire_tache synthese "synthèse hebdomadaire des commentaires (IA)" \
        "${HEURE_SYNTHESE}:00" "chaque jour à ${HEURE_SYNTHESE}" \
        "$COMPOSE exec -T api python -m app.cli synthese-commentaires"
      ;;
    ia-prix)
      # T8, phase 4 IA : explique les alertes prix ouvertes puis cherche un
      # prix internet pour les produits absents de la grille (spec §6.4) --
      # calendrier complet (toutes les heures ouvrées), pas une heure fixe.
      ecrire_tache ia-prix "avis de l'IA sur les alertes prix" \
        "$CALENDRIER_IA_PRIX" "$PHRASE_IA_PRIX" \
        "$COMPOSE exec -T api python -m app.cli ia-prix"
      ;;
    *)
      echo "installer-taches.sh : tâche inconnue « $tache » (sauvegarde, controles, photos, synthese, ia-prix)" >&2
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
