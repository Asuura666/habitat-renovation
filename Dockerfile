# Étage 1 : build du front React (L2-T6, L2-D16). Résultat statique copié
# dans l'étage Python ci-dessous ; ni Node ni npm ne finissent dans l'image
# servie.
FROM node:24-alpine AS front

WORKDIR /front

COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build

# Étage 2 : API Python (inchangé, sauf la copie du build front).
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=front /front/dist ./web/dist

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER 10001

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

# --forwarded-allow-ips=* : sans port publié en prod, api n'est joignable que
# par traefik via le réseau compose (IP bridge non-loopback), donc on lui fait
# confiance pour les en-têtes X-Forwarded-*.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
