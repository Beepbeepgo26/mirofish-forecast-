#!/usr/bin/env python3
"""Parse the Brooks Encyclopedia combined training data into JSONL.

Usage:
    python scripts/parse_brooks_corpus.py [--input PATH] [--output PATH]

Defaults:
    --input  /Users/sam/Desktop/file/output_pass2/combined_training_data.md
    --output data/brooks_corpus_parsed.jsonl
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add src to path for standalone script usage
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mirofish_forecast.brooks.parser import parse_corpus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_INPUT = Path("/Users/sam/Desktop/file/output_pass2/combined_training_data.md")
DEFAULT_OUTPUT = Path("data/brooks_corpus_parsed.jsonl")


def main() -> None:
    """Parse the Brooks corpus and write chart pages to JSONL."""
    parser = argparse.ArgumentParser(description="Parse Brooks Encyclopedia corpus")
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT,
        help="Path to combined_training_data.md",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help="Path to output JSONL file",
    )
    args = parser.parse_args()

    if not args.input.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    logger.info(f"Parsing {args.input}...")

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    chart_pages = 0
    title_slides = 0

    with open(args.output, "w", encoding="utf-8") as f:
        for page in parse_corpus(args.input):
            total += 1
            if page.is_chart_page:
                chart_pages += 1
                f.write(json.dumps(page.model_dump(), ensure_ascii=False) + "\n")
            else:
                title_slides += 1

    logger.info(f"Total pages: {total}")
    logger.info(f"Chart pages: {chart_pages}")
    logger.info(f"Filtered title slides: {title_slides}")
    logger.info(f"Wrote: {args.output}")


if __name__ == "__main__":
    main()
