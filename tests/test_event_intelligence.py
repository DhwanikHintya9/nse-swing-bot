from datetime import datetime, timedelta, UTC

import pytest

from nse_swing_bot.events.evidence import (
    EventDirection,
    EventTaxonomy,
    EvidenceAdmissionResult,
)
from nse_swing_bot.events.intelligence import (
    EventImpactAssessment,
    EventIntelligenceRecord,
    EventMateriality,
    build_event_features,
)


AS_OF = datetime(2026, 11, 6, 10, tzinfo=UTC)


def record(
    event_id: str,
    *,
    announced_at: datetime = AS_OF - timedelta(days=2),
    effective_at: datetime | None = None,
    assessment: EventImpactAssessment | None = None,
) -> EventIntelligenceRecord:
    return EventIntelligenceRecord(
        event_id=event_id,
        symbol="RELIANCE",
        event_class=EventTaxonomy.MANAGEMENT_GOVERNANCE,
        event_subclass="board_appointment",
        announced_at=announced_at,
        effective_at=effective_at,
        direction=EventDirection.UNKNOWN,
        impact_assessment=assessment,
    )


def admitted(*event_ids: str) -> dict[str, EvidenceAdmissionResult]:
    return {
        event_id: EvidenceAdmissionResult(True, (), (f"evidence-{event_id}",))
        for event_id in event_ids
    }


def test_only_admitted_events_announced_by_as_of_are_included() -> None:
    visible = record("visible")
    future = record("future", announced_at=AS_OF + timedelta(minutes=1))
    rejected = record("rejected")
    result = build_event_features(
        "reliance",
        AS_OF,
        [visible, future, rejected],
        {
            **admitted("visible", "future"),
            "rejected": EvidenceAdmissionResult(False, ("not_accepted",), ()),
        },
    )
    assert result.admitted_event_ids == ("visible",)
    assert result.admitted_event_count == 1


def test_market_impact_is_separate_from_admission_and_assessment_time() -> None:
    future_assessment = EventImpactAssessment(
        EventDirection.NEGATIVE,
        EventMateriality.HIGH,
        AS_OF + timedelta(minutes=1),
        "Assessment recorded after decision time",
    )
    current_assessment = EventImpactAssessment(
        EventDirection.POSITIVE,
        EventMateriality.HIGH,
        AS_OF - timedelta(hours=1),
        "Reviewed business impact",
    )
    result = build_event_features(
        "RELIANCE",
        AS_OF,
        [
            record("future-assessment", assessment=future_assessment),
            record("current-assessment", assessment=current_assessment),
        ],
        admitted("future-assessment", "current-assessment"),
    )
    assert result.unassessed_impact_count_30d == 1
    assert result.positive_event_count_30d == 1
    assert result.negative_event_count_30d == 0
    assert result.has_high_materiality_event_30d is True


def test_effective_date_feature_does_not_require_impact_assessment() -> None:
    event = record("scheduled", effective_at=AS_OF + timedelta(days=4))
    result = build_event_features("RELIANCE", AS_OF, [event], admitted("scheduled"))
    assert result.days_to_next_effective_event == 4
    assert result.unassessed_impact_count_30d == 1


def test_symbol_isolation_and_older_than_30_day_window() -> None:
    old = record("old", announced_at=AS_OF - timedelta(days=31))
    other_symbol = EventIntelligenceRecord(
        event_id="other",
        symbol="TCS",
        event_class=EventTaxonomy.FINANCIAL_RESULTS,
        event_subclass="quarterly_results",
        announced_at=AS_OF - timedelta(days=1),
        effective_at=None,
        direction=EventDirection.NEUTRAL,
    )
    result = build_event_features(
        "RELIANCE", AS_OF, [old, other_symbol], admitted("old", "other")
    )
    assert result.admitted_event_count == 1
    assert result.event_count_30d == 0
    assert result.admitted_event_ids == ("old",)


def test_duplicate_event_ids_fail_closed() -> None:
    with pytest.raises(ValueError, match="duplicate event IDs"):
        build_event_features(
            "RELIANCE", AS_OF, [record("dup"), record("dup")], admitted("dup")
        )


def test_naive_as_of_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_event_features("RELIANCE", datetime(2026, 11, 6, 10), [], {})


def test_impact_assessment_cannot_predate_announcement() -> None:
    with pytest.raises(ValueError, match="cannot predate"):
        record(
            "bad-assessment",
            announced_at=AS_OF,
            assessment=EventImpactAssessment(
                EventDirection.POSITIVE,
                EventMateriality.LOW,
                AS_OF - timedelta(minutes=1),
                "Invalid chronology",
            ),
        )
