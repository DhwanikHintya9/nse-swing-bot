"""Orchestration for refreshing instruments and syncing one equity's daily candles."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from nse_swing_bot.market_data.instruments import (
    normalize_instrument_master,
    save_instrument_snapshot,
)
from nse_swing_bot.market_data.kite_adapter import KiteMarketDataAdapter
from nse_swing_bot.market_data.parquet_store import ParquetCandleStore
from nse_swing_bot.market_data.quarantine import DataQualityQuarantine
from nse_swing_bot.market_data.validation import CandleDataError, validate_daily_candles


class MarketDataService:
    """Coordinates paced acquisition, validation, quarantine, and append-only storage."""

    def __init__(
        self,
        adapter: KiteMarketDataAdapter,
        store: ParquetCandleStore,
        snapshot_root: Path,
        quarantine: DataQualityQuarantine | None = None,
    ) -> None:
        self.adapter = adapter
        self.store = store
        self.snapshot_root = snapshot_root
        self.quarantine = quarantine

    def refresh_instrument_master(self) -> tuple[pd.DataFrame, Path]:
        rows = self.adapter.fetch_nse_instruments()
        instruments = normalize_instrument_master(rows)
        snapshot = save_instrument_snapshot(instruments, self.snapshot_root)
        return instruments, snapshot

    def sync_daily_history(
        self,
        instrument: pd.Series,
        start: date,
        end: date,
        expected_sessions: pd.DatetimeIndex | None = None,
        chunk_days: int = 365,
    ) -> list[Path]:
        """Fetch one symbol; quarantine invalid responses instead of persisting as good data."""
        exchange = str(instrument["exchange"])
        symbol = str(instrument["tradingsymbol"])
        token = int(instrument["instrument_token"])
        if exchange != "NSE":
            raise ValueError("only NSE instruments are supported by this sync service")
        try:
            candles = self.adapter.fetch_daily_candles(
                token,
                start,
                end,
                chunk_days=chunk_days,
                expected_sessions=expected_sessions,
            )
        except CandleDataError as error:
            if self.quarantine is not None:
                self.quarantine.store(
                    f"{exchange}:{symbol}", start, end, str(error), error.raw_candles
                )
            raise

        try:
            validated = validate_daily_candles(
                candles, expected_sessions=expected_sessions
            )
        except (ValueError, TypeError, KeyError) as error:
            if self.quarantine is not None:
                self.quarantine.store(
                    f"{exchange}:{symbol}", start, end, str(error), candles
                )
            raise
        return self.store.write_snapshot(f"{exchange}:{symbol}", validated)
