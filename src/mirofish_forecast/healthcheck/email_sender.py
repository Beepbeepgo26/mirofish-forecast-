"""Gmail SMTP email sender for health check reports.

Reads credentials from environment variables:
- MIROFISH_HEALTHCHECK_EMAIL_FROM
- MIROFISH_HEALTHCHECK_EMAIL_PASSWORD  (Gmail App Password)
- MIROFISH_HEALTHCHECK_EMAIL_TO
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from mirofish_forecast.healthcheck.checks import CheckResult

logger = logging.getLogger(__name__)

STATUS_DOTS = {
    "pass": "🟢",
    "warn": "🟡",
    "fail": "🔴",
}


def _build_subject(results: list[CheckResult]) -> str:
    """Build email subject line summarising pass/warn/fail counts."""
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for r in results:
        counts[r.status] += 1

    if counts["fail"] == 0 and counts["warn"] == 0:
        return "MiroFish Health: ALL GREEN ✅"

    parts: list[str] = []
    if counts["fail"] > 0:
        parts.append(f"{counts['fail']} FAIL")
    if counts["warn"] > 0:
        parts.append(f"{counts['warn']} WARN")
    return f"MiroFish Health: {', '.join(parts)}"


def _build_html(results: list[CheckResult]) -> str:
    """Build an HTML email body with a results table."""
    rows: list[str] = []
    for r in results:
        dot = STATUS_DOTS.get(r.status, "⚪")
        bg = {"pass": "#f0fdf4", "warn": "#fefce8", "fail": "#fef2f2"}.get(r.status, "#fff")
        rows.append(
            f"<tr style='background:{bg}'>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb'>{r.name}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb;text-align:center'>{dot}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb;font-family:monospace'>{r.value}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb'>{r.expected}</td>"
            f"<td style='padding:6px 10px;border:1px solid #e5e7eb'>{r.message}</td>"
            f"</tr>"
        )

    return f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #111;">
      <h2 style="margin-bottom:4px">MiroFish Forecast — Daily Health Check</h2>
      <p style="color:#6b7280;margin-top:0">
        {sum(1 for r in results if r.status == 'pass')} pass,
        {sum(1 for r in results if r.status == 'warn')} warn,
        {sum(1 for r in results if r.status == 'fail')} fail
        — {len(results)} total checks
      </p>
      <table style="border-collapse:collapse;width:100%;font-size:13px">
        <thead>
          <tr style="background:#f9fafb">
            <th style="padding:6px 10px;border:1px solid #e5e7eb;text-align:left">Check</th>
            <th style="padding:6px 10px;border:1px solid #e5e7eb">Status</th>
            <th style="padding:6px 10px;border:1px solid #e5e7eb;text-align:left">Value</th>
            <th style="padding:6px 10px;border:1px solid #e5e7eb;text-align:left">Expected</th>
            <th style="padding:6px 10px;border:1px solid #e5e7eb;text-align:left">Message</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
      <p style="color:#9ca3af;font-size:11px;margin-top:16px">
        Sent by mirofish-healthcheck Cloud Run job
      </p>
    </body>
    </html>
    """


def _build_plaintext(results: list[CheckResult]) -> str:
    """Build a plain-text fallback."""
    lines = ["MiroFish Forecast — Daily Health Check", ""]
    for r in results:
        marker = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}.get(r.status, "??")
        lines.append(f"[{marker:4s}] {r.name}: {r.value} — {r.message}")
    return "\n".join(lines)


def send_report(results: list[CheckResult]) -> None:
    """Send the health check report via Gmail SMTP.

    Raises:
        RuntimeError: If email credentials are not configured.
    """
    email_from = os.environ.get("MIROFISH_HEALTHCHECK_EMAIL_FROM")
    email_password = os.environ.get("MIROFISH_HEALTHCHECK_EMAIL_PASSWORD")
    email_to = os.environ.get("MIROFISH_HEALTHCHECK_EMAIL_TO")

    if not all([email_from, email_password, email_to]):
        logger.warning("Email credentials not configured — skipping email send")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = _build_subject(results)
    msg["From"] = email_from
    msg["To"] = email_to

    msg.attach(MIMEText(_build_plaintext(results), "plain"))
    msg.attach(MIMEText(_build_html(results), "html"))

    logger.info(f"Sending health report to {email_to}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(email_from, email_password)
        server.send_message(msg)

    logger.info("Health report email sent")
