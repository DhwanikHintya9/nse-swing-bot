import hashlib
import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from nse_swing_bot.research.outcomes import (
    ADJUSTMENT_METHOD,
    OUTCOME_COLUMNS,
    PRICE_BASIS,
    OutcomePriceMetadata,
    build_forward_outcome_labels,
    export_forward_outcome_labels,
)


def sample_data(missing: tuple[int, ...] = ()):
    sessions = pd.bdate_range("2026-01-05", periods=12, name="date")
    rows = []
    for position, _ in enumerate(sessions):
        rows.append(
            {
                "open": 100.0 + position,
                "high": 102.0 + position,
                "low": 99.0 + position,
                "close": 101.0 + position,
                "volume": 1000.0,
            }
        )
    candles = pd.DataFrame(rows, index=sessions).drop(
        index=[sessions[index] for index in missing]
    )
    decisions = pd.DatetimeIndex(
        [sessions[0].tz_localize("Asia/Kolkata") + pd.Timedelta(hours=15, minutes=30),
         sessions[1].tz_localize("Asia/Kolkata") + pd.Timedelta(hours=15, minutes=30)]
    )
    metadata = OutcomePriceMetadata(
        symbol="ABC",
        source_candle_snapshot_id="candles-2026-01",
        corporate_action_snapshot_id="actions-2026-01",
        calendar_snapshot_id="nse-calendar-2026",
        price_basis=PRICE_BASIS,
        adjustment_method=ADJUSTMENT_METHOD,
        outcome_as_of_date=sessions[-1].date(),
        calendar_coverage_start=sessions[0].date(),
        calendar_coverage_end=sessions[-1].date(),
        captured_at=datetime(2026, 1, 30, tzinfo=UTC),
    )
    return candles, decisions, sessions, metadata


def test_forward_labels_use_next_exchange_sessions_and_adjusted_ohlc() -> None:
    candles, decisions, sessions, metadata = sample_data()
    result = build_forward_outcome_labels(
        "ABC", candles, decisions, sessions, metadata, horizons=(2,)
    )
    first = result.iloc[0]
    assert first["label_status"] == "complete"
    assert first["label_start_session"] == sessions[1].date().isoformat()
    assert first["label_end_session"] == sessions[2].date().isoformat()
    assert first["forward_close_return"] == pytest.approx(103.0 / 101.0 - 1.0)
    assert first["max_favorable_excursion"] == pytest.approx(104.0 / 101.0 - 1.0)
    assert first["max_adverse_excursion"] == pytest.approx(100.0 / 101.0 - 1.0)
    assert first["price_basis"] == PRICE_BASIS


def test_missing_intermediate_candle_censors_entire_horizon() -> None:
    candles, decisions, sessions, metadata = sample_data(missing=(2,))
    result = build_forward_outcome_labels(
        "ABC", candles, decisions[:1], sessions, metadata, horizons=(3,)
    )
    row = result.iloc[0]
    assert row["label_status"] == "censored"
    assert row["label_reason"] == "missing_forward_candle"
    assert pd.isna(row["forward_close_return"])
    assert pd.isna(row["max_favorable_excursion"])
    assert pd.isna(row["max_adverse_excursion"])


def test_insufficient_calendar_horizon_is_censored_not_zero() -> None:
    candles, decisions, sessions, metadata = sample_data()
    late_decision = pd.DatetimeIndex(
        [sessions[-2].tz_localize("Asia/Kolkata") + pd.Timedelta(hours=15, minutes=30)]
    )
    result = build_forward_outcome_labels(
        "ABC", candles, late_decision, sessions, metadata, horizons=(5,)
    )
    row = result.iloc[0]
    assert row["label_status"] == "censored"
    assert row["label_reason"] == "calendar_window_unavailable"
    assert pd.isna(row["forward_close_return"])


