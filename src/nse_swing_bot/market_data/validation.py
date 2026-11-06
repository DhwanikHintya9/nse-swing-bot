"""Fail-closed validation for daily OHLCV candles."""

from __future__ import annotations

import numpy as np
import pandas as pd

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


class CandleDataError(ValueError):
    """Invalid candle payload with the original rows retained for quarantine."""

    def __init__(self, reason: str, raw_candles: pd.DataFrame) -> None:
        super().__init__(reason)
        self.raw_candles = raw_candles.copy()


def validate_daily_candles(
    candles: pd.DataFrame,
    expected_sessions: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Validate, normalize, and sort candles without fabricating missing sessions."""
    missing = set(OHLCV_COLUMNS).difference(candles.columns)
    if missing:
        raise ValueError(f"candle data missing columns: {', '.join(sorted(missing))}")
    if candles.empty:
        raise ValueError("candle response is empty")

    result = candles[OHLCV_COLUMNS].copy()
    index = pd.DatetimeIndex(pd.to_datetime(candles.index, errors="raise"))
    if index.tz is not None:
        index = index.tz_convert("Asia/Kolkata").tz_localize(None)
    if index.isna().any():
        raise ValueError("candle dates contain invalid timestamps")
    result.index = index.normalize()
    result.index.name = "date"
    result = result.sort_index()

    if result.index.has_duplicates:
        raise ValueError("duplicate daily candle dates detected")
    for column in OHLCV_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="raise").astype("float64")
    values = result[OHLCV_COLUMNS].to_numpy(dtype="float64")
    if not np.isfinite(values).all():
        raise ValueError("candle data contains missing or non-finite OHLCV values")
    if (result[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (result["volume"] < 0).any():
        raise ValueError("volume cannot be negative")
    if (result["high"] < result[["open", "low", "close"]].max(axis=1)).any():
        raise ValueError("high is inconsistent with open, low, or close")
    if (result["low"] > result[["open", "high", "close"]].min(axis=1)).any():
        raise ValueError("low is inconsistent with open, high, or close")

    if expected_sessions is not None:
        sessions = pd.DatetimeIndex(expected_sessions)
        if sessions.tz is not None:
            sessions = sessions.tz_convert("Asia/Kolkata").tz_localize(None)
        sessions = sessions.normalize().unique().sort_values()
        missing_sessions = sessions.difference(result.index)
        if len(missing_sessions):
            dates = ", ".join(value.strftime("%Y-%m-%d") for value in missing_sessions[:10])
            raise ValueError(f"missing expected trading sessions: {dates}")

    return result
