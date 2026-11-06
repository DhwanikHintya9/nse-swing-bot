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
from nse_swing_bot.market_data.validation import CandleDataError, validate_daily_candles


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

    @staticmethod
    def _frame_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
        try:
            raw = pd.DataFrame.from_records(records)
        except (TypeError, ValueError) as error:
            raise CandleDataError(
                f"malformed Kite historical response: {error}", pd.DataFrame()
            ) from error
        if "date" not in raw.columns:
            raise CandleDataError("Kite historical response did not include candle dates", raw)
        try:
            raw["date"] = pd.to_datetime(raw["date"], errors="raise")
            return raw.set_index("date")
        except (TypeError, ValueError, KeyError) as error:
            raise CandleDataError(f"invalid candle date payload: {error}", raw) from error

    @staticmethod
    def _sessions_for_chunk(
        expected_sessions: pd.DatetimeIndex | None, start: date, end: date
    ) -> pd.DatetimeIndex | None:
        if expected_sessions is None:
            return None
        sessions = pd.DatetimeIndex(expected_sessions)
        if sessions.tz is not None:
            sessions = sessions.tz_convert("Asia/Kolkata").tz_localize(None)
        sessions = sessions.normalize()
        lower, upper = pd.Timestamp(start), pd.Timestamp(end)
        return sessions[(sessions >= lower) & (sessions <= upper)]

    def _validate_chunk(
        self,
        records: list[dict[str, Any]],
        start: date,
        end: date,
        expected_sessions: pd.DatetimeIndex | None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        raw_frame = self._frame_from_records(records)
        try:
            validated = validate_daily_candles(
                raw_frame,
                expected_sessions=self._sessions_for_chunk(expected_sessions, start, end),
            )
        except (ValueError, TypeError, KeyError) as error:
            raise CandleDataError(str(error), raw_frame) from error
        return raw_frame, validated

    def fetch_daily_candles(
        self,
        instrument_token: int,
        start: date,
        end: date,
        chunk_days: int = 365,
        expected_sessions: pd.DatetimeIndex | None = None,
    ) -> pd.DataFrame:
        """Fetch sequentially; only validated chunks are eligible for checkpoint reuse."""
        if instrument_token <= 0:
            raise ValueError("instrument_token must be positive")
        if start > end:
            raise ValueError("start must be on or before end")
        if chunk_days < 1:
            raise ValueError("chunk_days must be positive")

        validated_chunks: list[pd.DataFrame] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=chunk_days - 1))
            chunk_records = None
            if self._checkpoints is not None:
                try:
                    chunk_records = self._checkpoints.load(
                        instrument_token, cursor, chunk_end, chunk_days
                    )
                except (ValueError, OSError):
                    # Corrupt or unreadable checkpoints are cache misses, not fatal data.
                    self._checkpoints.delete(instrument_token, cursor, chunk_end, chunk_days)
                    chunk_records = None

            validated = None
            if chunk_records is not None:
                try:
                    _, validated = self._validate_chunk(
                        chunk_records, cursor, chunk_end, expected_sessions
                    )
                except CandleDataError:
                    # A bad cache entry must never poison every future sync.
                    self._checkpoints.delete(instrument_token, cursor, chunk_end, chunk_days)
                    chunk_records = None

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
                try:
                    _, validated = self._validate_chunk(
                        chunk_records, cursor, chunk_end, expected_sessions
                    )
                except CandleDataError:
                    if self._checkpoints is not None:
                        self._checkpoints.delete(
                            instrument_token, cursor, chunk_end, chunk_days
                        )
                    raise
                if self._checkpoints is not None:
                    normalized_records = validated.reset_index().to_dict(orient="records")
                    self._checkpoints.save(
                        instrument_token, cursor, chunk_end, chunk_days, normalized_records
                    )

            assert validated is not None
            validated_chunks.append(validated)
            cursor = chunk_end + timedelta(days=1)

        if not validated_chunks:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return pd.concat(validated_chunks).sort_index()
