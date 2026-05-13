#!/usr/bin/env python3
"""Test retrieval from the Brooks vector index.

Runs 3 sample queries and prints top-5 results for each to validate
that Phase 4 indexing produced a usable vector store.

Required environment variables:
    MIROFISH_OPENAI_API_KEY   — OpenAI API key
    UPSTASH_VECTOR_REST_URL   — Upstash Vector REST URL
    UPSTASH_VECTOR_REST_TOKEN — Upstash Vector REST token
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openai import OpenAI
from upstash_vector import Index

from mirofish_forecast.brooks.retriever import embed_query_context, retrieve_analogs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Test queries
QUERIES = [
    {
        "name": "Bull trend with pullback",
        "text": (
            "Pattern: bull_flag\n"
            "Direction: long\n"
            "Outcome: success\n"
            "Day Type: trend\n"
            "Always-In: AIL\n"
            "Brooks Concepts: AIL, EMA, PB, H1, H2, BO\n\n"
            "Analysis:\n"
            "Strong bull trend with consistent higher highs and higher lows. "
            "Price is trading above the EMA. After a brief pullback to the EMA, "
            "a strong bull bar closes near its high, signaling a high-probability "
            "long entry."
        ),
    },
    {
        "name": "Bear breakout from trading range",
        "text": (
            "Pattern: failed_breakout\n"
            "Direction: short\n"
            "Outcome: success\n"
            "Day Type: TR\n"
            "Always-In: transition\n"
            "Brooks Concepts: TR, FBO, AIS, BO, MTR\n\n"
            "Analysis:\n"
            "Market in extended trading range. Bull breakout attempt fails, "
            "with price reversing back into the range. Strong bear bar closes "
            "near low, transitioning Always-In direction to short."
        ),
    },
    {
        "name": "Reversal at climax",
        "text": (
            "Pattern: major_trend_reversal\n"
            "Direction: long\n"
            "Outcome: success\n"
            "Day Type: trend\n"
            "Always-In: transition\n"
            "Brooks Concepts: SX, MTR, MDB, AIS, AIL, MM\n\n"
            "Analysis:\n"
            "After extended bear trend, price reaches sell climax with parabolic "
            "acceleration down. Micro double bottom forms, with strong bull "
            "reversal bar signaling exhaustion. Major trend reversal opportunity."
        ),
    },
]


def main() -> None:
    """Run test retrieval queries."""
    openai_key = os.environ.get("MIROFISH_OPENAI_API_KEY")
    vector_url = os.environ.get("UPSTASH_VECTOR_REST_URL")
    vector_token = os.environ.get("UPSTASH_VECTOR_REST_TOKEN")

    if not all([openai_key, vector_url, vector_token]):
        logger.error(
            "Required env vars: MIROFISH_OPENAI_API_KEY, "
            "UPSTASH_VECTOR_REST_URL, UPSTASH_VECTOR_REST_TOKEN"
        )
        sys.exit(1)

    openai_client = OpenAI(api_key=openai_key)
    vector_client = Index(url=vector_url, token=vector_token)

    for query in QUERIES:
        print(f"\n{'='*70}")
        print(f"Query: {query['name']}")
        print(f"{'='*70}")

        embedding = embed_query_context(openai_client, query["text"])
        analogs = retrieve_analogs(vector_client, embedding, top_k=5)

        if not analogs:
            print("  *** NO RESULTS ***")
            continue

        scores = [a.similarity_score for a in analogs]
        min_score, max_score = min(scores), max(scores)

        for i, analog in enumerate(analogs, 1):
            concepts = ", ".join(analog.brooks_concepts[:6])
            print(
                f"  {i}. Page {analog.page_number:>4} | "
                f"score={analog.similarity_score:.4f} | "
                f"{analog.pattern_type:<25} | "
                f"dir={analog.direction:<7} | "
                f"out={analog.outcome:<7} | "
                f"AI={analog.always_in_direction:<10} | "
                f"[{concepts}]"
            )

        # Quality flags
        if max_score < 0.50:
            print("  ⚠️  WARNING: All scores below 0.50 — possible indexing issue")
        elif min_score > 0.95:
            print("  ⚠️  WARNING: All scores above 0.95 — possible embedding collapse")
        else:
            print(f"  ✅ Score range: {min_score:.4f} – {max_score:.4f}")

    print()


if __name__ == "__main__":
    main()
