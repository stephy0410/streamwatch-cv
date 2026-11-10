# Imagen del portal (FastAPI + Jinja2). No incluye el extra `vision`: el portal solo lee el SQLite y las capturas,
# así que la imagen no descarga PyTorch.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev
COPY config ./config
COPY ops/portal-entrypoint.sh /usr/local/bin/portal-entrypoint.sh
RUN useradd --create-home streamwatch && mkdir -p /app/state && chown streamwatch /app/state
USER streamwatch
ENV STREAMWATCH_DB=/app/state/streamwatch.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["sh", "/usr/local/bin/portal-entrypoint.sh"]
