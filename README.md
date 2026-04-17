# MiroFish Forecast

> ⚠️ **Repo Identity Check:** This is `mirofish-forecast` — the standalone forecasting app.
> For the trading simulation app, see `mirofish-trading` repo.
> See `AGENT_CONTEXT.md` for full disambiguation.

Natural language forecasting layer for ES futures.

## Quick Start

```bash
# Install dependencies
make install

# Run tests
make test

# Run locally with Docker
make docker-run

# Lint & format
make lint
make format
```

## Architecture

See [AGENTS.md](AGENTS.md) for full details.

## Environment Setup

```bash
cp .env.example .env
# Fill in your API keys
```

## API Endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/health/startup` | GET | Startup probe |
| `/health/liveness` | GET | Liveness probe |
| `/health/readiness` | GET | Readiness probe (checks Redis) |
| `/api/market/context` | GET | Full MarketContext JSON |
