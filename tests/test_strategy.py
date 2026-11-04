import numpy as np
import pandas as pd
import pytest

from nse_swing_bot.strategy import MINIMUM_CANDLES, build_signal_frame


def sample_candles(rows: int = MINIMUM_CANDLES) -> pd.DataFrame:
    index = pd.bdate_range("2020-01-01", periods=rows)
    close = np.linspace(100.0, 150.0, rows)
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(rows, 1_000_000.0),
        },
        index=index,
    )


def test_signal_frame_contains_expected_columns() -> None:
    result = build_signal_frame(sample_candles())
    assert {"sma_50", "rsi_14", "atr_14", "volume_sma_20", "signal"} <= set(result.columns)
    assert result["signal"].dtype == bool


def test_volume_average_includes_current_candle() -> None:
    candles = sample_candles()
    candles.iloc[-1, candles.columns.get_loc("volume")] = 2_000_000.0
    result = build_signal_frame(candles)
    expected = candles["volume"].tail(20).mean()
    assert result["volume_sma_20"].iloc[-1] == pytest.approx(expected)


def test_insufficient_history_is_rejected() -> None:
    with pytest.raises(ValueError, match="250"):
        build_signal_frame(sample_candles(249))


def test_duplicate_dates_are_rejected() -> None:
    candles = sample_candles()
    candles.index = list(candles.index[:-1]) + [candles.index[-2]]
    with pytest.raises(ValueError, match="unique"):
        build_signal_frame(candles)
