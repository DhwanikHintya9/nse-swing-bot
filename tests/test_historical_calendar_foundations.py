from datetime import date
from pathlib import Path

import pandas as pd

from nse_swing_bot.market_data.trading_calendar import (
    NSETradingCalendar,
    load_special_sessions_csv,
)


def _calendar() -> NSETradingCalendar:
    root = Path(__file__).resolve().parents[1]
    calendar_dir = root / "data/market_calendar"
    start = date(2021, 1, 1)
    end = date(2026, 12, 31)
    special_sessions = load_special_sessions_csv(
        calendar_dir / "nse-equity-special-sessions-2021-2026.csv",
        start,
        end,
    )
    return NSETradingCalendar.from_csv(
        calendar_dir / "nse-equity-holidays-2021-2026.csv",
        source="NSE Capital Market equity holiday archive 2021-2026",
        coverage_start=start,
        coverage_end=end,
        special_sessions=special_sessions,
    )


def test_five_year_calendar_preserves_row_level_official_sources() -> None:
    calendar = _calendar()

    assert len(calendar.holidays) > 100
    assert calendar.holidays["source"].str.startswith("https://").all()
    sources = set(calendar.holidays["source"])
    assert any("CMTR46623" in source for source in sources)
    assert any("CMTR50560" in source for source in sources)
    assert any("CMTR54757" in source for source in sources)
    assert any("CMTR59722" in source for source in sources)
    assert any("CMTR65587" in source for source in sources)
    assert any("CMTR71775" in source for source in sources)


def test_five_year_calendar_adds_only_explicitly_sourced_special_sessions() -> None:
    calendar = _calendar()
    sessions = calendar.sessions(date(2021, 11, 6), date(2026, 11, 5))

    for special_day in (
        "2022-10-24",
        "2023-11-12",
        "2024-11-01",
        "2025-10-21",
        "2026-02-01",
    ):
        assert pd.Timestamp(special_day) in sessions

    for closed_day in (
        "2021-11-19",
        "2022-10-26",
        "2023-11-14",
        "2024-11-15",
        "2025-10-22",
        "2026-01-15",
        "2026-01-26",
    ):
        assert pd.Timestamp(closed_day) not in sessions

    assert pd.Timestamp("2023-11-11") not in sessions
    assert pd.Timestamp("2023-11-13") in sessions
    assert pd.Timestamp("2026-02-02") in sessions


def test_special_session_loader_rejects_duplicate_dates(tmp_path: Path) -> None:
    path = tmp_path / "special.csv"
    path.write_text(
        "Date,Description,Source\n"
        "2026-02-01,Budget session,https://example.test/one\n"
        "2026-02-01,Duplicate,https://example.test/two\n",
        encoding="utf-8",
    )

    try:
        load_special_sessions_csv(path, date(2026, 1, 1), date(2026, 12, 31))
    except ValueError as error:
        assert "duplicate dates" in str(error)
    else:
        raise AssertionError("duplicate special-session dates must be rejected")
