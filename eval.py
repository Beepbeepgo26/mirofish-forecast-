"""Offline evaluation harness for Mirofish 3-class direction forecast.

Fetches ES.c.0 hourly bars via Databento, caches as parquet, computes
features, generates 3-class labels (up/down/flat), and reports
direction_accuracy on the OOS (out-of-sample) split.

Usage:
    python eval.py --split oos --session rth
    python eval.py --split oos --session rth | grep "direction_accuracy"

TODO 1: Wire real model imports from src.ml once model artifacts exist.
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

CACHE_DIR = Path(os.getenv("MIROFISH_CACHE_DIR", "data/cache"))
DATABENTO_API_KEY = os.getenv("DATABENTO_API_KEY", "")
DATASET = "GLBX.MDP3"
SYMBOL = "ES.c.0"
SCHEMA = "ohlcv-1h"
DATA_START = "2024-04-01"
MIN_MOVE_PCT = 0.001
TRAIN_RATIO = 0.80
FEATURE_LOOKBACK = 78

MOMENTUM_WINDOWS = [1, 3, 6, 12]
VOL_WINDOW = 20


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mirofish eval harness")
    p.add_argument(
        "--split",
        choices=["oos", "is", "full"],
        default="oos",
        help="oos = out-of-sample (last 20%%), is = in-sample (first 80%%), full = all",
    )
    p.add_argument(
        "--session",
        choices=["rth", "eth", "all"],
        default="all",
        help="rth = regular trading hours only, eth = extended only, all = everything",
    )
    p.add_argument(
        "--horizon",
        type=int,
        default=120,
        help="Forecast horizon in minutes (default 120)",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Force re-fetch from Databento (ignore cache)",
    )
    return p.parse_args()


def _cache_path(split: str) -> Path:
    today = date.today().isoformat()
    return CACHE_DIR / f"{split}_{today}.parquet"


def fetch_databento() -> pd.DataFrame | None:
    if not DATABENTO_API_KEY or DATABENTO_API_KEY == "your-key-here":
        logger.warning("DATABENTO_API_KEY not set or is placeholder — cannot fetch live data")
        return None

    try:
        import databento as db

        client = db.Historical(DATABENTO_API_KEY)
        now = datetime.now(timezone.utc)
        end = now - timedelta(hours=25)

        logger.info(f"Fetching {SCHEMA} for {SYMBOL} from {DATA_START} to {end.date()}")

        data = client.timeseries.get_range(
            dataset=DATASET,
            symbols=SYMBOL,
            stype_in="continuous",
            schema=SCHEMA,
            start=DATA_START,
            end=end.isoformat(),
        )
        df = data.to_df()

        if df.empty:
            logger.warning("Databento returned 0 bars")
            return None

        logger.info(f"Fetched {len(df)} hourly bars from Databento")
        return df

    except Exception as e:
        logger.error(f"Databento fetch failed: {e}")
        return None


def load_or_fetch(split: str, no_cache: bool) -> pd.DataFrame | None:
    cache = _cache_path(split)

    if cache.exists() and not no_cache:
        logger.info(f"Loading cached data from {cache}")
        return pd.read_parquet(cache)

    df = fetch_databento()
    if df is not None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache)
        logger.info(f"Cached {len(df)} bars to {cache}")

    return df


def filter_rth(df: pd.DataFrame) -> pd.DataFrame:
    if df.index.tz is None:
        idx = df.index.tz_localize("UTC").tz_convert(ET)
    else:
        idx = df.index.tz_convert(ET)

    rth_mask = (idx.hour * 60 + idx.minute >= 9 * 60 + 30) & (
        idx.hour * 60 + idx.minute <= 16 * 60 + 15
    )
    weekday_mask = idx.weekday < 5
    filtered = df.loc[rth_mask & weekday_mask]
    logger.info(f"RTH filter: {len(df)} → {len(filtered)} bars")
    return filtered


def filter_eth(df: pd.DataFrame) -> pd.DataFrame:
    if df.index.tz is None:
        idx = df.index.tz_localize("UTC").tz_convert(ET)
    else:
        idx = df.index.tz_convert(ET)

    eth_mask = ~(
        (idx.hour * 60 + idx.minute >= 9 * 60 + 30)
        & (idx.hour * 60 + idx.minute <= 16 * 60 + 15)
    )
    filtered = df.loc[eth_mask]
    logger.info(f"ETH filter: {len(df)} → {len(filtered)} bars")
    return filtered


def build_labels(closes: np.ndarray, horizon_bars: int) -> np.ndarray:
    n = len(closes)
    labels = np.full(n, -1, dtype=np.int32)

    for i in range(n - horizon_bars):
        pct = (closes[i + horizon_bars] - closes[i]) / closes[i]
        if pct > MIN_MOVE_PCT:
            labels[i] = 2  # up
        elif pct < -MIN_MOVE_PCT:
            labels[i] = 0  # down
        else:
            labels[i] = 1  # flat

    return labels


def extract_features_historical(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    opens: np.ndarray,
    volumes: np.ndarray,
    idx: int,
    horizon_minutes: int,
) -> np.ndarray:
    f = np.zeros(25, dtype=np.float32)

    for i, w in enumerate(MOMENTUM_WINDOWS):
        if idx >= w:
            f[i] = (closes[idx] - closes[idx - w]) / max(closes[idx - w], 1e-9)

    if idx >= VOL_WINDOW:
        log_r = np.diff(np.log(np.maximum(closes[idx - VOL_WINDOW : idx + 1], 1e-9)))
        f[4] = float(np.std(log_r))
    f[5] = 0.5
    f[6] = 20.0
    f[7] = 1.0

    if idx >= 1:
        up, down = 0, 0
        for j in range(idx, max(idx - 20, 0), -1):
            if closes[j] > closes[j - 1]:
                if down == 0:
                    up += 1
                else:
                    break
            elif closes[j] < closes[j - 1]:
                if up == 0:
                    down += 1
                else:
                    break
            else:
                break
        f[8] = float(up)
        f[9] = float(down)

    if idx >= 5:
        bp, br = [], []
        for j in range(idx - 4, idx + 1):
            rng = max(highs[j] - lows[j], 0.01)
            bp.append(abs(closes[j] - opens[j]) / rng)
            br.append(highs[j] - lows[j])
        f[10] = float(np.mean(bp))
        f[11] = float(np.mean(br))

    if idx >= 20:
        v20 = np.mean(volumes[idx - 19 : idx + 1])
        vs = np.std(volumes[idx - 19 : idx + 1])
        f[12] = float((volumes[idx] - v20) / max(vs, 1))
        v5 = np.mean(volumes[idx - 4 : idx + 1])
        f[13] = float(v5 / max(v20, 1))

    f[14] = 0.0
    f[15] = 0.5
    f[16] = 3.0
    f[17] = 5.0

    f[18] = float((idx % 78) * 5)
    f[19] = 0.0
    f[20] = float(idx % 5)

    f[21] = 0.0
    f[22] = 0.0
    f[23] = 0.0

    f[24] = float(horizon_minutes)

    return f


def try_load_model():
    """Attempt to load model from src. Returns (model, mode) or (None, 'stub')."""
    model_path = os.getenv("MIROFISH_MODEL_PATH", "artifacts/lgbm_model.pkl")

    if Path(model_path).exists():
        try:
            import pickle

            with open(model_path, "rb") as fh:
                model = pickle.load(fh)
            logger.info(f"Loaded model from {model_path}")
            return model, "file"
        except Exception as e:
            logger.warning(f"Failed to load model from {model_path}: {e}")

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
        from mirofish_forecast.ml.feature_extractor import FeatureExtractor

        logger.info("src.ml imports available — feature extractor loaded")
    except ImportError:
        logger.info("src.ml not importable — running in stub mode")

    return None, "stub"


def stub_predict(x: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return rng.integers(0, 3, size=x.shape[0]).astype(np.int32)


def generate_stub_data() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n_bars = 2000
    dates = pd.date_range("2024-04-01", periods=n_bars, freq="1h", tz="UTC")

    price = 5200.0
    closes = np.zeros(n_bars)
    opens = np.zeros(n_bars)
    highs = np.zeros(n_bars)
    lows = np.zeros(n_bars)
    volumes = np.zeros(n_bars)

    for i in range(n_bars):
        change = rng.normal(0, 5)
        o = price
        c = price + change
        h = max(o, c) + abs(rng.normal(0, 2))
        lo = min(o, c) - abs(rng.normal(0, 2))
        v = rng.integers(50000, 200000)

        opens[i] = o
        closes[i] = c
        highs[i] = h
        lows[i] = lo
        volumes[i] = v
        price = c

    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )
    return df


def run_eval(args: argparse.Namespace) -> dict:
    df = load_or_fetch(args.split, args.no_cache)

    if df is None:
        logger.info("No Databento data available — generating synthetic stub data")
        df = generate_stub_data()

    if args.session == "rth":
        df = filter_rth(df)
    elif args.session == "eth":
        df = filter_eth(df)

    closes = df["close"].values.flatten().astype(np.float64)
    highs = df["high"].values.flatten().astype(np.float64)
    lows = df["low"].values.flatten().astype(np.float64)
    opens = df["open"].values.flatten().astype(np.float64)
    volumes = df["volume"].values.flatten().astype(np.float64)

    horizon_bars = max(1, args.horizon // 60)
    labels = build_labels(closes, horizon_bars)

    valid_mask = labels >= 0
    start_idx = FEATURE_LOOKBACK
    valid_mask[:start_idx] = False

    valid_indices = np.where(valid_mask)[0]

    if len(valid_indices) < 100:
        logger.error(f"Only {len(valid_indices)} valid samples — need at least 100")
        return {"error": "insufficient data"}

    split_point = int(len(valid_indices) * TRAIN_RATIO)

    if args.split == "oos":
        eval_indices = valid_indices[split_point:]
    elif args.split == "is":
        eval_indices = valid_indices[:split_point]
    else:
        eval_indices = valid_indices

    logger.info(
        f"Evaluating on {len(eval_indices)} bars "
        f"(split={args.split}, session={args.session}, horizon={args.horizon}min)"
    )

    x_list = []
    for idx in eval_indices:
        feat = extract_features_historical(
            closes, highs, lows, opens, volumes, idx, args.horizon
        )
        x_list.append(feat)

    x = np.array(x_list, dtype=np.float32)
    y_true = labels[eval_indices]

    model, mode = try_load_model()

    if mode == "stub":
        rng = np.random.default_rng(123)
        y_pred = stub_predict(x, rng)
    elif mode == "file":
        try:
            raw_preds = model.predict(x)
            if hasattr(model, "predict_proba"):
                probs = model.predict_proba(x)
                if probs.shape[1] == 2:
                    y_pred = np.where(
                        np.max(probs, axis=1) < 0.55,
                        1,
                        np.where(probs[:, 1] >= probs[:, 0], 2, 0),
                    ).astype(np.int32)
                else:
                    y_pred = raw_preds.astype(np.int32)
            else:
                y_pred = raw_preds.astype(np.int32)
        except Exception as e:
            logger.warning(f"Model prediction failed ({e}), falling back to stub")
            rng = np.random.default_rng(123)
            y_pred = stub_predict(x, rng)
    else:
        rng = np.random.default_rng(123)
        y_pred = stub_predict(x, rng)

    direction_accuracy = float(np.mean(y_pred == y_true))

    class_names = ["down", "flat", "up"]
    per_class = {}
    for c, name in enumerate(class_names):
        mask = y_true == c
        count = int(mask.sum())
        if count > 0:
            acc = float(np.mean(y_pred[mask] == c))
            per_class[name] = {"accuracy": round(acc, 3), "count": count}
        else:
            per_class[name] = {"accuracy": 0.0, "count": 0}

    total = len(y_true)
    label_dist = {
        name: round(int((y_true == c).sum()) / total, 3) for c, name in enumerate(class_names)
    }

    results = {
        "direction_accuracy": round(direction_accuracy, 3),
        "samples": total,
        "horizon_minutes": args.horizon,
        "horizon_bars": horizon_bars,
        "split": args.split,
        "session": args.session,
        "mode": mode,
        "label_distribution": label_dist,
        "per_class": per_class,
    }

    return results


def main() -> None:
    args = parse_args()
    results = run_eval(args)

    if "error" in results:
        print(f"ERROR: {results['error']}")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("MIROFISH EVAL RESULTS")
    print("=" * 50)
    print(f"direction_accuracy: {results['direction_accuracy']}")
    print(f"samples: {results['samples']}")
    print(f"split: {results['split']}")
    print(f"session: {results['session']}")
    print(f"horizon: {results['horizon_minutes']}min ({results['horizon_bars']} bars)")
    print(f"mode: {results['mode']}")
    print(f"label_distribution: {results['label_distribution']}")

    print("\nper-class accuracy:")
    for name, stats in results["per_class"].items():
        print(f"  {name}: {stats['accuracy']:.3f} (n={stats['count']})")

    print("=" * 50)


if __name__ == "__main__":
    main()
