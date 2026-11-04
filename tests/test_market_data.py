from datetime import UTC, date, datetime

import pandas as pd
import pytest

from nse_swing_bot.market_data.corporate_actions import (
    AdjustmentEvent,
    apply_verified_adjustments,
)
from nse_swing_bot.market_data.instruments import normalize_instrument_master
from nse_swing_bot.market_data.parquet_store import ParquetCandleStore
from nse_swing_bot.market_data.validation import validate_daily_candles


def valid_candles() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [10.0, 11.0],
            "high": [12.0, 13.0],
            "low": [9.0, 10.0],
            "close": [11.0, 12.0],
            "volume": [1000.0, 1200.0],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
    )


def test_normalize_instrument_master_keeps_nse_equities_only() -> None:
    rows = [
        {
            "instrument_token": 123,
            "tradingsymbol": "ABC",
            "name": "ABC LTD",
            "tick_size": 0.05,
            "lot_size": 1,
            "instrument_type": "EQ",
            "segment": "NSE",
            "exchange": "NSE",
        },
        {
            "instrument_token": 456,
            "tradingsymbol": "ABC24FUT",
            "name": "ABC",
            "tick_size": 0.05,
            "lot_size": 1,
            "instrument_type": "FUT",
            "segment": "NFO-FUT",
            "exchange": "NFO",
        },
    ]
    result = normalize_instrument_master(rows)
    assert result["tradingsymbol"].tolist() == ["ABC"]


def test_validation_rejects_bad_ohlc() -> None:
    candles = valid_candles()
    candles.loc[candles.index[0], "high"] = 8.0
    with pytest.raises(ValueError, match="high"):
        validate_daily_candles(candles)


def test_validation_rejects_missing_expected_session() -> None:
    candles = valid_candles().iloc[:1]
    expected = pd.DatetimeIndex(["2024-01-01", "2024-01-02"])
    with pytest.raises(ValueError, match="missing expected"):
        validate_daily_candles(candles, expected_sessions=expected)


def test_parquet_snapshots_are_append_only_and_latest_wins(tmp_path) -> None:
    store = ParquetCandleStore(tmp_path)
    original = valid_candles().iloc[:1]
    corrected = original.copy()
    corrected.iloc[0, corrected.columns.get_loc("close")] = 10.5

    first = store.write_snapshot("NSE:ABC", original, datetime(2024, 1, 3, tzinfo=UTC))
    second = store.write_snapshot("NSE:ABC", corrected, datetime(2024, 1, 4, tzinfo=timezone.utc))
    assert first[0].exists() and second[0].exists()
    assert first[0] != second[0]
    assert store.read_latest("NSE:ABC").iloc[0]["close"] == pytest.approx(10.5)


def test_adjustments_are_point_in_time_and_do_not_mutate_raw() -> None:
    raw = valid_candles()
    event = AdjustmentEvent(
        symbol="ABC",
        ex_date=date(2024, 1, 2),
        price_factor=0.5,
        volume_factor=2.0,
        source_primary="NSE announcement ref",
        source_secondary="Company IR ref",
        verified=True,
        event_id="ABC-BONUS-2024",
    )
    before_ex_date = apply_verified_adjustments(raw, [event], "ABC", date(2024, 1, 1))
    after_ex_date = apply_verified_adjustments(raw, [event], "ABC", date(2024, 1, 2))
    assert before_ex_date.iloc[0]["close"] == pytest.approx(11.0)
    assert after_ex_date.iloc[0]["close"] == pytest.approx(5.5)
    assert after_ex_date.iloc[0]["volume"] == pytest.approx(2000.0)
    assert raw.iloc[0]["close"] == pytest.approx(11.0)


def test_unverified_adjustment_fails_closed() -> None:
    event = AdjustmentEvent(
        symbol="ABC",
        ex_date=date(2024, 1, 2),
        price_factor=0.5,
        volume_factor=2.0,
        source_primary="NSE",
        source_secondary="",
        verified=False,
        event_id="UNVERIFIED",
    )
    with pytest.raises(ValueError, match="unverified"):
        apply_verified_adjustments(valid_candles(), [event], "ABC", date(2024, 1, 3))
