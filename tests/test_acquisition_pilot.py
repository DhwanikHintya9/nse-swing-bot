from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from nse_swing_bot.market_data.pilot import (
    _coverage_summary,
    _resolve_pilot_instruments,
    run_kite_daily_pilot,
)

PILOT_SYMBOLS = ["RELIANCE", "HDFCBANK", "INFY", "SUNPHARMA", "LT"]


def _universe_frame() -> pd.DataFrame:
    rows = []
    for index, symbol in enumerate(PILOT_SYMBOLS):
        rows.append(
            {
                "Company Name": f"Company {index}",
                "Industry": f"Industry {index}",
                "Symbol": symbol,
                "Series": "EQ",
                "ISIN Code": f"INE000A000{index:02d}",
            }
        )
    for index in range(496):
        rows.append(
            {
                "Company Name": f"Other Company {index}",
                "Industry": "Other",
                "Symbol": f"OTHER{index:03d}",
                "Series": "EQ",
                "ISIN Code": f"INZ000A{index:05d}",
            }
        )
    return pd.DataFrame(rows)


def _instrument_rows() -> list[dict[str, object]]:
    return [
        {
            "instrument_token": 1000 + index,
            "tradingsymbol": symbol,
            "name": symbol,
            "tick_size": 0.05,
            "lot_size": 1,
            "instrument_type": "EQ",
            "segment": "NSE",
            "exchange": "NSE",
        }
        for index, symbol in enumerate(PILOT_SYMBOLS)
    ]


class FakeKiteClient:
    def __init__(self, missing_symbol: str | None = None) -> None:
        self.missing_symbol = missing_symbol
        self.instrument_calls = 0
        self.history_calls: list[int] = []

    def instruments(self, exchange: str | None = None) -> list[dict[str, object]]:
        self.instrument_calls += 1
        assert exchange == "NSE"
        return _instrument_rows()

    def historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[dict[str, object]]:
        self.history_calls.append(instrument_token)
        assert interval == "day"
        assert continuous is False
        assert oi is False
        records = []
        for offset in range(3):
            if self.missing_symbol and instrument_token == 1000 and offset == 1:
                continue
            day = from_date + timedelta(days=offset)
            records.append(
                {
                    "date": day,
                    "open": 100.0,
                    "high": 103.0,
                    "low": 99.0,
                    "close": 102.0,
                    "volume": 10000.0,
                }
            )
        return records


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    universe_csv = tmp_path / "nifty500.csv"
    _universe_frame().to_csv(universe_csv, index=False)
    calendar_csv = tmp_path / "holidays.csv"
    calendar_csv.write_text("Date,Description\n", encoding="utf-8")
    return universe_csv, calendar_csv


def test_resolver_rejects_ambiguous_current_instrument_mapping() -> None:
    universe = pd.DataFrame(
        [
            {
                "symbol": symbol,
                "isin_code": f"INE000A000{index:02d}",
                "series": "EQ",
                "effective_date": "2026-09-30",
                "source": "official",
            }
            for index, symbol in enumerate(PILOT_SYMBOLS)
        ]
    )
    instruments = pd.DataFrame(_instrument_rows() + [_instrument_rows()[0]])

    with pytest.raises(ValueError, match="exactly one current"):
        _resolve_pilot_instruments(universe, instruments, PILOT_SYMBOLS)


def test_coverage_summary_reports_missing_sessions_without_filling() -> None:
    candles = pd.DataFrame(
        {"close": [10.0, 12.0]},
        index=pd.to_datetime(["2026-01-05", "2026-01-07"]),
    )
    expected = pd.bdate_range("2026-01-05", "2026-01-07")

    result = _coverage_summary(candles, expected, date(2026, 1, 5), date(2026, 1, 7))

    assert result["row_count"] == 2
    assert result["missing_expected_sessions"] == ["2026-01-06"]
    assert result["unexpected_returned_dates"] == []
    assert "2026-01-06" not in candles.index.strftime("%Y-%m-%d").tolist()


def test_five_symbol_pilot_writes_verified_manifest_and_parquet(tmp_path: Path) -> None:
    universe_csv, calendar_csv = _write_inputs(tmp_path)
    client = FakeKiteClient()
    data_root = tmp_path / "market_data"

    manifest_path, manifest = run_kite_daily_pilot(
        client,
        universe_csv=universe_csv,
        universe_effective_date=date(2026, 9, 30),
        universe_source="official archived NSE constituent CSV",
        calendar_csv=calendar_csv,
        calendar_source="official NSE test calendar",
        calendar_coverage_start=date(2026, 1, 5),
        calendar_coverage_end=date(2026, 1, 7),
        start=date(2026, 1, 5),
        end=date(2026, 1, 7),
        symbols=PILOT_SYMBOLS,
        data_root=data_root,
        chunk_days=365,
    )

    assert manifest_path.exists()
    assert manifest["pilot_status"] == "accepted"
    assert manifest["orders_endpoint_calls"] == 0
    assert manifest["adjustment_status"] == "provider_adjusted_unreconciled"
    assert len(manifest["symbols"]) == 5
    assert all(item["status"] == "accepted" for item in manifest["symbols"])
    assert all(item["readback_verified"] for item in manifest["symbols"])
    assert all(item["row_count"] == 3 for item in manifest["symbols"])
    assert client.instrument_calls == 1
    assert len(client.history_calls) == 5
    assert len(list((data_root / "parquet").rglob("snapshot=*.parquet"))) == 5


def test_pilot_marks_missing_session_incomplete_and_does_not_fill(tmp_path: Path) -> None:
    universe_csv, calendar_csv = _write_inputs(tmp_path)
    manifest_path, manifest = run_kite_daily_pilot(
        FakeKiteClient(missing_symbol="RELIANCE"),
        universe_csv=universe_csv,
        universe_effective_date=date(2026, 9, 30),
        universe_source="official archived NSE constituent CSV",
        calendar_csv=calendar_csv,
        calendar_source="official NSE test calendar",
        calendar_coverage_start=date(2026, 1, 5),
        calendar_coverage_end=date(2026, 1, 7),
        start=date(2026, 1, 5),
        end=date(2026, 1, 7),
        symbols=PILOT_SYMBOLS,
        data_root=tmp_path / "market_data",
        chunk_days=365,
    )

    reliance = next(item for item in manifest["symbols"] if item["symbol"] == "RELIANCE")
    assert manifest_path.exists()
    assert manifest["pilot_status"] == "failed_or_incomplete"
    assert reliance["status"] == "incomplete"
    assert reliance["missing_expected_sessions"] == ["2026-01-06"]
    assert reliance["row_count"] == 2
    assert reliance["readback_verified"] is True
