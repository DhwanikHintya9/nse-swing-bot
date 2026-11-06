#!/usr/bin/env python3
"""Validate the independent Stage 4C security and membership ledgers.

This validates ledger structure, temporal consistency, source attribution fields,
and cross-ledger references. It does not independently authenticate source
documents or grant research readiness.
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

IDENTIFIER_FIELDS = [
    "security_id",
    "issuer_id",
    "identifier_type",
    "identifier_value",
    "series",
    "valid_from",
    "valid_to",
    "source_url",
    "source_sha256",
    "identity_status",
    "notes",
]
IDENTITY_EVENT_FIELDS = [
    "identity_event_id",
    "event_type",
    "effective_date",
    "predecessor_security_id",
    "successor_security_id",
    "relationship",
    "old_isin",
    "new_isin",
    "old_symbol",
    "new_symbol",
    "ratio",
    "source_url",
    "source_sha256",
    "notes",
]
MEMBERSHIP_EVENT_FIELDS = [
    "event_id",
    "index_name",
    "issuer_id",
    "security_id",
    "isin_at_event",
    "symbol_at_event",
    "series",
    "action",
    "announcement_date",
    "published_at_utc",
    "effective_date",
    "event_status",
    "supersedes_event_id",
    "notice_url",
    "notice_section",
    "source_sha256",
    "notes",
]
IDENTIFIER_TYPES = {"ISIN", "NSE_SYMBOL"}
RELATIONSHIPS = {
    "continues_as",
    "split_into",
    "merged_into",
    "spun_off_as",
    "demerged_into",
}
MEMBERSHIP_ACTIONS = {"addition", "removal", "correction", "revocation"}
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
OFFICIAL_NOTICE_HOSTS = {"niftyindices.com", "nseindia.com", "nseindia.co.in"}


class LedgerValidationError(ValueError):
    """Raised when a Stage 4C ledger violates its documented contract."""


def _read_rows(path: Path, expected_fields: list[str]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != expected_fields:
                raise LedgerValidationError(
                    f"{path} header must exactly match the Stage 4C schema; "
                    f"expected {expected_fields}, got {reader.fieldnames}"
                )
            rows: list[dict[str, str]] = []
            for line_number, raw_row in enumerate(reader, start=2):
                if None in raw_row:
                    raise LedgerValidationError(
                        f"{path} line {line_number} has more columns than its header"
                    )
                row = {
                    key: (value or "").strip()
                    for key, value in raw_row.items()
                }
                if not any(row.values()):
                    continue
                rows.append(row)
            return rows
    except OSError as error:
        raise LedgerValidationError(f"cannot read {path}: {error}") from error


def _required(row: dict[str, str], field: str, context: str) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise LedgerValidationError(f"{context}: {field} is required")
    return value


def _iso_date(value: str, field: str, context: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise LedgerValidationError(
            f"{context}: {field} must be YYYY-MM-DD, got {value!r}"
        ) from error
    if parsed.isoformat() != value:
        raise LedgerValidationError(
            f"{context}: {field} must use canonical YYYY-MM-DD format"
        )
    return parsed


def _iso_timestamp(value: str, field: str, context: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise LedgerValidationError(
            f"{context}: {field} must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LedgerValidationError(
            f"{context}: {field} must include a UTC offset or Z"
        )
    if parsed.utcoffset() != timedelta(0):
        raise LedgerValidationError(f"{context}: {field} must be UTC")
    return parsed


def _source(
    row: dict[str, str],
    url_field: str,
    hash_field: str,
    context: str,
    *,
    official_notice: bool = False,
) -> None:
    url = _required(row, url_field, context)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise LedgerValidationError(f"{context}: {url_field} must be an HTTPS URL")
    if official_notice:
        host = parsed.hostname.lower().rstrip(".")
        if not any(
            host == domain or host.endswith("." + domain)
            for domain in OFFICIAL_NOTICE_HOSTS
        ):
            raise LedgerValidationError(
                f"{context}: {url_field} must use an official NSE/Nifty Indices host"
            )
    digest = _required(row, hash_field, context)
    if not SHA256_PATTERN.fullmatch(digest):
        raise LedgerValidationError(
            f"{context}: {hash_field} must be a 64-character SHA-256 hex digest"
        )


def _active_on(row: dict[str, str], when: date) -> bool:
    start = date.fromisoformat(row["valid_from"])
    end = date.fromisoformat(row["valid_to"]) if row["valid_to"] else None
    return start <= when and (end is None or when < end)


def _overlap(
    first_start: date,
    first_end: date | None,
    second_start: date,
    second_end: date | None,
) -> bool:
    first_upper = first_end or date.max
    second_upper = second_end or date.max
    return max(first_start, second_start) < min(first_upper, second_upper)


def validate_ledgers(
    identifiers_path: Path,
    identity_events_path: Path,
    membership_events_path: Path,
) -> dict[str, int]:
    """Validate all three Stage 4C CSV ledgers and their cross-references."""
    identifiers = _read_rows(identifiers_path, IDENTIFIER_FIELDS)
    identity_events = _read_rows(identity_events_path, IDENTITY_EVENT_FIELDS)
    membership_events = _read_rows(membership_events_path, MEMBERSHIP_EVENT_FIELDS)

    security_issuers: dict[str, str] = {}
    identifier_assignments: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for index, row in enumerate(identifiers, start=2):
        context = f"{identifiers_path} line {index}"
        security_id = _required(row, "security_id", context)
        issuer_id = _required(row, "issuer_id", context)
        identifier_type = _required(row, "identifier_type", context).upper()
        identifier_value = _required(row, "identifier_value", context)
        series = _required(row, "series", context).upper()
        status = _required(row, "identity_status", context)
        if identifier_type not in IDENTIFIER_TYPES:
            raise LedgerValidationError(
                f"{context}: unsupported identifier_type {identifier_type!r}"
            )
        if identifier_value != identifier_value.upper() or any(
            character.isspace() for character in identifier_value
        ):
            raise LedgerValidationError(
                f"{context}: identifier_value must be uppercase without whitespace"
            )
        if series != row["series"]:
            raise LedgerValidationError(f"{context}: series must be uppercase")
        start = _iso_date(_required(row, "valid_from", context), "valid_from", context)
        end_value = row["valid_to"]
        end = _iso_date(end_value, "valid_to", context) if end_value else None
        if end is not None and end <= start:
            raise LedgerValidationError(
                f"{context}: valid_to must be later than valid_from (half-open interval)"
            )
        _source(row, "source_url", "source_sha256", context)

        previous_issuer = security_issuers.setdefault(security_id, issuer_id)
        if previous_issuer != issuer_id:
            raise LedgerValidationError(
                f"{context}: security_id {security_id!r} maps to multiple issuer_ids"
            )
        # ISINs identify an instrument independently of series. NSE symbols may
        # legitimately differ by series, so series is part of that lookup key.
        series_key = series if identifier_type == "NSE_SYMBOL" else ""
        key = (identifier_type, identifier_value, series_key)
        assignment = {
            **row,
            "identifier_type": identifier_type,
            "series": series,
            "_start": start.isoformat(),
            "_end": end.isoformat() if end else "",
            "_security_id": security_id,
        }
        for prior in identifier_assignments.setdefault(key, []):
            prior_start = date.fromisoformat(prior["_start"])
            prior_end = date.fromisoformat(prior["_end"]) if prior["_end"] else None
            if _overlap(start, end, prior_start, prior_end):
                raise LedgerValidationError(
                    f"{context}: overlapping validity for {identifier_type} "
                    f"{identifier_value!r} (existing security_id "
                    f"{prior['_security_id']!r}, new {security_id!r})"
                )
        identifier_assignments[key].append(assignment)

    identity_event_ids: set[str] = set()
    for index, row in enumerate(identity_events, start=2):
        context = f"{identity_events_path} line {index}"
        event_id = _required(row, "identity_event_id", context)
        if event_id in identity_event_ids:
            raise LedgerValidationError(f"{context}: duplicate identity_event_id {event_id!r}")
        identity_event_ids.add(event_id)
        _required(row, "event_type", context)
        _iso_date(_required(row, "effective_date", context), "effective_date", context)
        predecessor = _required(row, "predecessor_security_id", context)
        successor = _required(row, "successor_security_id", context)
        relationship = _required(row, "relationship", context).lower()
        if relationship not in RELATIONSHIPS:
            raise LedgerValidationError(
                f"{context}: unsupported relationship {relationship!r}"
            )
        if predecessor not in security_issuers:
            raise LedgerValidationError(
                f"{context}: unknown predecessor_security_id {predecessor!r}"
            )
        if successor not in security_issuers:
            raise LedgerValidationError(
                f"{context}: unknown successor_security_id {successor!r}"
            )
        if predecessor == successor and relationship != "continues_as":
            raise LedgerValidationError(
                f"{context}: self-referencing identity event must use continues_as"
            )
        if predecessor != successor and relationship == "continues_as":
            raise LedgerValidationError(
                f"{context}: continues_as must retain the same internal security_id"
            )
        _source(row, "source_url", "source_sha256", context)

    membership_event_ids: dict[str, dict[str, str]] = {}
    for index, row in enumerate(membership_events, start=2):
        context = f"{membership_events_path} line {index}"
        event_id = _required(row, "event_id", context)
        if event_id in membership_event_ids:
            raise LedgerValidationError(f"{context}: duplicate event_id {event_id!r}")
        membership_event_ids[event_id] = row
        index_name = _required(row, "index_name", context)
        if index_name.casefold() != "nifty 500":
            raise LedgerValidationError(
                f"{context}: index_name must identify NIFTY 500, got {index_name!r}"
            )
        issuer_id = _required(row, "issuer_id", context)
        security_id = _required(row, "security_id", context)
        if security_id not in security_issuers:
            raise LedgerValidationError(
                f"{context}: unknown security_id {security_id!r}"
            )
        if security_issuers[security_id] != issuer_id:
            raise LedgerValidationError(
                f"{context}: issuer_id does not match security identifier ledger"
            )
        isin = _required(row, "isin_at_event", context).upper()
        symbol = _required(row, "symbol_at_event", context).upper()
        series = _required(row, "series", context).upper()
        action = _required(row, "action", context).lower()
        if action not in MEMBERSHIP_ACTIONS:
            raise LedgerValidationError(f"{context}: unsupported action {action!r}")
        _iso_date(
            _required(row, "announcement_date", context), "announcement_date", context
        )
        _iso_timestamp(
            _required(row, "published_at_utc", context), "published_at_utc", context
        )
        effective = _iso_date(
            _required(row, "effective_date", context), "effective_date", context
        )
        _required(row, "event_status", context)
        supersedes = row["supersedes_event_id"]
        if action in {"correction", "revocation"} and not supersedes:
            raise LedgerValidationError(
                f"{context}: {action} must reference supersedes_event_id"
            )
        if supersedes == event_id:
            raise LedgerValidationError(f"{context}: event cannot supersede itself")
        section = _required(row, "notice_section", context)
        if "nifty 500" not in section.casefold():
            raise LedgerValidationError(
                f"{context}: notice_section must explicitly identify the Nifty 500 section"
            )
        _source(
            row,
            "notice_url",
            "source_sha256",
            context,
            official_notice=True,
        )

        for identifier_type, identifier_value in (("ISIN", isin), ("NSE_SYMBOL", symbol)):
            key_series = series if identifier_type == "NSE_SYMBOL" else ""
            candidates = identifier_assignments.get(
                (identifier_type, identifier_value, key_series), []
            )
            if not any(
                candidate["security_id"] == security_id
                and candidate["issuer_id"] == issuer_id
                and candidate["series"] == series
                and _active_on(candidate, effective)
                for candidate in candidates
            ):
                raise LedgerValidationError(
                    f"{context}: {identifier_type} {identifier_value!r} is not mapped "
                    f"to security_id {security_id!r} on {effective.isoformat()}"
                )

    for index, row in enumerate(membership_events, start=2):
        context = f"{membership_events_path} line {index}"
        supersedes = row["supersedes_event_id"]
        if not supersedes:
            continue
        target = membership_event_ids.get(supersedes)
        if target is None:
            raise LedgerValidationError(
                f"{context}: supersedes_event_id {supersedes!r} does not exist"
            )
        if target["index_name"].casefold() != row["index_name"].casefold():
            raise LedgerValidationError(
                f"{context}: superseded event belongs to a different index"
            )

    return {
        "security_identifiers": len(identifiers),
        "security_identity_events": len(identity_events),
        "official_membership_events": len(membership_events),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    base = root / "data/universe/membership_reconciliation"
    parser = argparse.ArgumentParser(
        description="Validate Stage 4C security identity and membership event ledgers."
    )
    parser.add_argument("--identifiers", type=Path, default=base / "security-identifiers.csv")
    parser.add_argument(
        "--identity-events", type=Path, default=base / "security-identity-events.csv"
    )
    parser.add_argument(
        "--membership-events", type=Path, default=base / "official-membership-events.csv"
    )
    args = parser.parse_args()
    try:
        counts = validate_ledgers(
            args.identifiers, args.identity_events, args.membership_events
        )
    except (OSError, LedgerValidationError) as error:
        parser.error(str(error))
    print("Stage 4C ledger validation: PASSED")
    for name, count in counts.items():
        print(f"{name}: {count}")
    print("Source authenticity independently reviewed: NO")
    print("Research ready: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
