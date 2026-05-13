import json
import logging
import sys


_STANDARD_FIELDS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys())


class JSONFormatter(logging.Formatter):
    """Outputs structured JSON logs compatible with Google Cloud Logging.

    Any keys passed via ``extra={}`` are included as top-level fields
    in the JSON output, making them queryable via ``jsonPayload.*``
    in Cloud Logging.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, object] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Propagate extra fields
        for key, value in record.__dict__.items():
            if key not in _STANDARD_FIELDS and key not in log_entry:
                log_entry[key] = value

        return json.dumps(log_entry, default=str)


def setup_logging(debug: bool = False) -> None:
    """Configure structured logging for the application."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
