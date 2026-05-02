# CLAUDE.md — MiroFish Forecast

Guidance for Claude Code (and other AI assistants) working in this repo. This file is the single entry point; narrower topics are covered in `AGENTS.md`, `AGENT_CONTEXT.md`, and `README.md`.

---

## 1. Repo identity (read first)

- **This is `mirofish-forecast`** — the standalone natural-language forecasting app.
- **It is NOT `mirofish-trading`** — that's a separate repo with the trading simulation engine, Zep memory, and live order management.
- GitHub: `Beepbeepgo26/mirofish-forecast-`
- Python package: `mirofish_forecast` (underscore)
- Cloud Run service: `mirofish-forecast` (us-west2)
- Live URL: `https://mirofish-forecast-238599093681.us-west2.run.app`
- GCS bucket: `total-now-339022-mirofish-results`

If you find yourself touching anything related to live trading, order routing, websockets to a broker, or Zep — stop. You are probably in the wrong repo. See `AGENT_CONTEXT.md`.

---

## 2. Tech stack at a glance

| Layer | Stack |
| --- | --- |
| Backend | Python 3.12, Flask 3, Gunicorn (`gthread`, **1 worker**, 8 threads), Pydantic v2 + `pydantic-settings` |
| Frontend | Vue 3, Vite 6, TypeScript, Pinia, Tailwind v4, `lightweight-charts`, `echarts`/`vue-echarts`, `splitpanes`, `@vueuse/core` |
| Market data | Databento GLBX.MDP3 (via sidecar live-writer → Upstash Redis), FRED, yfinance, IB Market Internals relay, CNN Fear & Greed, VIX term structure |
| ML | LightGBM (binary direction + 2 quantile regressors), scikit-learn, CQR + ACI conformal calibration, `mlflow-skinny` for experiment tracking |
| LLM | OpenAI — `gpt-4o-2024-08-06` for parsing/synthesis, `gpt-4o-mini-2024-07-18` for simulation agents |
| Infra | Docker (multi-stage), Cloud Run (8 GiB / 4 CPU, min=1), Cloud Scheduler, Artifact Registry, Workload Identity Federation, GCS |

---

## 3. Directory layout

