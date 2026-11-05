"""Point-in-time corporate-event ingestion and conservative entry gating.

Exchange CSV exports are operator-acquired inputs. This module does not scrape
dynamic exchange pages or infer events from price/volume behaviour.
"""
from __future__ import annotations

import json
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
    if urlparse(primary).netloc.lower() == urlparse(secondary).netloc.lower():
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
    required_through = entry_date + timedelta(days=earnings_block_days)
    if coverage is None:
        reasons.append("missing_event_coverage")
    else:
        if coverage.symbol != symbol:
            reasons.append("event_coverage_symbol_mismatch")
        if not coverage.complete:
            reasons.append("event_coverage_incomplete")
        if coverage.captured_at > decision_at:
            reasons.append("event_coverage_not_available_at_decision_time")
        if coverage.covered_from > decision_at.date():
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
        if not entry_date <= event.event_date <= entry_date + timedelta(days=window):
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
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
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
            except (ValueError, TypeError) as error:
                raise ValueError(f"invalid event CSV row {row_number}: {error}") from error
    return events
