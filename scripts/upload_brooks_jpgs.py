#!/usr/bin/env python3
"""Upload Brooks Encyclopedia JPGs to GCS.

Reads the page-to-filename mapping from the combined training data,
then uploads each chart page's JPG to GCS with a standardized 4-digit
padded name for consistency.

Usage:
    python scripts/upload_brooks_jpgs.py [--source-dir PATH] [--bucket NAME] [--dry-run]

Background run:
    nohup python scripts/upload_brooks_jpgs.py > brooks_upload.log 2>&1 &
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_SOURCE_DIR = Path(
    "/Users/sam/Desktop/Converting .jpgs to text/encyclopedia_jpgs"
)
DEFAULT_BUCKET = "total-now-339022-mirofish-results"
DEFAULT_GCS_PREFIX = "brooks-charts"
DEFAULT_CORPUS_MD = Path(
    "/Users/sam/Desktop/file/output_pass2/combined_training_data.md"
)
DEFAULT_ENRICHED = Path("data/brooks_corpus_enriched.jsonl")


def build_page_to_source_map(corpus_path: Path) -> dict[int, str]:
    """Parse the combined markdown to extract page -> source JPG filename.

    Args:
        corpus_path: Path to combined_training_data.md.

    Returns:
        Dict mapping page number to source JPG filename
        (e.g. {1: "Encyclopedia_Part 1-16_Pg1.jpg"}).
    """
    text = corpus_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"## Page (\d+) — OCR\s*\n\s*<!-- Source: (Encyclopedia_Part[^|]+\.jpg)"
    )
    mapping: dict[int, str] = {}
    for match in pattern.finditer(text):
        page_num = int(match.group(1))
        filename = match.group(2).strip()
        mapping[page_num] = filename
    return mapping


def get_chart_page_numbers(enriched_path: Path) -> set[int]:
    """Load chart page numbers from the enriched JSONL.

    Args:
        enriched_path: Path to brooks_corpus_enriched.jsonl.

    Returns:
        Set of page numbers that are chart pages.
    """
    pages: set[int] = set()
    with open(enriched_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            pages.add(data["page_number"])
    return pages


def check_gcs_exists(bucket: str, prefix: str) -> set[str]:
    """List existing files in GCS to skip re-uploads.

    Args:
        bucket: GCS bucket name.
        prefix: GCS path prefix.

    Returns:
        Set of existing GCS object basenames.
    """
    gcs_path = f"gs://{bucket}/{prefix}/"
    try:
        result = subprocess.run(
            ["gsutil", "ls", gcs_path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            logger.info(f"GCS prefix {gcs_path} not found or empty, will create")
            return set()
        existing = set()
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                existing.add(line.strip().split("/")[-1])
        return existing
    except Exception as e:
        logger.warning(f"Failed to list GCS: {e}")
        return set()


def upload_file(
    local_path: Path,
    bucket: str,
    prefix: str,
    dest_name: str,
    dry_run: bool = False,
) -> bool:
    """Upload a single file to GCS.

    Args:
        local_path: Local file path.
        bucket: GCS bucket name.
        prefix: GCS path prefix.
        dest_name: Destination filename in GCS.
        dry_run: If True, don't actually upload.

    Returns:
        True if successful.
    """
    gcs_dest = f"gs://{bucket}/{prefix}/{dest_name}"

    if dry_run:
        logger.info(f"[DRY RUN] {local_path} -> {gcs_dest}")
        return True

    try:
        result = subprocess.run(
            [
                "gsutil", "-h", "Cache-Control:private, max-age=3600",
                "cp", str(local_path), gcs_dest,
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"Upload failed for {dest_name}: {result.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"Upload exception for {dest_name}: {e}")
        return False


def main() -> None:
    """Upload Brooks chart JPGs to GCS."""
    parser = argparse.ArgumentParser(
        description="Upload Brooks Encyclopedia JPGs to GCS"
    )
    parser.add_argument(
        "--source-dir", type=Path, default=DEFAULT_SOURCE_DIR,
        help="Directory containing source JPG files",
    )
    parser.add_argument(
        "--bucket", default=DEFAULT_BUCKET,
        help="GCS bucket name",
    )
    parser.add_argument(
        "--prefix", default=DEFAULT_GCS_PREFIX,
        help="GCS path prefix",
    )
    parser.add_argument(
        "--corpus-md", type=Path, default=DEFAULT_CORPUS_MD,
        help="Path to combined_training_data.md for page->filename mapping",
    )
    parser.add_argument(
        "--enriched", type=Path, default=DEFAULT_ENRICHED,
        help="Path to enriched JSONL (for chart page list)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be uploaded without uploading",
    )
    args = parser.parse_args()

    if not args.source_dir.exists():
        logger.error(f"Source directory not found: {args.source_dir}")
        sys.exit(1)

    # Build mapping
    logger.info("Building page -> source JPG mapping...")
    page_to_source = build_page_to_source_map(args.corpus_md)
    logger.info(f"Found {len(page_to_source)} page mappings")

    # Get chart pages only
    chart_pages = get_chart_page_numbers(args.enriched)
    logger.info(f"Chart pages to upload: {len(chart_pages)}")

    # Check existing uploads
    logger.info("Checking existing GCS files...")
    existing = check_gcs_exists(args.bucket, args.prefix)
    logger.info(f"Already in GCS: {len(existing)} files")

    # Upload
    uploaded = 0
    skipped = 0
    failed = 0
    missing = 0
    total_bytes = 0

    sorted_pages = sorted(chart_pages)
    total = len(sorted_pages)

    for i, page_num in enumerate(sorted_pages, 1):
        dest_name = f"page_{page_num:04d}.jpg"

        # Skip if already uploaded
        if dest_name in existing:
            skipped += 1
            continue

        # Find source file
        source_filename = page_to_source.get(page_num)
        if not source_filename:
            logger.warning(f"Page {page_num}: no source mapping found")
            missing += 1
            continue

        local_path = args.source_dir / source_filename
        if not local_path.exists():
            logger.warning(f"Page {page_num}: file not found: {local_path}")
            missing += 1
            continue

        file_size = local_path.stat().st_size
        success = upload_file(
            local_path, args.bucket, args.prefix, dest_name, args.dry_run,
        )

        if success:
            uploaded += 1
            total_bytes += file_size
        else:
            failed += 1

        if uploaded % 100 == 0 and uploaded > 0:
            logger.info(
                f"Progress: {i}/{total} processed | "
                f"{uploaded} uploaded, {skipped} skipped, "
                f"{failed} failed, {missing} missing | "
                f"{total_bytes / 1_000_000:.0f} MB uploaded"
            )

    logger.info(
        f"\nUpload complete:\n"
        f"  Uploaded: {uploaded}\n"
        f"  Skipped (already in GCS): {skipped}\n"
        f"  Failed: {failed}\n"
        f"  Missing source: {missing}\n"
        f"  Total bytes: {total_bytes / 1_000_000_000:.2f} GB"
    )


if __name__ == "__main__":
    main()
