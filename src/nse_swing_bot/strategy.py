"""Phase 1 signal rules. This module never places or manages broker orders."""

from __future__ import annotations

import pandas as pd

from nse_swing_bot.indicators import sma, wilder_atr, wilder_rsi

MINIMUM_CANDLES = 250


def build_signal_frame(candles: pd.DataFrame) -> pd.DataFrame:
    """Return indicators and long-entry signals for completed daily candles.

    Input columns are lowercase: open, high, low, close, volume.
    The caller supplies completed, validated candles only.
    Volume average includes the current signal candle (20 observations total).
    """
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(candles.columns)
    if missing:
        raise ValueError(f"missing required columns: {', '.join(sorted(missing))}")
    if len(candles) < MINIMUM_CANDLES:
        raise ValueError(f"at least {MINIMUM_CANDLES} completed candles are required")
    if not candles.index.is_monotonic_increasing or candles.index.has_duplicates:
        raise ValueError("candles must have a strictly increasing, unique index")
    if candles[list(required)].isna().any().any():
        raise ValueError("candles contain missing OHLCV values")
    if (candles["volume"] < 0).any():
        raise ValueError("volume cannot be negative")
    if (candles["high"] < candles["low"]).any():
        raise ValueError("high cannot be below low")

    result = candles.copy()
    result["sma_50"] = sma(result["close"], 50)
    result["rsi_14"] = wilder_rsi(result["close"], 14)
    result["atr_14"] = wilder_atr(result, 14)
    result["volume_sma_20"] = result["volume"].rolling(20, min_periods=20).mean()
    result["relative_volume"] = result["volume"] / result["volume_sma_20"]

    result["trend_pass"] = result["close"] > result["sma_50"]
    result["rsi_pass"] = result["rsi_14"] < 45.0
    result["volume_pass"] = result["volume"] > result["volume_sma_20"]
    result["signal"] = (
        result["trend_pass"] & result["rsi_pass"] & result["volume_pass"]
    ).fillna(False)

    return result
