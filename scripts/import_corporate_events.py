"""Import reviewed corporate-event and coverage CSVs into an immutable snapshot."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from nse_swing_bot.market_data.event_calendar import import_reviewed_event_snapshot


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
        description="Validate and persist reviewed corporate-event coverage."
    )
    parser.add_argument("--events", type=Path, required=True, help="Reviewed events CSV")
    parser.add_argument("--coverage", type=Path, required=True, help="Per-symbol coverage CSV")
    parser.add_argument(
        "--universe", type=Path, required=True, help="Universe CSV with a Symbol column (raw NSE or normalized snapshot)"
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="Snapshot output directory")
    parser.add_argument(
        "--captured-at",
        type=_aware_datetime,
        required=True,
        help="Snapshot capture time, ISO-8601 with timezone (for example +05:30)",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Reject the import if any per-symbol coverage row is incomplete",
    )
    args = parser.parse_args()

    snapshot = import_reviewed_event_snapshot(
        events_path=args.events,
        coverage_path=args.coverage,
        universe_path=args.universe,
        output_root=args.output_dir,
        captured_at=args.captured_at,
        require_complete=args.require_complete,
    )
    print(f"Saved immutable event snapshot: {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
