"""Inspect a captured PDF without modifying or extracting its contents."""
from __future__ import annotations

import argparse
from pathlib import Path

from nse_swing_bot.events.pdf_inspection import inspect_captured_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-pdf-bytes", type=int, default=250 * 1024 * 1024)
    parser.add_argument("--max-pages", type=int, default=5000)
    parser.add_argument("--max-attachment-bytes", type=int, default=100 * 1024 * 1024)
    args = parser.parse_args()
    output = inspect_captured_pdf(
        args.capture_manifest,
        args.output,
        max_pdf_bytes=args.max_pdf_bytes,
        max_pages=args.max_pages,
        max_attachment_bytes=args.max_attachment_bytes,
    )
    print(f"inspection_manifest={output}")
    print("source_authenticity=not_established")
    print("evidence_review_status=pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
