"""Forecast pipeline — orchestrates all stages and emits SSE events."""

import json
import logging
import threading
import time
from datetime import datetime
from queue import Queue
from typing import Any

import yfinance as yf

from mirofish_forecast.calibration.tracking import ForecastTracker
from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.ml.fast_path import FastPathRunner
from mirofish_forecast.models.forecast import (
    ForecastResult,
    ProbabilityDistribution,
)
from mirofish_forecast.services.data_aggregator import DataAggregator
from mirofish_forecast.services.forecast_synthesizer import ForecastSynthesizer
from mirofish_forecast.services.nlp_parser import NLPParser
from mirofish_forecast.services.scenario_builder import ScenarioBuilder
from mirofish_forecast.services.session_context import get_session_info
from mirofish_forecast.services.simulation_runner import MonteCarloRunner

logger = logging.getLogger(__name__)


class ForecastPipeline:
    """Orchestrates the full forecast pipeline with SSE event streaming.

    Stages: parsing → data_collection → scenario_building → simulation → synthesis → complete
    Fast path: parsing → data_collection → fast_inference → complete
    """

    def __init__(
        self,
        settings: Settings,
        event_queue: Queue,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._settings = settings
        self._queue = event_queue
        self._cancel_event = cancel_event or threading.Event()
        self._parser = NLPParser(settings)
        self._aggregator = DataAggregator(settings)
        self._scenario_builder = ScenarioBuilder(settings)
        self._simulation_runner = MonteCarloRunner(settings)
        self._synthesizer = ForecastSynthesizer(settings)
        self._tracker = ForecastTracker(settings)
        self._fast_path = FastPathRunner(settings)

    def _is_cancelled(self) -> bool:
        """Check if the pipeline has been cancelled."""
        return self._cancel_event.is_set()

    def run(
        self,
        raw_query: str,
        forecast_id: str = "",
        sim_preset: str = "standard",
        sim_count: int | None = None,
        path_override: str | None = None,
    ) -> None:
        """Execute the forecast pipeline. Runs in a background thread.

        Args:
            raw_query: Natural language query from the user
            forecast_id: Unique forecast ID
            sim_preset: Simulation tier preset
            sim_count: Optional custom simulation count
            path_override: "fast", "full", or None (auto-route)
        """
        pipeline_start = time.time()

        try:
            # Get session context
            session = get_session_info()

            # Stage 1: Parse the query
            if self._is_cancelled():
                self._emit_cancel()
                return
            self._emit_stage(constants.STAGE_PARSING)
            query = self._parser.parse(raw_query, sim_preset, sim_count)
            self._emit_stage_complete(
                constants.STAGE_PARSING,
                {
                    "query": json.loads(query.model_dump_json()),
                },
            )

            # Stage 2: Pull market data
            if self._is_cancelled():
                self._emit_cancel()
                return
            self._emit_stage(constants.STAGE_DATA_COLLECTION)
            context = self._aggregator.get_market_context()
            self._emit_stage_complete(
                constants.STAGE_DATA_COLLECTION,
                {
                    "context_summary": {
                        "es_price": context.cross_asset.es_price,
                        "vix_spot": context.vix.spot or context.cross_asset.vix_price,
                        "vix_regime": (context.vix.regime.value if context.vix.regime else None),
                        "fear_greed": context.fear_greed.value,
                        "fear_greed_desc": context.fear_greed.description,
                        "fed_funds": context.macro.fed_funds_rate,
                        "ten_year": context.macro.ten_year_yield,
                        "dxy": context.cross_asset.dxy_price,
                    },
                    "events_today": [
                        {
                            "name": e.name,
                            "full_name": e.full_name,
                            "time": e.time,
                            "impact": e.impact,
                            "hours_until": e.hours_until,
                            "consensus": e.consensus,
                        }
                        for e in context.events_today
                    ],
                },
            )

            # Route decision: fast path or full path?
            use_fast_path = self._should_use_fast_path(query, path_override)

            if use_fast_path and self._fast_path.is_available():
                self._run_fast_path(
                    context=context,
                    query=query,
                    forecast_id=forecast_id,
                    pipeline_start=pipeline_start,
                )
                return

            # ---- Full MC path (stages 3-5) ----

            # Stage 3: Build scenarios
            if self._is_cancelled():
                self._emit_cancel()
                return
            self._emit_stage(constants.STAGE_SCENARIO_BUILDING)
            scenario = self._scenario_builder.build(query, context)
            self._emit_stage_complete(
                constants.STAGE_SCENARIO_BUILDING,
                {
                    "market_regime": scenario.market_regime.value,
                    "scenarios_summary": [
                        {
                            "rank": s.rank.value,
                            "name": s.name,
                            "probability": s.probability,
                        }
                        for s in scenario.scenarios
                    ],
                },
            )

            # Stage 4: Run Monte Carlo simulations
            if self._is_cancelled():
                self._emit_cancel()
                return
            self._emit_stage(constants.STAGE_SIMULATION)

            def progress_callback(completed: int, total: int) -> None:
                progress = round(completed / total, 3)
                self._emit_event(
                    constants.STAGE_SIMULATION,
                    {
                        "message": f"Running simulations... {completed}/{total}",
                        "status": "progress",
                        "progress": progress,
                        "completed": completed,
                        "total": total,
                    },
                )

            sim_results = self._simulation_runner.run(
                scenario=scenario,
                sim_count=query.sim_count,
                progress_callback=progress_callback,
                session=session,
            )

            success_count = sum(1 for r in sim_results if r.success)
            self._emit_stage_complete(
                constants.STAGE_SIMULATION,
                {
                    "total_simulations": len(sim_results),
                    "successful_simulations": success_count,
                    "success_rate": round(success_count / max(len(sim_results), 1), 3),
                },
            )

            # Stage 5: Synthesize forecast
            if self._is_cancelled():
                self._emit_cancel()
                return
            self._emit_stage(constants.STAGE_SYNTHESIS)
            forecast = self._synthesizer.synthesize(
                results=sim_results,
                scenario=scenario,
                context=context,
                forecast_id=forecast_id,
                sim_preset=query.sim_preset.value,
                pipeline_start_time=pipeline_start,
                session_info=session,
            )
            self._emit_stage_complete(
                constants.STAGE_SYNTHESIS,
                {
                    "forecast_text_preview": forecast.forecast_text[:200] + "...",
                },
            )

            # Complete
            self._emit_event(
                constants.STAGE_COMPLETE,
                {
                    "forecast": json.loads(forecast.model_dump_json()),
                },
            )

            # Track forecast for calibration (fire-and-forget)
            try:
                vix_value = context.vix.spot or context.cross_asset.vix_price
                fg_value = context.fear_greed.value
                self._tracker.store_forecast(
                    forecast=forecast,
                    vix_at_forecast=vix_value,
                    fear_greed_at_forecast=fg_value,
                    agent_disagreement=float(forecast.distribution.std_dev),
                    market_regime=scenario.market_regime.value,
                )
            except Exception:
                logger.warning("Failed to store forecast tracking", exc_info=True)

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            self._emit_event(
                constants.STAGE_ERROR,
                {
                    "error": str(e),
                    "message": f"Forecast pipeline failed: {e}",
                },
            )

    # ---- Fast path ----

    def _run_fast_path(
        self,
        context: object,
        query: object,
        forecast_id: str,
        pipeline_start: float,
    ) -> None:
        """Execute the fast path: features → LightGBM → synthesis."""
        self._emit_event(
            constants.STAGE_FAST_INFERENCE,
            {
                "message": "Running fast inference...",
                "status": "started",
            },
        )

        ohlcv_bars = self._fetch_ohlcv_bars(query.instrument)  # type: ignore[union-attr]

        fast_result = self._fast_path.run(
            context=context,  # type: ignore[arg-type]
            ohlcv_bars=ohlcv_bars,
            instrument=query.instrument,  # type: ignore[union-attr]
            horizon_minutes=query.forecast_horizon_minutes,  # type: ignore[union-attr]
            forecast_id=forecast_id,
            pipeline_start_time=pipeline_start,
        )

        self._emit_event(
            constants.STAGE_FAST_INFERENCE,
            {
                "message": "Fast inference complete",
                "status": "completed",
            },
        )

        self._emit_event(
            constants.STAGE_COMPLETE,
            {
                "forecast": json.loads(fast_result.model_dump_json()),
                "path": "fast",
            },
        )

        # Track for calibration
        if self._settings.calibration_enabled:
            try:
                tracking_forecast = ForecastResult(
                    forecast_id=fast_result.forecast_id,
                    instrument=fast_result.instrument,
                    forecast_horizon_minutes=fast_result.forecast_horizon_minutes,
                    current_price=fast_result.current_price,
                    forecast_text=fast_result.forecast_text,
                    distribution=ProbabilityDistribution(
                        median=fast_result.predicted_median,
                        mean=fast_result.predicted_median,
                        std_dev=(fast_result.predicted_p95 - fast_result.predicted_p5) / 3.29,
                        percentile_5=fast_result.predicted_p5,
                        percentile_25=(fast_result.predicted_p5 + fast_result.predicted_median) / 2,
                        percentile_75=(fast_result.predicted_median + fast_result.predicted_p95)
                        / 2,
                        percentile_95=fast_result.predicted_p95,
                        skewness=0.0,
                        prob_up=fast_result.prob_up,
                        prob_down=fast_result.prob_down,
                        prob_flat=fast_result.prob_flat,
                    ),
                    total_simulations=0,
                    successful_simulations=0,
                    sim_preset="fast",
                    created_at=fast_result.created_at,
                    pipeline_duration_seconds=fast_result.pipeline_duration_seconds,
                    build_method="fast_path",
                )
                vix_value = context.vix.spot or context.cross_asset.vix_price  # type: ignore[union-attr]
                fg_value = context.fear_greed.value  # type: ignore[union-attr]
                self._tracker.store_forecast(
                    forecast=tracking_forecast,
                    vix_at_forecast=vix_value,
                    fear_greed_at_forecast=fg_value,
                )
            except Exception:
                logger.warning(
                    "Failed to track fast path forecast",
                    exc_info=True,
                )

    def _should_use_fast_path(
        self,
        query: object,
        path_override: str | None = None,
    ) -> bool:
        """Decide whether to use the fast path for this query."""
        if not self._settings.fast_path_enabled:
            return False

        if path_override == "fast":
            return True
        if path_override == "full":
            return False

        if not self._settings.fast_path_auto_route:
            return False

        eligible = constants.FAST_PATH_ELIGIBLE_QUERY_TYPES
        if query.query_type.value not in eligible:  # type: ignore[union-attr]
            return False

        if (
            query.forecast_horizon_minutes  # type: ignore[union-attr]
            > constants.FAST_PATH_MAX_HORIZON
        ):
            return False

        return True

    def _fetch_ohlcv_bars(self, instrument: str) -> list[dict]:
        """Fetch recent OHLCV bars for feature extraction."""
        try:
            config = constants.get_instrument_config(instrument)
            ticker = config["yfinance_ticker"]

            data = yf.download(
                ticker,
                period="5d",
                interval="1h",
                progress=False,
            )

            if data.empty:
                return []

            if hasattr(data.columns, "levels"):
                data.columns = data.columns.get_level_values(0)

            bars: list[dict] = []
            for ts, row in data.tail(constants.FEATURE_OHLCV_LOOKBACK).iterrows():
                bars.append(
                    {
                        "time": int(ts.timestamp()),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row.get("Volume", 0)),
                    }
                )
            return bars
        except Exception:
            logger.warning(
                f"Failed to fetch OHLCV for {instrument}",
                exc_info=True,
            )
            return []

    # ---- Event emission helpers ----

    def _emit_cancel(self) -> None:
        """Emit a cancellation event."""
        self._emit_event(
            constants.STAGE_ERROR,
            {"message": "Forecast cancelled", "cancelled": True},
        )

    def _emit_stage(self, stage: str) -> None:
        """Emit a stage-started event."""
        message = constants.STAGE_MESSAGES.get(stage, f"Running {stage}...")
        self._emit_event(stage, {"message": message, "status": "started"})

    def _emit_stage_complete(self, stage: str, data: dict[str, Any]) -> None:
        """Emit a stage-completed event with results."""
        self._emit_event(stage, {**data, "status": "completed"})

    def _emit_event(self, stage: str, data: dict[str, Any]) -> None:
        """Push an SSE event onto the queue."""
        event = {
            "stage": stage,
            "timestamp": datetime.utcnow().isoformat(),
            **data,
        }
        self._queue.put(event)
