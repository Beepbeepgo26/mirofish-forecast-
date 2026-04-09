"""Forecast pipeline — orchestrates all stages and emits SSE events."""

import json
import logging
import time
from datetime import datetime
from queue import Queue
from typing import Any

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.services.data_aggregator import DataAggregator
from mirofish_forecast.services.forecast_synthesizer import ForecastSynthesizer
from mirofish_forecast.services.nlp_parser import NLPParser
from mirofish_forecast.services.scenario_builder import ScenarioBuilder
from mirofish_forecast.services.simulation_runner import MonteCarloRunner

logger = logging.getLogger(__name__)


class ForecastPipeline:
    """Orchestrates the full forecast pipeline with SSE event streaming.

    Stages: parsing → data_collection → scenario_building → simulation → synthesis → complete
    """

    def __init__(self, settings: Settings, event_queue: Queue) -> None:
        self._settings = settings
        self._queue = event_queue
        self._parser = NLPParser(settings)
        self._aggregator = DataAggregator(settings)
        self._scenario_builder = ScenarioBuilder(settings)
        self._simulation_runner = MonteCarloRunner(settings)
        self._synthesizer = ForecastSynthesizer(settings)

    def run(
        self,
        raw_query: str,
        forecast_id: str = "",
        sim_preset: str = "standard",
        sim_count: int | None = None,
    ) -> None:
        """Execute the full forecast pipeline. Runs in a background thread."""
        pipeline_start = time.time()

        try:
            # Stage 1: Parse the query
            self._emit_stage(constants.STAGE_PARSING)
            query = self._parser.parse(raw_query, sim_preset, sim_count)
            self._emit_stage_complete(
                constants.STAGE_PARSING,
                {
                    "query": json.loads(query.model_dump_json()),
                },
            )

            # Stage 2: Pull market data
            self._emit_stage(constants.STAGE_DATA_COLLECTION)
            context = self._aggregator.get_market_context()
            self._emit_stage_complete(
                constants.STAGE_DATA_COLLECTION,
                {
                    "context_summary": {
                        "vix_spot": context.vix.spot,
                        "vix_regime": (context.vix.regime.value if context.vix.regime else None),
                        "fear_greed": context.fear_greed.value,
                        "es_price": context.cross_asset.es_price,
                    },
                },
            )

            # Stage 3: Build scenarios
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
            self._emit_stage(constants.STAGE_SYNTHESIS)
            forecast = self._synthesizer.synthesize(
                results=sim_results,
                scenario=scenario,
                context=context,
                forecast_id=forecast_id,
                sim_preset=query.sim_preset.value,
                pipeline_start_time=pipeline_start,
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

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            self._emit_event(
                constants.STAGE_ERROR,
                {
                    "error": str(e),
                    "message": f"Forecast pipeline failed: {e}",
                },
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
