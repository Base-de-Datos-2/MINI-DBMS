# Demo image for a single-instance host such as Render (docs/despliegue.md).
# Stage 1 compiles the frontend; stage 2 runs the API, which serves it.

FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY engine/ engine/
COPY api/ api/
COPY scripts/ scripts/
RUN pip install --no-cache-dir -e ".[api]"
COPY --from=frontend /app/frontend/dist frontend/dist
# The demo database is built into the image; every restart starts from it.
RUN python scripts/setup_demo.py
EXPOSE 8000
# One process owns the data directory. Render sets PORT; ALLOW_WRITES=1
# enables INSERT/DELETE, table creation and transactions.
CMD ["sh", "-c", "exec python -m api --host 0.0.0.0 --port \"${PORT:-8000}\" ${ALLOW_WRITES:+--allow-writes}"]
