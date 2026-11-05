"""Point-in-time corporate-event ingestion and conservative entry gating.

Exchange CSV exports are operator-acquired inputs. This module does not scrape
dynamic exchange pages or infer events from price/volume behaviour.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4


class EventType(StrEnum):
    EARNINGS = "earnings"
    ORDINARY_DIVIDEND = "ordinary_dividend"
    MATERIAL_CORPORATE_ACTION = "material_corporate_action"
    CRITICAL_CORPORATE_ACTION = "critical_corporate_action"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class ScheduledEvent:
    event_id: str
    symbol: str
    event_type: EventType
    event_date: date
    announced_at: datetime
    title: str
    source_primary: str
    source_secondary: str
    verification_status: VerificationStatus

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.symbol.strip() or not self.title.strip():
            raise ValueError("event_id, symbol, and title are required")
        if self.announced_at.tzinfo is None or self.announced_at.utcoffset() is None:
            raise ValueError("announced_at must be timezone-aware")
        _validate_source(self.source_primary, "source_primary")
        _validate_source(self.source_secondary, "source_secondary")
        _validate_independent_sources(self.source_primary, self.source_secondary)


@dataclass(frozen=True)
class EventCoverage:
    symbol: str
    covered_from: date
    covered_through: date
    captured_at: datetime
    source_primary: str
    source_secondary: str
    complete: bool

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("coverage symbol is required")
        if self.covered_from > self.covered_through:
            raise ValueError("coverage range is inverted")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("coverage captured_at must be timezone-aware")
        _validate_source(self.source_primary, "coverage source_primary")
        _validate_source(self.source_secondary, "coverage source_secondary")
        _validate_independent_sources(self.source_primary, self.source_secondary)


@dataclass(frozen=True)
class EntryGateResult:
    allowed: bool
    reasons: tuple[str, ...]


def _validate_source(value: str, field: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError(f"{field} must be an absolute http(s) source URL")


def _validate_independent_sources(primary: str, secondary: str) -> None:
    primary_host = (urlparse(primary).hostname or "").lower().rstrip(".")
    secondary_host = (urlparse(secondary).hostname or "").lower().rstrip(".")

    def domain_key(host: str) -> str:
        # Conservative registrable-domain approximation for exchange sources.
        # It intentionally treats sibling subdomains as the same source domain.
        labels = host.split(".")
        return ".".join(labels[-2:]) if len(labels) >= 2 else host

    related = (
        primary_host == secondary_host
        or primary_host.endswith("." + secondary_host)
        or secondary_host.endswith("." + primary_host)
        or domain_key(primary_host) == domain_key(secondary_host)
    )
    if related:
        raise ValueError("primary and secondary sources must use independent domains")


def evaluate_event_entry(
    symbol: str,
    decision_at: datetime,
    entry_date: date,
    events: list[ScheduledEvent],
    coverage: EventCoverage | None,
    earnings_block_days: int = 5,
    material_action_block_days: int = 3,
) -> EntryGateResult:
    """Fail closed unless event coverage is complete through the earnings horizon.

    Event visibility is point-in-time: an event is considered only if it was
    announced no later than decision_at. Future announcements cannot leak into
    historical backtests.
    """
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("decision_at must be timezone-aware")
    if not symbol.strip():
        raise ValueError("symbol is required")
    if entry_date < decision_at.date():
        raise ValueError("entry_date cannot precede the decision date")
    if earnings_block_days < 0 or material_action_block_days < 0:
        raise ValueError("event block windows cannot be negative")

    reasons: list[str] = []
    decision_date = decision_at.date()
    required_through = max(entry_date, decision_date) + timedelta(days=earnings_block_days)
    if coverage is None:
        reasons.append("missing_event_coverage")
    else:
        if coverage.symbol != symbol:
            reasons.append("event_coverage_symbol_mismatch")
        if not coverage.complete:
            reasons.append("event_coverage_incomplete")
        if coverage.captured_at > decision_at:
            reasons.append("event_coverage_not_available_at_decision_time")
        if coverage.covered_from > decision_date:
            reasons.append("event_coverage_starts_after_decision_date")
        if coverage.covered_through < required_through:
            reasons.append("event_coverage_does_not_cover_earnings_window")

    visible = [
        event for event in events
        if event.symbol == symbol and event.announced_at <= decision_at
    ]
    for event in visible:
        if event.event_type == EventType.ORDINARY_DIVIDEND:
            continue
        window = (
            earnings_block_days
            if event.event_type == EventType.EARNINGS
            else material_action_block_days
        )
        # Include the decision-to-entry gap: an event between signal creation
        # and the planned entry is still relevant to the trade decision.
        window_start = decision_date
        window_end = max(entry_date, decision_date) + timedelta(days=window)
        if not window_start <= event.event_date <= window_end:
            continue
        if event.verification_status != VerificationStatus.VERIFIED:
            reasons.append(f"event_requires_manual_review:{event.event_id}")
        elif event.event_type == EventType.EARNINGS:
            reasons.append(f"earnings_within_{earnings_block_days}_calendar_days:{event.event_id}")
        elif event.event_type == EventType.CRITICAL_CORPORATE_ACTION:
            reasons.append(f"critical_corporate_action_requires_manual_review:{event.event_id}")
        elif event.event_type == EventType.MATERIAL_CORPORATE_ACTION:
            reasons.append(f"corporate_action_within_{material_action_block_days}_calendar_days:{event.event_id}")

    return EntryGateResult(allowed=not reasons, reasons=tuple(dict.fromkeys(reasons)))


def write_event_snapshot(
    root: Path,
    events: list[ScheduledEvent],
    coverage: list[EventCoverage],
    captured_at: datetime,
) -> Path:
    """Write an immutable, timestamped JSON snapshot with full provenance."""
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    if any(item.captured_at > captured_at for item in coverage):
        raise ValueError("coverage cannot be captured after the snapshot")
    if any(item.announced_at > captured_at for item in events):
        raise ValueError("event announcement cannot be after the snapshot capture")
    event_ids = [item.event_id for item in events]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("event snapshot contains duplicate event IDs")
    coverage_symbols = [item.symbol for item in coverage]
    if len(coverage_symbols) != len(set(coverage_symbols)):
        raise ValueError("event snapshot contains duplicate coverage symbols")
    payload = {
        "schema_version": 1,
        "captured_at": captured_at.isoformat(),
        "events": [
            {
                **asdict(item),
                "event_type": item.event_type.value,
                "event_date": item.event_date.isoformat(),
                "announced_at": item.announced_at.isoformat(),
                "verification_status": item.verification_status.value,
            }
            for item in events
        ],
        "coverage": [
            {
                **asdict(item),
                "covered_from": item.covered_from.isoformat(),
                "covered_through": item.covered_through.isoformat(),
                "captured_at": item.captured_at.isoformat(),
            }
            for item in coverage
        ],
    }
    root.mkdir(parents=True, exist_ok=True)
    timestamp = captured_at.astimezone().strftime("%Y%m%dT%H%M%S%f%z")
    path = root / f"events-{timestamp}-{uuid4().hex[:8]}.json"
    fd, temporary = tempfile.mkstemp(prefix=".events-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link creation is atomic and fails rather than replacing an
        # existing immutable snapshot.
        os.link(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    Path(temporary).unlink(missing_ok=True)
    return path

def load_event_csv(path: Path) -> list[ScheduledEvent]:
    """Load an operator-reviewed NSE/BSE export in the documented normalized schema."""
    import csv

    required = {
        "event_id", "symbol", "event_type", "event_date", "announced_at",
        "title", "source_primary", "source_secondary", "verification_status",
    }
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = required.difference(reader.fieldnames or [])
            raise ValueError(f"event CSV missing columns: {', '.join(sorted(missing))}")
        events: list[ScheduledEvent] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                events.append(
                    ScheduledEvent(
                        event_id=row["event_id"].strip(),
                        symbol=row["symbol"].strip().upper(),
                        event_type=EventType(row["event_type"].strip()),
                        event_date=date.fromisoformat(row["event_date"].strip()),
                        announced_at=datetime.fromisoformat(row["announced_at"].strip()),
                        title=row["title"].strip(),
                        source_primary=row["source_primary"].strip(),
                        source_secondary=row["source_secondary"].strip(),
                        verification_status=VerificationStatus(
                            row["verification_status"].strip()
                        ),
                    )
                )
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError(f"invalid event CSV row {row_number}: {error}") from error
    return events


def load_event_coverage_csv(path: Path) -> list[EventCoverage]:
    """Load per-symbol coverage manifests from an operator-reviewed CSV."""
    import csv

    required = {
        "symbol", "covered_from", "covered_through", "captured_at",
        "source_primary", "source_secondary", "complete",
    }
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = required.difference(reader.fieldnames or [])
            raise ValueError(
                f"event coverage CSV missing columns: {', '.join(sorted(missing))}"
            )
        coverage_rows: list[EventCoverage] = []
        seen_symbols: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            try:
                complete_text = row["complete"].strip().lower()
                if complete_text not in {"true", "false"}:
                    raise ValueError("complete must be true or false")
                item = EventCoverage(
                    symbol=row["symbol"].strip().upper(),
                    covered_from=date.fromisoformat(row["covered_from"].strip()),
                    covered_through=date.fromisoformat(row["covered_through"].strip()),
                    captured_at=datetime.fromisoformat(row["captured_at"].strip()),
                    source_primary=row["source_primary"].strip(),
                    source_secondary=row["source_secondary"].strip(),
                    complete=complete_text == "true",
                )
                if item.symbol in seen_symbols:
                    raise ValueError(f"duplicate coverage symbol: {item.symbol}")
                seen_symbols.add(item.symbol)
                coverage_rows.append(item)
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError(
                    f"invalid event coverage CSV row {row_number}: {error}"
                ) from error
    return coverage_rows


def import_reviewed_event_snapshot(
    events_path: Path,
    coverage_path: Path,
    universe_path: Path,
    output_root: Path,
    captured_at: datetime,
    require_complete: bool = False,
) -> Path:
    """Validate reviewed event/coverage CSVs against a universe and persist a snapshot."""
    import csv

    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    events = load_event_csv(events_path)
    coverage = load_event_coverage_csv(coverage_path)

    with universe_path.open("r", encoding="utf-8-sig", newline="") as handle:
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
        universe_symbols = [
            (row.get(symbol_column) or "").strip().upper()
            for row in reader
        ]
    if not universe_symbols or any(not symbol for symbol in universe_symbols):
        raise ValueError("universe CSV contains no symbols or blank symbols")
    if len(universe_symbols) != len(set(universe_symbols)):
        raise ValueError("universe CSV contains duplicate symbols")

    universe_set = set(universe_symbols)
    coverage_set = {item.symbol for item in coverage}
    missing_coverage = sorted(universe_set - coverage_set)
    unexpected_coverage = sorted(coverage_set - universe_set)
    if missing_coverage:
        raise ValueError(
            "coverage manifest missing universe symbols: " + ", ".join(missing_coverage)
        )
    if unexpected_coverage:
        raise ValueError(
            "coverage manifest contains symbols outside universe: "
            + ", ".join(unexpected_coverage)
        )

    unexpected_events = sorted({item.symbol for item in events} - universe_set)
    if unexpected_events:
        raise ValueError(
            "event CSV contains symbols outside universe: " + ", ".join(unexpected_events)
        )
    incomplete = sorted(item.symbol for item in coverage if not item.complete)
    if require_complete and incomplete:
        raise ValueError(
            "coverage manifest contains incomplete symbols: " + ", ".join(incomplete)
        )
    return write_event_snapshot(output_root, events, coverage, captured_at)
