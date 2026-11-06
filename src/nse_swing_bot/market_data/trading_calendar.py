"""Source-attributed NSE equity trading calendar.

Weekdays are only a starting point: official holidays are removed and explicitly
declared special sessions are added back. Calendar coverage is bounded so a
partial holiday file cannot silently validate dates outside its declared range.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class NSETradingCalendar:
    holidays: pd.DataFrame
    special_sessions: dict[date, str]
    source: str
    coverage_start: date
    coverage_end: date

    @classmethod
    def from_csv(
        cls,
        path: Path,
        source: str,
        coverage_start: date,
        coverage_end: date,
        special_sessions: dict[date, str] | None = None,
    ) -> NSETradingCalendar:
        if not source.strip():
            raise ValueError("official calendar source is required")
        if coverage_start > coverage_end:
            raise ValueError("calendar coverage_start must be on or before coverage_end")
        frame = pd.read_csv(path)
        columns = {column.lower(): column for column in frame.columns}
        date_column = columns.get("date")
        if date_column is None:
            raise ValueError("holiday CSV must contain a Date column")
        description_column = columns.get("description") or columns.get("holiday")
        dates = pd.to_datetime(frame[date_column], errors="raise").dt.date
        if dates.duplicated().any():
            raise ValueError("holiday CSV contains duplicate dates")
        if any(day < coverage_start or day > coverage_end for day in dates):
            raise ValueError("holiday date falls outside declared calendar coverage")
        descriptions = (
            frame[description_column].astype("string").fillna("")
            if description_column
            else pd.Series([""] * len(frame), dtype="string")
        )
        source_column = columns.get("source")
        sources = (
            frame[source_column].astype("string").fillna("").str.strip()
            if source_column
            else pd.Series([source.strip()] * len(frame), dtype="string")
        )
        if (sources == "").any():
            raise ValueError("every holiday row must retain a non-empty source")
        holidays = pd.DataFrame(
            {"date": dates, "description": descriptions, "source": sources}
        ).sort_values("date", ignore_index=True)
        special = dict(special_sessions or {})
        for day, event_source in special.items():
            if day < coverage_start or day > coverage_end:
                raise ValueError("special session falls outside declared calendar coverage")
            if not event_source.strip():
                raise ValueError("special session source is required")
        return cls(
            holidays=holidays,
            special_sessions=special,
            source=source.strip(),
            coverage_start=coverage_start,
            coverage_end=coverage_end,
        )

    def sessions(self, start: date, end: date) -> pd.DatetimeIndex:
        """Return expected NSE sessions, including explicitly listed special days."""
        if start > end:
            raise ValueError("start must be on or before end")
        if start < self.coverage_start or end > self.coverage_end:
            raise ValueError("requested dates exceed declared calendar coverage")
        weekdays = pd.bdate_range(start=start, end=end)
        holidays = set(pd.to_datetime(self.holidays["date"]).dt.normalize())
        regular = [day for day in weekdays if day.normalize() not in holidays]
        special = [
            pd.Timestamp(day)
            for day in self.special_sessions
            if start <= day <= end
        ]
        return pd.DatetimeIndex(sorted(set(regular).union(special)), name="date")


def load_special_sessions_csv(
    path: Path,
    coverage_start: date,
    coverage_end: date,
) -> dict[date, str]:
    """Load explicitly sourced special sessions from a dated CSV archive."""
    if coverage_start > coverage_end:
        raise ValueError("coverage_start must be on or before coverage_end")
    frame = pd.read_csv(path)
    columns = {column.lower(): column for column in frame.columns}
    date_column = columns.get("date")
    source_column = columns.get("source")
    if date_column is None or source_column is None:
        raise ValueError("special-session CSV must contain Date and Source columns")
    dates = pd.to_datetime(frame[date_column], errors="raise").dt.date
    if dates.duplicated().any():
        raise ValueError("special-session CSV contains duplicate dates")
    sources = frame[source_column].astype("string").fillna("").str.strip()
    if (sources == "").any():
        raise ValueError("every special-session row must retain a non-empty source")
    if any(day < coverage_start or day > coverage_end for day in dates):
        raise ValueError("special-session date falls outside declared calendar coverage")
    return dict(zip(dates, sources, strict=True))

