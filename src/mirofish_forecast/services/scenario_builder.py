"""Scenario builder — translates ForecastQuery + MarketContext into SimulationScenario.

Two-tier approach:
1. LLM-powered: GPT-4o generates interpretive context blocks and ranked scenarios
2. Template fallback: Deterministic templates fill from raw data if LLM fails
"""

import logging
from datetime import datetime

from mirofish_forecast.config.settings import Settings
from mirofish_forecast.llm.client import LLMClient
from mirofish_forecast.llm.prompts.build_scenarios import BUILD_SCENARIOS_SYSTEM_PROMPT
from mirofish_forecast.llm.prompts.institutional_context import (
    build_institutional_context_template,
)
from mirofish_forecast.llm.prompts.interpret_context import (
    INTERPRET_CONTEXT_SYSTEM_PROMPT,
)
from mirofish_forecast.llm.prompts.market_maker_context import (
    build_market_maker_context_template,
)
from mirofish_forecast.llm.prompts.retail_context import build_retail_context_template
from mirofish_forecast.llm.schemas import (
    ParsedContextBlocks,
    ParsedScenarioSet,
)
from mirofish_forecast.models.market import MarketContext
from mirofish_forecast.models.query import ForecastQuery
from mirofish_forecast.models.scenario import (
    AgentContextBlock,
    KeyLevel,
    MarketRegime,
    ScenarioOutcome,
    ScenarioRank,
    SimulationScenario,
)

logger = logging.getLogger(__name__)


