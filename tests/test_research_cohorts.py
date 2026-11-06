from datetime import timedelta

import pandas as pd
import pytest

from nse_swing_bot.research.cohorts import (
    SUMMARY_COLUMNS,
    build_event_cohort_summary,
)


def sample_inputs():
    index = pd.date_range(
        "2026-03-02 15:30",
        periods=4,
        freq="D",
        tz="Asia/Kolkata",
        name="decision_at",
    )
    research = pd.DataFrame(
        {
            "signal": [True, True, True, True],
            "event_count_30d": [1, 0, 2, 0],
            "has_high_materiality_event_30d": [True, False, False, False],
            "unassessed_impact_count_30d": [1, 0, 1, 0],
            "positive_event_count_30d": [1, 0, 0, 0],
            "negative_event_count_30d": [0, 0, 1, 0],
            "mixed_event_count_30d": [0, 0, 0, 0],
        },
        index=index,
    )
    coverage_rows = []
    for position, decision_at in enumerate(index):
        decision_date = decision_at.date()
        coverage_rows.append(
            {
                "coverage_complete_30d": position != 3,
                "coverage_snapshot_id": f"coverage-{position}",
                "covered_from": (decision_date - timedelta(days=30)).isoformat(),
                "covered_through": decision_date.isoformat(),
                "captured_at": decision_at - pd.Timedelta(minutes=5),
            }
        )
    coverage = pd.DataFrame(coverage_rows, index=index)
    label_rows = []
    for position, decision_at in enumerate(index):
        for horizon in (5, 10):
            censored = position == 3 and horizon == 10
            label_rows.append(
                {
                    "symbol": "ABC",
                    "decision_at": decision_at.isoformat(),
                    "horizon_sessions": horizon,
                    "forward_close_return": None if censored else (position - 1) * 0.01,
                    "max_favorable_excursion": None if censored else 0.03 + position * 0.01,
                    "max_adverse_excursion": None if censored else -0.02 - position * 0.01,
                    "label_status": "censored" if censored else "complete",
                }
            )
    labels = pd.DataFrame(label_rows)
    return research, coverage, labels, index


def test_summary_reports_predeclared_cohorts_and_sample_counts() -> None:
    research, coverage, labels, _ = sample_inputs()
    result = build_event_cohort_summary(
        research, coverage, labels, "ABC", min_sample_size=2, bootstrap_samples=200
    )
    assert tuple(result.columns) == SUMMARY_COLUMNS
    five = result.loc[result["horizon_sessions"] == 5].set_index("cohort")
    assert five.loc["all_phase1_signals", "observation_count"] == 4
    assert five.loc["all_phase1_signals", "complete_label_count"] == 4
    assert five.loc["event_coverage_complete", "observation_count"] == 3
    assert five.loc["event_coverage_incomplete_or_unavailable", "observation_count"] == 1
    assert five.loc["admitted_event_present_30d", "observation_count"] == 2
    assert five.loc["no_admitted_event_in_complete_30d_window", "observation_count"] == 1
    assert five.loc["high_materiality_event_present_30d", "observation_count"] == 1
    assert five.loc["positive_impact_assessed_30d", "observation_count"] == 1
    assert bool(five.loc["all_phase1_signals", "sample_sufficient"])


def test_zero_event_count_with_incomplete_coverage_is_not_no_event_cohort() -> None:
    research, coverage, labels, _ = sample_inputs()
    result = build_event_cohort_summary(
        research, coverage, labels, "ABC", min_sample_size=1, bootstrap_samples=100
    )
    row = result.loc[
        (result["horizon_sessions"] == 5)
        & (result["cohort"] == "no_admitted_event_in_complete_30d_window")
    ].iloc[0]
    assert row["observation_count"] == 1
    # Only the second decision has complete coverage and zero admitted events.
    assert row["complete_label_count"] == 1


def test_censored_labels_remain_in_denominator_but_not_return_statistics() -> None:
    research, coverage, labels, _ = sample_inputs()
    result = build_event_cohort_summary(
        research, coverage, labels, "ABC", min_sample_size=1, bootstrap_samples=100
    )
    row = result.loc[
        (result["horizon_sessions"] == 10)
        & (result["cohort"] == "all_phase1_signals")
    ].iloc[0]
    assert row["observation_count"] == 4
    assert row["complete_label_count"] == 3
    assert row["censored_label_count"] == 1
    assert row["label_completion_rate"] == pytest.approx(0.75)


def test_summary_is_deterministic() -> None:
    research, coverage, labels, _ = sample_inputs()
    first = build_event_cohort_summary(
        research, coverage, labels, "ABC", min_sample_size=1, bootstrap_samples=200
    )
    second = build_event_cohort_summary(
        research, coverage, labels, "ABC", min_sample_size=1, bootstrap_samples=200
    )
    pd.testing.assert_frame_equal(first, second)


def test_rejects_coverage_captured_after_decision() -> None:
    research, coverage, labels, index = sample_inputs()
    coverage.loc[index[0], "captured_at"] = index[0] + pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="captured after"):
        build_event_cohort_summary(research, coverage, labels, "ABC")


def test_rejects_coverage_that_does_not_cover_full_lookback() -> None:
    research, coverage, labels, index = sample_inputs()
    coverage.loc[index[0], "covered_from"] = "2026-02-15"
    with pytest.raises(ValueError, match="full 30-day"):
        build_event_cohort_summary(research, coverage, labels, "ABC")


def test_rejects_misaligned_coverage_index() -> None:
    research, coverage, labels, _ = sample_inputs()
    coverage.index = coverage.index + pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="indexes must match exactly"):
        build_event_cohort_summary(research, coverage, labels, "ABC")


def test_rejects_missing_signal_horizon_label() -> None:
    research, coverage, labels, index = sample_inputs()
    labels = labels.loc[
        ~(
            (labels["decision_at"] == index[0].isoformat())
            & (labels["horizon_sessions"] == 10)
        )
    ]
    with pytest.raises(ValueError, match="every horizon"):
        build_event_cohort_summary(research, coverage, labels, "ABC")


def test_rejects_duplicate_outcome_keys() -> None:
    research, coverage, labels, _ = sample_inputs()
    labels = pd.concat([labels, labels.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        build_event_cohort_summary(research, coverage, labels, "ABC")


def test_rejects_naive_outcome_decision_timestamp() -> None:
    research, coverage, labels, index = sample_inputs()
    labels.loc[0, "decision_at"] = index[0].tz_localize(None).isoformat()
    with pytest.raises(ValueError, match="timezone-aware"):
        build_event_cohort_summary(research, coverage, labels, "ABC")


def test_rejects_non_boolean_signal_values() -> None:
    research, coverage, labels, _ = sample_inputs()
    research["signal"] = research["signal"].astype(int)
    with pytest.raises(ValueError, match="non-null booleans"):
        build_event_cohort_summary(research, coverage, labels, "ABC")


def test_rejects_labels_outside_research_frame() -> None:
    research, coverage, labels, index = sample_inputs()
    labels.loc[0, "decision_at"] = (
        index[0] - pd.Timedelta(days=1)
    ).isoformat()
    with pytest.raises(ValueError, match="outside research_frame"):
        build_event_cohort_summary(research, coverage, labels, "ABC")
