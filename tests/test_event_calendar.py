from datetime import UTC, date, datetime, timedelta

import json

import pytest

from nse_swing_bot.market_data.event_calendar import (
    EventCoverage,
    EventType,
    ScheduledEvent,
    VerificationStatus,
    evaluate_event_entry,
    load_event_csv,
    write_event_snapshot,
)


DECISION = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
PRIMARY = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"
SECONDARY = "https://www.bseindia.com/corporates.html"


def coverage(**overrides):
    values = {
        "symbol": "ABC",
        "covered_from": date(2026, 11, 1),
        "covered_through": date(2026, 11, 10),
        "captured_at": datetime(2026, 11, 4, 9, 0, tzinfo=UTC),
        "source_primary": PRIMARY,
        "source_secondary": SECONDARY,
        "complete": True,
    }
    values.update(overrides)
    return EventCoverage(**values)


def event(event_type=EventType.EARNINGS, **overrides):
    values = {
        "event_id": "ABC-EVENT-1",
        "symbol": "ABC",
        "event_type": event_type,
        "event_date": date(2026, 11, 8),
        "announced_at": datetime(2026, 11, 3, 12, 0, tzinfo=UTC),
        "title": "Board meeting / financial results",
        "source_primary": PRIMARY,
        "source_secondary": SECONDARY,
        "verification_status": VerificationStatus.VERIFIED,
    }
    values.update(overrides)
    return ScheduledEvent(**values)


def test_missing_or_incomplete_event_coverage_blocks_entry():
    missing = evaluate_event_entry("ABC", DECISION, date(2026, 11, 5), [], None)
    incomplete = evaluate_event_entry(
        "ABC", DECISION, date(2026, 11, 5), [], coverage(complete=False)
    )
    assert not missing.allowed
    assert "missing_event_coverage" in missing.reasons
    assert not incomplete.allowed
    assert "event_coverage_incomplete" in incomplete.reasons


def test_earnings_within_five_calendar_days_blocks_entry():
    result = evaluate_event_entry(
        "ABC", DECISION, date(2026, 11, 5), [event()], coverage()
    )
    assert not result.allowed
    assert result.reasons == ("earnings_within_5_calendar_days:ABC-EVENT-1",)


def test_ordinary_dividend_does_not_block_entry():
    result = evaluate_event_entry(
        "ABC",
        DECISION,
        date(2026, 11, 5),
        [event(EventType.ORDINARY_DIVIDEND)],
        coverage(),
    )
    assert result.allowed


@pytest.mark.parametrize(
    "status",
    [VerificationStatus.UNVERIFIED, VerificationStatus.CONFLICT],
)
def test_unverified_or_conflicting_material_event_requires_manual_review(status):
    result = evaluate_event_entry(
        "ABC",
        DECISION,
        date(2026, 11, 5),
        [event(EventType.MATERIAL_CORPORATE_ACTION, verification_status=status)],
        coverage(),
    )
    assert not result.allowed
    assert "event_requires_manual_review:ABC-EVENT-1" in result.reasons


def test_verified_material_action_within_three_days_blocks_entry():
    result = evaluate_event_entry(
        "ABC",
        DECISION,
        date(2026, 11, 5),
        [
            event(
                EventType.MATERIAL_CORPORATE_ACTION,
                event_date=date(2026, 11, 7),
            )
        ],
        coverage(),
    )
    assert not result.allowed
    assert "corporate_action_within_3_calendar_days:ABC-EVENT-1" in result.reasons


def test_future_announcement_is_not_visible_to_historical_decision():
    future = event(announced_at=DECISION + timedelta(minutes=1))
    result = evaluate_event_entry(
        "ABC", DECISION, date(2026, 11, 5), [future], coverage()
    )
    assert result.allowed


def test_coverage_must_be_available_at_decision_and_cover_full_horizon():
    late = coverage(captured_at=DECISION + timedelta(seconds=1))
    short = coverage(covered_through=date(2026, 11, 9))
    for item, expected in [
        (late, "event_coverage_not_available_at_decision_time"),
        (short, "event_coverage_does_not_cover_earnings_window"),
    ]:
        result = evaluate_event_entry("ABC", DECISION, date(2026, 11, 5), [], item)
        assert not result.allowed
        assert expected in result.reasons


def test_event_snapshot_is_immutable_and_preserves_provenance(tmp_path):
    first = write_event_snapshot(
        tmp_path, [event()], [coverage()], datetime(2026, 11, 4, 10, 1, tzinfo=UTC)
    )
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["events"][0]["source_primary"] == PRIMARY
    assert payload["coverage"][0]["source_secondary"] == SECONDARY
    second = write_event_snapshot(
        tmp_path, [event()], [coverage()], datetime(2026, 11, 4, 10, 1, tzinfo=UTC)
    )
    assert first != second
    assert first.exists() and second.exists()


def test_event_csv_loader_parses_normalized_reviewed_export(tmp_path):
    path = tmp_path / "events.csv"
    path.write_text(
        "event_id,symbol,event_type,event_date,announced_at,title,source_primary,"
        "source_secondary,verification_status\n"
        f"e1,abc,earnings,2026-11-08,2026-11-03T12:00:00+00:00,Results,{PRIMARY},"
        f"{SECONDARY},verified\n",
        encoding="utf-8",
    )
    loaded = load_event_csv(path)
    assert len(loaded) == 1
    assert loaded[0].symbol == "ABC"
    assert loaded[0].event_type == EventType.EARNINGS


def test_event_csv_loader_rejects_unknown_event_type(tmp_path):
    path = tmp_path / "events.csv"
    path.write_text(
        "event_id,symbol,event_type,event_date,announced_at,title,source_primary,"
        "source_secondary,verification_status\n"
        f"e1,ABC,guess,2026-11-08,2026-11-03T12:00:00+00:00,Unknown,{PRIMARY},"
        f"{SECONDARY},verified\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid event CSV row"):
        load_event_csv(path)

def test_verified_critical_action_still_requires_manual_review():
    result = evaluate_event_entry(
        "ABC",
        DECISION,
        date(2026, 11, 5),
        [event(EventType.CRITICAL_CORPORATE_ACTION)],
        coverage(),
    )
    assert not result.allowed
    assert "critical_corporate_action_requires_manual_review:ABC-EVENT-1" in result.reasons


def test_entry_date_before_decision_date_is_rejected():
    with pytest.raises(ValueError, match="cannot precede"):
        evaluate_event_entry(
            "ABC", DECISION, date(2026, 11, 3), [], coverage()
        )

def test_primary_and_secondary_sources_must_be_independent_domains():
    with pytest.raises(ValueError, match="independent domains"):
        event(source_secondary="https://www.nseindia.com/another-page")
