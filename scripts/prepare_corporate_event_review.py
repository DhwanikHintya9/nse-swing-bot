"""Prepare a fail-closed corporate-event review queue from acquired source CSVs.

This is a staging tool, NOT an event verifier. It never marks coverage complete
or creates an importable verified-event snapshot.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

COLUMNS = ("symbol", "event_type", "event_date", "announced_at", "title", "source_url")
QUEUE_COLUMNS = (
    "candidate_id", *COLUMNS, "source_file", "review_status",
    "secondary_source_url", "review_notes",
)
EVENT_TYPES = {
    "earnings",
    "ordinary_dividend",
    "material_corporate_action",
    "critical_corporate_action",
}


def _read_universe(path: Path) -> set[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        column = next(
            (
                name
                for name in (reader.fieldnames or [])
                if name.strip().lower() == "symbol"
            ),
            None,
        )
        if column is None:
            raise ValueError("universe CSV must contain a symbol column")
        symbols = [(row.get(column) or "").strip().upper() for row in reader]
    if (
        not symbols
        or any(not value for value in symbols)
        or len(symbols) != len(set(symbols))
    ):
        raise ValueError("universe must contain unique, nonblank symbols")
    return set(symbols)


def build_review_queue(universe: Path, inputs: list[Path], output: Path) -> int:
    if not inputs:
        raise ValueError("at least one candidate input is required")
    symbols = _read_universe(universe)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing review queue: {output}")
    candidates: dict[str, dict[str, str]] = {}
    for path in inputs:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not set(COLUMNS).issubset(reader.fieldnames or []):
                raise ValueError(f"{path}: missing required candidate columns")
            for number, row in enumerate(reader, start=2):
                try:
                    fields = {key: (row[key] or "").strip() for key in COLUMNS}
                    fields["symbol"] = fields["symbol"].upper()
                    if fields["symbol"] not in symbols:
                        raise ValueError("symbol outside universe")
                    if fields["event_type"] not in EVENT_TYPES:
                        raise ValueError("unknown event_type")
                    date.fromisoformat(fields["event_date"])
                    announced = datetime.fromisoformat(
                        fields["announced_at"].replace("Z", "+00:00")
                    )
                    if announced.utcoffset() is None:
                        raise ValueError("announced_at must include timezone")
                    if not fields["title"]:
                        raise ValueError("title is required")
                    parsed = urlparse(fields["source_url"])
                    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                        raise ValueError("source_url must be an absolute HTTP(S) URL")
                except (ValueError, TypeError, KeyError) as error:
                    raise ValueError(f"{path} row {number}: {error}") from error
                canonical = "\x1f".join(fields[key] for key in COLUMNS)
                candidate_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
                if candidate_id not in candidates:
                    candidates[candidate_id] = {
                        "candidate_id": candidate_id, **fields,
                        "source_file": path.name, "review_status": "pending",
                        "secondary_source_url": "", "review_notes": "",
                    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_COLUMNS)
        writer.writeheader()
        writer.writerows(candidates[key] for key in sorted(candidates))
    return len(candidates)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage source announcements for manual review; never verify automatically."
        )
    )
    parser.add_argument("--universe", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path, action="append", dest="inputs")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    count = build_review_queue(args.universe, args.inputs, args.output)
    print(f"Staged {count} unverified event candidates: {args.output}")
    print("All candidates require independent review; coverage remains incomplete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
