# Imagen del portal (FastAPI + Jinja2). No incluye el extra `vision`: el portal solo lee el SQLite y las capturas,
# así que la imagen no descarga PyTorch.

# --- builder: resuelve el entorno con uv desde uv.lock -------------------------------------------------------
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1 UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable
# El portal no usa ventanas de OpenCV: la variante headless (misma versión) evita instalar Mesa/libGL.
RUN OPENCV=$(/opt/venv/bin/python -c "import importlib.metadata as m; print(m.version('opencv-python'))") \
    && uv pip uninstall --python /opt/venv/bin/python opencv-python \
    && uv pip install --python /opt/venv/bin/python "opencv-python-headless==${OPENCV}"

# --- portal: imagen de ejecución --------------------------------------------------------------------------
FROM python:3.12-slim AS portal
WORKDIR /app
ENV PATH=/opt/venv/bin:$PATH
COPY --from=builder /opt/venv /opt/venv
COPY config ./config
COPY ops/portal-entrypoint.sh /usr/local/bin/portal-entrypoint.sh
RUN useradd --create-home streamwatch && mkdir -p /app/state && chown streamwatch /app/state
USER streamwatch
ENV STREAMWATCH_DB=/app/state/streamwatch.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["sh", "/usr/local/bin/portal-entrypoint.sh"]

# Demo pública (AWS): la evidencia viaja dentro de la imagen y el SQLite se construye al compilar.
# Solo lectura: el portal rechaza revisiones (403).
FROM portal AS demo
COPY --chown=streamwatch evidencias/runs ./evidencias/runs
COPY --chown=streamwatch evidencias/revisiones ./evidencias/revisiones
ENV STREAMWATCH_READONLY=1
RUN streamwatch import evidencias/runs/*/ --reviews evidencias/revisiones --db "$STREAMWATCH_DB"
