import json
from datetime import UTC, date, datetime, timedelta

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



def test_event_between_decision_and_entry_blocks_new_trade():
    planned_entry = date(2026, 11, 6)
    event_before_entry = event(event_date=date(2026, 11, 5))
    result = evaluate_event_entry(
        "ABC",
        DECISION,
        planned_entry,
        [event_before_entry],
        coverage(covered_through=date(2026, 11, 11)),
    )
    assert not result.allowed
    assert result.reasons == ("earnings_within_5_calendar_days:ABC-EVENT-1",)


def test_primary_and_secondary_subdomains_are_not_independent():
    with pytest.raises(ValueError, match="independent domains"):
        event(source_secondary="https://filings.nseindia.com/another-page")


def test_event_coverage_csv_loader_parses_reviewed_manifest(tmp_path):
    from nse_swing_bot.market_data.event_calendar import load_event_coverage_csv

    path = tmp_path / "coverage.csv"
    path.write_text(
        "symbol,covered_from,covered_through,captured_at,source_primary,"
        "source_secondary,complete\n"
        f"abc,2026-11-01,2026-11-30,2026-11-04T09:00:00+00:00,{PRIMARY},"
        f"{SECONDARY},true\n",
        encoding="utf-8",
    )
    loaded = load_event_coverage_csv(path)
    assert len(loaded) == 1
    assert loaded[0].symbol == "ABC"
    assert loaded[0].covered_from == date(2026, 11, 1)
    assert loaded[0].complete is True


