"""Monte Carlo simulation runner — runs N simulations with asyncio concurrency.

Each simulation:
1. Picks a random seed and LLM temperature
2. Starts from the current ES price
3. Simulates SIM_BARS_PER_HORIZON bars
4. At each bar:
   a. Pre-computes Brooks signal bar score (pure Python, sub-ms)
   b. Determines time-of-day regime and confidence multiplier
   c. 3 agents (institutional, retail, market maker) make decisions via TWO-CALL CoT:
      Call 1 — free-form 8-step reasoning chain
      Call 2 — structured JSON extraction with 0.55+ confidence floor
5. Confidence-weighted aggregation with regime-dependent agent weight adjustments
6. Bar price = weighted average of agent targets (clamped + drift-anchored + noise)

The runner uses dual semaphores:
- sim_semaphore: limits concurrent simulations
- api_semaphore: limits total in-flight LLM API calls
"""

import asyncio
import json
import logging
import random
from collections.abc import Callable

from openai import AsyncOpenAI

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.llm.prompts.agent_decision import (
    AGENT_EXTRACT_PROMPT,
    get_agent_cot_prompt,
)
from mirofish_forecast.ml.signal_bar import describe_signal_score, extract_bar_features, score_signal_bar
from mirofish_forecast.models.forecast import AgentDecision, SimulationResult
from mirofish_forecast.models.scenario import SimulationScenario
from mirofish_forecast.services.session_context import SessionInfo
from mirofish_forecast.services.tod_regime import format_tod_context, get_tod_regime

logger = logging.getLogger(__name__)

# Agent weight adjustments by regime/context
# Base weight: 0.333 each. These are additive deltas applied before normalization.
_AGENT_WEIGHT_DEFAULTS: dict[str, float] = {
    "institutional": 0.333,
    "market_maker": 0.333,
    "retail": 0.333,
}

# Direction enum mapping: uppercase (from LLM) → lowercase (internal model)
_DIRECTION_MAP = {
    "LONG": "long",
    "SHORT": "short",
    "long": "long",
    "short": "short",
}


