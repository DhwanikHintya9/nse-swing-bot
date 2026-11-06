"""Summarize the NSE announcement review inbox without inferring event coverage.

A symbol with no rows in this export is reported as having no candidates in this
export only. It is never treated as having complete or negative event coverage.
"""
import argparse
from collections import Counter
import csv
from pathlib import Path


REQUIRED_REVIEW_COLUMNS = {"symbol", "review_priority", "review_status"}


def _read_symbols(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        symbol_column = next(
            (
                name
                for name in (reader.fieldnames or [])
                if name.strip().lower() == "symbol"
            ),
            None,
        )
        if symbol_column is None:
            raise ValueError("universe CSV must contain a symbol column")
        symbols = [(row.get(symbol_column) or "").strip().upper() for row in reader]
    if (
        not symbols
        or any(not symbol for symbol in symbols)
        or len(symbols) != len(set(symbols))
    ):
        raise ValueError("universe must contain unique, nonblank symbols")
    return sorted(symbols)


def summarize_review_inbox(universe_path: Path, review_path: Path) -> str:
    symbols = _read_symbols(universe_path)
    universe = set(symbols)
    per_symbol: Counter[str] = Counter()
    priorities: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    total = 0

    with review_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_REVIEW_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "review CSV missing columns: " + ", ".join(sorted(missing))
            )
        for line_number, row in enumerate(reader, start=2):
            symbol = (row.get("symbol") or "").strip().upper()
            if symbol not in universe:
                raise ValueError(
                    f"review CSV row {line_number}: symbol outside universe: {symbol!r}"
                )
            priority = (row.get("review_priority") or "").strip().lower()
            status = (row.get("review_status") or "").strip().lower()
            if priority not in {"high", "medium"}:
                raise ValueError(
                    f"review CSV row {line_number}: invalid review_priority {priority!r}"
                )
            if not status:
                raise ValueError(
                    f"review CSV row {line_number}: review_status is required"
                )
            total += 1
            per_symbol[symbol] += 1
            priorities[priority] += 1
            statuses[status] += 1

    represented = sorted(per_symbol)
    no_candidates = [symbol for symbol in symbols if symbol not in per_symbol]
    lines = [
        "NSE corporate-announcement review inbox summary",
        f"Universe symbols: {len(symbols)}",
        f"Candidate records: {total}",
        f"Symbols represented: {len(represented)}",
        f"Symbols with no candidates in this export: {len(no_candidates)}",
        f"High-priority candidates: {priorities['high']}",
        f"Medium-priority candidates: {priorities['medium']}",
        "Review statuses: "
        + (
            ", ".join(f"{key}={statuses[key]}" for key in sorted(statuses))
            if statuses
            else "none"
        ),
        "",
        "Symbols with no candidates in this export (not proof of no events):",
        ", ".join(no_candidates) if no_candidates else "None",
        "",
        "Candidate counts by symbol:",
    ]
    lines.extend(f"{symbol}: {per_symbol[symbol]}" for symbol in represented)
    lines.append("")
    lines.append(
        "Coverage is not inferred from candidate counts. Every symbol/date range "
        "still requires independently reviewed coverage evidence."
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize an NSE announcement review inbox; never infer event coverage."
        )
    )
    parser.add_argument("--universe", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    print(summarize_review_inbox(args.universe, args.input))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
