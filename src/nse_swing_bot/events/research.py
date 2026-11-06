"""Research-only composition of Phase 1 signals and point-in-time event diagnostics.

This module adds event context to a separate reporting frame. It never changes
or recalculates the underlying strategy signals.
"""

from __future__ import annotations

import pandas as pd

from nse_swing_bot.events.diagnostics import DIAGNOSTIC_COLUMNS

REQUIRED_SIGNAL_COLUMNS = frozenset({"signal"})
REQUIRED_EVENT_COLUMNS = frozenset(DIAGNOSTIC_COLUMNS)


def build_research_event_frame(
    signal_frame: pd.DataFrame,
    event_diagnostics: pd.DataFrame,
) -> pd.DataFrame:
    """Return a reporting-only frame with event diagnostics aligned by exact index.

    Both inputs must have unique, timezone-aware, identical indexes. The
    function appends only the declared event diagnostic columns, rejects
    collisions, and leaves both caller-owned frames untouched.

    This output is not an execution signal and must not be fed back into
    build_signal_frame or trade-management logic.
    """
    if not REQUIRED_SIGNAL_COLUMNS.issubset(signal_frame.columns):
        raise ValueError("signal_frame must contain the Phase 1 'signal' column")
    if not REQUIRED_EVENT_COLUMNS.issubset(event_diagnostics.columns):
        missing = sorted(REQUIRED_EVENT_COLUMNS.difference(event_diagnostics.columns))
        raise ValueError(f"event_diagnostics is missing required columns: {', '.join(missing)}")

    for name, frame in (
        ("signal_frame", signal_frame),
        ("event_diagnostics", event_diagnostics),
    ):
        if frame.index.has_duplicates:
            raise ValueError(f"{name} index must be unique")
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            raise ValueError(f"{name} index must be a timezone-aware DatetimeIndex")

    if not signal_frame.index.equals(event_diagnostics.index):
        raise ValueError(
            "signal_frame and event_diagnostics indexes must match exactly; "
            "implicit reindexing and nearest-time joins are not permitted"
        )

    collisions = set(signal_frame.columns).intersection(event_diagnostics.columns)
    if collisions:
        raise ValueError(
            f"research event columns collide with signal columns: {', '.join(sorted(collisions))}"
        )

    # Explicit column selection prevents unreviewed diagnostics from leaking
    # into the reporting contract.
    return pd.concat(
        [signal_frame.copy(), event_diagnostics.loc[:, list(DIAGNOSTIC_COLUMNS)].copy()],
        axis=1,
        verify_integrity=True,
    )
