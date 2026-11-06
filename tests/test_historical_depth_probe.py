from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from nse_swing_bot.market_data.acquisition_manifest import verify_acquisition_manifest
from nse_swing_bot.market_data.depth_probe import run_kite_historical_depth_probe

SYMBOLS = ["RELIANCE", "HDFCBANK", "INFY", "SUNPHARMA", "LT"]


def _inputs(tmp_path: Path) -> Path:
    rows = []
    for index, symbol in enumerate(SYMBOLS):
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
    path = tmp_path / "nifty500.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


class HistoricalProbeClient:
    def __init__(self) -> None:
        self.history_calls: list[tuple[int, datetime, datetime]] = []

    def instruments(self, exchange: str | None = None) -> list[dict[str, object]]:
        assert exchange == "NSE"
        return [
            {
                "instrument_token": 2000 + index,
                "tradingsymbol": symbol,
                "name": symbol,
                "tick_size": 0.05,
                "lot_size": 1,
                "instrument_type": "EQ",
                "segment": "NSE",
                "exchange": "NSE",
            }
            for index, symbol in enumerate(SYMBOLS)
        ]

    def historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[dict[str, object]]:
        assert interval == "day"
        assert continuous is False
        assert oi is False
        self.history_calls.append((instrument_token, from_date, to_date))
        return [
            {
                "date": from_date + timedelta(days=offset),
                "open": 100.0,
                "high": 103.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 10000,
            }
            for offset in (0, 1, 2)
        ]


def test_historical_depth_probe_records_availability_without_claiming_completeness(
    tmp_path: Path,
) -> None:
    universe_csv = _inputs(tmp_path)
    client = HistoricalProbeClient()
    data_root = tmp_path / "depth_probe"

    manifest_path, manifest = run_kite_historical_depth_probe(
        client,
        universe_csv=universe_csv,
        universe_effective_date=date(2026, 9, 30),
        universe_source="official archived NSE constituent CSV",
        start=date(2021, 11, 6),
        end=date(2022, 11, 5),
        symbols=SYMBOLS,
        data_root=data_root,
        chunk_days=365,
    )

    assert manifest_path.exists()
    assert verify_acquisition_manifest(manifest)
    assert manifest["probe_status"] == "completed"
    assert manifest["read_only"] is True
    assert manifest["orders_endpoint_calls"] == 0
    assert manifest["adjustment_status"] == "provider_adjusted_unreconciled"
    assert len(manifest["symbols"]) == 5
    assert all(item["status"] == "data_returned" for item in manifest["symbols"])
    assert all(item["returned_rows"] == 3 for item in manifest["symbols"])
    assert all(item["earliest_returned_date"] == "2021-11-06" for item in manifest["symbols"])
    assert all(item["latest_returned_date"] == "2021-11-08" for item in manifest["symbols"])
    assert len(client.history_calls) == 5
    assert not list(data_root.rglob("snapshot=*.parquet"))
    assert any("not a completeness" in note for note in manifest["interpretation"])
