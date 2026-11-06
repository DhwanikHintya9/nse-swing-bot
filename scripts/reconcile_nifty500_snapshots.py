"""Reconcile adjacent Nifty 500 snapshots without inventing effective dates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nse_swing_bot.market_data.membership_evidence import reconcile_membership_snapshots


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Diff adjacent source-attributed Nifty 500 snapshots by ISIN. "
            "Observed changes are bounded between snapshot dates; "
            "exact effective dates are not inferred."
        )
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=root / "data/universe/historical_snapshots",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "data/universe/membership_reconciliation",
    )
    args = parser.parse_args()
    snapshot_dir = (
        args.snapshot_dir
        if args.snapshot_dir.is_absolute()
        else root / args.snapshot_dir
    )
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    diff_path = output_dir / "observed-membership-changes.csv"
    report_path = output_dir / "reconciliation-report.json"
    try:
        report = reconcile_membership_snapshots(snapshot_dir, diff_path)
    except ValueError as error:
        parser.error(str(error))
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Snapshots reconciled: {report['snapshot_count']}")
    print(f"Observed changes: {report['total_observed_changes']}")
    print(f"Diff CSV: {diff_path}")
    print(f"Report: {report_path}")
    print("Exact effective dates inferred: NO")
    print("Research ready: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
