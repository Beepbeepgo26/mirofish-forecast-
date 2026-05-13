# ---- Frontend build stage ----
FROM node:22-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Python build stage ----
FROM python:3.12-slim AS backend-builder

WORKDIR /build
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --prefix=/install .

# ---- Runtime stage ----
FROM python:3.12-slim AS runtime

ARG GIT_SHA=unknown
LABEL git.sha="${GIT_SHA}"

WORKDIR /app

# LightGBM requires OpenMP runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=backend-builder /install /usr/local

# Copy application code
COPY src/ src/
COPY gunicorn.conf.py .
COPY --from=frontend-builder /frontend/dist frontend/dist/

# Brooks corpus enriched data for RAG retrieval summary lookup
COPY data/brooks_corpus_enriched.jsonl data/brooks_corpus_enriched.jsonl

# Create non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8080

CMD ["gunicorn", "mirofish_forecast.app:create_app()", "-c", "gunicorn.conf.py"]
