"""Source-attributed NSE equity trading calendar.

Weekdays are only a starting point: official holidays are removed and explicitly
declared special sessions are added back. This avoids assuming every weekday is
a trading day or every weekend is closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class NSETradingCalendar:
    holidays: pd.DataFrame
    special_sessions: frozenset[date]
    source: str

    @classmethod
    def from_csv(
        cls,
        path: Path,
        source: str,
        special_sessions: set[date] | None = None,
    ) -> NSETradingCalendar:
        if not source.strip():
            raise ValueError("official calendar source is required")
        frame = pd.read_csv(path)
        columns = {column.lower(): column for column in frame.columns}
        date_column = columns.get("date")
        if date_column is None:
            raise ValueError("holiday CSV must contain a Date column")
        description_column = columns.get("description") or columns.get("holiday")
        dates = pd.to_datetime(frame[date_column], errors="raise").dt.date
        if dates.duplicated().any():
            raise ValueError("holiday CSV contains duplicate dates")
        descriptions = (
            frame[description_column].astype("string").fillna("")
            if description_column
            else pd.Series([""] * len(frame), dtype="string")
        )
        holidays = pd.DataFrame(
            {"date": dates, "description": descriptions, "source": source.strip()}
        ).sort_values("date", ignore_index=True)
        return cls(
            holidays=holidays,
            special_sessions=frozenset(special_sessions or set()),
            source=source.strip(),
        )

    def sessions(self, start: date, end: date) -> pd.DatetimeIndex:
        """Return expected NSE sessions, including explicitly listed special days."""
        if start > end:
            raise ValueError("start must be on or before end")
        weekdays = pd.bdate_range(start=start, end=end)
        holidays = set(pd.to_datetime(self.holidays["date"]).dt.normalize())
        regular = [day for day in weekdays if day.normalize() not in holidays]
        special = [
            pd.Timestamp(day)
            for day in self.special_sessions
            if start <= day <= end
        ]
        return pd.DatetimeIndex(sorted(set(regular).union(special)), name="date")
