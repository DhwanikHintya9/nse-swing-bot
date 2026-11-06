"""Capture and hash an already-downloaded original NSE/issuer source file."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from nse_swing_bot.events.capture import capture_source_bytes


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("captured-at must include a timezone offset")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive local original source bytes immutably and record SHA-256."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--source-record-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--document-type", required=True)
    parser.add_argument("--captured-at", type=_aware_datetime, required=True)
    args = parser.parse_args()

    captured = capture_source_bytes(
        args.input,
        args.archive_dir,
        event_id=args.event_id,
        source_record_id=args.source_record_id,
        source_url=args.source_url,
        document_type=args.document_type,
        captured_at=args.captured_at,
    )
    print(f"Archived: {captured.archive_path}")
    print(f"Manifest: {captured.manifest_path}")
    print(f"Bytes: {captured.byte_length}")
    print(f"SHA-256: {captured.sha256}")
    print("Review status: pending; direct review and fact excerpts are still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
