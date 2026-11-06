import hashlib
import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from nse_swing_bot.research.splits import (
    ASSIGNMENT_COLUMNS,
    WalkForwardWindow,
    build_walk_forward_assignments,
    export_walk_forward_assignments,
)


def sample_split_inputs():
    sessions = pd.bdate_range("2026-01-05", periods=45, name="date")
    observations = [
        # Earlier history remains eligible for the expanding training set.
        ("ABC", 10, 5, "complete"),
        ("XYZ", 10, 15, "complete"),
        # A date is purged as a group if any symbol/horizon label reaches test start.
        ("ABC", 20, 5, "complete"),
        ("XYZ", 20, 15, "complete"),
        # A date inside the embargo window, with label windows ending before test.
        ("ABC", 28, 1, "complete"),
        ("XYZ", 28, 1, "censored"),
        # First test window.
        ("ABC", 30, 1, "complete"),
        ("XYZ", 30, 2, "censored"),
        ("ABC", 31, 1, "complete"),
        # Second test window; earlier test observations become prior history.
        ("ABC", 35, 1, "complete"),
        ("XYZ", 35, 2, "complete"),
    ]
    rows = []
    for symbol, decision_position, horizon, status in observations:
        start_position = decision_position + 1
        end_position = decision_position + horizon
        rows.append(
            {
                "symbol": symbol,
                "decision_at": (
                    sessions[decision_position].tz_localize("Asia/Kolkata")
                    + pd.Timedelta(hours=15, minutes=30)
                ).isoformat(),
                "horizon_sessions": horizon,
                "label_start_session": sessions[start_position].date().isoformat(),
                "label_end_session": sessions[end_position].date().isoformat(),
                "label_status": status,
            }
        )
    labels = pd.DataFrame(rows)
    windows = (
        WalkForwardWindow("fold-1", sessions[30].date(), sessions[32].date()),
        WalkForwardWindow("fold-2", sessions[35].date(), sessions[36].date()),
    )
    return labels, sessions, windows


def test_walk_forward_assignments_purge_by_decision_date_group() -> None:
    labels, sessions, windows = sample_split_inputs()
    result = build_walk_forward_assignments(
        labels, sessions, windows, "calendar-2026", embargo_sessions=2, min_train_sessions=1
    )
    assert tuple(result.columns) == ASSIGNMENT_COLUMNS
    first = result.loc[result["fold_id"] == "fold-1"]
    purged = first.loc[first["decision_session"] == sessions[20].date().isoformat()]
    assert set(purged["partition"]) == {"purged"}
    assert len(purged) == 2
    assert purged["partition_reason"].str.contains("date_group").all()


def test_embargo_applies_to_full_decision_date_group() -> None:
    labels, sessions, windows = sample_split_inputs()
    result = build_walk_forward_assignments(
        labels, sessions, windows, "calendar-2026", embargo_sessions=2, min_train_sessions=1
    )
    first = result.loc[result["fold_id"] == "fold-1"]
    embargoed = first.loc[first["decision_session"] == sessions[28].date().isoformat()]
    assert set(embargoed["partition"]) == {"embargoed"}
    assert len(embargoed) == 2


def test_all_symbols_and_horizons_at_test_date_share_test_partition() -> None:
    labels, sessions, windows = sample_split_inputs()
    result = build_walk_forward_assignments(
        labels, sessions, windows, "calendar-2026", embargo_sessions=2, min_train_sessions=1
    )
    test_rows = result.loc[
        (result["fold_id"] == "fold-1")
        & (result["decision_session"] == sessions[30].date().isoformat())
    ]
    assert set(test_rows["partition"]) == {"test"}
    assert set(test_rows["symbol"]) == {"ABC", "XYZ"}
    censored_rows = test_rows.loc[test_rows["label_status"] == "censored"]
    assert not bool(censored_rows["training_eligible"].any())


