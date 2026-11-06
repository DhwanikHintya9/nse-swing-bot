"""Point-in-time event intelligence projection for research and signal context.

Evidence admission and assessed market impact are deliberately separate.
This module does not change entry rules, assign automatic sentiment, or place
orders. Only events with a successful upstream evidence-admission result can
appear in production-facing features.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from nse_swing_bot.events.evidence import (
    EventDirection,
    EventTaxonomy,
    EvidenceAdmissionResult,
)


class EventMateriality(StrEnum):
    """Human-assessed potential business/financial magnitude, not evidence quality."""

    UNASSESSED = "unassessed"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class EventImpactAssessment:
    """Optional reviewed interpretation kept independent from source confidence."""

    direction: EventDirection
    materiality: EventMateriality
    assessed_at: datetime
    rationale: str

    def __post_init__(self) -> None:
        _require_aware(self.assessed_at, "assessed_at")
        if not self.rationale.strip():
            raise ValueError("impact assessment rationale is required")


@dataclass(frozen=True)
class EventIntelligenceRecord:
    """Normalized event with explicit point-in-time availability."""

    event_id: str
    symbol: str
    event_class: EventTaxonomy
    event_subclass: str
    announced_at: datetime
    effective_at: datetime | None
    direction: EventDirection
    impact_assessment: EventImpactAssessment | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.symbol.strip():
            raise ValueError("event_id and symbol are required")
        if not self.event_subclass.strip():
            raise ValueError("event_subclass is required")
        _require_aware(self.announced_at, "announced_at")
        if self.effective_at is not None:
            _require_aware(self.effective_at, "effective_at")
        if (
            self.impact_assessment is not None
            and self.impact_assessment.assessed_at < self.announced_at
        ):
            raise ValueError("impact assessment cannot predate the announcement")


@dataclass(frozen=True)
class EventFeatureSnapshot:
    """Deterministic, as-of features; no feature uses information learned later."""

    symbol: str
    as_of: datetime
    admitted_event_count: int
    event_count_7d: int
    event_count_30d: int
    days_to_next_effective_event: int | None
    has_high_materiality_event_30d: bool
    positive_event_count_30d: int
    negative_event_count_30d: int
    mixed_event_count_30d: int
    unassessed_impact_count_30d: int
    taxonomy_counts_30d: tuple[tuple[str, int], ...]
    admitted_event_ids: tuple[str, ...]


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def build_event_features(
    symbol: str,
    as_of: datetime,
    records: list[EventIntelligenceRecord],
    admission_results: dict[str, EvidenceAdmissionResult],
) -> EventFeatureSnapshot:
    """Build event features using only admitted records announced by as_of.

    Events announced after as_of are excluded even if present in the input
    dataset. Assessments made after as_of are treated as unassessed.
    Event time windows use calendar days in the as-of timezone.
    """
    _require_aware(as_of, "as_of")
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol is required")

    ids = [record.event_id for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("event intelligence records contain duplicate event IDs")

    admitted: list[EventIntelligenceRecord] = []
    for record in records:
        if record.symbol.strip().upper() != normalized_symbol:
            continue
        if record.announced_at > as_of:
            continue
        result = admission_results.get(record.event_id)
        if result is None or not result.eligible:
            continue
        admitted.append(record)

    cutoff_30d = as_of.date()
    window_30d = [
        record
        for record in admitted
        if 0 <= (cutoff_30d - record.announced_at.astimezone(as_of.tzinfo).date()).days <= 30
    ]
    window_7d = [
        record
        for record in admitted
        if 0 <= (cutoff_30d - record.announced_at.astimezone(as_of.tzinfo).date()).days <= 7
    ]

    positive = negative = mixed = unassessed = 0
    high_materiality = False
    taxonomy_counts: dict[str, int] = {}
    for record in window_30d:
        taxonomy_counts[record.event_class.value] = (
            taxonomy_counts.get(record.event_class.value, 0) + 1
        )
        assessment = record.impact_assessment
        if assessment is None or assessment.assessed_at > as_of:
            unassessed += 1
            continue
        if assessment.direction == EventDirection.POSITIVE:
            positive += 1
        elif assessment.direction == EventDirection.NEGATIVE:
            negative += 1
        elif assessment.direction == EventDirection.MIXED:
            mixed += 1
        if assessment.materiality == EventMateriality.HIGH:
            high_materiality = True

    future_effective_dates = [
        record.effective_at.astimezone(as_of.tzinfo).date()
        for record in admitted
        if record.effective_at is not None
        and record.effective_at.astimezone(as_of.tzinfo).date() >= as_of.date()
    ]
    days_to_next = (
        min((item - as_of.date()).days for item in future_effective_dates)
        if future_effective_dates
        else None
    )

    return EventFeatureSnapshot(
        symbol=normalized_symbol,
        as_of=as_of,
        admitted_event_count=len(admitted),
        event_count_7d=len(window_7d),
        event_count_30d=len(window_30d),
        days_to_next_effective_event=days_to_next,
        has_high_materiality_event_30d=high_materiality,
        positive_event_count_30d=positive,
        negative_event_count_30d=negative,
        mixed_event_count_30d=mixed,
        unassessed_impact_count_30d=unassessed,
        taxonomy_counts_30d=tuple(sorted(taxonomy_counts.items())),
        admitted_event_ids=tuple(sorted(record.event_id for record in admitted)),
    )
