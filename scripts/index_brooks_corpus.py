#!/usr/bin/env python3
"""Index the Brooks enriched corpus into Upstash Vector.

Usage:
    python scripts/index_brooks_corpus.py [--input PATH]

Required environment variables:
    MIROFISH_OPENAI_API_KEY   — OpenAI API key
    UPSTASH_VECTOR_REST_URL   — Upstash Vector REST URL
    UPSTASH_VECTOR_REST_TOKEN — Upstash Vector REST token
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openai import OpenAI
from upstash_vector import Index

from mirofish_forecast.brooks.embedder import (
    build_embedding_text,
    embed_text,
    index_page,
)
from mirofish_forecast.models.brooks import BrooksEnrichedPage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_INPUT = Path("data/brooks_corpus_enriched.jsonl")


def get_existing_ids(vector_client: Index) -> set[str]:
    """Fetch existing vector IDs from the index for resumability.

    Args:
        vector_client: Upstash Vector Index client.

    Returns:
        Set of vector IDs already in the index.
    """
    existing: set[str] = set()
    try:
        info = vector_client.info()
        if info.vector_count == 0:
            return existing

        # Use range to scan all existing IDs
        cursor = "0"
        while cursor:
            result = vector_client.range(cursor=cursor, limit=1000)
            for vec in result.vectors:
                existing.add(vec.id)
            cursor = result.next_cursor if result.next_cursor != "" else None
    except Exception as e:
        logger.warning(f"Failed to fetch existing IDs: {e}")

    return existing


def main() -> None:
    """Run the Brooks corpus indexing pipeline."""
    parser = argparse.ArgumentParser(
        description="Index Brooks corpus into Upstash Vector"
    )
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT,
        help="Path to enriched JSONL from Phase 2",
    )
    args = parser.parse_args()

    # Validate environment
    openai_key = os.environ.get("MIROFISH_OPENAI_API_KEY")
    vector_url = os.environ.get("UPSTASH_VECTOR_REST_URL")
    vector_token = os.environ.get("UPSTASH_VECTOR_REST_TOKEN")

    if not openai_key:
        logger.error("MIROFISH_OPENAI_API_KEY not set")
        sys.exit(1)
    if not vector_url or not vector_token:
        logger.error("UPSTASH_VECTOR_REST_URL and UPSTASH_VECTOR_REST_TOKEN required")
        sys.exit(1)

    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    # Load pages
    pages: list[BrooksEnrichedPage] = []
    with open(args.input, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            pages.append(BrooksEnrichedPage(**json.loads(line)))

    logger.info(f"Loaded {len(pages)} enriched pages from {args.input}")

    # Initialize clients
    openai_client = OpenAI(api_key=openai_key)
    vector_client = Index(url=vector_url, token=vector_token)

    # Check existing vectors
    existing = get_existing_ids(vector_client)
    logger.info(f"Existing vectors in index: {len(existing)}")

    # Filter to pages needing indexing
    to_index = [
        p for p in pages
        if f"page_{p.page_number:04d}" not in existing
    ]
    logger.info(f"Pages to index: {len(to_index)}")

    if not to_index:
        logger.info("All pages already indexed — nothing to do")
        return

    # Index
    total_tokens = 0
    indexed = 0
    failed = 0
    start_time = time.time()

    for i, page in enumerate(to_index, 1):
        try:
            text = build_embedding_text(page)
            embedding = embed_text(openai_client, text)
            index_page(vector_client, page, embedding)
            indexed += 1

            # Rough token estimate: ~4 chars per token
            total_tokens += len(text) // 4

        except Exception as e:
            logger.error(f"Page {page.page_number}: failed: {e}")
            failed += 1

        if i % 100 == 0 or i == len(to_index):
            elapsed = time.time() - start_time
            rate = indexed / elapsed * 3600 if elapsed > 0 else 0
            logger.info(
                f"Progress: {i}/{len(to_index)} ({100 * i / len(to_index):.1f}%) | "
                f"{indexed} indexed, {failed} failed | "
                f"{rate:.0f} pages/hr"
            )

    elapsed = time.time() - start_time

    # Cost estimate: text-embedding-3-small = $0.02 / 1M tokens
    cost = total_tokens * 0.02 / 1_000_000
    logger.info(
        f"\nIndexing complete:\n"
        f"  Indexed: {indexed}\n"
        f"  Failed: {failed}\n"
        f"  Wall time: {elapsed / 60:.1f} min\n"
        f"  Est. tokens: {total_tokens:,}\n"
        f"  Est. cost: ${cost:.2f}"
    )


if __name__ == "__main__":
    main()