```
mirofish-forecast-/
├── src/mirofish_forecast/         # Python package (src layout)
│   ├── app.py                     # Flask factory; serves Vue SPA + API blueprints
│   ├── api/                       # Flask blueprints
│   │   ├── health.py              # /health/{startup,liveness,readiness}
│   │   ├── market_routes.py       # /api/market/{context,ohlcv,snapshot}
│   │   ├── forecast_routes.py     # /api/forecast/* (SSE-driven)
│   │   ├── ml_routes.py           # /api/ml/{train,status,experiments,...}
│   │   └── middleware.py          # Request ID, CORS, error handlers
│   ├── services/                  # Orchestration
│   │   ├── pipeline.py            # ForecastPipeline — runs in background thread
│   │   ├── data_aggregator.py     # Builds MarketContext from all data clients
│   │   ├── nlp_parser.py          # Raw query → ForecastQuery
│   │   ├── scenario_builder.py    # MarketContext → SimulationScenario
│   │   ├── simulation_runner.py   # Monte Carlo with LLM agents
│   │   ├── forecast_synthesizer.py# Sims → ForecastResult
│   │   ├── bar_analytics.py       # Pre-computed signals for agent prompts
│   │   ├── session_context.py     # RTH/overnight/closed status
│   │   └── tod_regime.py          # Time-of-day regime adjustments
│   ├── data/                      # External clients (one per source)
│   │   ├── cache.py               # Upstash Redis wrapper (mf: prefix)
│   │   ├── databento_client.py    # Reads bars/prices from Redis (writer-fed)
│   │   ├── fred_client.py         # FRED macro data
│   │   ├── yfinance_client.py     # Cross-asset prices
│   │   ├── ib_client.py           # NYSE TICK/ADD/VOLD via private relay
│   │   ├── fear_greed_client.py   # CNN Fear & Greed
│   │   ├── vix_client.py          # VIX term structure
│   │   ├── economic_calendar.py   # FOMC/CPI/NFP/GDP/PPI/PCE/ISM
│   │   └── session_levels.py      # Daily/overnight reference levels
│   ├── ml/                        # LightGBM fast path
│   │   ├── feature_extractor.py   # 25 features (22 direction + 3 cross-asset)
│   │   ├── fast_path.py           # FastPathRunner (sub-5s inference)
│   │   ├── trainer.py             # ModelTrainer; reads tracked outcomes
│   │   ├── model_store.py         # Pickled models in Redis (30d TTL)
│   │   ├── signal_bar.py          # Brooks 0–100 rubric for agents
│   │   └── experiment_tracker.py  # Run history (last 100, 6mo retention)
│   ├── calibration/               # Conformal calibration (CQR + ACI)
│   │   ├── tracking.py            # ForecastTracker: store + score outcomes
│   │   ├── cqr.py                 # Conformalized Quantile Regression
│   │   ├── aci.py                 # Adaptive Conformal Inference
│   │   ├── reliability.py         # Reliability diagram + summary stats
│   │   └── bootstrap.py           # Synthetic cold-start data
│   ├── llm/                       # OpenAI client + structured-output schemas
│   │   ├── client.py              # LLMClient (rate-limited via aiolimiter)
│   │   ├── schemas.py             # JSON schemas for parse/synthesis
│   │   └── prompts/               # Prompt templates
│   ├── models/                    # Pydantic v2 domain models — frozen, extra=forbid
│   │   ├── base.py                # MiroFishBaseModel
│   │   ├── forecast.py            # ForecastResult, FastPathResult, tracking
│   │   ├── market.py              # MarketContext + sub-models
│   │   ├── query.py               # ForecastQuery, SimPreset, QueryType
│   │   └── scenario.py            # SimulationScenario, MarketRegime, KeyLevel
│   ├── config/
│   │   ├── settings.py            # pydantic-settings, MIROFISH_ env prefix
│   │   └── constants.py           # All TTLs, keys, instrument configs, model params
│   └── utils/
│       ├── logging.py             # JSON formatter for Cloud Logging
│       └── aggregation.py         # OHLCV resampling helpers
├── frontend/                      # Vue 3 SPA
│   └── src/
│       ├── App.vue                # Header + DashboardLayout
│       ├── components/
│       │   ├── layout/            # AppHeader, DashboardLayout, StatusBar, SessionStatus
│       │   ├── chart/             # PriceChart (lightweight-charts) + usePriceData
│       │   ├── chat/              # ChatContainer/Input/Message + StreamingIndicator
│       │   ├── forecast/          # ForecastCard, ProbabilityChart, AgentTraces, ScenarioCards, MarketContextBar
│       │   └── agents/            # AgentPanel
│       ├── composables/
│       │   ├── useForecastStream.ts  # SSE lifecycle + fast-path normalization
│       │   └── useAutoScroll.ts
│       ├── stores/forecastStore.ts   # Pinia: chat history + active instrument
│       └── types/                    # ForecastResult, SSEEvent, SIM_PRESETS, etc.
├── live-writer/                   # Independent Cloud Run service
│   ├── writer.py                  # Databento Live → Redis bars/prices
│   ├── Dockerfile
│   └── deploy_writer.sh
├── tests/
│   ├── conftest.py                # mock_settings, mock_cache, app, client fixtures
│   ├── unit/                      # ~35 files, one per module
│   └── integration/               # Flask route tests
├── .github/workflows/{ci,deploy}.yml
├── Dockerfile                     # Multi-stage: frontend-builder + backend-builder + runtime
├── docker-compose.yml             # Local: app + Redis 7-alpine
├── Makefile                       # install, test, lint, typecheck, format, docker-*, frontend-*
├── pyproject.toml                 # Deps + ruff + mypy + pytest config
├── gunicorn.conf.py               # workers=1, threads=8 — DO NOT scale workers
├── .env.example
├── README.md
├── AGENTS.md                      # Short conventions crib sheet
└── AGENT_CONTEXT.md               # Repo disambiguation
```

