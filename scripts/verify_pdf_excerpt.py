"""Verify one exact text excerpt against one page of a captured PDF."""
from __future__ import annotations

import argparse
from pathlib import Path

from nse_swing_bot.events.pdf_inspection import write_excerpt_verification


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-manifest", type=Path, required=True)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--excerpt", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = write_excerpt_verification(
        args.capture_manifest, args.output, args.page, args.excerpt
    )
    print(f"excerpt_verification={output}")
    print("match=exact")
    print("evidence_review_status=pending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
