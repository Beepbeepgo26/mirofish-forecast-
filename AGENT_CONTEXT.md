# MiroFish Forecast — Repo Identity

**This is the STANDALONE FORECASTING app. NOT mirofish-trading.**

## Repo Identification
- Local path: `/Users/sam/Desktop/mirofish-forecast/`
- GitHub: `github.com/Beepbeepgo26/mirofish-forecast-`
- Cloud Run service: `mirofish-forecast` (us-west2)
- Live URL: `https://mirofish-forecast-238599093681.us-west2.run.app/`
- GCS bucket: `total-now-339022-mirofish-results`
- Deploy SA: `mirofish-forecast-deploy@total-now-339022.iam.gserviceaccount.com`

## What This App Does
Natural language forecasting for ES/NQ/CL/GC futures. Users submit queries, get calibrated probabilistic forecasts via Monte Carlo simulation or LightGBM fast path.

## Key Technologies
- Flask + Vue 3 + Vite + Tailwind
- LightGBM (direction + quantile models)
- GPT-4o / 4o-mini (agents, synthesis)
- Upstash Redis (caching + calibration storage)
- CQR + ACI (calibration layer)
- Databento GLBX.MDP3 (primary price data)
- Cloud Run + Cloud Scheduler

## What This Repo Does NOT Contain
- Zep Cloud memory integration (that's mirofish-trading)
- MiroFish trading simulation engine (that's mirofish-trading)
- Websocket streaming for live trading (that's mirofish-trading)
- Any execution or order management logic

## Before Making Changes
Confirm you are working in this repo by checking:
1. Path starts with `/Users/sam/Desktop/mirofish-forecast/`
2. Package name is `mirofish_forecast` (with underscore)
3. Cloud Run service target is `mirofish-forecast`

If ANY of these don't match, STOP — you may be in the wrong repo.
