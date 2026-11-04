"""Deterministic technical indicators used by every execution mode."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average, requiring a complete rolling window."""
    _validate_period(period)
    return series.astype("float64").rolling(window=period, min_periods=period).mean()


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI with arithmetic-mean seed and Wilder recursive smoothing.

    Edge cases: no losses -> 100, no gains -> 0, no movement -> 50.
    The first value is emitted after period price changes are available.
    """
    _validate_period(period)
    prices = close.astype("float64")
    delta = prices.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)

    avg_gain = pd.Series(np.nan, index=prices.index, dtype="float64")
    avg_loss = pd.Series(np.nan, index=prices.index, dtype="float64")

    if len(prices) <= period:
        return pd.Series(np.nan, index=prices.index, dtype="float64", name=f"rsi_{period}")

    avg_gain.iloc[period] = gains.iloc[1 : period + 1].mean()
    avg_loss.iloc[period] = losses.iloc[1 : period + 1].mean()

    for i in range(period + 1, len(prices)):
        avg_gain.iloc[i] = ((period - 1) * avg_gain.iloc[i - 1] + gains.iloc[i]) / period
        avg_loss.iloc[i] = ((period - 1) * avg_loss.iloc[i - 1] + losses.iloc[i]) / period

    denominator = avg_gain + avg_loss
    result = 100.0 * avg_gain / denominator
    result = result.mask((avg_gain > 0) & (avg_loss == 0), 100.0)
    result = result.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
    result = result.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
    result.name = f"rsi_{period}"
    return result


def true_range(frame: pd.DataFrame) -> pd.Series:
    """True range using high, low, and previous close."""
    _require_columns(frame, {"high", "low", "close"})
    high = frame["high"].astype("float64")
    low = frame["low"].astype("float64")
    previous_close = frame["close"].astype("float64").shift(1)
    ranges = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    )
    result = ranges.max(axis=1, skipna=True)
    result.name = "true_range"
    return result


def wilder_atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ATR: mean seed of first period true ranges, then Wilder recursion."""
    _validate_period(period)
    ranges = true_range(frame)
    result = pd.Series(np.nan, index=frame.index, dtype="float64", name=f"atr_{period}")

    if len(ranges) < period:
        return result

    result.iloc[period - 1] = ranges.iloc[:period].mean()
    for i in range(period, len(ranges)):
        result.iloc[i] = ((period - 1) * result.iloc[i - 1] + ranges.iloc[i]) / period

    return result


def _validate_period(period: int) -> None:
    if not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")


def _require_columns(frame: pd.DataFrame, required: set[str]) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {', '.join(sorted(missing))}")
