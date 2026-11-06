"""Normalize an NSE corporate-announcement CSV export into a review inbox.

The input is downloaded by an operator from NSE's public filings page. This
adapter preserves the exchange's broadcast timestamp as metadata; it does not
pretend that broadcast time is the event date or infer an event classification.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

NSE_ANNOUNCEMENTS_URL = (
    "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
)
ALIASES = {
    "symbol": {"symbol", "ticker"},
    "company_name": {"company name", "company"},
    "subject": {"subject", "event / subject", "event/subject"},
    "details": {"details", "description"},
    "broadcast_date_time": {"broadcast date/time", "broadcast date time", "broadcast datetime"},
    "attachment": {"attachment", "attachments"},
    "xbrl": {"xbrl"},
    "submission_type": {"type of submission", "submission type"},
}
OUTPUT_FIELDS = (
    "record_id", "symbol", "company_name", "subject", "details",
    "broadcast_date_time_raw", "attachment", "xbrl", "submission_type",
    "source_file", "source_page_url", "review_status", "event_type",
    "event_date", "announcement_url", "secondary_source_url", "review_notes",
    "review_priority", "priority_reason",
)


HIGH_PRIORITY_RULES = {
    "earnings_results": ("financial results", "audited results", "unaudited results", "quarterly results", "annual results"),
    "board_decision": ("outcome of board meeting", "board meeting outcome", "board meeting"),
    "capital_action": ("dividend", "record date", "bonus", "stock split", "sub-division", "rights issue", "buyback", "preferential issue", "qip", "delisting"),
    "transaction": ("acquisition", "merger", "amalgamation", "scheme of arrangement", "demerger", "open offer", "sale of undertaking"),
    "management_change": ("change in management", "appointment", "resignation", "change in director", "cessation of director", "key managerial"),
    "credit_or_distress": ("credit rating", "default", "insolvency", "resolution plan", "downgrade"),
}
MEDIUM_PRIORITY_RULES = {
    "investor_communication": ("analysts/institutional investor", "investor presentation", "investor meet", "earnings call", "conference call"),
    "general_disclosure": ("general updates", "updates", "press release", "shareholders meeting", "monitoring agency report"),
}


def classify_review_priority(subject: str, details: str = "") -> tuple[str, str]:
    """Prioritize human review only; never infer verified event type or coverage."""
    text = f"{subject} {details}".casefold()
    for reason, phrases in HIGH_PRIORITY_RULES.items():
        if any(phrase in text for phrase in phrases):
            return "high", reason
    for reason, phrases in MEDIUM_PRIORITY_RULES.items():
        if any(phrase in text for phrase in phrases):
            return "medium", reason
    return "medium", "unclassified_manual_triage"


def _column_map(fieldnames: list[str] | None) -> dict[str, str]:
    actual = fieldnames or []
    normalized = {name.strip().lower(): name for name in actual}
    result: dict[str, str] = {}
    for target, aliases in ALIASES.items():
        matches = [normalized[name] for name in aliases if name in normalized]
        if matches:
            result[target] = matches[0]
    required = {"symbol", "company_name", "subject", "details", "broadcast_date_time"}
    missing = required - result.keys()
    if missing:
        raise ValueError("NSE export missing columns: " + ", ".join(sorted(missing)))
    return result


def _read_universe(path: Path) -> set[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        symbol_col = next(
            (name for name in (reader.fieldnames or []) if name.strip().lower() == "symbol"),
            None,
        )
        if symbol_col is None:
            raise ValueError("universe CSV must contain a Symbol column")
        symbols = [(row.get(symbol_col) or "").strip().upper() for row in reader]
    if not symbols or any(not symbol for symbol in symbols):
        raise ValueError("universe CSV contains no symbols or blank symbols")
    if len(symbols) != len(set(symbols)):
        raise ValueError("universe CSV contains duplicate symbols")
    return set(symbols)


def normalize_export(
    source: Path,
    universe: Path,
    in_universe_output: Path,
    excluded_output: Path,
) -> tuple[int, int]:
    if in_universe_output.exists() or excluded_output.exists():
        raise FileExistsError("refusing to overwrite an existing NSE review export")
    symbols = _read_universe(universe)
    included: dict[str, dict[str, str]] = {}
    excluded: list[dict[str, str]] = []
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = _column_map(reader.fieldnames)
        for line_number, raw in enumerate(reader, start=2):
            symbol = (raw.get(columns["symbol"]) or "").strip().upper()
            if symbol in {"-", "—", "–"}:
                symbol = ""
            if not symbol:
                excluded.append({
                    "source_file": source.name,
                    "source_row": str(line_number),
                    "reason": "blank_symbol",
                    "raw_symbol": "",
                    "company_name": (raw.get(columns["company_name"]) or "").strip(),
                    "subject": (raw.get(columns["subject"]) or "").strip(),
                })
                continue
            row = {
                "symbol": symbol,
                "company_name": (raw.get(columns["company_name"]) or "").strip(),
                "subject": (raw.get(columns["subject"]) or "").strip(),
                "details": (raw.get(columns["details"]) or "").strip(),
                "broadcast_date_time_raw": (
                    raw.get(columns["broadcast_date_time"]) or ""
                ).strip(),
                "attachment": (raw.get(columns.get("attachment", "")) or "").strip(),
                "xbrl": (raw.get(columns.get("xbrl", "")) or "").strip(),
                "submission_type": (raw.get(columns.get("submission_type", "")) or "").strip(),
            }
            canonical = json.dumps(row, sort_keys=True, ensure_ascii=False)
            record_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
            if symbol not in symbols:
                excluded.append({
                    "source_file": source.name,
                    "source_row": str(line_number),
                    "reason": "symbol_outside_universe",
                    "raw_symbol": symbol,
                    "company_name": row["company_name"],
                    "subject": row["subject"],
                })
                continue
            priority, priority_reason = classify_review_priority(
                row["subject"], row["details"]
            )
            included.setdefault(record_id, {
                "record_id": record_id, **row,
                "source_file": source.name,
                "source_page_url": NSE_ANNOUNCEMENTS_URL,
                "review_status": "pending",
                "event_type": "",
                "event_date": "",
                "announcement_url": "",
                "secondary_source_url": "",
                "review_notes": "",
                "review_priority": priority,
                "priority_reason": priority_reason,
            })

    in_universe_output.parent.mkdir(parents=True, exist_ok=True)
    excluded_output.parent.mkdir(parents=True, exist_ok=True)
    with in_universe_output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(included[key] for key in sorted(included))
    with excluded_output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "source_file", "source_row", "reason", "raw_symbol",
                "company_name", "subject",
            ),
        )
        writer.writeheader()
        writer.writerows(excluded)
    return len(included), len(excluded)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize an operator-downloaded NSE announcements CSV for review."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--universe", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--excluded-output", required=True, type=Path)
    args = parser.parse_args()
    included, excluded = normalize_export(
        args.input, args.universe, args.output, args.excluded_output
    )
    print(f"NSE announcement candidates in universe: {included}")
    print(f"Rows excluded (blank/out-of-universe symbols): {excluded}")
    print("Priority is a review-order hint only; event type/date remain blank and coverage incomplete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
