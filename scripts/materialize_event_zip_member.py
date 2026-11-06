"""CLI for safely materializing one inventoried ZIP member."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from nse_swing_bot.events.zip_member_capture import materialize_verified_zip_member


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--captured-at", required=True, help="ISO-8601 timestamp with timezone")
    args = parser.parse_args()
    captured_at = datetime.fromisoformat(args.captured_at.replace("Z", "+00:00"))
    manifest = materialize_verified_zip_member(
        args.capture_manifest, args.inventory, args.member, args.output_dir,
        captured_at=captured_at,
    )
    print(f"member_manifest={manifest}")
    print("integrity_verified=true")
    print("evidence_review_status=pending")
    print("source_authenticity=not_established")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
