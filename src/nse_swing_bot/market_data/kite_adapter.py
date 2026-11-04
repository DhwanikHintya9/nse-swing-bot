"""Thin adapter over the official Kite Connect Python client.

Authentication is injected by the caller. This module never performs an
interactive login, stores tokens, or places orders.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Protocol

import pandas as pd

from nse_swing_bot.market_data.checkpoints import JsonChunkCheckpointStore
from nse_swing_bot.market_data.request_control import KiteRequestExecutor


class KiteMarketClient(Protocol):
    def instruments(self, exchange: str | None = None) -> list[dict[str, Any]]: ...
    def historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[dict[str, Any]]: ...


class KiteMarketDataAdapter:
    def __init__(
        self,
        client: KiteMarketClient,
        request_executor: KiteRequestExecutor | None = None,
        checkpoint_store: JsonChunkCheckpointStore | None = None,
    ) -> None:
        self._client = client
        self._requests = request_executor or KiteRequestExecutor()
        self._checkpoints = checkpoint_store

    def fetch_nse_instruments(self) -> list[dict[str, Any]]:
        """Fetch the current Kite instrument dump with the general endpoint limit."""
        return self._requests.call("other", lambda: self._client.instruments("NSE"))

    def fetch_daily_candles(
        self,
        instrument_token: int,
        start: date,
        end: date,
        chunk_days: int = 365,
    ) -> pd.DataFrame:
        """Fetch daily candles sequentially, resuming from durable completed chunks."""
        if start > end:
            raise ValueError("start must be on or before end")
        if chunk_days < 1:
            raise ValueError("chunk_days must be positive")

        records: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=chunk_days - 1))
            chunk_records = (
                self._checkpoints.load(instrument_token, cursor, chunk_end, chunk_days)
                if self._checkpoints is not None
                else None
            )
            if chunk_records is None:
                from_dt = datetime.combine(cursor, time.min)
                to_dt = datetime.combine(chunk_end, time.max.replace(microsecond=0))
                chunk_records = self._requests.call(
                    "historical",
                    lambda from_dt=from_dt, to_dt=to_dt: self._client.historical_data(
                        instrument_token=instrument_token,
                        from_date=from_dt,
                        to_date=to_dt,
                        interval="day",
                        continuous=False,
                        oi=False,
                    ),
                )
                if self._checkpoints is not None:
                    self._checkpoints.save(
                        instrument_token, cursor, chunk_end, chunk_days, chunk_records
                    )
            records.extend(chunk_records)
            cursor = chunk_end + timedelta(days=1)

        if not records:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        frame = pd.DataFrame.from_records(records)
        if "date" not in frame.columns:
            raise ValueError("Kite historical response did not include candle dates")
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
        return frame.set_index("date")[["open", "high", "low", "close", "volume"]]
