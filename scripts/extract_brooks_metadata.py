#!/usr/bin/env python3
"""Extract structured metadata from Brooks corpus using Gemini 2.5 Flash.

Usage:
    python scripts/extract_brooks_metadata.py [--input PATH] [--output PATH] [--limit N]

Full background run:
    nohup python scripts/extract_brooks_metadata.py > brooks_extract.log 2>&1 &

Defaults:
    --input   data/brooks_corpus_parsed.jsonl
    --output  data/brooks_corpus_enriched.jsonl
    --limit   0 (no limit — process all pages)
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add src to path for standalone script usage
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mirofish_forecast.brooks.extractor import (
    configure_client,
    extract_batch,
    load_already_done,
)
from mirofish_forecast.models.brooks import BrooksPage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_INPUT = Path("data/brooks_corpus_parsed.jsonl")
DEFAULT_OUTPUT = Path("data/brooks_corpus_enriched.jsonl")


def main() -> None:
    """Run the Gemini extraction pipeline."""
    parser = argparse.ArgumentParser(
        description="Extract structured metadata from Brooks corpus"
    )
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT,
        help="Path to parsed JSONL from Phase 1",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="Path to enriched JSONL output",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max pages to process (0 = all)",
    )
    args = parser.parse_args()

    # Get API key from environment
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error(
            "GEMINI_API_KEY environment variable not set. "
            "Get a key from https://aistudio.google.com/apikey"
        )
        sys.exit(1)

    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    # Load pages
    pages: list[BrooksPage] = []
    with open(args.input, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            pages.append(BrooksPage(**data))

    logger.info(f"Loaded {len(pages)} pages from {args.input}")

    if args.limit > 0:
        pages = pages[:args.limit]
        logger.info(f"Limited to first {args.limit} pages")

    # Check resumability
    already_done = load_already_done(args.output)
    remaining = len(pages) - len(already_done & {p.page_number for p in pages})
    logger.info(f"Remaining to extract: {remaining}")

    if remaining == 0:
        logger.info("All pages already extracted — nothing to do")
        return

    # Estimate time
    est_minutes = remaining * 4.1 / 60
    est_hours = est_minutes / 60
    logger.info(
        f"Estimated time: {est_minutes:.0f} min ({est_hours:.1f} hours) "
        f"at ~14.6 req/min"
    )

    # Configure Gemini
    model = configure_client(api_key)

    # Run extraction
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = extract_batch(
        model=model,
        pages=pages,
        output_path=args.output,
        already_done=already_done,
    )

    logger.info(f"Extraction complete: {len(results)} new pages extracted")
    logger.info(f"Total in output: {len(already_done) + len(results)}")


if __name__ == "__main__":
    main()
