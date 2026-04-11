"""Monte Carlo simulation runner — runs N simulations with asyncio concurrency.

Each simulation:
1. Picks a random seed and LLM temperature
2. Starts from the current ES price
3. Simulates SIM_BARS_PER_HORIZON bars
4. At each bar, 3 agents (institutional, retail, market maker) make decisions
5. The bar's price change = weighted average of agent price targets
6. Final price is the result

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
from mirofish_forecast.llm.prompts.agent_decision import AGENT_DECISION_SYSTEM_PROMPT
from mirofish_forecast.models.forecast import AgentDecision, SimulationResult
from mirofish_forecast.models.scenario import SimulationScenario
from mirofish_forecast.services.session_context import SessionInfo

logger = logging.getLogger(__name__)


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
    ) -> list[SimulationResult]:
        """Run Monte Carlo simulations. Blocks until all complete.

        This is called from a background thread (gevent greenlet), so we
        create a new asyncio event loop for the async simulation work.

        Args:
            scenario: The simulation scenario from the scenario builder
            sim_count: Number of simulations to run (100–500)
            progress_callback: Called with (completed_count, total_count) after each sim
            session: Current market session info (optional)

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
                    self._run_in_new_loop, scenario, sim_count, progress_callback, session
                )
                return future.result()
        else:
            return self._run_in_new_loop(scenario, sim_count, progress_callback, session)

    def _run_in_new_loop(
        self,
        scenario: SimulationScenario,
        sim_count: int,
        progress_callback: Callable[[int, int], None] | None,
        session: SessionInfo | None = None,
    ) -> list[SimulationResult]:
        """Run async simulations in a fresh event loop."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self._run_async(scenario, sim_count, progress_callback, session)
            )
        finally:
            loop.close()

    async def _run_async(
        self,
        scenario: SimulationScenario,
        sim_count: int,
        progress_callback: Callable[[int, int], None] | None,
        session: SessionInfo | None = None,
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
                    sim_id, scenario, api_semaphore, session=session
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

        # Fix 1B: Agent decision history across bars
        decision_history: dict[str, list[str]] = {
            t: [] for t in ["institutional", "retail", "market_maker"]
        }

        try:
            for bar_num in range(constants.SIM_BARS_PER_HORIZON):
                # Opt 2E: Pre-compute price_history_str per bar
                price_history_str = ", ".join(f"{p:.2f}" for p in price_path[-5:])

                # Build prior_decisions strings for each agent (last 5 entries)
                prior_decisions = {
                    t: "; ".join(decision_history[t][-5:]) or "None (first bar)"
                    for t in ["institutional", "retail", "market_maker"]
                }

                # All 3 agents decide concurrently
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
                    ),
                    return_exceptions=True,
                )

                # Process decisions, skip failed agents
                valid_targets: list[float] = []
                bar_decisions: list[AgentDecision] = []
                for d in decisions:
                    if isinstance(d, AgentDecision):
                        bar_decisions.append(d)
                        if d.price_target is not None:
                            valid_targets.append(d.price_target)

                # Fix 1B: Append decision summaries to history
                for d in bar_decisions:
                    summary = (
                        f"bar{bar_num}:{d.direction}@"
                        f"{d.price_target:.1f}(conf:{d.confidence:.2f})"
                        if d.price_target is not None
                        else f"bar{bar_num}:{d.direction}(conf:{d.confidence:.2f})"
                    )
                    decision_history[d.agent_type].append(summary)

                # Update price: weighted average of agent targets + noise + drift anchoring
                if valid_targets:
                    avg_target = sum(valid_targets) / len(valid_targets)

                    # Clamp: max per-bar move — instrument-specific
                    max_move = current_price * inst_config["max_bar_move_pct"]
                    clamped_target = max(
                        current_price - max_move,
                        min(current_price + max_move, avg_target),
                    )

                    # Drift anchor: blend toward starting price — regime-conditional
                    start_price = price_path[0]
                    anchor_weight = constants.REGIME_ANCHOR_WEIGHTS.get(
                        scenario.market_regime.value,
                        constants.SIM_DRIFT_ANCHOR_WEIGHT,
                    )
                    anchored = (
                        clamped_target * (1 - anchor_weight)
                        + start_price * anchor_weight
                    )

                    # Add small random noise
                    noise = rng.gauss(0, current_price * 0.0003)
                    current_price = round(anchored + noise, 2)
                else:
                    # No valid targets — small random walk
                    current_price = round(current_price + rng.gauss(0, current_price * 0.0003), 2)

                price_path.append(current_price)

                # Keep last bar's decisions for the result
                if bar_num == constants.SIM_BARS_PER_HORIZON - 1:
                    all_decisions = bar_decisions

            # Determine consensus direction
            directions = [d.direction for d in all_decisions]
            direction_consensus = (
                max(set(directions), key=directions.count) if directions else "neutral"
            )
            confidence_mean = (
                sum(d.confidence for d in all_decisions) / len(all_decisions)
                if all_decisions
                else 0.5
            )

            # Opt 2B: final_price is all synthesis uses
            final_price = price_path[-1]

            return SimulationResult(
                sim_id=sim_id,
                seed=seed,
                temperature=temperature,
                final_price=final_price,
                price_path=[],  # path not needed downstream — final_price is all synthesis uses
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
    ) -> AgentDecision:
        """Get a single agent's decision for one bar."""
        from mirofish_forecast.config.constants import get_instrument_config

        inst_config = get_instrument_config(instrument)

        # Fix 1C: Build session context string
        session_ctx = ""
        if session:
            session_ctx = (
                f"Session: {session.session_label} | "
                f"Phase: {session.session_phase if hasattr(session, 'session_phase') else session.session_type} | "
                f"Minutes to close: {session.minutes_to_rth_close}"
            )

        prompt = AGENT_DECISION_SYSTEM_PROMPT.format(
            agent_type=agent_type,
            agent_context=context_text,
            current_price=current_price,
            bar_number=bar_number + 1,
            total_bars=constants.SIM_BARS_PER_HORIZON,
            horizon_minutes=horizon_minutes,
            minutes_per_bar=round(minutes_per_bar, 1),
            price_history=price_history_str or ", ".join(f"{p:.2f}" for p in price_path[-5:]),
            scenario_name=active_scenario["name"],
            scenario_description=active_scenario["description"],
            instrument_name=inst_config["name"],
            instrument_price_guidance=self._get_price_guidance(instrument, current_price),
            prior_decisions=prior_decisions or "None (first bar)",
            session_context=session_ctx,
        )

        async with api_semaphore:
            try:
                response = await self._client.chat.completions.create(
                    model=self._settings.openai_model_agents,
                    messages=[
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": (
                                f"Make your decision for bar {bar_number + 1}."
                                f" Current price: {current_price}"
                            ),
                        },
                    ],
                    temperature=temperature,
                    max_tokens=200,
                    timeout=15,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content or "{}"
                data = json.loads(content)

                return AgentDecision(
                    agent_type=agent_type,
                    direction=data.get("direction", "neutral"),
                    confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                    price_target=(
                        float(data["price_target"]) if data.get("price_target") else None
                    ),
                    reasoning=data.get("reasoning", ""),
                )

            except Exception as e:
                logger.debug(f"Agent {agent_type} bar {bar_number} failed: {e}")
                return AgentDecision(
                    agent_type=agent_type,
                    direction="neutral",
                    confidence=0.5,
                    price_target=current_price,
                    reasoning=f"Fallback — agent call failed: {str(e)[:50]}",
                )
