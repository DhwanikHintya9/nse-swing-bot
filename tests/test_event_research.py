import numpy as np
import pandas as pd
import pytest

from nse_swing_bot.events.diagnostics import DIAGNOSTIC_COLUMNS, build_event_diagnostics
from nse_swing_bot.events.evidence import (
    EventDirection,
    EventTaxonomy,
    EvidenceAdmissionResult,
)
from nse_swing_bot.events.intelligence import EventIntelligenceRecord
from nse_swing_bot.events.research import build_research_event_frame
from nse_swing_bot.strategy import MINIMUM_CANDLES, build_signal_frame


def sample_signal_frame() -> pd.DataFrame:
    index = pd.date_range(
        "2026-01-01", periods=MINIMUM_CANDLES, freq="D", tz="Asia/Kolkata"
    )
    close = np.linspace(100.0, 150.0, MINIMUM_CANDLES)
    candles = pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(MINIMUM_CANDLES, 1_000_000.0),
        },
        index=index,
    )
    return build_signal_frame(candles)


def test_research_frame_preserves_phase_one_signals_and_inputs() -> None:
    signals = sample_signal_frame()
    decisions = signals.index[-3:]
    event = EventIntelligenceRecord(
        event_id="evt-1",
        symbol="RELIANCE",
        event_class=EventTaxonomy.FINANCIAL_RESULTS,
        event_subclass="quarterly_results",
        announced_at=decisions[0].to_pydatetime(),
        effective_at=None,
        direction=EventDirection.UNKNOWN,
    )
    admission = {"evt-1": EvidenceAdmissionResult(True, (), ("evidence-1",))}
    diagnostics = build_event_diagnostics(
        "RELIANCE", decisions, [event], admission
    )
    signals_before = signals.copy(deep=True)
    diagnostics_before = diagnostics.copy(deep=True)

    result = build_research_event_frame(signals.loc[decisions], diagnostics)

    pd.testing.assert_frame_equal(signals, signals_before)
    pd.testing.assert_frame_equal(diagnostics, diagnostics_before)
    pd.testing.assert_series_equal(result["signal"], signals.loc[decisions]["signal"])
    pd.testing.assert_frame_equal(
        result.loc[:, signals.columns],
        signals.loc[decisions],
    )
    assert result["admitted_event_count"].tolist() == [1, 1, 1]


def test_research_frame_rejects_misaligned_timestamps() -> None:
    signals = sample_signal_frame().tail(3)
    diagnostics = pd.DataFrame(
        {"admitted_event_count": [0, 0, 0]},
        index=signals.index + pd.Timedelta(minutes=1),
    )
    diagnostics = diagnostics.reindex(columns=[
        "admitted_event_count",
        "event_count_7d",
        "event_count_30d",
        "days_to_next_effective_event",
        "has_high_materiality_event_30d",
        "positive_event_count_30d",
        "negative_event_count_30d",
        "mixed_event_count_30d",
        "unassessed_impact_count_30d",
        "taxonomy_counts_30d",
        "admitted_event_ids",
    ])
    with pytest.raises(ValueError, match="indexes must match exactly"):
        build_research_event_frame(signals, diagnostics)


def test_research_frame_rejects_missing_event_columns() -> None:
    signals = sample_signal_frame().tail(1)
    with pytest.raises(ValueError, match="missing required columns"):
        build_research_event_frame(signals, pd.DataFrame(index=signals.index))


def test_research_frame_rejects_naive_timestamps() -> None:
    signals = sample_signal_frame().tail(1)
    signals.index = signals.index.tz_localize(None)
    diagnostics = pd.DataFrame(columns=DIAGNOSTIC_COLUMNS, index=signals.index)
    with pytest.raises(ValueError, match="timezone-aware"):
        build_research_event_frame(signals, diagnostics)


def test_research_frame_rejects_column_collisions() -> None:
    signals = sample_signal_frame().tail(1)
    diagnostics = build_event_diagnostics("RELIANCE", signals.index, [], {})
    signals["event_count_7d"] = 999
    with pytest.raises(ValueError, match="collide"):
        build_research_event_frame(signals, diagnostics)
