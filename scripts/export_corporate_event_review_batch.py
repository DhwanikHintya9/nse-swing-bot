"""Export a bounded, auditable batch from the NSE corporate-event review inbox.

This utility only slices pending candidates for human review. It does not
classify events, verify filings, or alter event-coverage state.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

REQUIRED_COLUMNS = {
    "record_id", "symbol", "review_priority", "review_status",
    "broadcast_date_time_raw", "subject", "details", "attachment",
    "source_file", "source_page_url", "event_type", "event_date",
    "announcement_url", "secondary_source_url", "review_notes",
}


def export_review_batch(
    source: Path,
    output: Path,
    priority: str,
    limit: int,
    offset: int,
) -> tuple[int, int]:
    if priority not in {"high", "medium", "all"}:
        raise ValueError("priority must be high, medium, or all")
    if limit < 1 or offset < 0:
        raise ValueError("limit must be positive and offset must be nonnegative")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing batch: {output}")

    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        missing = REQUIRED_COLUMNS - set(fields)
        if missing:
            raise ValueError(
                "review CSV missing columns: " + ", ".join(sorted(missing))
            )
        pending = []
        seen_ids = set()
        for line_number, row in enumerate(reader, start=2):
            record_id = (row.get("record_id") or "").strip()
            if not record_id:
                raise ValueError(f"review CSV row {line_number}: record_id is required")
            if record_id in seen_ids:
                raise ValueError(f"review CSV row {line_number}: duplicate record_id {record_id!r}")
            seen_ids.add(record_id)
            row_priority = (row.get("review_priority") or "").strip().lower()
            if row_priority not in {"high", "medium"}:
                raise ValueError(
                    f"review CSV row {line_number}: invalid review_priority {row_priority!r}"
                )
            status = (row.get("review_status") or "").strip().lower()
            if not status:
                raise ValueError(f"review CSV row {line_number}: review_status is required")
            if status != "pending":
                continue
            if priority == "all" or row_priority == priority:
                pending.append(row)

    selected = pending[offset : offset + limit]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(selected)
    return len(pending), len(selected)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a bounded pending review batch; no event verification is performed."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--priority", choices=("high", "medium", "all"), default="high")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    total, exported = export_review_batch(
        args.input, args.output, args.priority, args.limit, args.offset
    )
    print(f"Pending candidates matching priority: {total}")
    print(f"Candidates exported in this batch: {exported}")
    print(f"Priority: {args.priority}; offset: {args.offset}; limit: {args.limit}")
    print("This batch is an unverified review aid; event coverage remains unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
