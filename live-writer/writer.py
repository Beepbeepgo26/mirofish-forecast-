"""Databento Live Writer — writes real-time OHLCV bars to Redis.

Runs as a persistent service. Subscribes to ohlcv-1m for ES, NQ, CL, GC
on GLBX.MDP3 and writes each completed bar to Upstash Redis.

Bars are immutable once closed — cache aggressively.
"""

import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import databento as db
from upstash_redis import Redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration from environment
DATABENTO_API_KEY = os.environ["DATABENTO_API_KEY"]
REDIS_URL = os.environ["REDIS_URL"]
REDIS_TOKEN = os.environ["REDIS_TOKEN"]

# Symbols to subscribe
SYMBOLS = ["ES.c.0", "NQ.c.0", "CL.c.0", "GC.c.0"]
DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"

# Redis key patterns
# Live bars: mf:databento:bar:{symbol}:{timestamp}
# Latest price: mf:databento:price:{symbol}
# Bar list: mf:databento:barlist:{symbol} (sorted set by timestamp)
BAR_TTL = 172800  # 48 hours
PRICE_TTL = 10    # 10 seconds — overwritten every minute anyway

# Symbol name mapping (Databento raw_symbol → our instrument code)
SYMBOL_MAP = {
    "ES": "ES",
    "NQ": "NQ",
    "CL": "CL",
    "GC": "GC",
}


def resolve_instrument(raw_symbol: str) -> str | None:
    """Map a Databento raw_symbol (e.g. ESM6) to our instrument code (ES)."""
    for prefix, instrument in SYMBOL_MAP.items():
        if raw_symbol.startswith(prefix):
            return instrument
    return None


# ---------------------------------------------------------------------------
# Cloud Run health server (required — CR won't route traffic without HTTP)
# ---------------------------------------------------------------------------

_health_state: dict = {"status": "starting", "bars": 0, "errors": 0}


def start_health_server(port: int = 8080) -> None:
    """Start a minimal HTTP server in a daemon thread for Cloud Run health checks."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps(_health_state).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002
            pass  # Suppress access logs to keep Cloud Run logs clean

    server = HTTPServer(("", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    logger.info(f"Health server listening on :{port}")


def main():
    # Start Cloud Run health server first so startup probe passes immediately
    port = int(os.environ.get("PORT", 8080))
    start_health_server(port)
    _health_state["status"] = "initializing"

    redis = Redis(url=REDIS_URL, token=REDIS_TOKEN)
    logger.info("Connected to Redis")

    # Test Redis connection
    redis.set("mf:databento:writer:heartbeat", datetime.now(timezone.utc).isoformat(), ex=120)
    logger.info("Redis heartbeat set")
    _health_state["status"] = "subscribed"

    client = db.Live(key=DATABENTO_API_KEY)
    logger.info(f"Subscribing to {DATASET} {SCHEMA} for {SYMBOLS}")

    client.subscribe(
        dataset=DATASET,
        schema=SCHEMA,
        stype_in="continuous",
        symbols=SYMBOLS,
    )

    bar_count = 0
    error_count = 0

    # Build instrument_id → instrument name mapping at runtime
    # Populated by SymbolMappingMsg records before OHLCV data arrives
    instrument_id_map: dict[int, str] = {}

    def handle_ohlcv(record) -> None:
        nonlocal bar_count
        try:
            # Extract fields
            # Databento prices are in fixed-point 1e-9; to_df() handles this,
            # but raw records need manual conversion
            o = record.open / 1e9
            h = record.high / 1e9
            l = record.low / 1e9
            c = record.close / 1e9
            v = record.volume

            # Get the bar's timestamp (end of bar period)
            ts = int(record.ts_event / 1e9)  # nanoseconds → seconds
            ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

            # Resolve instrument: try instrument_id map first, then pretty_symbol
            instrument = None
            iid = getattr(record, "instrument_id", None)
            if iid is not None and iid in instrument_id_map:
                instrument = instrument_id_map[iid]

            if instrument is None:
                # Try pretty_symbol or symbol attribute
                for attr in ("pretty_symbol", "symbol"):
                    sym = getattr(record, attr, None)
                    if sym:
                        instrument = resolve_instrument(str(sym))
                        if instrument:
                            break

            if instrument is None:
                instrument = "ES"  # Conservative fallback

            bar = {
                "time": ts,
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
                "volume": int(v),
                "instrument": instrument,
                "ts_iso": ts_iso,
            }

            # Write bar to Redis
            bar_key = f"mf:databento:bar:{instrument}:{ts}"
            redis.set(bar_key, json.dumps(bar), ex=BAR_TTL)

            # Update latest price
            price_key = f"mf:databento:price:{instrument}"
            redis.set(price_key, str(round(c, 2)), ex=PRICE_TTL)

            # Add to sorted set for range queries
            list_key = f"mf:databento:barlist:{instrument}"
            redis.zadd(list_key, {bar_key: float(ts)})

            # Trim old entries from sorted set (keep 48 hours)
            cutoff = ts - BAR_TTL
            redis.zremrangebyscore(list_key, 0, cutoff)

            bar_count += 1
            _health_state["bars"] = bar_count
            _health_state["status"] = "streaming"
            if bar_count % 10 == 0:
                logger.info(
                    f"Bars written: {bar_count} | Latest {instrument}: {c:.2f}"
                )

            # Update heartbeat
            if bar_count % 60 == 0:
                redis.set(
                    "mf:databento:writer:heartbeat",
                    datetime.now(timezone.utc).isoformat(),
                    ex=120,
                )

        except Exception as e:
            nonlocal error_count
            error_count += 1
            _health_state["errors"] = error_count
            logger.error(f"Error processing bar: {e}")
            if error_count > 100:
                logger.critical("Too many errors, exiting")
                sys.exit(1)

    def handle_symbol_mapping(record) -> None:
        """Build instrument_id → instrument name mapping."""
        stype_out = getattr(record, "stype_out_symbol", "")
        stype_in = getattr(record, "stype_in_symbol", "")
        iid = getattr(record, "instrument_id", None)
        logger.info(f"Symbol mapping: {stype_in} → {stype_out} (id={iid})")
        if stype_out and iid is not None:
            instrument = resolve_instrument(stype_out)
            if instrument:
                instrument_id_map[iid] = instrument
                logger.info(f"  Mapped instrument_id {iid} → {instrument}")

    # Graceful shutdown
    def shutdown(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        try:
            client.stop()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Main loop — blocks and dispatches records
    # Use type().__name__ + hasattr instead of singledispatch because Databento's
    # C-struct records don't always resolve correctly with singledispatch.
    logger.info("Live writer running. Processing bars...")
    try:
        for record in client:
            rtype = type(record).__name__
            # OHLCV bars have 'volume' attribute; SystemMsg does not
            if rtype == "OHLCVMsg" or (hasattr(record, "volume") and hasattr(record, "ts_event")):
                handle_ohlcv(record)
            elif rtype == "SymbolMappingMsg" or hasattr(record, "stype_out_symbol"):
                handle_symbol_mapping(record)
            elif rtype == "ErrorMsg":
                logger.error(f"Databento error: {getattr(record, 'err', record)}")
            elif rtype == "SystemMsg":
                msg = getattr(record, "msg", "")
                code = getattr(record, "code", "")
                logger.info(f"system message code={code} msg='{msg}'")
            else:
                # Log unknown types for debugging
                logger.info(f"Unknown record type={rtype} attrs={dir(record)}")
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        try:
            client.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
