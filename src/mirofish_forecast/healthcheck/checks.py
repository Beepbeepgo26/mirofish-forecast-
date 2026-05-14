"""Health check definitions and execution logic.

Each check is a function that returns a CheckResult with pass/warn/fail
status, the observed value, expected range, and a human-readable message.
"""

import json
import logging
import subprocess
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)

BASE_URL = "https://mirofish-forecast-238599093681.us-west2.run.app"

CheckStatus = Literal["pass", "warn", "fail"]


class CheckResult(BaseModel):
    """Result of a single health check."""

    name: str
    status: CheckStatus
    value: str
    expected: str
    message: str


def _safe_check(func):
    """Decorator that catches unhandled exceptions in check functions."""

    def wrapper(*args, **kwargs) -> CheckResult:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return CheckResult(
                name=func.__name__,
                status="fail",
                value="exception",
                expected="no exception",
                message=f"Check raised: {type(e).__name__}: {e}",
            )

    wrapper.__name__ = func.__name__
    return wrapper


def _get_json(
    url: str, method: str = "GET", json_body: dict | None = None, timeout: int = 30
) -> tuple[int, dict]:
    """Make an HTTP request and return (status_code, json_body).

    Uses requests since it's already a project dependency.
    """
    import requests

    if method == "POST":
        resp = requests.post(url, json=json_body, timeout=timeout)
    else:
        resp = requests.get(url, timeout=timeout)
    return resp.status_code, resp.json() if resp.ok else {}


# --- Service Reachability Checks ---


@_safe_check
def ml_status_reachable() -> CheckResult:
    """GET /api/ml/status — pass if HTTP 200 and JSON parseable."""
    code, data = _get_json(f"{BASE_URL}/api/ml/status")
    if code == 200 and data:
        return CheckResult(
            name="ml_status_reachable",
            status="pass",
            value=f"HTTP {code}",
            expected="HTTP 200",
            message="ML status endpoint responding",
        )
    return CheckResult(
        name="ml_status_reachable",
        status="fail",
        value=f"HTTP {code}",
        expected="HTTP 200",
        message="ML status endpoint not reachable",
    )


@_safe_check
def market_snapshot_reachable() -> CheckResult:
    """GET /api/market/snapshot — pass if HTTP 200."""
    code, _ = _get_json(f"{BASE_URL}/api/market/snapshot")
    if code == 200:
        return CheckResult(
            name="market_snapshot_reachable",
            status="pass",
            value=f"HTTP {code}",
            expected="HTTP 200",
            message="Market snapshot endpoint responding",
        )
    return CheckResult(
        name="market_snapshot_reachable",
        status="fail",
        value=f"HTTP {code}",
        expected="HTTP 200",
        message="Market snapshot endpoint not reachable",
    )


@_safe_check
def fast_forecast_reachable() -> CheckResult:
    """POST /api/forecast/quick — pass if HTTP 200 and < 30s."""
    import time

    start = time.monotonic()
    code, data = _get_json(
        f"{BASE_URL}/api/forecast/quick",
        method="POST",
        json_body={"instrument": "ES", "horizon_minutes": 30},
        timeout=30,
    )
    elapsed = time.monotonic() - start

    if code == 200:
        return CheckResult(
            name="fast_forecast_reachable",
            status="pass",
            value=f"HTTP {code} in {elapsed:.1f}s",
            expected="HTTP 200, <30s",
            message="Fast forecast endpoint responding",
        )
    return CheckResult(
        name="fast_forecast_reachable",
        status="fail",
        value=f"HTTP {code} in {elapsed:.1f}s",
        expected="HTTP 200, <30s",
        message=f"Fast forecast failed with HTTP {code}",
    )


# --- Model Health Checks ---


@_safe_check
def direction_model_fresh(ml_status: dict) -> CheckResult:
    """Check direction_model.trained_at is within 8 days."""
    trained_at_str = ml_status.get("direction_model", {}).get("trained_at", "")
    if not trained_at_str:
        return CheckResult(
            name="direction_model_fresh",
            status="fail",
            value="no trained_at",
            expected="within 8 days",
            message="No trained_at timestamp found",
        )

    trained_at = datetime.fromisoformat(trained_at_str).replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - trained_at).total_seconds() / 86400

    if age_days <= 8:
        status: CheckStatus = "pass"
    elif age_days <= 14:
        status = "warn"
    else:
        status = "fail"

    return CheckResult(
        name="direction_model_fresh",
        status=status,
        value=f"{age_days:.1f} days old",
        expected="≤8 days (pass), ≤14 days (warn)",
        message=f"Model trained at {trained_at_str}",
    )


@_safe_check
def direction_model_accuracy_sane(ml_status: dict) -> CheckResult:
    """Check direction accuracy is in [0.48, 0.58]."""
    accuracy = ml_status.get("direction_model", {}).get("accuracy")
    if accuracy is None:
        return CheckResult(
            name="direction_model_accuracy_sane",
            status="fail",
            value="missing",
            expected="0.48–0.58",
            message="No accuracy field found",
        )

    if 0.48 <= accuracy <= 0.58:
        status: CheckStatus = "pass"
        msg = "Accuracy within expected range"
    elif accuracy > 0.58:
        status = "warn"
        msg = "Accuracy suspiciously high — possible data leakage"
    else:
        status = "warn"
        msg = "Accuracy below expected range — possible model degradation"

    return CheckResult(
        name="direction_model_accuracy_sane",
        status=status,
        value=f"{accuracy:.4f}",
        expected="0.48–0.58",
        message=msg,
    )


