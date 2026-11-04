import numpy as np
import pandas as pd
import pytest

from nse_swing_bot.indicators import sma, true_range, wilder_atr, wilder_rsi


def test_sma_requires_full_window() -> None:
    result = sma(pd.Series([1.0, 2.0, 3.0]), 2)
    assert np.isnan(result.iloc[0])
    assert result.iloc[1] == pytest.approx(1.5)
    assert result.iloc[2] == pytest.approx(2.5)


def test_rsi_flat_series_is_fifty_after_seed() -> None:
    result = wilder_rsi(pd.Series([10.0] * 16), 14)
    assert result.iloc[:14].isna().all()
    assert result.iloc[14] == pytest.approx(50.0)
    assert result.iloc[15] == pytest.approx(50.0)


def test_rsi_no_losses_is_one_hundred() -> None:
    result = wilder_rsi(pd.Series(range(20), dtype="float64"), 14)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_no_gains_is_zero() -> None:
    result = wilder_rsi(pd.Series(range(20, 0, -1), dtype="float64"), 14)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_true_range_uses_previous_close_for_gaps() -> None:
    frame = pd.DataFrame(
        {"high": [11.0, 15.0], "low": [9.0, 12.0], "close": [10.0, 14.0]}
    )
    result = true_range(frame)
    assert result.iloc[0] == pytest.approx(2.0)
    assert result.iloc[1] == pytest.approx(5.0)


def test_atr_wilder_seed_and_recurrence() -> None:
    frame = pd.DataFrame(
        {
            "high": [11.0, 12.0, 13.0, 14.0],
            "low": [9.0, 10.0, 11.0, 12.0],
            "close": [10.0, 11.0, 12.0, 13.0],
        }
    )
    result = wilder_atr(frame, 3)
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[3] == pytest.approx(2.0)


def test_invalid_period_rejected() -> None:
    with pytest.raises(ValueError):
        wilder_rsi(pd.Series([1.0, 2.0]), 0)
