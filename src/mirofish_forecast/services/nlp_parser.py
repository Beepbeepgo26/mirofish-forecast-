"""NLP parser: converts natural language queries into ForecastQuery objects.

Uses a two-tier approach:
1. Regex pre-validation handles unambiguous queries in ~5ms
2. GPT-4o Structured Outputs handles complex/ambiguous queries in ~500ms
"""

import logging
import re
from datetime import datetime

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.llm.client import LLMClient
from mirofish_forecast.llm.prompts.parse_query import PARSE_QUERY_SYSTEM_PROMPT
from mirofish_forecast.llm.schemas import ParsedForecastQuery
from mirofish_forecast.models.query import ForecastQuery, QueryType, SimPreset

logger = logging.getLogger(__name__)


class NLPParser:
    """Parses natural language forecast queries into structured ForecastQuery objects."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = LLMClient(settings)

    def parse(
        self,
        raw_query: str,
        sim_preset: str = "standard",
        sim_count: int | None = None,
    ) -> ForecastQuery:
        """Parse a natural language query. Tries regex first, falls back to LLM.

        Args:
            raw_query: The user's natural language question
            sim_preset: "quick", "standard", or "deep"
            sim_count: Override sim count (for custom/advanced mode)

        Returns:
            ForecastQuery with all parsed fields populated
        """
        # Resolve simulation count from preset or custom value
        resolved_preset, resolved_count = self._resolve_sim_config(sim_preset, sim_count)

        # Try regex extraction first
        regex_result = self._try_regex_parse(raw_query)
        if regex_result is not None:
            logger.info(f"Query parsed via regex: instrument={regex_result.instrument}")
            return regex_result.model_copy(
                update={
                    "sim_preset": resolved_preset,
                    "sim_count": resolved_count,
                }
            )

        # Fall back to LLM
        logger.info("Regex parse insufficient, falling back to LLM")
        return self._llm_parse(raw_query, resolved_preset, resolved_count)

    def _resolve_sim_config(self, preset: str, custom_count: int | None) -> tuple[SimPreset, int]:
        """Resolve simulation preset and count."""
        if custom_count is not None:
            clamped = max(100, min(500, custom_count))
            return SimPreset.CUSTOM, clamped

        preset_map = {
            "quick": (SimPreset.QUICK, constants.DEFAULT_SIM_COUNT_QUICK),
            "standard": (SimPreset.STANDARD, constants.DEFAULT_SIM_COUNT_STANDARD),
            "deep": (SimPreset.DEEP, constants.DEFAULT_SIM_COUNT_DEEP),
        }
        return preset_map.get(preset, (SimPreset.STANDARD, constants.DEFAULT_SIM_COUNT_STANDARD))

    def _try_regex_parse(self, raw_query: str) -> ForecastQuery | None:
        """Attempt to parse a simple query using regex only.

        Returns a ForecastQuery if the query is unambiguous, None if LLM is needed.
        A query is regex-parseable if we can confidently extract:
        - An instrument (or default to ES)
        - A clear time horizon or target time
        """
        query_lower = raw_query.lower().strip()

        # Extract instrument
        instrument_match = re.search(constants.REGEX_INSTRUMENT, raw_query, re.IGNORECASE)
        instrument = instrument_match.group(0).upper() if instrument_match else "ES"

        # Extract time horizon (e.g., "next 2 hours", "30 minutes")
        horizon_match = re.search(constants.REGEX_HORIZON, query_lower)
        horizon_minutes = None
        if horizon_match:
            amount = int(horizon_match.group(1))
            unit = horizon_match.group(2).lower()
            if unit.startswith("min"):
                horizon_minutes = amount
            elif unit.startswith("h"):
                horizon_minutes = amount * 60
            elif unit.startswith("d"):
                horizon_minutes = amount * 60 * 24
            elif unit.startswith("w"):
                horizon_minutes = amount * 60 * 24 * 7

        # Extract target time (e.g., "11:30 AM PT")
        time_match = re.search(constants.REGEX_TIME, raw_query, re.IGNORECASE)
        target_time = time_match.group(0).strip() if time_match else None

        # Extract price target
        price_match = re.search(constants.REGEX_PRICE_TARGET, raw_query)
        target_price = float(price_match.group(1)) if price_match else None

        # Extract direction bias
        direction_match = re.search(constants.REGEX_DIRECTION, query_lower)
        direction_bias = None
        if direction_match:
            word = direction_match.group(0)
            if word in ("bullish", "long", "up", "rally", "pump", "moon"):
                direction_bias = "bullish"
            elif word in ("bearish", "short", "down", "sell-off", "selloff", "dump"):
                direction_bias = "bearish"

        # Determine query type
        query_type = self._infer_query_type(query_lower, target_price, direction_bias)

        # We need at least a horizon or target time to consider this a valid regex parse
        if horizon_minutes is None and target_time is None:
            # Too ambiguous — need LLM
            return None

        return ForecastQuery(
            raw_query=raw_query,
            instrument=instrument,
            query_type=query_type,
            target_time=target_time,
            forecast_horizon_minutes=horizon_minutes or constants.DEFAULT_HORIZON_MINUTES,
            target_price=target_price,
            direction_bias=direction_bias,
            parsed_at=datetime.utcnow(),
            parse_method="regex",
        )

    def _infer_query_type(
        self,
        query_lower: str,
        target_price: float | None,
        direction_bias: str | None,
    ) -> QueryType:
        """Infer the query type from extracted features."""
        if target_price is not None and any(
            kw in query_lower
            for kw in ("probability", "chance", "odds", "will", "hit", "reach", "break")
        ):
            return QueryType.PROBABILITY_FORECAST

        if any(kw in query_lower for kw in ("where will", "price at", "what price", "target")):
            return QueryType.POINT_FORECAST

        if any(kw in query_lower for kw in ("range", "between", "high and low")):
            return QueryType.RANGE_FORECAST

        if any(
            kw in query_lower
            for kw in ("direction", "up or down", "bullish or bearish", "long or short")
        ):
            return QueryType.DIRECTION_FORECAST

        if any(kw in query_lower for kw in ("scenario", "scenarios", "what if", "possibilities")):
            return QueryType.SCENARIO_FORECAST

        if direction_bias is not None:
            return QueryType.DIRECTION_FORECAST

        return QueryType.RANGE_FORECAST

    def _llm_parse(self, raw_query: str, preset: SimPreset, sim_count: int) -> ForecastQuery:
        """Parse using GPT-4o Structured Outputs."""
        try:
            parsed: ParsedForecastQuery = self._llm.parse_structured(
                system_prompt=PARSE_QUERY_SYSTEM_PROMPT,
                user_message=raw_query,
                response_format=ParsedForecastQuery,
                temperature=constants.LLM_PARSE_TEMPERATURE,
                max_tokens=constants.LLM_PARSE_MAX_TOKENS,
                timeout=constants.LLM_PARSE_TIMEOUT,
            )

            # Map the OpenAI schema to our domain model
            return ForecastQuery(
                raw_query=raw_query,
                instrument=parsed.instrument or constants.DEFAULT_INSTRUMENT,
                query_type=QueryType(parsed.query_type.value),
                target_time=parsed.target_time,
                forecast_horizon_minutes=(
                    parsed.forecast_horizon_minutes or constants.DEFAULT_HORIZON_MINUTES
                ),
                target_price=parsed.target_price,
                direction_bias=parsed.direction_bias,
                additional_context=parsed.additional_context,
                mentions_event=parsed.mentions_event,
                sim_preset=preset,
                sim_count=sim_count,
                parsed_at=datetime.utcnow(),
                parse_method="llm",
            )
        except Exception:
            logger.error("LLM parse failed, using defaults", exc_info=True)
            # Graceful degradation: return a basic query with defaults
            return ForecastQuery(
                raw_query=raw_query,
                instrument=constants.DEFAULT_INSTRUMENT,
                query_type=QueryType.RANGE_FORECAST,
                forecast_horizon_minutes=constants.DEFAULT_HORIZON_MINUTES,
                sim_preset=preset,
                sim_count=sim_count,
                parsed_at=datetime.utcnow(),
                parse_method="fallback",
            )
