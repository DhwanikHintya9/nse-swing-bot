"""Create an immutable, read-only Stage 3C migration snapshot."""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from nse_swing_bot.events.stage3c_adapter import (
    migrate_stage3c_files,
    write_stage3c_migration_snapshot,
)


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
        description="Migrate Stage 3C CSVs into an immutable, non-production snapshot."
    )
    parser.add_argument("--triage", type=Path, required=True)
    parser.add_argument("--canonical-events", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--aliases", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--captured-at", type=_aware_datetime, required=True)
    args = parser.parse_args()

    snapshot = migrate_stage3c_files(
        args.triage,
        args.canonical_events,
        args.queue,
        args.aliases,
        args.captured_at,
    )
    output = write_stage3c_migration_snapshot(snapshot, args.output_dir)
    counts = snapshot.to_dict()["counts"]
    print(f"Saved read-only Stage 3C migration snapshot: {output}")
    print(f"Counts: {counts}")
    print("Production eligibility: false; evidence admission: not evaluated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
