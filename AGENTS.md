# MiroFish Forecast — Agent Instructions

## Project Overview
Natural language forecasting layer for ES futures. Flask backend, Vue.js frontend (Phase 2+).
Separate project from MiroFish Trading — shares GCP project but zero code dependency in Phase 1.

## Commands
- `make install` — Install project + dev dependencies in editable mode
- `make test` — Run all tests with coverage
- `make lint` — Lint with ruff
- `make typecheck` — Type check with mypy
- `make format` — Auto-format code
- `make docker-build` — Build Docker image
- `make docker-run` — Run with docker compose (includes Redis)

## Architecture
- `src/mirofish_forecast/` — Application code (src layout)
- `src/mirofish_forecast/app.py` — Flask application factory
- `src/mirofish_forecast/config/settings.py` — pydantic-settings configuration
- `src/mirofish_forecast/models/` — Shared Pydantic v2 domain models (frozen, extra=forbid)
- `src/mirofish_forecast/data/` — Data source clients (one per source)
- `src/mirofish_forecast/services/` — Business logic orchestration
- `src/mirofish_forecast/api/` — Flask blueprints
- `tests/` — pytest tests (unit/ and integration/)

## Conventions
- All models use `MiroFishBaseModel` from `models/base.py` (frozen=True, extra="forbid")
- All settings use `MIROFISH_` env prefix
- All data clients return Pydantic models, never raw dicts
- Cache keys use `mf:` prefix
- Structured JSON logging for Cloud Logging compatibility
