from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from nse_swing_bot.events.diagnostics import (
    DIAGNOSTIC_COLUMNS,
    build_event_diagnostics,
)
from nse_swing_bot.events.evidence import (
    EventDirection,
    EventTaxonomy,
    EvidenceAdmissionResult,
)
from nse_swing_bot.events.intelligence import (
    EventImpactAssessment,
    EventIntelligenceRecord,
    EventMateriality,
)


T0 = datetime(2026, 10, 1, 15, 30, tzinfo=UTC)


def event(
    event_id: str,
    announced_at: datetime,
    assessment: EventImpactAssessment | None = None,
) -> EventIntelligenceRecord:
    return EventIntelligenceRecord(
        event_id=event_id,
        symbol="RELIANCE",
        event_class=EventTaxonomy.FINANCIAL_RESULTS,
        event_subclass="quarterly_results",
        announced_at=announced_at,
        effective_at=None,
        direction=EventDirection.UNKNOWN,
        impact_assessment=assessment,
    )


def admission(*ids: str) -> dict[str, EvidenceAdmissionResult]:
    return {
        item: EvidenceAdmissionResult(True, (), (f"evidence-{item}",))
        for item in ids
    }


def test_diagnostics_reconstructs_information_available_at_each_decision_time() -> None:
    first = event("first", T0 + timedelta(days=1))
    second = event("second", T0 + timedelta(days=3))
    decisions = pd.date_range(T0, periods=5, freq="D")
    result = build_event_diagnostics(
        "reliance", decisions, [first, second], admission("first", "second")
    )
    assert list(result.columns) == list(DIAGNOSTIC_COLUMNS)
    assert result.index.equals(decisions)
    assert result["admitted_event_count"].tolist() == [0, 1, 1, 2, 2]
    assert result.iloc[1]["admitted_event_ids"] == ("first",)
    assert result.iloc[3]["admitted_event_ids"] == ("first", "second")


def test_future_impact_assessment_does_not_leak_into_earlier_diagnostics() -> None:
    announced = T0 + timedelta(days=1)
    assessed = EventImpactAssessment(
        EventDirection.NEGATIVE,
        EventMateriality.HIGH,
        T0 + timedelta(days=3),
        "Assessment recorded later",
    )
    record = event("one", announced, assessed)
    decisions = pd.date_range(T0, periods=5, freq="D")
    result = build_event_diagnostics("RELIANCE", decisions, [record], admission("one"))
    assert result["negative_event_count_30d"].tolist() == [0, 0, 0, 1, 1]
    assert result["unassessed_impact_count_30d"].tolist() == [0, 0, 1, 0, 0]


def test_ineligible_event_never_enters_diagnostics() -> None:
    record = event("rejected", T0)
    result = build_event_diagnostics(
        "RELIANCE",
        [T0],
        [record],
        {"rejected": EvidenceAdmissionResult(False, ("pending_review",), ())},
    )
    assert result.iloc[0]["admitted_event_count"] == 0
    assert result.iloc[0]["admitted_event_ids"] == ()


def test_diagnostics_are_isolated_from_other_symbols() -> None:
    other = EventIntelligenceRecord(
        event_id="other",
        symbol="TCS",
        event_class=EventTaxonomy.OPERATIONS,
        event_subclass="plant_update",
        announced_at=T0,
        effective_at=None,
        direction=EventDirection.UNKNOWN,
    )
    result = build_event_diagnostics("RELIANCE", [T0], [other], admission("other"))
    assert result.iloc[0]["admitted_event_count"] == 0


@pytest.mark.parametrize(
    "times, message",
    [
        ([], "at least one"),
        ([datetime(2026, 10, 1, 15, 30)], "timezone-aware"),
        ([pd.NaT], "timezone-aware"),
        ([T0 + timedelta(days=1), T0], "strictly increasing"),
        ([T0, T0], "strictly increasing"),
    ],
)
def test_invalid_decision_time_sequences_fail_closed(times, message) -> None:
    with pytest.raises(ValueError, match=message):
        build_event_diagnostics("RELIANCE", times, [], {})
