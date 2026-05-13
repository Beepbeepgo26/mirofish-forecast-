"""Forecast synthesizer — aggregates simulation results and produces natural language forecast.

Pipeline: SimulationResults → filter failures → compute distribution →
logarithmic pooling → scenario probabilities → GPT-4o synthesis → ForecastResult
"""

import logging
import time
from datetime import datetime

from mirofish_forecast.config import constants
from mirofish_forecast.config.constants import get_instrument_config
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.llm.client import LLMClient
from mirofish_forecast.llm.prompts.synthesize_forecast import (
    SYNTHESIZE_FORECAST_SYSTEM_PROMPT,
)
from mirofish_forecast.models.forecast import (
    ForecastResult,
    ProbabilityDistribution,
    SimulationResult,
)
from mirofish_forecast.models.market import MarketContext
from mirofish_forecast.models.scenario import SimulationScenario
from mirofish_forecast.utils.aggregation import (
    compute_distribution_stats,
    compute_scenario_probabilities,
)

logger = logging.getLogger(__name__)


class ForecastSynthesizer:
    """Aggregates Monte Carlo results and synthesizes a natural language forecast."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = LLMClient(settings)

    def synthesize(
        self,
        results: list[SimulationResult],
        scenario: SimulationScenario,
        context: MarketContext,
        forecast_id: str,
        sim_preset: str,
        pipeline_start_time: float,
        session_info: object | None = None,
        agent_raw_analogs: dict[str, list[dict]] | None = None,
    ) -> ForecastResult:
        """Aggregate simulation results and produce the final forecast.

        Args:
            results: All simulation results (including failures)
            scenario: The simulation scenario used
            context: Market context at forecast time
            forecast_id: Unique forecast identifier
            sim_preset: "quick", "standard", "deep", "custom"
            pipeline_start_time: time.time() when pipeline started
            session_info: Current market session info (optional)

        Returns:
            ForecastResult with forecast text, distribution, and metadata
        """
        # Filter to successful simulations
        successful = [r for r in results if r.success]
        total = len(results)
        success_count = len(successful)

        logger.info(f"Synthesizing forecast: {success_count}/{total} simulations succeeded")

        # Check minimum success threshold
        if total > 0 and success_count / total < constants.SIM_MIN_SUCCESS_RATE:
            return self._error_forecast(
                forecast_id=forecast_id,
                instrument=scenario.instrument,
                horizon=scenario.forecast_horizon_minutes,
                current_price=scenario.current_price or 0,
                sim_preset=sim_preset,
                total=total,
                success_count=success_count,
                start_time=pipeline_start_time,
                reason=(
                    f"Only {success_count}/{total} simulations succeeded"
                    f" ({success_count / total:.0%})."
                    f" Minimum threshold is {constants.SIM_MIN_SUCCESS_RATE:.0%}."
                ),
            )

        current_price = scenario.current_price or 5400.0
        final_prices = [r.final_price for r in successful]

        # Compute distribution statistics
        dist_stats = compute_distribution_stats(final_prices, current_price)

        # Compute scenario probabilities
        scenario_dicts = [
            {
                "rank": s.rank.value,
                "price_range_low": s.price_range_low,
                "price_range_high": s.price_range_high,
            }
            for s in scenario.scenarios
        ]
        scenario_probs = compute_scenario_probabilities(final_prices, scenario_dicts)

        # Build probability distribution
        distribution = ProbabilityDistribution(
            **dist_stats,
            scenario_probs=scenario_probs,
        )

        # Extract representative agent reasoning (from median-priced simulation)
        median_sim = self._find_median_simulation(successful, distribution.median)
        inst_reasoning, retail_reasoning, mm_reasoning = self._extract_agent_reasoning(median_sim)
        agent_cot = self._extract_agent_cot(median_sim)

        # Generate natural language forecast via GPT-4o
        forecast_text = self._generate_forecast_text(
            distribution=distribution,
            scenario=scenario,
            context=context,
            num_simulations=success_count,
            inst_reasoning=inst_reasoning,
            retail_reasoning=retail_reasoning,
            mm_reasoning=mm_reasoning,
            session_info=session_info,
        )

        duration = round(time.time() - pipeline_start_time, 1)

        return ForecastResult(
            forecast_id=forecast_id,
            instrument=scenario.instrument,
            forecast_horizon_minutes=scenario.forecast_horizon_minutes,
            current_price=current_price,
            forecast_text=forecast_text,
            distribution=distribution,
            total_simulations=total,
            successful_simulations=success_count,
            sim_preset=sim_preset,
            institutional_reasoning=inst_reasoning,
            retail_reasoning=retail_reasoning,
            market_maker_reasoning=mm_reasoning,
            created_at=datetime.utcnow(),
            pipeline_duration_seconds=duration,
            agent_cot=agent_cot,
            agent_analogs=agent_raw_analogs or {},
        )

    def _generate_forecast_text(
        self,
        distribution: ProbabilityDistribution,
        scenario: SimulationScenario,
        context: MarketContext,
        num_simulations: int,
        inst_reasoning: str,
        retail_reasoning: str,
        mm_reasoning: str,
        session_info: object | None = None,
    ) -> str:
        """Use GPT-4o to generate the plain-English forecast."""
        # Build scenario summary
        scenario_lines = []
        for s in scenario.scenarios:
            realized_prob = distribution.scenario_probs.get(s.rank.value, s.probability)
            scenario_lines.append(
                f"- {s.rank.value}: {s.name} (model prob: {s.probability:.0%},"
                f" realized: {realized_prob:.0%}) — {s.description}"
            )
        scenario_summary = "\n".join(scenario_lines)

        # Build market context summary
        market_summary = (
            f"VIX: {context.vix.spot}"
            f" ({context.vix.regime.value if context.vix.regime else 'unknown'}),"
            f" Fear & Greed: {context.fear_greed.value}"
            f" ({context.fear_greed.description}),"
            f" 10Y Yield: {context.macro.ten_year_yield}%,"
            f" DXY: {context.cross_asset.dxy_price}"
        )

        # Build session context
        session_context = ""
        if session_info:
            si = session_info
            session_context = (
                "\n## SESSION CONTEXT\n"
                f"Current time: {si.current_time_et} ({si.day_of_week})\n"
                f"Market status: {si.session_label}\n"
            )
            if not si.is_rth_open and si.next_rth_open:
                session_context += f"Next RTH open: {si.next_rth_open}\n"
            session_context += (
                "\nIMPORTANT: If the market is currently closed, "
                "frame your forecast in terms of the next trading "
                "session, NOT 'the next X minutes'. For example, "
                "say 'For Monday's RTH session...' instead of "
                "'over the next 120 minutes...' when markets are "
                "closed.\n"
            )

        inst_config = get_instrument_config(scenario.instrument)
        instrument_name = inst_config["name"]

        # Build events context
        events_context = ""
        if hasattr(context, "events_today") and context.events_today:
            event_lines = []
            for e in context.events_today:
                line = f"- {e.time or 'TBD'}: {e.full_name} ({e.impact.upper()})"
                if e.consensus:
                    line += f" — Expected: {e.consensus}"
                    if e.prior:
                        line += f", Prior: {e.prior}"
                if e.hours_until is not None and e.hours_until < 0:
                    line += " [ALREADY RELEASED]"
                event_lines.append(line)
            events_context = "Today's events:\n" + "\n".join(event_lines)
        else:
            events_context = "No major economic events scheduled today."

        prompt = SYNTHESIZE_FORECAST_SYSTEM_PROMPT.format(
            num_simulations=num_simulations,
            instrument_name=instrument_name,
            current_price=scenario.current_price,
            horizon_minutes=scenario.forecast_horizon_minutes,
            median=distribution.median,
            mean=distribution.mean,
            p5=distribution.percentile_5,
            p25=distribution.percentile_25,
            p75=distribution.percentile_75,
            p95=distribution.percentile_95,
            std_dev=distribution.std_dev,
            prob_up=distribution.prob_up,
            prob_down=distribution.prob_down,
            prob_flat=distribution.prob_flat,
            scenario_summary=scenario_summary,
            market_context_summary=market_summary,
            institutional_summary=inst_reasoning[:300],
            retail_summary=retail_reasoning[:300],
            market_maker_summary=mm_reasoning[:300],
            session_context=session_context,
            events_context=events_context,
        )

        try:
            return self._llm.chat(
                system_prompt=prompt,
                user_message="Generate the forecast summary.",
                model=constants.SYNTHESIS_MODEL,
                temperature=constants.SYNTHESIS_TEMPERATURE,
                max_tokens=constants.SYNTHESIS_MAX_TOKENS,
                timeout=constants.SYNTHESIS_TIMEOUT,
            )
        except Exception as e:
            logger.error(f"Synthesis LLM call failed: {e}", exc_info=True)
            # Fallback: deterministic text from distribution
            return (
                f"{scenario.instrument} is most likely to trade between"
                f" {distribution.percentile_25:.2f}–{distribution.percentile_75:.2f}"
                f" over the next {scenario.forecast_horizon_minutes} minutes"
                f" (50% confidence interval)."
                f" The median forecast is {distribution.median:.2f} with"
                f" a {distribution.prob_up:.0%} probability of moving higher and"
                f" {distribution.prob_down:.0%} probability of moving lower."
                f" Based on {num_simulations} simulations."
            )

    def _find_median_simulation(
        self, results: list[SimulationResult], median_price: float
    ) -> SimulationResult | None:
        """Find the simulation whose final price is closest to the median."""
        if not results:
            return None
        return min(results, key=lambda r: abs(r.final_price - median_price))

    def _extract_agent_reasoning(self, sim: SimulationResult | None) -> tuple[str, str, str]:
        """Extract reasoning traces from the median simulation's agents."""
        if sim is None or not sim.agent_decisions:
            return ("No data", "No data", "No data")

        inst = next((d for d in sim.agent_decisions if d.agent_type == "institutional"), None)
        retail = next((d for d in sim.agent_decisions if d.agent_type == "retail"), None)
        mm = next((d for d in sim.agent_decisions if d.agent_type == "market_maker"), None)

        return (
            f"{inst.direction} ({inst.confidence:.0%}): {inst.reasoning}" if inst else "No data",
            f"{retail.direction} ({retail.confidence:.0%}): {retail.reasoning}"
            if retail
            else "No data",
            f"{mm.direction} ({mm.confidence:.0%}): {mm.reasoning}" if mm else "No data",
        )

    def _extract_agent_cot(self, sim: SimulationResult | None) -> dict[str, str]:
        """Extract full CoT reasoning from the median simulation's agents."""
        if sim is None or not sim.agent_decisions:
            return {}

        cot: dict[str, str] = {}
        for d in sim.agent_decisions:
            if d.cot_reasoning:
                cot[d.agent_type] = d.cot_reasoning
        return cot

    def _error_forecast(self, **kwargs: object) -> ForecastResult:
        """Generate an error forecast when not enough simulations succeed."""
        current_price = float(kwargs["current_price"])
        start_time = float(kwargs["start_time"])
        return ForecastResult(
            forecast_id=str(kwargs["forecast_id"]),
            instrument=str(kwargs["instrument"]),
            forecast_horizon_minutes=int(kwargs["horizon"]),
            current_price=current_price,
            forecast_text=f"Forecast could not be generated: {kwargs['reason']}",
            distribution=ProbabilityDistribution(
                median=current_price,
                mean=current_price,
                std_dev=0,
                percentile_5=current_price,
                percentile_25=current_price,
                percentile_75=current_price,
                percentile_95=current_price,
                skewness=0,
                prob_up=0.33,
                prob_down=0.33,
                prob_flat=0.34,
            ),
            total_simulations=int(kwargs["total"]),
            successful_simulations=int(kwargs["success_count"]),
            sim_preset=str(kwargs["sim_preset"]),
            created_at=datetime.utcnow(),
            pipeline_duration_seconds=round(time.time() - start_time, 1),
            build_method="error",
        )
