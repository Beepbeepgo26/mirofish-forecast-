# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# ---- Runtime stage ----
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY src/ src/
COPY gunicorn.conf.py .

# Create non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8080

CMD ["gunicorn", "mirofish_forecast.app:create_app()", "-c", "gunicorn.conf.py"]