---

## 4. Forecast pipelines

There are **two pipelines** sharing the same SSE event channel.

### Full Monte Carlo path (default)

1. `POST /api/forecast/start` → `api/forecast_routes.py` registers a session (`forecast_id`, `Queue`, `cancel Event`) in the in-process `_active_sessions` dict. Returns `202` with `stream_url`.
2. `ForecastPipeline.run()` (`services/pipeline.py`) executes in a daemon thread, emitting SSE events at each stage:
   - `parsing` → `NLPParser` → `ForecastQuery`
   - `data_collection` → `DataAggregator` → `MarketContext` (FRED + yfinance + VIX + Fear&Greed + IB internals + economic calendar)
   - `scenario_building` → `ScenarioBuilder` → `SimulationScenario` (3 ranked scenarios + market regime + per-agent context blocks)
   - `simulation` → `MonteCarloRunner` (concurrency 20, wave size 50, 100/200/500 sims). Emits `progress` events.
   - `synthesis` → `ForecastSynthesizer` → `ForecastResult`
   - `complete` (final SSE event with the full `ForecastResult` payload)
3. The pipeline calls `ForecastTracker.store_forecast()` fire-and-forget after `complete` for calibration tracking.
4. The client subscribes to `GET /api/forecast/stream/<forecast_id>` (EventSource). Pipeline owns one queue per session; `stream_forecast` drains it and tears the session down on `complete` / `error`.
5. `POST /api/forecast/cancel/<forecast_id>` sets the cancel event; the pipeline checks it between stages.

### Fast path

`ml/fast_path.FastPathRunner` skips Monte Carlo and runs in ~5 seconds:

1. `FeatureExtractor` builds a 25-dim vector from `MarketContext`, OHLCV bars, and 1-day cross-asset returns (DXY, TLT, CL).
2. **Binary** LightGBM direction classifier — operates on a 22-feature subset (cross-asset indices `[21, 22, 23]` masked out via `_CROSS_ASSET_INDICES` in `fast_path.py`). Returns `prob_up` / `prob_down`. Below `ML_DIRECTION_CONFIDENCE_THRESHOLD = 0.55` → abstain (report `flat`).
3. Two LightGBM quantile regressors (α = 0.05 and 0.95) → P5 / P95 price interval. These use the **full** 25-feature input.
4. GPT-4o synthesizes a 2–3 sentence paragraph.
5. `_run_fast_path` in `pipeline.py` normalizes `FastPathResult` into a `ForecastResult`-shaped payload (with `build_method="fast_path"` and a few extra `predicted_*` fields) so the frontend renders without special-casing. Always emit through that normalization — never return raw `FastPathResult` to the client.

### Routing priority (`ForecastPipeline._should_use_fast_path`)

1. Explicit `path` in request body (`"fast"` or `"full"`) — wins outright.
2. Sim tier: `quick` / `standard` / `deep` force full MC; `simple` forces fast path.
3. Auto-route fallback: only for unrecognized presets, gated on `fast_path_auto_route` setting, eligible `QueryType` (`direction_forecast`, `point_forecast`), and horizon ≤ `FAST_PATH_MAX_HORIZON` (240 min).

---

