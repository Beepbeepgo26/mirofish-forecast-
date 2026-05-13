"""Retriever for querying Brooks corpus analogs from Upstash Vector.

Embeds a query context, queries the vector index for top-K similar
pages, and returns BrooksAnalog Pydantic models with analysis summaries
loaded from the local enriched JSONL.
"""

import json
import logging
import re
from pathlib import Path

from openai import OpenAI
from upstash_vector import Index

from mirofish_forecast.brooks.embedder import _EMBEDDING_MODEL
from mirofish_forecast.models.brooks import BrooksAnalog

logger = logging.getLogger(__name__)

# Default path for the enriched JSONL (analysis summary source)
_DEFAULT_ENRICHED_PATH = Path("data/brooks_corpus_enriched.jsonl")

# In-memory cache: page_number -> cleaned first 400 chars of analysis_text
_analysis_cache: dict[int, str] = {}

# Patterns for Gemma boilerplate stripping
_RE_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_RE_HEADER_LINE = re.compile(r"^#{1,3}\s.*$", re.MULTILINE)


def _strip_boilerplate(text: str) -> str:
    """Remove Gemma-generated boilerplate from analysis text.

    Strips HTML comments (``<!-- ... -->``) and leading markdown headers
    (``# ...``, ``## ...``, ``### ...``) so the cached summary starts
    with actual analytical content.

    Args:
        text: Raw analysis_text from enriched JSONL.

    Returns:
        Cleaned text with boilerplate removed and whitespace normalized.
    """
    text = _RE_HTML_COMMENT.sub("", text)
    text = _RE_HEADER_LINE.sub("", text)
    # Collapse leftover blank lines and strip leading/trailing whitespace
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text


def _load_analysis_cache(enriched_path: Path | None = None) -> None:
    """Load analysis summaries from enriched JSONL into memory.

    Called once on first retrieval. Subsequent calls are no-ops.
    Strips Gemma boilerplate headers before truncating to 400 chars.

    Args:
        enriched_path: Path to enriched JSONL file.
    """
    if _analysis_cache:
        return  # already loaded

    path = enriched_path or _DEFAULT_ENRICHED_PATH
    if not path.exists():
        logger.warning(f"Enriched JSONL not found at {path}, summaries unavailable")
        return

    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            page_num = data["page_number"]
            analysis = data.get("analysis_text", "")
            cleaned = _strip_boilerplate(analysis)
            _analysis_cache[page_num] = cleaned[:400]
            count += 1

    logger.info(f"Loaded {count} analysis summaries into cache")


def embed_query_context(client: OpenAI, context_text: str) -> list[float]:
    """Embed a free-form query context for retrieval.

    Args:
        client: OpenAI client instance.
        context_text: Query context string.

    Returns:
        1536-dim embedding vector.
    """
    response = client.embeddings.create(
        model=_EMBEDDING_MODEL,
        input=context_text,
    )
    return response.data[0].embedding


def retrieve_analogs(
    vector_client: Index,
    query_embedding: list[float],
    top_k: int = 5,
    filters: dict[str, str] | None = None,
    enriched_path: Path | None = None,
) -> list[BrooksAnalog]:
    """Query the Brooks vector index for similar historical patterns.

    Args:
        vector_client: Upstash Vector Index client.
        query_embedding: 1536-dim query embedding.
        top_k: Number of results to return.
        filters: Optional metadata filters (unused in Phase 4).
        enriched_path: Path to enriched JSONL for summary lookup.

    Returns:
        List of BrooksAnalog results sorted by similarity (descending).
    """
    _load_analysis_cache(enriched_path)

    # Query Upstash Vector
    results = vector_client.query(
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True,
    )

    analogs: list[BrooksAnalog] = []
    for result in results:
        meta = result.metadata or {}
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
                similarity_score=result.score,
                gcs_jpg_path=meta.get("gcs_jpg_url", ""),
                analysis_summary=_analysis_cache.get(page_number, ""),
            )
        )

    return analogs