@_safe_check
def direction_model_mode_binary(ml_status: dict) -> CheckResult:
    """Check direction_model.mode == 'binary'."""
    mode = ml_status.get("direction_model", {}).get("mode", "unknown")
    if mode == "binary":
        return CheckResult(
            name="direction_model_mode_binary",
            status="pass",
            value=mode,
            expected="binary",
            message="Binary classification active",
        )
    return CheckResult(
        name="direction_model_mode_binary",
        status="fail",
        value=mode,
        expected="binary",
        message="Binary classification NOT active — legacy 3-class mode detected",
    )


@_safe_check
def confidence_filtered_pct_sane(ml_status: dict) -> CheckResult:
    """Check confidence_filtered_pct is in [30, 95]."""
    pct = ml_status.get("direction_model", {}).get("confidence_filtered_pct")
    if pct is None:
        return CheckResult(
            name="confidence_filtered_pct_sane",
            status="fail",
            value="missing",
            expected="30–95%",
            message="No confidence_filtered_pct field found",
        )

    if 30 <= pct <= 95:
        status: CheckStatus = "pass"
    else:
        status = "warn"

    return CheckResult(
        name="confidence_filtered_pct_sane",
        status=status,
        value=f"{pct:.1f}%",
        expected="30–95%",
        message=f"Confidence filtering retains {pct:.1f}% of predictions",
    )


@_safe_check
def direction_samples_sufficient(ml_status: dict) -> CheckResult:
    """Check direction_model.direction_samples >= 1500."""
    samples = ml_status.get("direction_model", {}).get("direction_samples")
    if samples is None:
        return CheckResult(
            name="direction_samples_sufficient",
            status="fail",
            value="missing",
            expected="≥1500",
            message="No direction_samples field found",
        )

    if samples >= 1500:
        return CheckResult(
            name="direction_samples_sufficient",
            status="pass",
            value=str(samples),
            expected="≥1500",
            message=f"Training has {samples} direction samples",
        )
    return CheckResult(
        name="direction_samples_sufficient",
        status="warn",
        value=str(samples),
        expected="≥1500",
        message=f"Low sample count: {samples}",
    )


@_safe_check
def last_train_status_complete(ml_status: dict) -> CheckResult:
    """Check last_train_status == 'complete'."""
    status_val = ml_status.get("last_train_status", "unknown")
    if status_val == "complete":
        return CheckResult(
            name="last_train_status_complete",
            status="pass",
            value=status_val,
            expected="complete",
            message="Last training completed successfully",
        )
    return CheckResult(
        name="last_train_status_complete",
        status="fail",
        value=str(status_val),
        expected="complete",
        message=f"Last train status: {status_val}",
    )


@_safe_check
def quantile_high_coverage_sane(ml_status: dict) -> CheckResult:
    """Check quantile_high_model.coverage is in [0.85, 0.95]."""
    coverage = ml_status.get("quantile_high_model", {}).get("coverage")
    if coverage is None:
        return CheckResult(
            name="quantile_high_coverage_sane",
            status="fail",
            value="missing",
            expected="0.85–0.95",
            message="No coverage field found",
        )

    if 0.85 <= coverage <= 0.95:
        status: CheckStatus = "pass"
    else:
        status = "warn"

    return CheckResult(
        name="quantile_high_coverage_sane",
        status=status,
        value=f"{coverage:.4f}",
        expected="0.85–0.95",
        message=f"P95 interval coverage: {coverage:.2%}",
    )


# --- Data Source ---


@_safe_check
def market_snapshot_uses_databento(snapshot: dict) -> CheckResult:
    """Check source == 'databento'."""
    source = snapshot.get("source", "unknown")
    if source == "databento":
        return CheckResult(
            name="market_snapshot_uses_databento",
            status="pass",
            value=source,
            expected="databento",
            message="Primary data source is Databento",
        )
    return CheckResult(
        name="market_snapshot_uses_databento",
        status="warn",
        value=source,
        expected="databento",
        message=f"Falling back to {source}",
    )


# --- Live Writer ---


