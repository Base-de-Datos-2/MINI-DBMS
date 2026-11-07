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
COPY benchmarks/__init__.py benchmarks/
COPY benchmarks/spatial/__init__.py benchmarks/spatial/datasets.py benchmarks/spatial/
COPY data/lima/ data/lima/
COPY data/multimedia_demo/ data/multimedia_demo/
COPY data/text_demo/ data/text_demo/
# Part 4 needs numpy, OpenCV (SIFT), soundfile and librosa (MFCC).
RUN pip install --no-cache-dir -e ".[api,multimedia]"
COPY --from=frontend /app/frontend/dist frontend/dist
# The four demo databases are built into the image (data/generated/todas);
# a recreated container starts from them again.
RUN python scripts/setup_all.py
EXPOSE 8000
# One process owns the four data directories and serves every part on one
# port, one tab each. Render sets PORT; ALLOW_WRITES=1 enables INSERT/DELETE,
# table creation and transactions in Parts 1 and 2.
CMD ["sh", "-c", "exec python -m api --all --host 0.0.0.0 --port \"${PORT:-8000}\" ${ALLOW_WRITES:+--allow-writes}"]
