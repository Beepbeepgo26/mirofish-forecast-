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

# Working Style

This section defines how Antigravity (or any AI coding agent) should approach work on this repository. These principles are derived from Andrej Karpathy's observations on common LLM coding pitfalls and adapted to the specifics of this project.

Append this section to the existing `AGENTS.md` file in each repository. The project-specific rules already in `AGENTS.md` (architecture, conventions, cache prefixes, env vars, etc.) take precedence — these working-style rules govern *how* you work, not *what* you build.

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

LLMs frequently pick one interpretation of an ambiguous request silently and run with it. That is the single most expensive failure mode on this project. Avoid it.

- **State assumptions explicitly.** If you are unsure which file, function, or behavior the user means, say so before writing code. Example: "I'm assuming you mean the binary classification path in `direction.py`, not the legacy 3-class path. Confirm?"
- **Present multiple interpretations.** If a request can reasonably mean two things, surface both with the tradeoffs and ask which is intended. Do not silently pick one.
- **Push back when warranted.** If a simpler approach exists, say so. If the user's plan has a flaw, name it. Helpful disagreement is more valuable than compliant execution of a bad plan.
- **Stop when confused.** If something doesn't add up — a missing file, a contradiction with `AGENT_CONTEXT.md`, a service account mismatch — name it and ask. Do not guess.

**Specific to mirofish:**
- **Always confirm which repo you're operating in.** This codebase has a sibling repo (`mirofish-forecast` vs `mirofish-trading`). Read `AGENT_CONTEXT.md` first. Cross-repo confusion has produced real bugs on this project.
- **Always confirm the service account before any `gcloud run deploy` command.** Wrong service accounts have been a recurring error class. Read it from `AGENT_CONTEXT.md` rather than from memory.
- **Always confirm the secret key names** (`DATABENTO_API_KEY` vs `MIROFISH_DATABENTO_API_KEY`, etc.) by inspecting the code that reads them, not by guessing.

---

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

Combat the tendency toward overengineering:

- **No features beyond what was asked.** If the user asked for a Flask context fix, fix the Flask context. Do not also rewrite the trainer, add metrics, or refactor the route layer.
- **No abstractions for single-use code.** If something is called once, inline it. Do not create a factory, a manager class, or a configuration system unless explicitly requested.
- **No "flexibility" or "configurability" that wasn't requested.** Do not add optional parameters, environment variable overrides, or feature flags that the user did not ask for.
- **No error handling for impossible scenarios.** Handle errors that can actually happen given the surrounding code. Do not catch `Exception` everywhere "just in case."
- **If 200 lines could be 50, rewrite it.**

**The test:** Would a senior engineer reviewing this PR ask "why is this so complicated?" If yes, simplify before submitting.

**Specific to mirofish:**
- **No new infrastructure unless asked.** Do not propose multi-agent code review frameworks, elaborate orchestration patterns, or metaprogramming layers as solutions to small problems. The user has explicitly descoped these in past sessions.
- **Match the existing patterns.** This codebase uses Flask + LightGBM + Upstash Redis + Cloud Run. Don't propose Kubernetes, Kafka, or microservice splits unless the user specifically requests them.

---

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- **Don't "improve" adjacent code, comments, or formatting.** If the user asked you to fix line 41, fix line 41. Don't reformat lines 30-50.
- **Don't refactor things that aren't broken.** If existing code uses a pattern you wouldn't choose, leave it alone unless the user asked.
- **Match existing style, even if you'd do it differently.** Look at neighboring functions before writing new ones. Use the same naming conventions, error handling style, and indentation.
- **If you notice unrelated dead code, mention it — don't delete it.** Surface the observation and let the user decide.

When your changes create orphans:

- **Remove imports/variables/functions that YOUR changes made unused.** If you delete the only caller of a helper, remove the helper too.
- **Don't remove pre-existing dead code unless asked.** It may be load-bearing in ways you don't see.

**The test:** Every changed line should trace directly to the user's request. If you can't explain why a specific change was needed, revert it.

**Specific to mirofish:**
- **Do not modify deployment configs (`gcloud` commands, `cloudbuild.yaml`, GitHub Actions workflows) without explicit instruction.** These have caused production outages when changed unnecessarily.
- **Do not touch `AGENT_CONTEXT.md` or `AGENTS.md` themselves** unless the user explicitly asks for an update to project documentation.

---

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform imperative tasks into verifiable goals:

| Instead of... | Transform to... |
| --- | --- |
| "Add validation" | "Write tests for invalid inputs, then make them pass" |
| "Fix the bug" | "Write a test that reproduces it, then make it pass" |
| "Refactor X" | "Ensure tests pass before and after, behavior is unchanged" |
| "Deploy the patch" | "Patch deployed, `/api/ml/status` returns updated `trained_at`, no exceptions in Cloud Run logs" |

For multi-step tasks, state a brief plan up front:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let the agent loop independently. Weak criteria ("make it work") require constant clarification.

**Specific to mirofish:**

Verification commands the agent should use to confirm work landed:

- **After ML changes:** `curl https://mirofish-forecast-238599093681.us-west2.run.app/api/ml/status` — confirm `trained_at` updates and `last_train_status` is `complete`
- **After Live Writer changes:** `gcloud run services logs read mirofish-live-writer --project=total-now-339022 --region=us-west2 --limit=20` — confirm "Bars written" is increasing, no auth errors
- **After any deploy:** `gcloud run services logs read <service> --project=total-now-339022 --region=us-west2 --limit=50 | grep -i error` — confirm no exceptions in the latest revision
- **After test-related changes:** `make test` — confirm all tests pass (currently 333/333 in mirofish-forecast)

A change is not "done" until the relevant verification command returns the expected result. Submitting a PR with claims of success but no verification output is not acceptable on this project.

---

## Tradeoff Note

These principles bias toward **caution and clarity over speed**. For trivial tasks (typo fixes, obvious one-liners), use judgment — not every change needs the full rigor.

The goal is reducing costly mistakes on non-trivial work, not slowing down simple tasks.

---

## Acknowledgment

These working-style principles are adapted from [Karpathy-Inspired Claude Code Guidelines](https://github.com/forrestchang/andrej-karpathy-skills) by Forrest Chang, derived from Andrej Karpathy's observations on LLM coding pitfalls. Adapted for Antigravity and the mirofish project context.