class MonteCarloRunner:
    """Runs N Monte Carlo simulations with asyncio concurrency control."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    def run(
        self,
        scenario: SimulationScenario,
        sim_count: int,
        progress_callback: Callable[[int, int], None] | None = None,
        session: SessionInfo | None = None,
        bar_analytics: dict | None = None,
        session_levels_text: str = "",
        price_bars_text: str = "",
        analytics_text: str = "",
        agent_analog_blocks: dict[str, str] | None = None,
    ) -> list[SimulationResult]:
        """Run Monte Carlo simulations. Blocks until all complete.

        This is called from a background thread (gevent greenlet), so we
        create a new asyncio event loop for the async simulation work.

        Args:
            scenario: The simulation scenario from the scenario builder
            sim_count: Number of simulations to run (100–500)
            progress_callback: Called with (completed_count, total_count) after each sim
            session: Current market session info (optional)
            bar_analytics: Pre-computed analytics dict from bar_analytics.compute_bar_analytics
            session_levels_text: Formatted session levels text for agent prompts
            price_bars_text: Formatted recent 5-min bars text for agent prompts
            analytics_text: Formatted analytics text for agent prompts

        Returns:
            List of SimulationResult objects
        """
        try:
            # Check if there's already a running event loop (e.g., inside gunicorn)
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # Already in an async context — run in a new thread with its own loop
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    self._run_in_new_loop, scenario, sim_count, progress_callback,
                    session, bar_analytics, session_levels_text, price_bars_text,
                    analytics_text, agent_analog_blocks,
                )
                return future.result()
        else:
            return self._run_in_new_loop(
                scenario, sim_count, progress_callback, session,
                bar_analytics, session_levels_text, price_bars_text, analytics_text,
                agent_analog_blocks,
            )

    def _run_in_new_loop(
        self,
        scenario: SimulationScenario,
        sim_count: int,
        progress_callback: Callable[[int, int], None] | None,
        session: SessionInfo | None = None,
        bar_analytics: dict | None = None,
        session_levels_text: str = "",
        price_bars_text: str = "",
        analytics_text: str = "",
        agent_analog_blocks: dict[str, str] | None = None,
    ) -> list[SimulationResult]:
        """Run async simulations in a fresh event loop."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self._run_async(
                    scenario, sim_count, progress_callback, session,
                    bar_analytics, session_levels_text, price_bars_text,
                    analytics_text, agent_analog_blocks,
                )
            )
        finally:
            loop.close()

    async def _run_async(
        self,
        scenario: SimulationScenario,
        sim_count: int,
        progress_callback: Callable[[int, int], None] | None,
        session: SessionInfo | None = None,
        bar_analytics: dict | None = None,
        session_levels_text: str = "",
        price_bars_text: str = "",
        analytics_text: str = "",
        agent_analog_blocks: dict[str, str] | None = None,
    ) -> list[SimulationResult]:
        """Async core — manages semaphores and wave-based batching."""
        sim_semaphore = asyncio.Semaphore(constants.SIM_CONCURRENCY)
        api_semaphore = asyncio.Semaphore(constants.API_CONCURRENCY)
        completed = 0
        results: list[SimulationResult] = []
        lock = asyncio.Lock()

        async def run_one(sim_id: int) -> SimulationResult:
            nonlocal completed
            async with sim_semaphore:
                result = await self._run_single_simulation(
                    sim_id, scenario, api_semaphore, session=session,
                    bar_analytics=bar_analytics,
                    session_levels_text=session_levels_text,
                    price_bars_text=price_bars_text,
                    analytics_text=analytics_text,
                    agent_analog_blocks=agent_analog_blocks,
                )
                async with lock:
                    completed += 1
                    results.append(result)
                    if progress_callback:
                        progress_callback(completed, sim_count)
                return result

        # Wave-based batching to prevent rate limit bursts
        tasks: list[asyncio.Task] = []
        for wave_start in range(0, sim_count, constants.WAVE_SIZE):
            wave_end = min(wave_start + constants.WAVE_SIZE, sim_count)
            wave_tasks = [asyncio.create_task(run_one(i)) for i in range(wave_start, wave_end)]
            tasks.extend(wave_tasks)

            # If not the last wave, pause briefly
            if wave_end < sim_count:
                await asyncio.sleep(constants.WAVE_PAUSE_SECONDS)

        await asyncio.gather(*tasks, return_exceptions=True)
        return results

    async def _run_single_simulation(
        self,
        sim_id: int,
        scenario: SimulationScenario,
        api_semaphore: asyncio.Semaphore,
        session: SessionInfo | None = None,
        bar_analytics: dict | None = None,
        session_levels_text: str = "",
        price_bars_text: str = "",
        analytics_text: str = "",
        agent_analog_blocks: dict[str, str] | None = None,
    ) -> SimulationResult:
        """Run one full simulation across all bars."""
        from mirofish_forecast.config.constants import get_instrument_config

        inst_config = get_instrument_config(scenario.instrument)
        seed = random.randint(0, 2**32 - 1)
        rng = random.Random(seed)
        temperature = round(
            rng.uniform(constants.SIM_TEMPERATURE_MIN, constants.SIM_TEMPERATURE_MAX), 2
        )

        current_price = scenario.current_price or 5400.0
        price_path = [current_price]
        all_decisions: list[AgentDecision] = []
        minutes_per_bar = scenario.forecast_horizon_minutes / constants.SIM_BARS_PER_HORIZON

        # Pick a scenario to test (weighted by probability)
        active_scenario = self._pick_scenario(scenario, rng)

        # Agent decision history across bars
        decision_history: dict[str, list[str]] = {
            t: [] for t in ["institutional", "retail", "market_maker"]
        }

        # Determine if FOMC day from events context
        is_fomc_day = self._detect_fomc_day(scenario)

        # Compute context-level agent weight adjustments once per simulation
        agent_weight_adjustments = self._compute_agent_weights(scenario, session)

        try:
            for bar_num in range(constants.SIM_BARS_PER_HORIZON):
                # Pre-compute price_history_str per bar
                price_history_str = ", ".join(f"{p:.2f}" for p in price_path[-5:])

                # Pre-compute Brooks signal bar score from price path
                # Build minimal bar dicts from price path for scoring
                signal_bar_score = self._compute_signal_bar_score(
                    price_path, current_price, inst_config
                )
                signal_score_desc = describe_signal_score(signal_bar_score)

                # Time-of-day regime and confidence multiplier
                tod_context = format_tod_context(is_fomc_day=is_fomc_day)
                _, tod_multiplier, _ = get_tod_regime(is_fomc_day=is_fomc_day)

                # Build prior_decisions strings for each agent (last 5 entries)
                prior_decisions = {
                    t: "; ".join(decision_history[t][-5:]) or "None (first bar)"
                    for t in ["institutional", "retail", "market_maker"]
                }

                # All 3 agents decide concurrently (each uses TWO LLM calls internally)
                _blocks = agent_analog_blocks or {}
                decisions = await asyncio.gather(
                    self._agent_decision(
                        "institutional",
                        scenario.institutional_context.context_text,
                        current_price,
                        bar_num,
                        price_path,
                        active_scenario,
                        minutes_per_bar,
                        scenario.forecast_horizon_minutes,
                        temperature,
                        api_semaphore,
                        instrument=scenario.instrument,
                        prior_decisions=prior_decisions["institutional"],
                        session=session,
                        price_history_str=price_history_str,
                        signal_bar_score=signal_bar_score,
                        signal_score_desc=signal_score_desc,
                        tod_context=tod_context,
                        tod_multiplier=tod_multiplier,
                        bar_analytics=bar_analytics,
                        session_levels_text=session_levels_text,
                        price_bars_text=price_bars_text,
                        analytics_text=analytics_text,
                        historical_analogs=_blocks.get("institutional", ""),
                    ),
                    self._agent_decision(
                        "retail",
                        scenario.retail_context.context_text,
                        current_price,
                        bar_num,
                        price_path,
                        active_scenario,
                        minutes_per_bar,
                        scenario.forecast_horizon_minutes,
                        temperature,
                        api_semaphore,
                        instrument=scenario.instrument,
                        prior_decisions=prior_decisions["retail"],
                        session=session,
                        price_history_str=price_history_str,
                        signal_bar_score=signal_bar_score,
                        signal_score_desc=signal_score_desc,
                        tod_context=tod_context,
                        tod_multiplier=tod_multiplier,
                        bar_analytics=bar_analytics,
                        session_levels_text=session_levels_text,
                        price_bars_text=price_bars_text,
                        analytics_text=analytics_text,
                        historical_analogs=_blocks.get("retail", ""),
                    ),
                    self._agent_decision(
                        "market_maker",
                        scenario.market_maker_context.context_text,
                        current_price,
                        bar_num,
                        price_path,
                        active_scenario,
                        minutes_per_bar,
                        scenario.forecast_horizon_minutes,
                        temperature,
                        api_semaphore,
                        instrument=scenario.instrument,
                        prior_decisions=prior_decisions["market_maker"],
                        session=session,
                        price_history_str=price_history_str,
                        signal_bar_score=signal_bar_score,
                        signal_score_desc=signal_score_desc,
                        tod_context=tod_context,
                        tod_multiplier=tod_multiplier,
                        bar_analytics=bar_analytics,
                        session_levels_text=session_levels_text,
                        price_bars_text=price_bars_text,
                        analytics_text=analytics_text,
                        historical_analogs=_blocks.get("market_maker", ""),
                    ),
                    return_exceptions=True,
                )

                # Process decisions, skip failed agents
                valid_decisions: list[AgentDecision] = []
                for d in decisions:
                    if isinstance(d, AgentDecision):
                        valid_decisions.append(d)

                # Append decision summaries to history
                for d in valid_decisions:
                    summary = (
                        f"bar{bar_num}:{d.direction}@{d.price_target:.1f}"
                        f"(conf:{d.confidence:.2f},score:{d.signal_bar_score})"
                        if d.price_target is not None
                        else f"bar{bar_num}:{d.direction}(conf:{d.confidence:.2f})"
                    )
                    decision_history[d.agent_type].append(summary)

                # Confidence-weighted aggregation
                new_price = self._aggregate_decisions(
                    valid_decisions,
                    current_price,
                    agent_weight_adjustments,
                    inst_config,
                    price_path[0],
                    scenario.market_regime.value,
                    rng,
                )
                current_price = new_price
                price_path.append(current_price)

                # Keep last bar's decisions for the result
                if bar_num == constants.SIM_BARS_PER_HORIZON - 1:
                    all_decisions = valid_decisions

            # Confidence-weighted consensus (not simple majority)
            direction_consensus, confidence_mean = self._compute_consensus(
                all_decisions, agent_weight_adjustments
            )

            final_price = price_path[-1]

            return SimulationResult(
                sim_id=sim_id,
                seed=seed,
                temperature=temperature,
                final_price=final_price,
                price_path=[],  # path not needed downstream
                agent_decisions=all_decisions,
                direction_consensus=direction_consensus,
                confidence_mean=round(confidence_mean, 3),
                success=True,
            )

        except Exception as e:
            logger.warning(f"Simulation {sim_id} failed: {e}")
            return SimulationResult(
                sim_id=sim_id,
                seed=seed,
                temperature=temperature,
                final_price=scenario.current_price or 5400.0,
                success=False,
                error=str(e),
            )

    def _compute_signal_bar_score(
        self,
        price_path: list[float],
        current_price: float,
        inst_config: dict,
    ) -> int:
        """Compute Brooks signal bar score from the simulated price path.

        Uses the price path as synthetic OHLC bars. In production, real 5-min bars
        would be used but during simulation this provides a relative quality signal.
        """
        if len(price_path) < 3:
            return 50  # Neutral default at start of simulation

        # Build minimal bar representation from price path
        # Simulate OHLC from adjacent prices
        bars = []
        for i in range(1, len(price_path)):
            prev = price_path[i - 1]
            curr = price_path[i]
            # Simple synthetic bar: open=prev, close=curr, high=max+small, low=min-small
            spread = abs(curr - prev) * 0.3
            bars.append({
                "open": prev,
                "high": max(prev, curr) + spread,
                "low": min(prev, curr) - spread,
                "close": curr,
                "volume": 10000,
            })

        if not bars:
            return 50

        current_bar = bars[-1]
        features = extract_bar_features(bars, current_idx=len(bars) - 1)

        try:
            score = score_signal_bar(
                bar=current_bar,
                prior_bar=features.get("prior_bar"),
                ema_20=features.get("ema_20"),
                trend_context=features.get("trend_context", "unknown"),
                avg_bar_range=features.get("avg_bar_range"),
            )
        except Exception:
            score = 50  # Fallback to neutral

        return score

    def _detect_fomc_day(self, scenario: SimulationScenario) -> bool:
        """Check if scenario context references a FOMC announcement today."""
        # Check institutional context text for FOMC mention
        ctx_text = (
            scenario.institutional_context.context_text
            if scenario.institutional_context
            else ""
        )
        return "FOMC" in ctx_text and "ALREADY RELEASED" not in ctx_text

    def _compute_agent_weights(
        self,
        scenario: SimulationScenario,
        session: SessionInfo | None,
    ) -> dict[str, float]:
        """Compute regime-dependent agent weights.

        Base: equal weights (0.333 each).
        Adjustments:
        - Market maker +10% during lunch (mean-reversion regime)
        - Institutional +15% on macro event days (FOMC, CPI, NFP)
        - Retail +15% when Fear & Greed < 20 or > 80 (sentiment extremes)
        """
        weights = dict(_AGENT_WEIGHT_DEFAULTS)

        # Check FOMC / major event day
        is_event_day = self._detect_fomc_day(scenario)
        if is_event_day:
            weights["institutional"] += 0.15
            weights["retail"] -= 0.075
            weights["market_maker"] -= 0.075

        # Check sentiment extreme (retail gets higher weight)
        mm_ctx = scenario.market_maker_context.context_text if scenario.market_maker_context else ""
        inst_ctx = scenario.institutional_context.context_text if scenario.institutional_context else ""

        # Fear & Greed extreme detection from context text
        if "EXTREME FEAR" in inst_ctx or "EXTREME GREED" in inst_ctx:
            weights["retail"] += 0.15
            weights["institutional"] -= 0.075
            weights["market_maker"] -= 0.075

        # Lunch hour — market maker (mean-reversion dealer) gets higher weight
        _, multiplier, _ = get_tod_regime()
        if multiplier <= 0.55:  # Lunch doldrums
            weights["market_maker"] += 0.10
            weights["institutional"] -= 0.05
            weights["retail"] -= 0.05

        # Normalize to sum = 1.0
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        return weights

    def _aggregate_decisions(
        self,
        decisions: list[AgentDecision],
        current_price: float,
        agent_weights: dict[str, float],
        inst_config: dict,
        start_price: float,
        regime_value: str,
        rng: random.Random,
    ) -> float:
        """Confidence-weighted price target aggregation."""
        if not decisions:
            return round(current_price + rng.gauss(0, current_price * 0.0003), 2)

        weighted_targets: list[tuple[float, float]] = []  # (target, weight)
        for d in decisions:
            if d.price_target is None:
                continue
            agent_weight = agent_weights.get(d.agent_type, 0.333)
            # Confidence weighting: multiply base agent weight by normalized confidence
            # Confidence range 0.55–0.95 → scale to 0.5–1.5 weight multiplier
            conf_scale = 0.5 + (d.confidence - 0.55) / (0.95 - 0.55)
            effective_weight = agent_weight * conf_scale
            weighted_targets.append((d.price_target, effective_weight))

        if not weighted_targets:
            return round(current_price + rng.gauss(0, current_price * 0.0003), 2)

        total_weight = sum(w for _, w in weighted_targets)
        avg_target = sum(t * w for t, w in weighted_targets) / total_weight

        # Clamp: max per-bar move — instrument-specific
        max_move = current_price * inst_config["max_bar_move_pct"]
        clamped_target = max(
            current_price - max_move,
            min(current_price + max_move, avg_target),
        )

        # Drift anchor: blend toward starting price — regime-conditional
        anchor_weight = constants.REGIME_ANCHOR_WEIGHTS.get(
            regime_value,
            constants.SIM_DRIFT_ANCHOR_WEIGHT,
        )
        anchored = clamped_target * (1 - anchor_weight) + start_price * anchor_weight

        # Add small random noise
        noise = rng.gauss(0, current_price * 0.0003)
        return round(anchored + noise, 2)

    def _compute_consensus(
        self,
        decisions: list[AgentDecision],
        agent_weights: dict[str, float],
    ) -> tuple[str, float]:
        """Compute confidence-weighted direction consensus and mean confidence.

        Returns:
            (direction_consensus, confidence_mean)
        """
        if not decisions:
            return "neutral", 0.5

        # Weighted vote tally
        weighted_long = 0.0
        weighted_short = 0.0
        total_weight = 0.0
        confidence_sum = 0.0

        for d in decisions:
            w = agent_weights.get(d.agent_type, 0.333)
            confidence_sum += d.confidence * w
            total_weight += w

            if d.direction == "long":
                weighted_long += d.confidence * w
            elif d.direction == "short":
                weighted_short += d.confidence * w

        confidence_mean = confidence_sum / max(total_weight, 0.001)

        if weighted_long > weighted_short:
            return "long", confidence_mean
        elif weighted_short > weighted_long:
            return "short", confidence_mean
        else:
            return "neutral", confidence_mean

    def _pick_scenario(self, scenario: SimulationScenario, rng: random.Random) -> dict[str, str]:
        """Randomly select which scenario this simulation tests, weighted by probability."""
        if not scenario.scenarios:
            return {"name": "Default", "description": "No scenarios available"}

        roll = rng.random()
        cumulative = 0.0
        for s in scenario.scenarios:
            cumulative += s.probability
            if roll <= cumulative:
                return {"name": s.name, "description": s.description}

        last = scenario.scenarios[-1]
        return {"name": last.name, "description": last.description}

    @staticmethod
    def _get_price_guidance(instrument: str, current_price: float) -> str:
        """Get instrument-specific price target guidance for agent prompts."""
        guidance = {
            "ES": (
                f"ES typically moves 1-5 points per bar. Keep your target within"
                f" 10 points of {current_price:.2f}. 1 ES point = $50."
            ),
            "NQ": (
                f"NQ typically moves 5-20 points per bar. Keep your target within"
                f" 40 points of {current_price:.2f}. 1 NQ point = $20."
            ),
            "CL": (
                f"Crude oil typically moves $0.05-$0.20 per bar. Keep your target"
                f" within $0.50 of {current_price:.2f}. 1 CL point = $1,000."
            ),
            "GC": (
                f"Gold typically moves $1-5 per bar. Keep your target within"
                f" $15 of {current_price:.2f}. 1 GC point = $100."
            ),
        }
        return guidance.get(instrument.upper(), guidance["ES"])

    async def _agent_decision(
        self,
        agent_type: str,
        context_text: str,
        current_price: float,
        bar_number: int,
        price_path: list[float],
        active_scenario: dict[str, str],
        minutes_per_bar: float,
        horizon_minutes: int,
        temperature: float,
        api_semaphore: asyncio.Semaphore,
        instrument: str = "ES",
        prior_decisions: str = "",
        session: SessionInfo | None = None,
        price_history_str: str = "",
        signal_bar_score: int = 50,
        signal_score_desc: str = "",
        tod_context: str = "",
        tod_multiplier: float = 1.0,
        bar_analytics: dict | None = None,
        session_levels_text: str = "",
        price_bars_text: str = "",
        analytics_text: str = "",
        historical_analogs: str = "",
    ) -> AgentDecision:
        """Get a single agent's decision using two-call CoT architecture.

        Call 1: Free-form 8-step reasoning (agent-specific CoT prompt)
        Call 2: Structured JSON extraction (AGENT_EXTRACT_PROMPT)
        """
        from mirofish_forecast.config.constants import get_instrument_config

        inst_config = get_instrument_config(instrument)
        price_guidance = self._get_price_guidance(instrument, current_price)

        # Build session context string
        session_ctx = ""
        if session:
            phase = (
                session.session_phase if hasattr(session, "session_phase") else session.session_type
            )
            session_ctx = (
                f"Session: {session.session_label} | "
                f"Phase: {phase} | "
                f"Minutes to close: {session.minutes_to_rth_close}"
            )

        # Format signal bar score with description
        score_context = f"{signal_bar_score}/100 — {signal_score_desc}"

        # ─── Call 1: CoT Reasoning (agent-specific prompt) ────────────────────
        cot_template = get_agent_cot_prompt(agent_type)
        cot_prompt = cot_template.format(
            agent_type=agent_type,
            instrument_name=inst_config["name"],
            agent_context=context_text,
            bar_number=bar_number + 1,
            total_bars=constants.SIM_BARS_PER_HORIZON,
            horizon_minutes=horizon_minutes,
            minutes_per_bar=round(minutes_per_bar, 1),
            current_price=current_price,
            price_history=price_history_str or ", ".join(f"{p:.2f}" for p in price_path[-5:]),
            signal_bar_score=score_context,
            time_of_day_context=tod_context,
            scenario_name=active_scenario["name"],
            scenario_description=active_scenario["description"],
            session_context=session_ctx,
            prior_decisions=prior_decisions or "None (first bar)",
            instrument_price_guidance=price_guidance,
            # New hybrid agent framework fields
            session_levels=session_levels_text or "Not available",
            bar_analytics=analytics_text or "Not available",
            price_bars=price_bars_text or "Not available",
            # Brooks RAG analogs (empty string = no block in prompt)
            historical_analogs=historical_analogs,
        )

        async with api_semaphore:
            try:
                # Call 1: reasoning (no JSON constraint — free-form)
                cot_response = await self._client.chat.completions.create(
                    model=self._settings.openai_model_agents,
                    messages=[
                        {"role": "system", "content": cot_prompt},
                        {
                            "role": "user",
                            "content": (
                                f"Analyze bar {bar_number + 1}. "
                                f"Current price: {current_price}. "
                                "Work through all 8 steps."
                            ),
                        },
                    ],
                    temperature=temperature,
                    max_tokens=400,
                    timeout=15,
                )
                cot_reasoning = cot_response.choices[0].message.content or ""

            except Exception as e:
                logger.debug(f"Agent {agent_type} CoT call failed bar {bar_number}: {e}")
                cot_reasoning = (
                    f"Analysis: Price at {current_price}, signal score {signal_bar_score}/100. "
                    f"Scenario: {active_scenario['name']}."
                )

        async with api_semaphore:
            try:
                # Call 2: structured extraction (JSON constrained)
                extract_prompt = AGENT_EXTRACT_PROMPT.format(
                    cot_reasoning=cot_reasoning,
                    current_price=current_price,
                    instrument_price_guidance=price_guidance,
                    instrument_name=inst_config["name"],
                    total_bars=constants.SIM_BARS_PER_HORIZON,
                    signal_bar_score=signal_bar_score,
                )

                extract_response = await self._client.chat.completions.create(
                    model=self._settings.openai_model_agents,
                    messages=[
                        {
                            "role": "system",
                            "content": "You extract structured trading decisions from analysis text. "
                                       "Output valid JSON only.",
                        },
                        {"role": "user", "content": extract_prompt},
                    ],
                    temperature=0.0,   # Deterministic extraction
                    max_tokens=200,
                    timeout=15,
                    response_format={"type": "json_object"},
                )

                content = extract_response.choices[0].message.content or "{}"
                data = json.loads(content)

                # Map uppercase direction → lowercase internal
                raw_direction = data.get("direction", "LONG")
                direction = _DIRECTION_MAP.get(raw_direction, "long")

                # Apply time-of-day confidence multiplier, clamp to [0.55, 0.95]
                raw_confidence = max(0.0, min(1.0, float(data.get("confidence", 0.6))))
                adjusted_confidence = max(0.55, min(0.95, raw_confidence * tod_multiplier))

                return AgentDecision(
                    agent_type=agent_type,
                    direction=direction,
                    confidence=round(adjusted_confidence, 3),
                    price_target=(
                        float(data["primary_target"])
                        if data.get("primary_target")
                        else None
                    ),
                    reasoning=data.get("reasoning", ""),
                    signal_bar_score=int(data.get("signal_bar_score", signal_bar_score)),
                    regime=data.get("regime"),
                    time_horizon_bars=data.get("time_horizon_bars"),
                )

            except Exception as e:
                logger.debug(f"Agent {agent_type} extract call failed bar {bar_number}: {e}")
                # Fallback: use CoT reasoning to infer direction heuristically
                direction = "long" if "LONG" in cot_reasoning.upper() else "short"
                return AgentDecision(
                    agent_type=agent_type,
                    direction=direction,
                    confidence=0.55,
                    price_target=current_price,
                    reasoning=f"Fallback from CoT — extract failed: {str(e)[:50]}",
                    signal_bar_score=signal_bar_score,
                )
