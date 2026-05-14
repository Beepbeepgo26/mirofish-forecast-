"""Embedding and indexing functions for the Brooks corpus vector store.

Generates text-embedding-3-small vectors via OpenAI and upserts them
into Upstash Vector with structured metadata for retrieval.
"""

import logging
import time

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from upstash_vector import Index

from mirofish_forecast.models.brooks import BrooksEnrichedPage

logger = logging.getLogger(__name__)

# OpenAI embedding model
_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIM = 1536
_MAX_CHARS = 30_000  # ~7500 tokens, well under 8191 token limit

# GCS bucket for chart JPGs
_GCS_BUCKET = "total-now-339022-mirofish-results"
_GCS_PREFIX = "brooks-charts"


def build_embedding_text(page: BrooksEnrichedPage) -> str:
    """Build the text to embed for a Brooks page.

    Structured fields appear first to dominate the embedding's semantic
    signal. The full analysis text follows for context.

    Args:
        page: Enriched Brooks page record.

    Returns:
        Formatted text string for embedding.
    """
    concepts = ", ".join(page.brooks_concepts)
    header = (
        f"Pattern: {page.pattern_type}\n"
        f"Direction: {page.direction}\n"
        f"Outcome: {page.outcome}\n"
        f"Probability: {page.probability}\n"
        f"Day Type: {page.day_type}\n"
        f"Always-In: {page.always_in_direction}\n"
        f"Brooks Concepts: {concepts}\n"
    )
    body = f"\nAnalysis:\n{page.analysis_text}"

    full = header + body
    if len(full) > _MAX_CHARS:
        # Truncate analysis_text only, preserve structured fields
        allowed = _MAX_CHARS - len(header) - len("\nAnalysis:\n")
        body = f"\nAnalysis:\n{page.analysis_text[:allowed]}"
        full = header + body
        logger.debug(f"Page {page.page_number}: truncated to {len(full)} chars")

    return full


def embed_text(
    client: OpenAI,
    text: str,
    max_retries: int = 3,
) -> list[float]:
    """Generate an embedding vector for the given text.

    Args:
        client: OpenAI client instance.
        text: Text to embed.
        max_retries: Max retries on transient errors.

    Returns:
        1536-dim embedding vector.

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = client.embeddings.create(
                model=_EMBEDDING_MODEL,
                input=text,
            )
            return response.data[0].embedding
        except RateLimitError:
            wait = 2**attempt
            logger.warning(f"Rate limited, retrying in {wait}s (attempt {attempt})")
            time.sleep(wait)
        except (APIConnectionError, APITimeoutError) as e:
            wait = 2**attempt
            logger.warning(f"API error: {e}, retrying in {wait}s (attempt {attempt})")
            time.sleep(wait)

    raise RuntimeError(f"Embedding failed after {max_retries} retries")


def index_page(
    vector_client: Index,
    page: BrooksEnrichedPage,
    embedding: list[float],
) -> None:
    """Upsert a single page's embedding into the Upstash Vector index.

    Args:
        vector_client: Upstash Vector Index client.
        page: Enriched Brooks page record.
        embedding: 1536-dim embedding vector.
    """
    vector_id = f"page_{page.page_number:04d}"
    gcs_url = f"gs://{_GCS_BUCKET}/{_GCS_PREFIX}/page_{page.page_number:04d}.jpg"

    metadata = {
        "page_number": page.page_number,
        "pattern_type": page.pattern_type,
        "direction": page.direction,
        "outcome": page.outcome,
        "probability": page.probability,
        "always_in_direction": page.always_in_direction,
        "day_type": page.day_type,
        "brooks_concepts": page.brooks_concepts,
        "gcs_jpg_url": gcs_url,
        "source_jpg": page.source_jpg,
    }

    vector_client.upsert(
        vectors=[
            {
                "id": vector_id,
                "vector": embedding,
                "metadata": metadata,
            }
        ]
    )
