"""Ingest one source-attributed Nifty 500 constituent snapshot."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from nse_swing_bot.market_data.membership_evidence import ingest_membership_snapshot


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Validate and hash one Nifty 500 constituent CSV. "
            "Third-party reconstructions are discovery-only and cannot be ingested as anchors."
        )
    )
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--as-of-date", required=True, type=date.fromisoformat)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--evidence-url", required=True)
    parser.add_argument(
        "--source-kind", required=True, choices=["official_snapshot", "wayback_capture"]
    )
    parser.add_argument("--captured-at-utc", required=True)
    parser.add_argument("--published-at-utc")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "data/universe/historical_snapshots",
    )
    parser.add_argument("--min-rows", type=int, default=450)
    parser.add_argument("--max-rows", type=int, default=550)
    args = parser.parse_args()
    csv_path = args.csv if args.csv.is_absolute() else root / args.csv
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    if not csv_path.is_file():
        parser.error(f"snapshot CSV does not exist: {csv_path}")
    if args.min_rows < 1 or args.max_rows < args.min_rows:
        parser.error("--min-rows/--max-rows bounds are invalid")
    try:
        manifest_path = ingest_membership_snapshot(
            csv_path,
            as_of_date=args.as_of_date,
            source_url=args.source_url,
            evidence_url=args.evidence_url,
            source_kind=args.source_kind,
            captured_at_utc=args.captured_at_utc,
            published_at_utc=args.published_at_utc,
            output_dir=output_dir,
            min_rows=args.min_rows,
            max_rows=args.max_rows,
        )
    except (ValueError, FileExistsError) as error:
        parser.error(str(error))
    print(f"Snapshot accepted for evidence storage: {manifest_path}")
    print("Raw CSV retained with SHA-256; normalized ISIN-keyed snapshot written.")
    print("Membership effective date inferred: NO")
    print("Research ready: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
