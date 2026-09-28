# Conteneur interne OpenCode (`opencode serve`, phase 4 IA, T8, spec §3.1).
# Ce conteneur ne parle qu'à `api` (réseau `habitat_ia`, jamais publié) et à
# OpenAI/Exa vers l'extérieur : jamais de socket Docker, jamais de base,
# jamais le dépôt applicatif monté dedans. Version figée en dur (montée de
# version = geste volontaire, jamais automatique -- voir `autoupdate: false`
# dans `opencode.json`).

FROM node:22-slim

# Utilisateur non root dédié, uid/gid fixes (cohérent avec `appuser` 10001 de
# l'image API -- 10002 pour rester distinct). `--create-home` pose
# /home/opencode appartenant à opencode:opencode ; HOME est fixé
# explicitement plutôt que laissé à la résolution implicite de `USER` par
# nom (portabilité entre runtimes OCI).
RUN groupadd --gid 10002 opencode \
    && useradd --uid 10002 --gid 10002 --create-home --home-dir /home/opencode \
       --shell /usr/sbin/nologin opencode
ENV HOME=/home/opencode

RUN npm install -g opencode-ai@1.18.32 \
    && npm cache clean --force

# Configuration copiée dans l'image, jamais montée : `opencode.json` ne
# contient aucun secret (mots de passe et clé Exa restent dans `.env`, lus
# par le conteneur via `environment`/`env_file` du compose). Appartient à
# root, lecture seule pour `opencode` (0444) : même en cas de faille dans un
# agent, le processus ne peut pas modifier ses propres permissions ou
# rajouter un outil.
RUN mkdir -p /home/opencode/.config/opencode
COPY opencode.json /home/opencode/.config/opencode/opencode.json
RUN chown -R root:root /home/opencode/.config \
    && chmod 0444 /home/opencode/.config/opencode/opencode.json \
    && chmod 0555 /home/opencode/.config/opencode

# Répertoire de travail vide et non inscriptible : `opencode serve` ne doit
# jamais avoir accès à un dépôt de code ou à des documents (l'IA n'a jamais
# d'outil `read`/`edit`/`bash`, mais un répertoire de travail vide est une
# seconde barrière, pas une question de confiance dans le seul `permission`).
RUN mkdir -p /srv/vide \
    && chown root:root /srv/vide \
    && chmod 0555 /srv/vide
WORKDIR /srv/vide

# Répertoire de données persistantes : monté par le compose sur le volume
# nommé `opencode-donnees` (contient `auth.json`, le jeton de l'abonnement,
# et les sessions). Créé et donné à `opencode` ici pour que le volume nommé,
# vide au premier démarrage, hérite des bonnes permissions (Docker recopie
# le contenu/les droits du répertoire de l'image dans un volume nommé vide).
RUN mkdir -p /home/opencode/.local/share/opencode \
    && chown -R opencode:opencode /home/opencode/.local

USER opencode

EXPOSE 4096

CMD ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"]
