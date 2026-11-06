"""Create an incomplete per-symbol event-coverage worksheet from a universe CSV."""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
from pathlib import Path


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("captured-at must include a timezone offset")
    return parsed


def _read_symbols(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        symbol_column = next(
            (
                column
                for column in (reader.fieldnames or [])
                if column.strip().lower() == "symbol"
            ),
            None,
        )
        if symbol_column is None:
            raise ValueError("universe CSV must contain a symbol column")
        symbols = [(row.get(symbol_column) or "").strip().upper() for row in reader]
    if not symbols or any(not symbol for symbol in symbols):
        raise ValueError("universe CSV contains no symbols or blank symbols")
    if len(symbols) != len(set(symbols)):
        raise ValueError("universe CSV contains duplicate symbols")
    return sorted(symbols)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a per-symbol event coverage worksheet; all rows start incomplete."
    )
    parser.add_argument(
        "--universe",
        type=Path,
        required=True,
        help="NSE or normalized universe CSV",
    )
    parser.add_argument("--covered-from", type=date.fromisoformat, required=True)
    parser.add_argument("--covered-through", type=date.fromisoformat, required=True)
    parser.add_argument("--captured-at", type=_aware_datetime, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.covered_from > args.covered_through:
        parser.error("--covered-from must be on or before --covered-through")
    symbols = _read_symbols(args.universe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        parser.error(f"refusing to overwrite existing coverage worksheet: {args.output}")

    with args.output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "symbol", "covered_from", "covered_through", "captured_at",
                "source_primary", "source_secondary", "complete",
            ],
        )
        writer.writeheader()
        for symbol in symbols:
            writer.writerow(
                {
                    "symbol": symbol,
                    "covered_from": args.covered_from.isoformat(),
                    "covered_through": args.covered_through.isoformat(),
                    "captured_at": args.captured_at.isoformat(),
                    "source_primary": "",
                    "source_secondary": "",
                    "complete": "false",
                }
            )

    print(f"Created {len(symbols)} incomplete coverage rows: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
