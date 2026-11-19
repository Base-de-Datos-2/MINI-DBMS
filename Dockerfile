# Demo image for a single-instance host such as Render (docs/despliegue.md).
# Stage 1 compiles the frontend; stage 2 runs the API, which serves it.

FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Two legacy papers in the extended corpus require Poppler font decoding.
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY engine/ engine/
COPY api/ api/
COPY scripts/ scripts/
COPY benchmarks/__init__.py benchmarks/
COPY benchmarks/spatial/__init__.py benchmarks/spatial/datasets.py benchmarks/spatial/
COPY data/lima/ data/lima/
COPY data/multimedia_demo/ data/multimedia_demo/
COPY data/text_demo/ data/text_demo/
# Part 4 extracts features. Part 5 prepares PDFs and generates answers.
RUN pip install --no-cache-dir -e ".[api,multimedia,academic,rag]"
COPY --from=frontend /app/frontend/dist frontend/dist
COPY PART_05/corpus.json PART_05/corpus_extra.json PART_05/corpus_practica.json PART_05/
# Fetch the fixed corpus only during the build. The offline preparer checks
# every hash before publishing the academic database.
ARG ACADEMIC_CORPUS=base
RUN python -m scripts.setup_academic_image --corpus "$ACADEMIC_CORPUS"
RUN if [ "$ACADEMIC_CORPUS" = "practica" ]; then \
        python scripts/setup_all.py --only parte1 parte2 && \
        OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m scripts.setup_practica --data-dir data/generated/todas; \
    else python scripts/setup_all.py --only parte1 parte2 parte3 parte4; fi
EXPOSE 8000
# One process owns the five data directories and serves every part on one
# port, one tab each. Render sets PORT; ALLOW_WRITES=1 enables INSERT/DELETE,
# table creation and transactions in Parts 1 and 2.
CMD ["sh", "-c", "exec python -m api --all --host 0.0.0.0 --port \"${PORT:-8000}\" ${ALLOW_WRITES:+--allow-writes}"]