@_safe_check
def live_writer_no_errors() -> CheckResult:
    """Check last 100 live writer log lines for errors."""
    result = subprocess.run(
        [
            "gcloud",
            "logging",
            "read",
            "resource.type=cloud_run_revision AND resource.labels.service_name=mirofish-live-writer",
            "--project=total-now-339022",
            "--limit=100",
            "--format=json",
            "--freshness=1d",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        return CheckResult(
            name="live_writer_no_errors",
            status="warn",
            value="gcloud failed",
            expected="0 errors",
            message=f"Could not read logs: {result.stderr[:200]}",
        )

    log_text = result.stdout
    error_keywords = ["[ERROR]", "Authentication failed", "Exception", "Traceback"]
    error_count = sum(log_text.count(kw) for kw in error_keywords)

    if error_count == 0:
        return CheckResult(
            name="live_writer_no_errors",
            status="pass",
            value="0 errors",
            expected="0 errors",
            message="No errors in recent live writer logs",
        )
    return CheckResult(
        name="live_writer_no_errors",
        status="fail",
        value=f"{error_count} errors",
        expected="0 errors",
        message=f"Found {error_count} error indicators in live writer logs",
    )


@_safe_check
def live_writer_bars_increasing() -> CheckResult:
    """Check that bars are being written (skip weekends)."""
    now = datetime.now(UTC)
    # CME closed Sat-Sun — skip this check
    if now.weekday() in (5, 6):
        return CheckResult(
            name="live_writer_bars_increasing",
            status="pass",
            value="weekend",
            expected="skipped on weekends",
            message="CME closed — check skipped",
        )

    result = subprocess.run(
        [
            "gcloud",
            "logging",
            "read",
            'resource.type=cloud_run_revision AND resource.labels.service_name=mirofish-live-writer AND textPayload:"Bars written"',
            "--project=total-now-339022",
            "--limit=5",
            "--format=json",
            "--freshness=2h",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        return CheckResult(
            name="live_writer_bars_increasing",
            status="warn",
            value="gcloud failed",
            expected="bars > 0",
            message=f"Could not read logs: {result.stderr[:200]}",
        )

    try:
        entries = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        entries = []

    if not entries:
        return CheckResult(
            name="live_writer_bars_increasing",
            status="fail",
            value="0 entries",
            expected="bars increasing",
            message="No 'Bars written' entries in last 2 hours",
        )

    # Extract the latest bar count
    import re

    latest_text = entries[0].get("textPayload", "")
    match = re.search(r"Bars written:\s*(\d+)", latest_text)
    bar_count = int(match.group(1)) if match else 0

    return CheckResult(
        name="live_writer_bars_increasing",
        status="pass" if bar_count > 0 else "fail",
        value=f"{bar_count} bars",
        expected="bars > 0",
        message=f"Latest bar count: {bar_count}",
    )


# --- Hybrid Agents ---


@_safe_check
def hybrid_agents_firing(forecast_response: dict) -> CheckResult:
    """Check forecast response contains Brooks-specific analytical terms."""
    brooks_terms = [
        "VWAP",
        "signal score",
        "Always-In",
        "day type",
        "IB",
        "PDH",
        "PDL",
        "ONH",
        "ONL",
    ]

    # Combine all reasoning fields
    text = " ".join(
        [
            str(forecast_response.get("institutional_reasoning", "")),
            str(forecast_response.get("retail_reasoning", "")),
            str(forecast_response.get("market_maker_reasoning", "")),
            str(forecast_response.get("forecast_text", "")),
        ]
    )

    found = [term for term in brooks_terms if term in text]

    if len(found) >= 2:
        return CheckResult(
            name="hybrid_agents_firing",
            status="pass",
            value=f"{len(found)} terms found",
            expected="≥2 Brooks terms",
            message=f"Found: {', '.join(found[:5])}",
        )
    return CheckResult(
        name="hybrid_agents_firing",
        status="fail",
        value=f"{len(found)} terms found",
        expected="≥2 Brooks terms",
        message="Hybrid agent framework may not be wired into forecast path",
    )


# --- Check Runner ---


def run_all_checks() -> list[CheckResult]:
    """Execute all health checks and return results."""
    results: list[CheckResult] = []

    # Phase 1: Fetch shared data
    logger.info("Fetching ML status...")
    ml_code, ml_data = _get_json(f"{BASE_URL}/api/ml/status")

    logger.info("Fetching market snapshot...")
    snap_code, snap_data = _get_json(f"{BASE_URL}/api/market/snapshot")

    logger.info("Fetching fast forecast...")
    fc_code, fc_data = _get_json(
        f"{BASE_URL}/api/forecast/quick",
        method="POST",
        json_body={"instrument": "ES", "horizon_minutes": 30},
        timeout=30,
    )

    # Phase 2: Service reachability
    results.append(ml_status_reachable())
    results.append(market_snapshot_reachable())
    results.append(fast_forecast_reachable())

    # Phase 3: Model health (use cached ml_data)
    results.append(direction_model_fresh(ml_data))
    results.append(direction_model_accuracy_sane(ml_data))
    results.append(direction_model_mode_binary(ml_data))
    results.append(confidence_filtered_pct_sane(ml_data))
    results.append(direction_samples_sufficient(ml_data))
    results.append(last_train_status_complete(ml_data))
    results.append(quantile_high_coverage_sane(ml_data))

    # Phase 4: Data source
    results.append(market_snapshot_uses_databento(snap_data))

    # Phase 5: Live writer
    results.append(live_writer_no_errors())
    results.append(live_writer_bars_increasing())

    # Phase 6: Hybrid agents
    results.append(hybrid_agents_firing(fc_data))

    for r in results:
        logger.info(f"  [{r.status.upper():4s}] {r.name}: {r.value} — {r.message}")

    return results