def test_overlapping_forward_windows_are_counted() -> None:
    candles, decisions, sessions, metadata = sample_data()
    result = build_forward_outcome_labels(
        "ABC", candles, decisions, sessions, metadata, horizons=(2,)
    )
    assert result["overlapping_label_count"].tolist() == [1, 1]


def test_label_horizon_is_not_observed_row_offset() -> None:
    candles, decisions, sessions, metadata = sample_data(missing=(2,))
    result = build_forward_outcome_labels(
        "ABC", candles, decisions[:1], sessions, metadata, horizons=(3,)
    )
    assert result.iloc[0]["label_end_session"] == sessions[3].date().isoformat()
    assert result.iloc[0]["label_status"] == "censored"


def test_rejects_raw_or_unsupported_price_basis() -> None:
    candles, decisions, sessions, metadata = sample_data()
    with pytest.raises(ValueError, match="price_basis"):
        OutcomePriceMetadata(
            **{
                **metadata.__dict__,
                "price_basis": "raw_kite_ohlc",
            }
        )


def test_rejects_naive_decision_timestamps() -> None:
    candles, decisions, sessions, metadata = sample_data()
    naive = decisions.tz_localize(None)
    with pytest.raises(ValueError, match="timezone-aware"):
        build_forward_outcome_labels("ABC", candles, naive, sessions, metadata)


def test_rejects_decision_without_exchange_session_candle() -> None:
    candles, decisions, sessions, metadata = sample_data(missing=(0,))
    with pytest.raises(ValueError, match="decision-session candle"):
        build_forward_outcome_labels("ABC", candles, decisions[:1], sessions, metadata)


def test_rejects_future_or_out_of_calendar_candles() -> None:
    candles, decisions, sessions, metadata = sample_data()
    extra = candles.iloc[[-1]].copy()
    extra.index = pd.DatetimeIndex([sessions[-1] + pd.Timedelta(days=1)])
    extended = pd.concat([candles, extra]).sort_index()
    with pytest.raises(ValueError, match="supplied NSE calendar"):
        build_forward_outcome_labels("ABC", extended, decisions[:1], sessions, metadata)


def test_rejects_invalid_horizons() -> None:
    candles, decisions, sessions, metadata = sample_data()
    with pytest.raises(ValueError, match="positive integer"):
        build_forward_outcome_labels("ABC", candles, decisions[:1], sessions, metadata, (0,))


def test_export_writes_hash_bound_research_only_artifacts(tmp_path) -> None:
    candles, decisions, sessions, metadata = sample_data()
    labels = build_forward_outcome_labels(
        "ABC", candles, decisions, sessions, metadata, horizons=(2,)
    )
    csv_path, manifest_path = export_forward_outcome_labels(labels, metadata, tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == manifest["csv_sha256"]
    assert manifest["row_count"] == 2
    assert manifest["production_eligible"] is False
    assert manifest["broker_execution_eligible"] is False
    assert manifest["strategy_signal_modified"] is False
    assert manifest["labels_are_simulated_trades"] is False
    assert list(pd.read_csv(csv_path).columns) == list(OUTCOME_COLUMNS)


def test_export_refuses_overwrite(tmp_path) -> None:
    candles, decisions, sessions, metadata = sample_data()
    labels = build_forward_outcome_labels(
        "ABC", candles, decisions, sessions, metadata, horizons=(2,)
    )
    export_forward_outcome_labels(labels, metadata, tmp_path)
    with pytest.raises(FileExistsError):
        export_forward_outcome_labels(labels, metadata, tmp_path)


def test_export_rejects_provenance_mismatch(tmp_path) -> None:
    candles, decisions, sessions, metadata = sample_data()
    labels = build_forward_outcome_labels(
        "ABC", candles, decisions, sessions, metadata, horizons=(2,)
    )
    labels.loc[0, "source_candle_snapshot_id"] = "other-snapshot"
    with pytest.raises(ValueError, match="provenance mismatch"):
        export_forward_outcome_labels(labels, metadata, tmp_path)
