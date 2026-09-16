FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER 10001

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

# --forwarded-allow-ips=* : sans port publié en prod, api n'est joignable que
# par traefik via le réseau compose (IP bridge non-loopback), donc on lui fait
# confiance pour les en-têtes X-Forwarded-*.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
