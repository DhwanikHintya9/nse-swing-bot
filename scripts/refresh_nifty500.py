"""Refresh the dated Nifty 500 universe from the official NSE CSV."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from nse_swing_bot.market_data.nse_sources import acquire_and_save_nifty500_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download and archive the official NSE Nifty 500 constituent CSV."
    )
    parser.add_argument(
        "--effective-date",
        type=date.fromisoformat,
        required=True,
        help="Official index membership effective date (YYYY-MM-DD); never inferred",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Root directory; snapshot is written under universe/",
    )
    args = parser.parse_args()

    snapshot = acquire_and_save_nifty500_snapshot(
        root=args.output_dir,
        effective_date=args.effective_date,
    )
    print(f"Saved immutable Nifty 500 snapshot: {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
