from datetime import date

import pandas as pd
import pytest

from nse_swing_bot.market_data.nse_sources import (
    NIFTY_500_CSV_URL,
    acquire_and_save_nifty500_snapshot,
    download_nifty500_constituents,
)
from nse_swing_bot.market_data.trading_calendar import NSETradingCalendar


def test_nifty500_downloader_uses_official_source_and_records_effective_date() -> None:
    csv = b"Company Name,Symbol\nAlpha,AAA\nBeta,BBB\n"
    requested: list[str] = []

    def fake_download(url: str) -> bytes:
        requested.append(url)
        return csv

    result = download_nifty500_constituents(
        date(2026, 11, 4), downloader=fake_download, expected_count=2
    )
    assert requested == [NIFTY_500_CSV_URL]
    assert result["symbol"].tolist() == ["AAA", "BBB"]
    assert result["effective_date"].unique().tolist() == ["2026-11-04"]
    assert result["source"].unique().tolist() == [NIFTY_500_CSV_URL]


def test_nifty500_downloader_fails_closed_on_empty_or_wrong_size() -> None:
    with pytest.raises(ValueError, match="empty"):
        download_nifty500_constituents(
            date(2026, 11, 4), downloader=lambda _: b"", expected_count=2
        )
    with pytest.raises(ValueError, match="expected 2"):
        download_nifty500_constituents(
            date(2026, 11, 4),
            downloader=lambda _: b"Symbol\nAAA\n",
            expected_count=2,
        )


def test_acquired_nifty500_snapshot_is_immutable(tmp_path) -> None:
    payload = b"Symbol\nAAA\nBBB\n"
    path = acquire_and_save_nifty500_snapshot(
        tmp_path,
        date(2026, 11, 4),
        downloader=lambda _: payload,
        expected_count=2,
    )
    saved = pd.read_csv(path)
    assert saved["symbol"].tolist() == ["AAA", "BBB"]
    assert saved["source"].str.startswith("https://nsearchives.nseindia.com/").all()
    with pytest.raises(FileExistsError, match="overwrite"):
        acquire_and_save_nifty500_snapshot(
            tmp_path,
            date(2026, 11, 4),
            downloader=lambda _: payload,
            expected_count=2,
        )


def test_calendar_excludes_holidays_and_includes_special_weekend_session(tmp_path) -> None:
    path = tmp_path / "holidays.csv"
    pd.DataFrame(
        {
            "Date": ["2026-11-03", "2026-11-05"],
            "Description": ["Holiday A", "Holiday B"],
        }
    ).to_csv(path, index=False)
    calendar = NSETradingCalendar.from_csv(
        path,
        source="NSE official 2026 equity holiday circular",
        special_sessions={date(2026, 11, 8)},
    )

    sessions = calendar.sessions(date(2026, 11, 2), date(2026, 11, 9))
    assert sessions.strftime("%Y-%m-%d").tolist() == [
        "2026-11-02",
        "2026-11-04",
        "2026-11-06",
        "2026-11-08",
        "2026-11-09",
    ]


def test_calendar_requires_source_and_date_column(tmp_path) -> None:
    path = tmp_path / "bad.csv"
    pd.DataFrame({"Holiday": ["2026-01-01"]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="source"):
        NSETradingCalendar.from_csv(path, source="")
    with pytest.raises(ValueError, match="Date"):
        NSETradingCalendar.from_csv(path, source="NSE")