## 5. API surface

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health/startup` | Confirms config loaded |
| GET | `/health/liveness` | Process is up |
| GET | `/health/readiness` | Includes Upstash Redis ping |
| GET | `/api/market/context` | Full `MarketContext` JSON |
| GET | `/api/market/ohlcv?instrument=ES&interval=5m&count=200` | Bars (Databento via Redis if available, yfinance fallback) |
| GET | `/api/market/snapshot` | Cross-asset header ticker prices |
| POST | `/api/forecast/start` | Body: `{query, sim_preset?, sim_count?, path?}` → `{forecast_id, stream_url}` |
| GET | `/api/forecast/stream/<id>` | SSE stream of pipeline events |
| POST | `/api/forecast/cancel/<id>` | Cancels in-flight forecast |
| GET | `/api/forecast/session-info` | Market session (RTH/overnight/closed/holiday) |
| GET | `/api/forecast/sessions` | Debug: active forecast sessions |
| GET | `/api/forecast/history` | Tracked forecasts + scored outcomes |
| GET | `/api/forecast/calibration` | CQR/ACI metrics + reliability diagram bins |
| POST | `/api/forecast/check-outcomes` | Score pending forecasts (called by Cloud Scheduler every 30 min) |
| POST | `/api/forecast/bootstrap` | Synthetic cold-start for CQR |
| POST | `/api/forecast/bootstrap/reset` | Resets bootstrap status |
| GET | `/api/forecast/bootstrap/status` | Bootstrap + tracking counts |
| POST | `/api/ml/train` | Kicks off LightGBM training in background thread |
| GET | `/api/ml/status` | Model metadata + last training run |
| GET | `/api/ml/experiments?limit=20` | Run history |
| GET | `/api/ml/experiments/<run_id>` | One run |
| POST | `/api/ml/experiments/compare` | Body: `{run_ids: [...]}` |
| `*` | `/<path>` (catch-all) | Serves Vue SPA from `frontend/dist` (falls back to `index.html`) |

SSE events share a `{stage, status, timestamp, ...}` shape. Statuses are `started`, `progress`, `completed`. Stages are defined in `config/constants.py` (`STAGE_*`) — use the constants, never hardcode strings.

---

## 6. Conventions & invariants

- **Every domain model inherits `MiroFishBaseModel`** (`models/base.py`) — `frozen=True, extra="forbid"`. Mutating raises; typos in field names fail at validation. Use `model.model_copy(update={...})` to derive a new instance.
- **Settings use the `MIROFISH_` env prefix** and are accessed via `get_settings()` (an `lru_cache(maxsize=1)` singleton in `config/settings.py`). Tests must `get_settings.cache_clear()` after `monkeypatch.setenv` (already done in `conftest.py`).
- **All Redis keys are prefixed `mf:`** automatically by `CacheClient`. Databento namespace: `mf:databento:bar:{instrument}:{ts}`, `mf:databento:price:{instrument}`, `mf:databento:barlist:{instrument}` (sorted set by timestamp), `mf:databento:writer:heartbeat`. Tracking: `mf:track:*`. ML models: `mf:ml:*`. Experiments: `mf:experiments:*`.
- **Data clients return Pydantic models, not raw dicts.**
- **Structured JSON logging** via `utils/logging.JSONFormatter` for Cloud Logging compatibility.
- **`INSTRUMENT_CONFIG` in `config/constants.py` is the source of truth** for ES/NQ/CL/GC (tick size, point value, drift anchor weight, max bar move %, decimals, key drivers). Always look up via `get_instrument_config(symbol)` — never hardcode ES values elsewhere.
- **Style:** line length 100, ruff (`E,F,I,N,W,UP`), mypy strict + pydantic plugin, Python 3.12 only.
- **Comments:** prefer self-documenting names. Reserve comments for non-obvious WHY (workarounds, calibrated constants, hidden invariants). Don't add comments that restate the code.

---

## 7. Dev workflow

```bash
# Setup (Python)
make install                      # pip install -e ".[dev]"
cp .env.example .env              # then fill in real keys

# Tests / lint / types
make test                         # pytest with coverage on src/mirofish_forecast
make lint                         # ruff check + ruff format --check
make format                       # ruff format + ruff check --fix
make typecheck                    # mypy --strict src/

# Run a single test
pytest tests/unit/test_pipeline.py::test_name -xvs

# Local Docker (also brings up Redis 7-alpine)
make docker-build
make docker-run                   # docker compose up --build

