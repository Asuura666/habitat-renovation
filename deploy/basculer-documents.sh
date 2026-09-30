#!/bin/sh
# Bascule de DOCS_HOST_DIR, exécutée par restore.sh DANS un conteneur jetable
# lancé en root (image postgres:18, --entrypoint sh, script monté en lecture
# seule) : ni l'opérateur hôte ni son uid n'interviennent.
#
# Pourquoi un conteneur root : (1) les documents doivent appartenir à
# l'uid/gid 10001 de l'API (Dockerfile), ce que seul root peut poser ;
# (2) sur ce VPS le parent de DOCS_HOST_DIR (prod/, demo/) appartient à root
# et n'est pas inscriptible par `debian`. Même principe que backup.sh pour
# pg_dump : un conteneur jetable plutôt que sudo.
#
# Usage : basculer-documents.sh <source> <nouveau> <cible> <ancien>
#   source  contenu restauré (lu seulement)
#   nouveau dossier frère temporaire (n'existe pas encore), même parent que cible
#   cible   DOCS_HOST_DIR
#   ancien  destination de l'ancien contenu de cible (jamais supprimé)
#
# Ordre : copie, droits (uid/gid 10001, dossiers 0750, fichiers 0640, ceux du
# 25/09/2026), puis seulement deux renommages. Si la copie ou les droits
# échouent, `cible` n'a pas été touchée.
set -eu

if [ "$#" -ne 4 ]; then
  echo "basculer-documents.sh : usage : <source> <nouveau> <cible> <ancien>" >&2
  exit 2
fi
source_dir="$1"
nouveau="$2"
cible="$3"
ancien="$4"

cp -a -- "$source_dir" "$nouveau"
chown -R 10001:10001 -- "$nouveau"
find "$nouveau" -type d -exec chmod 0750 {} +
find "$nouveau" -type f -exec chmod 0640 {} +

if [ -e "$cible" ]; then
  mv -- "$cible" "$ancien"
fi
mv -- "$nouveau" "$cible"
