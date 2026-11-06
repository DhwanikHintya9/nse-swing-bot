"""Research-only, point-in-time event diagnostics aligned to decision timestamps.

This adapter deliberately does not modify or wrap the Phase 1 signal frame.
"""
from __future__ import annotations

from datetime import datetime  # noqa: I001

import pandas as pd

from nse_swing_bot.events.evidence import EvidenceAdmissionResult
from nse_swing_bot.events.intelligence import (
    EventFeatureSnapshot,
    EventIntelligenceRecord,
    build_event_features,
)


DIAGNOSTIC_COLUMNS = (
    "admitted_event_count",
    "event_count_7d",
    "event_count_30d",
    "days_to_next_effective_event",
    "has_high_materiality_event_30d",
    "positive_event_count_30d",
    "negative_event_count_30d",
    "mixed_event_count_30d",
    "unassessed_impact_count_30d",
    "taxonomy_counts_30d",
    "admitted_event_ids",
)


def _snapshot_row(snapshot: EventFeatureSnapshot) -> dict[str, object]:
    return {
        "admitted_event_count": snapshot.admitted_event_count,
        "event_count_7d": snapshot.event_count_7d,
        "event_count_30d": snapshot.event_count_30d,
        "days_to_next_effective_event": snapshot.days_to_next_effective_event,
        "has_high_materiality_event_30d": snapshot.has_high_materiality_event_30d,
        "positive_event_count_30d": snapshot.positive_event_count_30d,
        "negative_event_count_30d": snapshot.negative_event_count_30d,
        "mixed_event_count_30d": snapshot.mixed_event_count_30d,
        "unassessed_impact_count_30d": snapshot.unassessed_impact_count_30d,
        "taxonomy_counts_30d": snapshot.taxonomy_counts_30d,
        "admitted_event_ids": snapshot.admitted_event_ids,
    }


def build_event_diagnostics(
    symbol: str,
    decision_times: list[datetime] | pd.DatetimeIndex,
    records: list[EventIntelligenceRecord],
    admission_results: dict[str, EvidenceAdmissionResult],
) -> pd.DataFrame:
    """Return research-only event features for each timezone-aware decision time.

    The output index exactly matches decision_times. Each row is independently
    reconstructed as-of that timestamp, so later announcements and later
    impact assessments cannot appear in earlier rows. Events without an
    eligible upstream admission result are excluded. No prices or signals are
    read or modified by this function.
    """
    timestamps = pd.DatetimeIndex(decision_times)
    if timestamps.empty:
        raise ValueError("at least one decision timestamp is required")
    if timestamps.tz is None:
        raise ValueError("decision timestamps must be timezone-aware")
    if timestamps.hasnans:
        raise ValueError("decision timestamps cannot contain NaT")
    if not timestamps.is_monotonic_increasing or timestamps.has_duplicates:
        raise ValueError("decision timestamps must be strictly increasing and unique")
    if not symbol.strip():
        raise ValueError("symbol is required")

    rows: list[dict[str, object]] = []
    for timestamp in timestamps:
        snapshot = build_event_features(
            symbol=symbol,
            as_of=timestamp.to_pydatetime(),
            records=records,
            admission_results=admission_results,
        )
        rows.append(_snapshot_row(snapshot))

    result = pd.DataFrame(rows, index=timestamps, columns=DIAGNOSTIC_COLUMNS)
    result.index.name = "decision_at"
    return result
