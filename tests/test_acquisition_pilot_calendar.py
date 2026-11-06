from datetime import date
from pathlib import Path

import pandas as pd

from nse_swing_bot.market_data.trading_calendar import NSETradingCalendar


def test_archived_official_calendar_covers_default_pilot_window() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    calendar_path = (
        repository_root / "data/market_calendar/nse-equity-holidays-2025-2026.csv"
    )
    calendar = NSETradingCalendar.from_csv(
        calendar_path,
        source="NSE 2025 Capital Market circular and 2026 equity holiday page",
        coverage_start=date(2025, 1, 1),
        coverage_end=date(2026, 12, 31),
    )

    sessions = calendar.sessions(date(2025, 11, 6), date(2026, 11, 5))

    early_november = calendar.sessions(date(2025, 11, 4), date(2025, 11, 6))
    assert pd.Timestamp("2025-11-04") in early_november
    assert pd.Timestamp("2025-11-05") not in early_november
    assert pd.Timestamp("2025-11-06") in early_november
    assert pd.Timestamp("2026-01-15") not in sessions
    assert pd.Timestamp("2026-01-26") not in sessions
    assert pd.Timestamp("2026-11-05") in sessions


def test_muhurat_session_is_only_added_back_when_explicitly_sourced() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    calendar_path = (
        repository_root / "data/market_calendar/nse-equity-holidays-2025-2026.csv"
    )
    calendar = NSETradingCalendar.from_csv(
        calendar_path,
        source="NSE 2025 Capital Market circular and 2026 equity holiday page",
        coverage_start=date(2025, 1, 1),
        coverage_end=date(2026, 12, 31),
    )

    closed = calendar.sessions(date(2025, 10, 20), date(2025, 10, 22))
    with_muhurat = NSETradingCalendar.from_csv(
        calendar_path,
        source="NSE 2025 Capital Market circular and 2026 equity holiday page",
        coverage_start=date(2025, 1, 1),
        coverage_end=date(2026, 12, 31),
        special_sessions={date(2025, 10, 21): "NSE Circular 170/2024"},
    ).sessions(date(2025, 10, 20), date(2025, 10, 22))

    assert pd.Timestamp("2025-10-21") not in closed
    assert pd.Timestamp("2025-10-21") in with_muhurat
    assert pd.Timestamp("2025-10-22") not in with_muhurat
