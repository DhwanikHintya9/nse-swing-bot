from datetime import UTC, date, datetime

import pandas as pd
import pytest

from nse_swing_bot.market_data.corporate_actions import (
    AdjustmentEvent,
    apply_verified_adjustments,
)
from nse_swing_bot.market_data.instruments import (
    load_nifty500_constituents,
    normalize_instrument_master,
    save_instrument_snapshot,
)
from nse_swing_bot.market_data.kite_adapter import KiteMarketDataAdapter
from nse_swing_bot.market_data.parquet_store import ParquetCandleStore
from nse_swing_bot.market_data.service import MarketDataService
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
    second = store.write_snapshot("NSE:ABC", corrected, datetime(2024, 1, 4, tzinfo=UTC))
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



def test_validation_rejects_infinite_ohlcv() -> None:
    candles = valid_candles()
    candles.iloc[0, candles.columns.get_loc("close")] = float("inf")
    with pytest.raises(ValueError, match="non-finite"):
        validate_daily_candles(candles)


def test_nifty500_loader_requires_and_records_source(tmp_path) -> None:
    csv_path = tmp_path / "constituents.csv"
    pd.DataFrame({"Symbol": ["ABC", "XYZ"]}).to_csv(csv_path, index=False)
    result = load_nifty500_constituents(
        csv_path, date(2026, 1, 1), "NSE official constituent file", expected_count=2
    )
    assert result["symbol"].tolist() == ["ABC", "XYZ"]
    assert result["effective_date"].unique().tolist() == ["2026-01-01"]
    assert result["source"].unique().tolist() == ["NSE official constituent file"]


def test_nifty500_loader_rejects_missing_provenance(tmp_path) -> None:
    csv_path = tmp_path / "constituents.csv"
    pd.DataFrame({"Symbol": ["ABC"]}).to_csv(csv_path, index=False)
    with pytest.raises(ValueError, match="source_name"):
        load_nifty500_constituents(csv_path, date(2026, 1, 1), "", expected_count=1)


def test_kite_adapter_fetches_daily_candles_in_sequential_chunks() -> None:
    class FakeKiteClient:
        def __init__(self) -> None:
            self.calls = []

        def instruments(self, exchange=None):
            return []

        def historical_data(
            self,
            instrument_token,
            from_date,
            to_date,
            interval,
            continuous=False,
            oi=False,
        ):
            self.calls.append((instrument_token, from_date, to_date, interval))
            return [
                {
                    "date": from_date,
                    "open": 10.0,
                    "high": 12.0,
                    "low": 9.0,
                    "close": 11.0,
                    "volume": 100.0,
                }
            ]

    client = FakeKiteClient()
    adapter = KiteMarketDataAdapter(client)
    result = adapter.fetch_daily_candles(
        123,
        date(2024, 1, 1),
        date(2024, 1, 5),
        chunk_days=2,
    )

    assert len(client.calls) == 3
    assert [call[3] for call in client.calls] == ["day", "day", "day"]
    assert client.calls[0][1].date() == date(2024, 1, 1)
    assert client.calls[0][2].date() == date(2024, 1, 2)
    assert client.calls[1][1].date() == date(2024, 1, 3)
    assert client.calls[2][1].date() == date(2024, 1, 5)
    assert list(result.columns) == ["open", "high", "low", "close", "volume"]



def test_instrument_snapshot_is_immutable_and_requires_aware_timestamp(tmp_path) -> None:
    frame = pd.DataFrame({"tradingsymbol": ["ABC"]})
    with pytest.raises(ValueError, match="timezone-aware"):
        save_instrument_snapshot(frame, tmp_path, datetime(2026, 1, 1))

    captured_at = datetime(2026, 1, 1, tzinfo=UTC)
    first = save_instrument_snapshot(frame, tmp_path, captured_at)
    assert first.exists()
    with pytest.raises(FileExistsError, match="overwrite"):
        save_instrument_snapshot(frame, tmp_path, captured_at)



def test_market_data_service_refreshes_master_and_syncs_one_symbol(tmp_path) -> None:
    class FakeKiteClient:
        def instruments(self, exchange=None):
            return [
                {
                    "instrument_token": 123,
                    "tradingsymbol": "ABC",
                    "name": "ABC LTD",
                    "tick_size": 0.05,
                    "lot_size": 1,
                    "instrument_type": "EQ",
                    "segment": "NSE",
                    "exchange": "NSE",
                }
            ]

        def historical_data(
            self,
            instrument_token,
            from_date,
            to_date,
            interval,
            continuous=False,
            oi=False,
        ):
            return [
                {
                    "date": pd.Timestamp("2024-01-01"),
                    "open": 10.0,
                    "high": 12.0,
                    "low": 9.0,
                    "close": 11.0,
                    "volume": 100.0,
                }
            ]

    adapter = KiteMarketDataAdapter(FakeKiteClient())
    store = ParquetCandleStore(tmp_path / "parquet")
    service = MarketDataService(adapter, store, tmp_path / "snapshots")
    instruments, snapshot = service.refresh_instrument_master()

    assert snapshot.exists()
    assert instruments.iloc[0]["tradingsymbol"] == "ABC"

    instrument = instruments.iloc[0]
    paths = service.sync_daily_history(
        instrument,
        date(2024, 1, 1),
        date(2024, 1, 1),
        expected_sessions=pd.DatetimeIndex(["2024-01-01"]),
    )
    assert len(paths) == 1
    assert store.read_latest("NSE:ABC").iloc[0]["close"] == pytest.approx(11.0)


@pytest.mark.parametrize("symbols", [[" "], ["ABC", " ABC "], ["abc", "ABC"]])
def test_normalize_instrument_master_rejects_blank_or_normalized_duplicate_symbols(symbols) -> None:
    rows = [
        {
            "instrument_token": index + 1,
            "tradingsymbol": symbol,
            "name": "Example Ltd",
            "tick_size": 0.05,
            "lot_size": 1,
            "instrument_type": "EQ",
            "segment": "NSE",
            "exchange": "NSE",
        }
        for index, symbol in enumerate(symbols)
    ]
    with pytest.raises(ValueError, match="trading symbols"):
        normalize_instrument_master(rows)