def test_event_coverage_csv_loader_rejects_ambiguous_complete_flag(tmp_path):
    from nse_swing_bot.market_data.event_calendar import load_event_coverage_csv

    path = tmp_path / "coverage.csv"
    path.write_text(
        "symbol,covered_from,covered_through,captured_at,source_primary,"
        "source_secondary,complete\n"
        f"ABC,2026-11-01,2026-11-30,2026-11-04T09:00:00+00:00,{PRIMARY},"
        f"{SECONDARY},yes\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="complete must be true or false"):
        load_event_coverage_csv(path)


def test_event_coverage_csv_loader_rejects_duplicate_symbols(tmp_path):
    from nse_swing_bot.market_data.event_calendar import load_event_coverage_csv

    path = tmp_path / "coverage.csv"
    row = (
        f"ABC,2026-11-01,2026-11-30,2026-11-04T09:00:00+00:00,"
        f"{PRIMARY},{SECONDARY},true\n"
    )
    path.write_text(
        "symbol,covered_from,covered_through,captured_at,source_primary,"
        "source_secondary,complete\n" + row + row,
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate coverage symbol"):
        load_event_coverage_csv(path)


def test_event_csv_loader_wraps_missing_field_as_row_validation_error(tmp_path):
    path = tmp_path / "events.csv"
    path.write_text(
        "event_id,symbol,event_type,event_date,announced_at,title,source_primary,"
        "source_secondary,verification_status\n"
        f"e1,ABC,earnings,2026-11-08,2026-11-03T12:00:00+00:00,Results,{PRIMARY},"
        f"{SECONDARY}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid event CSV row"):
        load_event_csv(path)


def test_event_coverage_csv_loader_wraps_missing_field_as_row_validation_error(tmp_path):
    from nse_swing_bot.market_data.event_calendar import load_event_coverage_csv

    path = tmp_path / "coverage.csv"
    path.write_text(
        "symbol,covered_from,covered_through,captured_at,source_primary,"
        "source_secondary,complete\n"
        f"ABC,2026-11-01,2026-11-30,2026-11-04T09:00:00+00:00,{PRIMARY},"
        f"{SECONDARY}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid event coverage CSV row"):
        load_event_coverage_csv(path)


def test_reviewed_event_import_validates_universe_and_writes_snapshot(tmp_path):
    from nse_swing_bot.market_data.event_calendar import import_reviewed_event_snapshot

    events_path = tmp_path / "events.csv"
    events_path.write_text(
        "event_id,symbol,event_type,event_date,announced_at,title,source_primary,"
        "source_secondary,verification_status\n"
        f"e1,ABC,earnings,2026-11-08,2026-11-03T12:00:00+00:00,Results,{PRIMARY},"
        f"{SECONDARY},verified\n",
        encoding="utf-8",
    )
    coverage_path = tmp_path / "coverage.csv"
    coverage_path.write_text(
        "symbol,covered_from,covered_through,captured_at,source_primary,"
        "source_secondary,complete\n"
        f"ABC,2026-11-01,2026-11-30,2026-11-04T09:00:00+00:00,{PRIMARY},"
        f"{SECONDARY},true\n",
        encoding="utf-8",
    )
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text("Symbol\nABC\n", encoding="utf-8")

    snapshot = import_reviewed_event_snapshot(
        events_path,
        coverage_path,
        universe_path,
        tmp_path / "snapshots",
        datetime(2026, 11, 4, 10, 1, tzinfo=UTC),
        require_complete=True,
    )
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert len(payload["events"]) == 1
    assert len(payload["coverage"]) == 1
    assert payload["coverage"][0]["complete"] is True


def test_reviewed_event_import_rejects_missing_universe_coverage(tmp_path):
    from nse_swing_bot.market_data.event_calendar import import_reviewed_event_snapshot

    events_path = tmp_path / "events.csv"
    events_path.write_text(
        "event_id,symbol,event_type,event_date,announced_at,title,source_primary,"
        "source_secondary,verification_status\n",
        encoding="utf-8",
    )
    coverage_path = tmp_path / "coverage.csv"
    coverage_path.write_text(
        "symbol,covered_from,covered_through,captured_at,source_primary,"
        "source_secondary,complete\n",
        encoding="utf-8",
    )
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text("symbol\nABC\nXYZ\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing universe symbols: ABC, XYZ"):
        import_reviewed_event_snapshot(
            events_path,
            coverage_path,
            universe_path,
            tmp_path / "snapshots",
            datetime(2026, 11, 4, 10, 1, tzinfo=UTC),
        )


def test_reviewed_event_import_can_require_all_coverage_complete(tmp_path):
    from nse_swing_bot.market_data.event_calendar import import_reviewed_event_snapshot

    events_path = tmp_path / "events.csv"
    events_path.write_text(
        "event_id,symbol,event_type,event_date,announced_at,title,source_primary,"
        "source_secondary,verification_status\n",
        encoding="utf-8",
    )
    coverage_path = tmp_path / "coverage.csv"
    coverage_path.write_text(
        "symbol,covered_from,covered_through,captured_at,source_primary,"
        "source_secondary,complete\n"
        f"ABC,2026-11-01,2026-11-30,2026-11-04T09:00:00+00:00,{PRIMARY},"
        f"{SECONDARY},false\n",
        encoding="utf-8",
    )
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text("symbol\nABC\n", encoding="utf-8")

    with pytest.raises(ValueError, match="incomplete symbols: ABC"):
        import_reviewed_event_snapshot(
            events_path,
            coverage_path,
            universe_path,
            tmp_path / "snapshots",
            datetime(2026, 11, 4, 10, 1, tzinfo=UTC),
            require_complete=True,
        )


def test_coverage_template_script_creates_all_symbols_as_incomplete(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    import pandas as pd

    universe = tmp_path / "universe.csv"
    universe.write_text("Symbol\nXYZ\nABC\n", encoding="utf-8")
    output = tmp_path / "coverage.csv"
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "create_event_coverage_template.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--universe",
            str(universe),
            "--covered-from",
            "2026-09-30",
            "--covered-through",
            "2026-11-30",
            "--captured-at",
            "2026-11-05T15:30:00+05:30",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    generated = pd.read_csv(output)
    assert generated["symbol"].tolist() == ["ABC", "XYZ"]
    assert generated["complete"].tolist() == [False, False]
    assert generated["source_primary"].isna().all()
    assert generated["source_secondary"].isna().all()


def test_coverage_template_script_refuses_to_overwrite(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    universe = tmp_path / "universe.csv"
    universe.write_text("symbol\nABC\n", encoding="utf-8")
    output = tmp_path / "coverage.csv"
    output.write_text("existing", encoding="utf-8")
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "create_event_coverage_template.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--universe",
            str(universe),
            "--covered-from",
            "2026-09-30",
            "--covered-through",
            "2026-11-30",
            "--captured-at",
            "2026-11-05T15:30:00+05:30",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert output.read_text(encoding="utf-8") == "existing"


def test_event_snapshot_rejects_announcements_after_snapshot_capture(tmp_path):
    future_event = event(announced_at=DECISION + timedelta(seconds=1))
    with pytest.raises(ValueError, match="announcement cannot be after"):
        write_event_snapshot(tmp_path, [future_event], [coverage()], DECISION)
