"""Verified, versioned corporate-action adjustment factors.

No event is inferred from prices. A verified source must supply explicit
adjustment factors. Adjustments are point-in-time: an action is only applied
when its ex-date is on or before the requested as-of date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class AdjustmentEvent:
    symbol: str
    ex_date: date
    price_factor: float
    volume_factor: float
    source_primary: str
    source_secondary: str
    verified: bool
    event_id: str


def apply_verified_adjustments(
    raw_candles: pd.DataFrame,
    events: list[AdjustmentEvent],
    symbol: str,
    as_of_date: date,
) -> pd.DataFrame:
    """Return an adjusted copy; raw input is never mutated.

    For each eligible action, the explicit factors apply only to candles
    strictly before its ex-date. Multiple verified actions compound.
    """
    result = raw_candles.copy()
    price_columns = ["open", "high", "low", "close"]
    required = set(price_columns + ["volume"])
    missing = required.difference(result.columns)
    if missing:
        raise ValueError(f"candle data missing columns: {', '.join(sorted(missing))}")

    eligible: list[AdjustmentEvent] = []
    for event in events:
        if event.symbol != symbol or event.ex_date > as_of_date:
            continue
        if not event.verified:
            raise ValueError(f"unverified corporate action blocks adjustment: {event.event_id}")
        if not event.source_primary.strip() or not event.source_secondary.strip():
            raise ValueError(f"corporate action lacks two source references: {event.event_id}")
        if not (0 < event.price_factor <= 1.5 and 0 < event.volume_factor <= 100):
            raise ValueError(f"invalid adjustment factors: {event.event_id}")
        eligible.append(event)

    if not eligible:
        return result

    index = pd.DatetimeIndex(pd.to_datetime(result.index))
    if index.tz is not None:
        index = index.tz_convert("Asia/Kolkata").tz_localize(None)
    dates = index.date

    for event in sorted(eligible, key=lambda item: item.ex_date):
        mask = dates < event.ex_date
        result.loc[mask, price_columns] = result.loc[mask, price_columns] * event.price_factor
        result.loc[mask, "volume"] = result.loc[mask, "volume"] * event.volume_factor

    return result