# Frontend
make frontend-install             # npm ci
make frontend-dev                 # vite on :5173, proxies /api → :8080
make frontend-build               # writes frontend/dist/ — required for SPA serving
```

Required env vars (see `.env.example`):

- `MIROFISH_FRED_API_KEY`
- `MIROFISH_REDIS_URL` / `MIROFISH_REDIS_TOKEN` (Upstash HTTP)
- `MIROFISH_IB_RELAY_URL`
- `MIROFISH_OPENAI_API_KEY`
- `MIROFISH_DATABENTO_API_KEY` (optional — only needed if you run a local writer)

CI runs with placeholder values (see `.github/workflows/ci.yml`); reuse those when running tests without real credentials.

---

## 8. Testing

- 35+ unit test files in `tests/unit/` (one per module — `test_pipeline.py`, `test_databento_client.py`, `test_cqr.py`, `test_aci.py`, `test_signal_bar.py`, etc.).
- 2 Flask integration tests in `tests/integration/` (`test_forecast_routes.py`, `test_market_routes.py`).
- `tests/conftest.py` provides:
  - `mock_settings` — sets the `MIROFISH_*` env vars and clears the settings cache.
  - `mock_cache` — `MagicMock(spec=CacheClient)` that misses on every `get`.
  - `app` — Flask app via `create_app()` with `TESTING=True`.
  - `client` — Flask test client.
- Coverage target: package `src/mirofish_forecast`. `pytest` is configured in `pyproject.toml` with `--tb=short --cov=... --cov-report=term-missing`.

---

## 9. CI/CD & deployment

`.github/workflows/ci.yml` runs on push/PR to `main`:

- Backend: `ruff check`, `ruff format --check`, `mypy` (non-blocking), `pytest`.
- Frontend: `vue-tsc --noEmit`, `vite build`.
- Reusable via `workflow_call` so deploy can chain it.

`.github/workflows/deploy.yml` runs on push to `main`:

1. Calls `ci.yml` first.
2. Authenticates via Workload Identity Federation.
3. Builds the multi-stage Dockerfile, tags `${github.sha}` + `latest`, pushes to `us-west2-docker.pkg.dev/total-now-339022/mirofish-forecast/forecast-api`.
4. `gcloud run deploy mirofish-forecast` — region `us-west2`, gen2 execution env, **8 GiB / 4 CPU**, concurrency=4, min=1, max=10, CPU boost, no CPU throttling, timeout=3600s.
5. Polls `/health/liveness` 5× with 10s sleep.

Concurrency group `deploy-production` does NOT cancel in-progress deploys.

`gunicorn.conf.py` runs **1 worker × 8 threads** by design (see "Known gotchas" §11).

---

## 10. live-writer sidecar

- Lives in `live-writer/` and deploys as its own Cloud Run service: `mirofish-live-writer`, region `us-west2`, **min=max=1**, 256 MiB, 1 CPU, no unauthenticated traffic.
- `writer.py` subscribes to Databento Live `ohlcv-1m` on `GLBX.MDP3` for `ES.c.0, NQ.c.0, CL.c.0, GC.c.0`.
- For each completed bar it writes:
  - `mf:databento:bar:{instrument}:{ts}` — JSON OHLCV (TTL 48 h).
  - `mf:databento:price:{instrument}` — latest close (TTL 10 s).
  - `mf:databento:barlist:{instrument}` — sorted set keyed by timestamp; trimmed to 48 h.
- Heartbeat: `mf:databento:writer:heartbeat` refreshed every ~60 bars.
- A tiny HTTP server runs in a daemon thread on `$PORT` to satisfy Cloud Run's startup probe.
- **The main app's `DatabentoClient` reads exclusively from Redis.** Never call Databento directly from the Flask app.
- Deploy: `cd live-writer && ./deploy_writer.sh` (interactive — prompts for API key, Redis URL, Redis token).

---

## 11. Calibration loop

- Every forecast (full MC and fast path) is stored via `ForecastTracker.store_forecast()` (Redis `mf:track:*`, 90-day retention).
- `POST /api/forecast/check-outcomes` is invoked by Cloud Scheduler every 30 minutes. It scores forecasts whose horizon has elapsed by at least `TRACKING_CHECK_DELAY_MINUTES` (5 min buffer).
- CQR (`calibration/cqr.py`) activates once ≥ `CALIBRATION_MIN_SAMPLES` (200) forecasts have scored outcomes. Retrains every 50 new forecasts on the last 500 (`CALIBRATION_WINDOW_SIZE`).
- ACI (`calibration/aci.py`) nudges the miscoverage rate online with `ACI_GAMMA = 0.02`, clamped to `[0.02, 0.30]`.
- Cold start: `POST /api/forecast/bootstrap` synthesizes calibration data and trains CQR immediately so we don't wait for 200 organic forecasts.

---

## 12. Known gotchas (high signal — read before non-trivial changes)

1. **Do not increase `gunicorn` workers.** `_active_sessions` in `api/forecast_routes.py` is an in-process Python dict guarding the SSE queue + cancel event for each forecast. If you need to scale horizontally, move that state to Redis pubsub first.
2. **`frontend/dist` must exist** for the SPA catch-all. The Dockerfile builds it in the `frontend-builder` stage. Locally, run `make frontend-build` once or `make frontend-dev` (separate port). Without it, `serve_frontend` returns 404 with a build hint.
3. **Don't call Databento directly from Flask.** The live-writer sidecar is the only producer; `DatabentoClient.is_enabled` just checks that recent data exists in Redis.
4. **Direction model feature mask is hardcoded.** `fast_path.py` excludes feature indices `[21, 22, 23]` (cross-asset DXY/TLT/CL) from the binary direction model but keeps them for the quantile models. If you reorder `FeatureExtractor` outputs, update `_CROSS_ASSET_INDICES` in lockstep — and retrain.
5. **Always normalize fast-path results.** `_run_fast_path` reshapes `FastPathResult` into a `ForecastResult`-compatible dict before emitting `complete`. The frontend (`useForecastStream.normalizeFastPathResult`) handles it on its side too. Don't bypass either layer.
6. **`MiroFishBaseModel` is frozen.** Mutation raises. Use `.model_copy(update={...})` to derive a new instance.
7. **`get_settings()` is `lru_cache`d.** When you patch env vars in tests, call `get_settings.cache_clear()` afterward (or rely on the `mock_settings` fixture).
8. **Multi-instrument code is ES-centric by default.** Always look up `INSTRUMENT_CONFIG[symbol]` via `get_instrument_config()` rather than assuming ES tick size / point value / drift anchor / decimals.
9. **SSE keep-alive is 30 s.** Any reverse proxy that buffers will silently break streaming. The Flask response already sets `Cache-Control: no-cache` and `X-Accel-Buffering: no` — preserve those headers.
10. **Redis is Upstash HTTP**, not the binary protocol. Use the `CacheClient` wrapper (or `upstash_redis.Redis`) — not `redis-py`.
11. **Branch policy:** for documentation/auto-task work driven by Claude, develop on the branch listed in the task instructions (currently `claude/add-claude-documentation-WWIIP`). Push with `git push -u origin <branch>`. Retry up to 4× with exponential backoff (2 s, 4 s, 8 s, 16 s) on network failure. **Do NOT open a pull request unless the user explicitly asks.**

---

## 13. See also

- `AGENT_CONTEXT.md` — repo identity & disambiguation from `mirofish-trading`.
- `AGENTS.md` — short conventions crib sheet.
- `README.md` — user onboarding & quick start.
- `pyproject.toml` — dependency versions, ruff / mypy / pytest config.
- `src/mirofish_forecast/config/constants.py` — every TTL, key prefix, instrument config, model hyperparameter, FRED series ID, FOMC date, and routing threshold lives here.
