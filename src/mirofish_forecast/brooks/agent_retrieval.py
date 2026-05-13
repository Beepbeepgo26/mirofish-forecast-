"""Per-agent retrieval orchestration for Brooks RAG integration.

Handles agent-specific filters, diversity capping, timeout, and graceful
fallback. Returns (analogs, telemetry) — never raises.
"""

import asyncio
import logging
import time
from typing import Literal

from openai import OpenAI
from upstash_vector import Index

from mirofish_forecast.brooks.retriever import embed_query_context, retrieve_analogs
from mirofish_forecast.models.brooks import BrooksAnalog

logger = logging.getLogger(__name__)

# Agent-specific Upstash Vector filter expressions (validated in Stage 5A)
AGENT_FILTERS: dict[str, str] = {
    "institutional_flow": (
        "outcome = 'success' AND day_type IN ('trend', 'channel')"
    ),
    "market_maker": (
        "day_type IN ('TR', 'mixed') OR pattern_type GLOB '*fade*' "
        "OR pattern_type GLOB '*reversal*' OR pattern_type GLOB '*trap*'"
    ),
    "retail_contrarian": (
        "outcome IN ('trap', 'failure') OR pattern_type GLOB '*failed*' "
        "OR pattern_type GLOB '*trap*'"
    ),
}

# Map simulation agent_type names to RAG filter keys
_AGENT_TYPE_TO_FILTER_KEY: dict[str, str] = {
    "institutional": "institutional_flow",
    "market_maker": "market_maker",
    "retail": "retail_contrarian",
}


def _apply_diversity_cap(
    candidates: list[BrooksAnalog],
    top_k: int,
    max_per_pattern: int,
) -> list[BrooksAnalog]:
    """Select diverse analogs from ranked candidates.

    Walks candidates in rank order, including each only if its pattern_type
    count in the result set is below max_per_pattern. Stops at top_k.

    Args:
        candidates: Ranked list of analogs (highest similarity first).
        top_k: Maximum number of results to return.
        max_per_pattern: Maximum occurrences of any single pattern_type.

    Returns:
        Diverse subset of candidates.
    """
    result: list[BrooksAnalog] = []
    pattern_counts: dict[str, int] = {}

    for candidate in candidates:
        if len(result) >= top_k:
            break
        count = pattern_counts.get(candidate.pattern_type, 0)
        if count < max_per_pattern:
            result.append(candidate)
            pattern_counts[candidate.pattern_type] = count + 1

    return result


async def retrieve_agent_analogs(
    agent_role: str,
    query_context: str,
    vector_client: Index,
    openai_client: OpenAI,
    *,
    top_k: int = 5,
    max_per_pattern_type: int = 2,
    timeout_seconds: float = 5.0,
    precomputed_embedding: list[float] | None = None,
) -> tuple[list[BrooksAnalog], dict[str, object]]:
    """Retrieve Brooks analogs filtered for a specific agent role.

    Args:
        agent_role: One of "institutional", "market_maker", "retail".
        query_context: Structured text describing current market state.
        vector_client: Upstash Vector Index client.
        openai_client: OpenAI client for embedding.
        top_k: Number of analogs to return.
        max_per_pattern_type: Diversity cap per pattern_type.
        timeout_seconds: Total retrieval timeout.
        precomputed_embedding: If provided, skip the embedding call.

    Returns:
        Tuple of (analogs, telemetry_dict). Never raises.
    """
    filter_key = _AGENT_TYPE_TO_FILTER_KEY.get(agent_role, agent_role)
    filter_expr = AGENT_FILTERS.get(filter_key, "")
    start = time.monotonic()

    telemetry: dict[str, object] = {
        "agent_role": agent_role,
        "analogs_retrieved": 0,
        "fallback_reason": None,
        "retrieval_latency_ms": 0.0,
        "filter_used": filter_expr,
        "pattern_types_returned": [],
    }

    try:
        result = await asyncio.wait_for(
            _do_retrieval(
                query_context=query_context,
                vector_client=vector_client,
                openai_client=openai_client,
                filter_expr=filter_expr,
                top_k=top_k,
                max_per_pattern=max_per_pattern_type,
                precomputed_embedding=precomputed_embedding,
            ),
            timeout=timeout_seconds,
        )

        elapsed_ms = (time.monotonic() - start) * 1000
        telemetry["retrieval_latency_ms"] = round(elapsed_ms, 1)
        telemetry["analogs_retrieved"] = len(result)
        telemetry["pattern_types_returned"] = list(
            {a.pattern_type for a in result}
        )
        return result, telemetry

    except asyncio.TimeoutError:
        elapsed_ms = (time.monotonic() - start) * 1000
        telemetry["retrieval_latency_ms"] = round(elapsed_ms, 1)
        telemetry["fallback_reason"] = "upstash_timeout"
        logger.warning(f"Brooks RAG timeout for {agent_role} ({elapsed_ms:.0f}ms)")
        return [], telemetry

    except Exception as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        telemetry["retrieval_latency_ms"] = round(elapsed_ms, 1)
        telemetry["fallback_reason"] = "upstash_error"
        logger.warning(f"Brooks RAG error for {agent_role}: {e}")
        return [], telemetry


async def _do_retrieval(
    query_context: str,
    vector_client: Index,
    openai_client: OpenAI,
    filter_expr: str,
    top_k: int,
    max_per_pattern: int,
    precomputed_embedding: list[float] | None,
) -> list[BrooksAnalog]:
    """Internal async retrieval — runs in executor for sync SDK calls."""
    loop = asyncio.get_event_loop()

    # Embed (or use precomputed)
    if precomputed_embedding is not None:
        embedding = precomputed_embedding
    else:
        embedding = await loop.run_in_executor(
            None, embed_query_context, openai_client, query_context,
        )

    # Query Upstash with filter, over-fetch for diversity cap
    fetch_k = top_k * 4  # Over-fetch to allow diversity filtering

    def _query() -> list[BrooksAnalog]:
        results = vector_client.query(
            vector=embedding,
            top_k=fetch_k,
            include_metadata=True,
            filter=filter_expr,
        )
        # Convert to BrooksAnalog models
        from mirofish_forecast.brooks.retriever import _analysis_cache, _load_analysis_cache
        _load_analysis_cache()

        analogs: list[BrooksAnalog] = []
        for r in results:
            meta = r.metadata or {}
            page_number = meta.get("page_number", 0)
            analogs.append(
                BrooksAnalog(
                    page_number=page_number,
                    pattern_type=meta.get("pattern_type", "unknown"),
                    direction=meta.get("direction", "neutral"),
                    outcome=meta.get("outcome", "unclear"),
                    probability=meta.get("probability", "medium"),
                    always_in_direction=meta.get("always_in_direction", "neutral"),
                    day_type=meta.get("day_type", "mixed"),
                    brooks_concepts=meta.get("brooks_concepts", []),
                    similarity_score=r.score,
                    gcs_jpg_path=meta.get("gcs_jpg_url", ""),
                    analysis_summary=_analysis_cache.get(page_number, ""),
                )
            )
        return analogs

    candidates = await loop.run_in_executor(None, _query)

    # Apply diversity cap
    return _apply_diversity_cap(candidates, top_k, max_per_pattern)
