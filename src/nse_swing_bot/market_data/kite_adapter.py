"""Thin adapter over the official Kite Connect Python client.

Authentication is injected by the caller. This module never performs an
interactive login, stores tokens, or places orders.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Protocol

import pandas as pd


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
    def __init__(self, client: KiteMarketClient) -> None:
        self._client = client

    def fetch_nse_instruments(self) -> list[dict[str, Any]]:
        """Fetch the current Kite instrument dump and leave filtering to the normalizer."""
        return self._client.instruments("NSE")

    def fetch_daily_candles(
        self,
        instrument_token: int,
        start: date,
        end: date,
        chunk_days: int = 365,
    ) -> pd.DataFrame:
        """Fetch daily candles in bounded, sequential chunks.

        The caller supplies the token from a current or historically cached
        instrument master. Chunking is conservative and configurable; no
        concurrency is used, so API pacing can be centrally controlled later.
        """
        if start > end:
            raise ValueError("start must be on or before end")
        if chunk_days < 1:
            raise ValueError("chunk_days must be positive")

        records: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=chunk_days - 1))
            from_dt = datetime.combine(cursor, time.min)
            to_dt = datetime.combine(chunk_end, time.max.replace(microsecond=0))
            chunk = self._client.historical_data(
                instrument_token=instrument_token,
                from_date=from_dt,
                to_date=to_dt,
                interval="day",
                continuous=False,
                oi=False,
            )
            records.extend(chunk)
            cursor = chunk_end + timedelta(days=1)

        if not records:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        frame = pd.DataFrame.from_records(records)
        if "date" not in frame.columns:
            raise ValueError("Kite historical response did not include candle dates")
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
        return frame.set_index("date")[["open", "high", "low", "close", "volume"]]