class ScenarioBuilder:
    """Builds SimulationScenario from ForecastQuery + MarketContext."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = LLMClient(settings)

    def build(self, query: ForecastQuery, context: MarketContext) -> SimulationScenario:
        """Build a complete SimulationScenario.

        Attempts LLM-powered generation first, falls back to templates on failure.
        """
        logger.info(
            f"Building scenario for {query.instrument} ({query.forecast_horizon_minutes}min)"
        )

        # Step 1: Generate agent-specific context blocks
        inst_ctx, retail_ctx, mm_ctx = self._build_context_blocks(context)

        # Step 2: Generate ranked scenarios and market regime
        scenario_data = self._build_scenarios(query, context)

        return SimulationScenario(
            instrument=query.instrument,
            forecast_horizon_minutes=query.forecast_horizon_minutes,
            current_price=context.cross_asset.es_price,
            target_time=query.target_time,
            market_regime=scenario_data["market_regime"],
            always_in_direction=scenario_data["always_in_direction"],
            market_state_score=scenario_data["market_state_score"],
            key_levels=scenario_data["key_levels"],
            scenarios=scenario_data["scenarios"],
            institutional_context=inst_ctx,
            retail_context=retail_ctx,
            market_maker_context=mm_ctx,
            built_at=datetime.utcnow(),
            build_method=scenario_data["build_method"],
        )

    # ---------------------------------------------------------------
    # Context block generation
    # ---------------------------------------------------------------

    def _build_context_blocks(
        self, context: MarketContext
    ) -> tuple[AgentContextBlock, AgentContextBlock, AgentContextBlock]:
        """Generate agent-specific context blocks. LLM first, template fallback."""
        try:
            return self._build_context_blocks_llm(context)
        except Exception:
            logger.warning("LLM context interpretation failed, using templates", exc_info=True)
            return self._build_context_blocks_template(context)

    def _build_context_blocks_llm(
        self, context: MarketContext
    ) -> tuple[AgentContextBlock, AgentContextBlock, AgentContextBlock]:
        """Use GPT-4o to generate interpretive context blocks."""
        context_json = context.model_dump_json()

        parsed: ParsedContextBlocks = self._llm.parse_structured(
            system_prompt=INTERPRET_CONTEXT_SYSTEM_PROMPT,
            user_message=f"Current market data:\n{context_json}",
            response_format=ParsedContextBlocks,
            temperature=0.3,
            max_tokens=2000,
            timeout=20,
        )

        institutional = AgentContextBlock(
            agent_type="institutional",
            context_text=parsed.institutional.context,
            priority_signals=parsed.institutional.priority_signals,
        )
        retail = AgentContextBlock(
            agent_type="retail",
            context_text=parsed.retail.context,
            priority_signals=parsed.retail.priority_signals,
        )
        market_maker = AgentContextBlock(
            agent_type="market_maker",
            context_text=parsed.market_maker.context,
            priority_signals=parsed.market_maker.priority_signals,
        )

        return institutional, retail, market_maker

    def _build_context_blocks_template(
        self, context: MarketContext
    ) -> tuple[AgentContextBlock, AgentContextBlock, AgentContextBlock]:
        """Deterministic template fallback for context blocks."""
        institutional = AgentContextBlock(
            agent_type="institutional",
            context_text=build_institutional_context_template(
                fed_funds=context.macro.fed_funds_rate,
                ten_year=context.macro.ten_year_yield,
                two_year=context.macro.two_year_yield,
                spread_2s10s=context.macro.ten_year_2_year_spread,
                cpi_yoy=context.macro.cpi_yoy,
                gdp_growth=context.macro.gdp_growth,
                unemployment=context.macro.unemployment_rate,
                vix_spot=context.vix.spot,
                vix_regime=context.vix.regime.value if context.vix.regime else None,
                fear_greed=context.fear_greed.value,
                es_price=context.cross_asset.es_price,
                dxy_price=context.cross_asset.dxy_price,
                tlt_price=context.cross_asset.tlt_price,
                gld_price=context.cross_asset.gld_price,
                crude_price=context.cross_asset.crude_price,
            ),
            priority_signals=self._infer_institutional_signals(context),
        )

        retail = AgentContextBlock(
            agent_type="retail",
            context_text=build_retail_context_template(
                fear_greed=context.fear_greed.value,
                fear_greed_desc=context.fear_greed.description,
                vix_spot=context.vix.spot,
                es_price=context.cross_asset.es_price,
                nq_price=context.cross_asset.nq_price,
                spy_price=context.cross_asset.spy_price,
            ),
            priority_signals=self._infer_retail_signals(context),
        )

        market_maker = AgentContextBlock(
            agent_type="market_maker",
            context_text=build_market_maker_context_template(
                nyse_tick=context.internals.nyse_tick,
                nyse_add=context.internals.nyse_add,
                nyse_vold=context.internals.nyse_vold,
                vix_spot=context.vix.spot,
                es_price=context.cross_asset.es_price,
            ),
            priority_signals=self._infer_mm_signals(context),
        )

        return institutional, retail, market_maker

    # ---------------------------------------------------------------
    # Scenario generation
    # ---------------------------------------------------------------

    def _build_scenarios(self, query: ForecastQuery, context: MarketContext) -> dict:
        """Generate three ranked scenarios. LLM first, template fallback."""
        try:
            return self._build_scenarios_llm(query, context)
        except Exception:
            logger.warning("LLM scenario generation failed, using template", exc_info=True)
            return self._build_scenarios_template(query, context)

    def _build_scenarios_llm(self, query: ForecastQuery, context: MarketContext) -> dict:
        """Use GPT-4o to generate ranked scenarios."""
        user_message = (
            f"Forecast query: {query.raw_query}\n"
            f"Instrument: {query.instrument}\n"
            f"Horizon: {query.forecast_horizon_minutes} minutes\n"
            f"Direction bias: {query.direction_bias or 'none stated'}\n"
            f"Event mention: {query.mentions_event or 'none'}\n\n"
            f"Current market data:\n{context.model_dump_json()}"
        )

        parsed: ParsedScenarioSet = self._llm.parse_structured(
            system_prompt=BUILD_SCENARIOS_SYSTEM_PROMPT,
            user_message=user_message,
            response_format=ParsedScenarioSet,
            temperature=0.4,
            max_tokens=2000,
            timeout=25,
        )

        # Map parsed scenarios to domain models
        scenarios = []
        for s in parsed.scenarios:
            try:
                rank = ScenarioRank(s.rank)
            except ValueError:
                rank = ScenarioRank.MOST_PROBABLE
            scenarios.append(
                ScenarioOutcome(
                    rank=rank,
                    name=s.name,
                    description=s.description,
                    probability=s.probability,
                    price_target=s.price_target,
                    price_range_low=s.price_range_low,
                    price_range_high=s.price_range_high,
                    trigger=s.trigger,
                    invalidation=s.invalidation,
                    key_risk=s.key_risk,
                )
            )

        # Ensure exactly 3 scenarios
        while len(scenarios) < 3:
            scenarios.append(
                ScenarioOutcome(
                    rank=ScenarioRank.FAILURE_TRAP,
                    name="Unknown",
                    description="Insufficient data to generate this scenario.",
                    probability=0.1,
                )
            )

        # Normalize probabilities to sum to 1.0
        total_prob = sum(s.probability for s in scenarios[:3])
        if total_prob > 0:
            scenarios = [
                s.model_copy(update={"probability": round(s.probability / total_prob, 3)})
                for s in scenarios[:3]
            ]

        key_levels = [
            KeyLevel(
                price=kl.price,
                label=kl.label,
                significance=kl.significance,
                source=kl.source,
            )
            for kl in parsed.key_levels
        ]

        try:
            regime = MarketRegime(parsed.market_regime)
        except ValueError:
            regime = MarketRegime.VOLATILE_CHOP

        return {
            "market_regime": regime,
            "always_in_direction": parsed.always_in_direction,
            "market_state_score": parsed.market_state_score,
            "key_levels": key_levels,
            "scenarios": scenarios,
            "build_method": "llm",
        }

    def _build_scenarios_template(self, query: ForecastQuery, context: MarketContext) -> dict:
        """Deterministic fallback scenario generation based on VIX regime and Fear & Greed."""
        es_price = context.cross_asset.es_price or 5400.0
        vix = context.vix.spot or 20.0
        fg = context.fear_greed.value or 50.0

        # Determine regime from VIX + Fear & Greed
        if vix > 30:
            regime = MarketRegime.BREAKDOWN
            direction = "short"
            score = 2.5
        elif vix > 25 and fg < 30:
            regime = MarketRegime.VOLATILE_CHOP
            direction = "neutral"
            score = 4.0
        elif vix < 15 and fg > 60:
            regime = MarketRegime.TIGHT_RANGE
            direction = "long"
            score = 6.5
        elif fg > 70:
            regime = MarketRegime.TRENDING_UP
            direction = "long"
            score = 7.0
        elif fg < 30:
            regime = MarketRegime.TRENDING_DOWN
            direction = "short"
            score = 3.0
        else:
            regime = MarketRegime.TIGHT_RANGE
            direction = "neutral"
            score = 5.0

        # Scale range by VIX
        range_factor = vix / 20.0  # VIX 20 = baseline
        base_range = 15.0 * range_factor  # ~15 points at VIX 20

        # Generate key levels
        lower_round = int(es_price / 50) * 50
        upper_round = lower_round + 50
        key_levels = [
            KeyLevel(
                price=float(lower_round),
                label="Support",
                significance="medium",
                source="Round number",
            ),
            KeyLevel(
                price=float(upper_round),
                label="Resistance",
                significance="medium",
                source="Round number",
            ),
            KeyLevel(
                price=round(es_price - base_range, 2),
                label="Support",
                significance="high",
                source="VIX-scaled range",
            ),
            KeyLevel(
                price=round(es_price + base_range, 2),
                label="Resistance",
                significance="high",
                source="VIX-scaled range",
            ),
        ]

        # Generate three scenarios
        scenarios = [
            ScenarioOutcome(
                rank=ScenarioRank.MOST_PROBABLE,
                name=f"Range-bound near {es_price:.0f}",
                description=(
                    f"{query.instrument} consolidates in a"
                    f" {base_range:.0f}-point range around current levels."
                ),
                probability=0.55,
                price_target=es_price,
                price_range_low=round(es_price - base_range * 0.6, 2),
                price_range_high=round(es_price + base_range * 0.6, 2),
                trigger="Continued low-conviction flow",
                invalidation=(
                    f"Break above {es_price + base_range:.0f} or below {es_price - base_range:.0f}"
                ),
                key_risk="Unexpected headline catalyst",
            ),
            ScenarioOutcome(
                rank=ScenarioRank.SECONDARY,
                name=(
                    f"Move to {es_price + base_range:.0f}"
                    if direction != "short"
                    else f"Decline to {es_price - base_range:.0f}"
                ),
                description=(
                    f"Directional move {'higher' if direction != 'short' else 'lower'}"
                    " driven by momentum."
                ),
                probability=0.30,
                price_target=round(
                    es_price + base_range if direction != "short" else es_price - base_range,
                    2,
                ),
                price_range_low=round(
                    es_price - base_range * 0.3
                    if direction != "short"
                    else es_price - base_range * 1.3,
                    2,
                ),
                price_range_high=round(
                    es_price + base_range * 1.3
                    if direction != "short"
                    else es_price + base_range * 0.3,
                    2,
                ),
                trigger=(
                    f"Break {'above' if direction != 'short' else 'below'} key level with volume"
                ),
                invalidation="Reversal back through entry zone",
                key_risk=(
                    "False breakout / bull trap" if direction != "short" else "Short squeeze"
                ),
            ),
            ScenarioOutcome(
                rank=ScenarioRank.FAILURE_TRAP,
                name="Volatility expansion",
                description=(
                    "Unexpected move catches the crowd wrong-footed."
                    f" {base_range * 2:.0f}+ point range day."
                ),
                probability=0.15,
                price_target=None,
                price_range_low=round(es_price - base_range * 2, 2),
                price_range_high=round(es_price + base_range * 2, 2),
                trigger="Surprise headline, liquidity vacuum, or gamma unwind",
                invalidation="Quick mean reversion to prior range",
                key_risk="Gap risk, stop cascades",
            ),
        ]

        return {
            "market_regime": regime,
            "always_in_direction": direction,
            "market_state_score": score,
            "key_levels": key_levels,
            "scenarios": scenarios,
            "build_method": "template",
        }

    # ---------------------------------------------------------------
    # Signal inference helpers (for template fallback)
    # ---------------------------------------------------------------

    def _infer_institutional_signals(self, ctx: MarketContext) -> list[str]:
        """Infer top institutional signals from market context."""
        signals: list[str] = []
        if ctx.macro.ten_year_2_year_spread is not None:
            if ctx.macro.ten_year_2_year_spread < 0:
                signals.append("Inverted yield curve")
            else:
                signals.append(f"2s10s spread at {ctx.macro.ten_year_2_year_spread:.2f}%")
        if ctx.vix.regime:
            signals.append(f"VIX {ctx.vix.regime.value}")
        if ctx.cross_asset.dxy_price:
            signals.append(f"DXY at {ctx.cross_asset.dxy_price:.1f}")
        return signals[:3]

    def _infer_retail_signals(self, ctx: MarketContext) -> list[str]:
        """Infer top retail signals from market context."""
        signals: list[str] = []
        if ctx.fear_greed.value is not None:
            signals.append(
                f"Fear & Greed: {ctx.fear_greed.value:.0f} ({ctx.fear_greed.description})"
            )
        if ctx.vix.spot is not None:
            signals.append(f"VIX at {ctx.vix.spot:.1f}")
        if ctx.cross_asset.es_price is not None:
            signals.append(f"ES at {ctx.cross_asset.es_price:.2f}")
        return signals[:3]

    def _infer_mm_signals(self, ctx: MarketContext) -> list[str]:
        """Infer top market maker signals from market context."""
        signals: list[str] = []
        if ctx.internals.nyse_tick is not None:
            signals.append(f"TICK at {ctx.internals.nyse_tick:+.0f}")
        elif ctx.vix.spot is not None:
            signals.append(f"VIX at {ctx.vix.spot:.1f} (IB offline)")
        if ctx.internals.nyse_add is not None:
            signals.append(f"ADD at {ctx.internals.nyse_add:+.0f}")
        if ctx.internals.nyse_vold is not None:
            signals.append(f"VOLD at {ctx.internals.nyse_vold:+.0f}")
        return signals[:3]
