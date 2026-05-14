"""Integration tests for the healthcheck runner."""

from unittest.mock import MagicMock, patch

import pytest

from mirofish_forecast.healthcheck.checks import CheckResult
from mirofish_forecast.healthcheck.runner import _build_report_json, main


@pytest.fixture
def mock_check_results() -> list[CheckResult]:
    """Sample check results for testing."""
    return [
        CheckResult(name="test_pass", status="pass", value="ok", expected="ok", message="All good"),
        CheckResult(
            name="test_warn", status="warn", value="5", expected="<3", message="Slightly high"
        ),
        CheckResult(
            name="test_fail", status="fail", value="down", expected="up", message="Service down"
        ),
    ]


class TestBuildReportJson:
    def test_summary_counts(self, mock_check_results: list[CheckResult]) -> None:
        report = _build_report_json(mock_check_results)

        assert report["summary"]["total"] == 3
        assert report["summary"]["pass"] == 1
        assert report["summary"]["warn"] == 1
        assert report["summary"]["fail"] == 1
        assert "timestamp" in report
        assert len(report["checks"]) == 3

    def test_checks_serialized(self, mock_check_results: list[CheckResult]) -> None:
        report = _build_report_json(mock_check_results)

        first = report["checks"][0]
        assert first["name"] == "test_pass"
        assert first["status"] == "pass"
        assert first["value"] == "ok"


class TestMainRunner:
    @patch("mirofish_forecast.healthcheck.runner._write_to_gcs")
    @patch("mirofish_forecast.healthcheck.runner.send_report")
    @patch("mirofish_forecast.healthcheck.runner.run_all_checks")
    def test_all_pass_exits_zero(
        self,
        mock_checks: MagicMock,
        mock_email: MagicMock,
        mock_gcs: MagicMock,
    ) -> None:
        mock_checks.return_value = [
            CheckResult(name="test", status="pass", value="ok", expected="ok", message="ok"),
        ]

        # main() should not raise or call sys.exit(1)
        main()

        mock_email.assert_called_once()
        mock_gcs.assert_called_once()

    @patch("mirofish_forecast.healthcheck.runner._write_to_gcs")
    @patch("mirofish_forecast.healthcheck.runner.send_report")
    @patch("mirofish_forecast.healthcheck.runner.run_all_checks")
    def test_failure_exits_one(
        self,
        mock_checks: MagicMock,
        mock_email: MagicMock,
        mock_gcs: MagicMock,
    ) -> None:
        mock_checks.return_value = [
            CheckResult(name="test", status="fail", value="bad", expected="good", message="broken"),
        ]

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

        mock_email.assert_called_once()
        mock_gcs.assert_called_once()

    @patch("mirofish_forecast.healthcheck.runner._write_to_gcs")
    @patch("mirofish_forecast.healthcheck.runner.send_report")
    @patch("mirofish_forecast.healthcheck.runner.run_all_checks")
    def test_email_failure_does_not_crash(
        self,
        mock_checks: MagicMock,
        mock_email: MagicMock,
        mock_gcs: MagicMock,
    ) -> None:
        mock_checks.return_value = [
            CheckResult(name="test", status="pass", value="ok", expected="ok", message="ok"),
        ]
        mock_email.side_effect = Exception("SMTP connection refused")

        # Should not raise despite email failure
        main()

        mock_gcs.assert_called_once()


class TestEmailContent:
    def test_subject_all_green(self, mock_check_results: list[CheckResult]) -> None:
        from mirofish_forecast.healthcheck.email_sender import _build_subject

        all_pass = [r for r in mock_check_results if r.status == "pass"]
        subject = _build_subject(all_pass)
        assert "ALL GREEN" in subject

    def test_subject_with_failures(self, mock_check_results: list[CheckResult]) -> None:
        from mirofish_forecast.healthcheck.email_sender import _build_subject

        subject = _build_subject(mock_check_results)
        assert "1 FAIL" in subject
        assert "1 WARN" in subject

    def test_html_contains_checks(self, mock_check_results: list[CheckResult]) -> None:
        from mirofish_forecast.healthcheck.email_sender import _build_html

        html = _build_html(mock_check_results)
        assert "test_pass" in html
        assert "test_fail" in html
        assert "🟢" in html
        assert "🔴" in html

    def test_plaintext_contains_checks(self, mock_check_results: list[CheckResult]) -> None:
        from mirofish_forecast.healthcheck.email_sender import _build_plaintext

        text = _build_plaintext(mock_check_results)
        assert "test_pass" in text
        assert "[FAIL]" in text