def test_prior_test_window_can_enter_later_expanding_training_window() -> None:
    labels, sessions, windows = sample_split_inputs()
    result = build_walk_forward_assignments(
        labels, sessions, windows, "calendar-2026", embargo_sessions=2, min_train_sessions=1
    )
    fold_two = result.loc[result["fold_id"] == "fold-2"]
    prior_test_date = sessions[30].date().isoformat()
    rows = fold_two.loc[fold_two["decision_session"] == prior_test_date]
    assert set(rows["partition"]) == {"train"}


def test_censored_training_rows_are_retained_but_not_training_eligible() -> None:
    labels, sessions, windows = sample_split_inputs()
    result = build_walk_forward_assignments(
        labels, sessions, windows, "calendar-2026", embargo_sessions=2, min_train_sessions=1
    )
    fold_two = result.loc[result["fold_id"] == "fold-2"]
    censored = fold_two.loc[
        (fold_two["decision_session"] == sessions[28].date().isoformat())
        & (fold_two["label_status"] == "censored")
    ]
    assert len(censored) == 1
    assert not bool(censored.iloc[0]["training_eligible"])


def test_rejects_label_end_that_does_not_match_exchange_calendar() -> None:
    labels, sessions, windows = sample_split_inputs()
    labels.loc[0, "label_end_session"] = sessions[27].date().isoformat()
    with pytest.raises(ValueError, match="label_end_session"):
        build_walk_forward_assignments(
            labels, sessions, windows, "calendar-2026", embargo_sessions=2, min_train_sessions=1
        )


def test_rejects_naive_decision_timestamp() -> None:
    labels, sessions, windows = sample_split_inputs()
    labels.loc[0, "decision_at"] = "2026-02-02T15:30:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        build_walk_forward_assignments(
            labels, sessions, windows, "calendar-2026", embargo_sessions=2, min_train_sessions=1
        )


def test_rejects_overlapping_test_windows() -> None:
    labels, sessions, windows = sample_split_inputs()
    overlapping = (
        WalkForwardWindow("fold-1", sessions[30].date(), sessions[34].date()),
        WalkForwardWindow("fold-2", sessions[33].date(), sessions[36].date()),
    )
    with pytest.raises(ValueError, match="non-overlapping"):
        build_walk_forward_assignments(
            labels, sessions, overlapping, "calendar-2026", embargo_sessions=2, min_train_sessions=1
        )


def test_rejects_insufficient_training_history() -> None:
    labels, sessions, windows = sample_split_inputs()
    with pytest.raises(ValueError, match="eligible training sessions"):
        build_walk_forward_assignments(
            labels, sessions, windows, "calendar-2026", embargo_sessions=2, min_train_sessions=20
        )


def test_split_export_is_hash_bound_and_research_only(tmp_path) -> None:
    labels, sessions, windows = sample_split_inputs()
    assignments = build_walk_forward_assignments(
        labels, sessions, windows, "calendar-2026", embargo_sessions=2, min_train_sessions=1
    )
    csv_path, manifest_path = export_walk_forward_assignments(
        assignments,
        windows,
        tmp_path,
        "calendar-2026",
        "a" * 64,
        embargo_sessions=2,
        min_train_sessions=1,
        captured_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == manifest["csv_sha256"]
    assert manifest["source_label_artifact_sha256"] == "a" * 64
    assert manifest["production_eligible"] is False
    assert manifest["broker_execution_eligible"] is False
    assert manifest["strategy_signal_modified"] is False
    assert manifest["model_fitted"] is False
    assert len(pd.read_csv(csv_path)) == len(assignments)


def test_split_export_refuses_overwrite(tmp_path) -> None:
    labels, sessions, windows = sample_split_inputs()
    assignments = build_walk_forward_assignments(
        labels, sessions, windows, "calendar-2026", embargo_sessions=2, min_train_sessions=1
    )
    args = (
        assignments,
        windows,
        tmp_path,
        "calendar-2026",
        "b" * 64,
        2,
        1,
        datetime(2026, 4, 1, tzinfo=UTC),
    )
    export_walk_forward_assignments(*args)
    with pytest.raises(FileExistsError):
        export_walk_forward_assignments(*args)
