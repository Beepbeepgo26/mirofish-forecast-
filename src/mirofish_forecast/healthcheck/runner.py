"""Health check runner — main entry point.

Usage: python -m mirofish_forecast.healthcheck.runner

Runs all checks, sends email report, writes JSON to GCS.
"""

import json
import logging
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from mirofish_forecast.healthcheck.checks import CheckResult, run_all_checks
from mirofish_forecast.healthcheck.email_sender import send_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

GCS_BUCKET = "total-now-339022-mirofish-results"


def _build_report_json(results: list[CheckResult]) -> dict:
    """Build a JSON-serializable report dict."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(results),
            "pass": sum(1 for r in results if r.status == "pass"),
            "warn": sum(1 for r in results if r.status == "warn"),
            "fail": sum(1 for r in results if r.status == "fail"),
        },
        "checks": [r.model_dump() for r in results],
    }


def _write_to_gcs(report: dict) -> None:
    """Write report JSON to GCS using gsutil."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    gcs_path = f"gs://{GCS_BUCKET}/healthchecks/{date_str}.json"

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(report, f, indent=2)
            tmp_path = f.name

        result = subprocess.run(
            ["gsutil", "cp", tmp_path, gcs_path],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            logger.info(f"Report written to {gcs_path}")
        else:
            logger.warning(f"GCS write failed: {result.stderr[:200]}")

    except Exception:
        logger.warning("Failed to write report to GCS", exc_info=True)


def main() -> None:
    """Run all health checks, send email, write to GCS."""
    logger.info("=== MiroFish Health Check Starting ===")

    results = run_all_checks()
    report = _build_report_json(results)

    # Log summary
    summary = report["summary"]
    logger.info(
        f"Results: {summary['pass']} pass, "
        f"{summary['warn']} warn, {summary['fail']} fail"
    )

    # Send email
    try:
        send_report(results)
    except Exception:
        logger.error("Failed to send email report", exc_info=True)

    # Write to GCS
    _write_to_gcs(report)

    logger.info("=== MiroFish Health Check Complete ===")

    # Exit with code 1 if any checks failed
    if summary["fail"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
