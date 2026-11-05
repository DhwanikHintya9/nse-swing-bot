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
    csv = (
        b"Company Name,Industry,Symbol,Series,ISIN Code\n"
        b"Alpha,Technology,AAA,EQ,INE000A01001\n"
        b"Beta,Banking,BBB,BE,INE000B01001\n"
    )
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
    assert result.loc[result["symbol"] == "BBB", "series"].item() == "BE"
    assert result.loc[result["symbol"] == "AAA", "isin_code"].item() == "INE000A01001"
    assert result.loc[result["symbol"] == "AAA", "company_name"].item() == "Alpha"


def test_nifty500_downloader_fails_closed_on_empty_or_wrong_size() -> None:
    with pytest.raises(ValueError, match="empty"):
        download_nifty500_constituents(
            date(2026, 11, 4), downloader=lambda _: b"", expected_count=2
        )
    with pytest.raises(ValueError, match="expected 2"):
        download_nifty500_constituents(
            date(2026, 11, 4),
            downloader=lambda _: (
                b"Company Name,Industry,Symbol,Series,ISIN Code\n"
                b"Alpha,Technology,AAA,EQ,INE000A01001\n"
            ),
            expected_count=2,
        )


def test_acquired_nifty500_snapshot_is_immutable(tmp_path) -> None:
    payload = (
        b"Company Name,Industry,Symbol,Series,ISIN Code\n"
        b"Alpha,Technology,AAA,EQ,INE000A01001\n"
        b"Beta,Banking,BBB,RR,INE000B01001\n"
    )
    path = acquire_and_save_nifty500_snapshot(
        tmp_path,
        date(2026, 11, 4),
        downloader=lambda _: payload,
        expected_count=2,
    )
    saved = pd.read_csv(path)
    assert saved["symbol"].tolist() == ["AAA", "BBB"]
    assert saved["series"].tolist() == ["EQ", "RR"]
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
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 12, 31),
        special_sessions={date(2026, 11, 8): "NSE Muhurat trading circular 2026"},
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
        NSETradingCalendar.from_csv(
            path, source="", coverage_start=date(2026, 1, 1), coverage_end=date(2026, 12, 31)
        )
    with pytest.raises(ValueError, match="Date"):
        NSETradingCalendar.from_csv(
            path, source="NSE", coverage_start=date(2026, 1, 1), coverage_end=date(2026, 12, 31)
        )


def test_calendar_fails_closed_outside_declared_coverage(tmp_path) -> None:
    path = tmp_path / "holidays.csv"
    pd.DataFrame({"Date": ["2026-11-03"]}).to_csv(path, index=False)
    calendar = NSETradingCalendar.from_csv(
        path,
        source="NSE official 2026 equity holiday circular",
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 12, 31),
    )
    with pytest.raises(ValueError, match="coverage"):
        calendar.sessions(date(2025, 12, 31), date(2026, 1, 2))


@pytest.mark.parametrize(
    "csv, message",
    [
        (
            b"Company Name,Industry,Symbol,Series,ISIN Code\n"
            b"Alpha,Tech,AAA,EQ,INE000A01001\n"
            b"Beta,Tech,AAA,EQ,INE000B01001\n",
            "duplicate symbols",
        ),
        (
            b"Company Name,Industry,Symbol,Series,ISIN Code\n"
            b"Alpha,Tech,AAA,EQ,INE000A01001\n"
            b"Beta,Tech, ,EQ,INE000B01001\n",
            "blank or missing symbols",
        ),
    ],
)
def test_nifty500_downloader_rejects_duplicate_and_blank_symbols(csv, message) -> None:
    with pytest.raises(ValueError, match=message):
        download_nifty500_constituents(
            date(2026, 11, 4), downloader=lambda _: csv, expected_count=2
        )


def test_archived_2026_nse_calendar_includes_official_holidays_and_muhurat_session() -> None:
    from pathlib import Path

    calendar_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "market_calendar"
        / "nse-equity-holidays-2026.csv"
    )
    calendar = NSETradingCalendar.from_csv(
        calendar_path,
        source="NSE India Market Timings & Holidays, verified 2026-11-05",
        coverage_start=date(2026, 1, 1),
        coverage_end=date(2026, 12, 31),
        special_sessions={
            date(2026, 11, 8): "NSE Circular NSE/CMTR/76941 dated 2026-10-19"
        },
    )

    assert len(calendar.holidays) == 16
    sessions = calendar.sessions(date(2026, 11, 7), date(2026, 11, 11))
    assert sessions.strftime("%Y-%m-%d").tolist() == [
        "2026-11-08",
        "2026-11-09",
        "2026-11-11",
    ]


def test_archived_nifty500_snapshot_matches_september_2026_reconstitution() -> None:
    from pathlib import Path

    from nse_swing_bot.market_data.instruments import normalize_nifty500_constituents

    source_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "universe"
        / "source"
        / "nse-nifty500-captured-2026-11-05.csv"
    )
    source = pd.read_csv(source_path, skip_blank_lines=False)
    normalized = normalize_nifty500_constituents(
        source,
        effective_date=date(2026, 9, 30),
        source_name=NIFTY_500_CSV_URL,
        expected_count=501,
    )

    assert len(normalized) == 501
    assert normalized["effective_date"].eq("2026-09-30").all()
    assert normalized["series"].value_counts().to_dict() == {
        "EQ": 496,
        "RR": 3,
        "BE": 2,
    }
    assert normalized["isin_code"].nunique() == 501

    additions = {
        "AETHER", "AVANTIFEED", "AZAD", "BAGMANE", "BHARATCOAL", "BBOX",
        "BIRET", "CMPDI", "CLEANMAX", "CUPID", "EMBASSY", "FRACTAL",
        "INOXINDIA", "KIRLOSBROS", "KSB", "MTARTECH", "PRIVISCL",
        "RUBICON", "SANSERA", "SHRIPISTON", "STLTECH", "TDPOWERSYS",
        "THANGAMAYL", "VAML", "VISL", "VOGL", "VEDPOWER",
    }
    exclusions = {
        "3MINDIA", "ABFRL", "ABLBL", "BAYERCROP", "BIKAJI", "BLUEDART",
        "BLUEJET", "BBTC", "MAPMYINDIA", "CHALET", "DCMSHRIRAM", "ERIS",
        "GODIGIT", "INDGN", "JSWDULUX", "JUBLPHARMA", "LATENTVIEW",
        "THELEELA", "NEWGEN", "NIVABUPA", "PFIZER", "SAPPHIRE",
        "SAREGAMA", "SBFC", "SONATSOFTW", "SPLPETRO", "TRAVELFOOD",
    }
    published_symbols = set(normalized["symbol"])
    assert additions <= published_symbols
    assert exclusions.isdisjoint(published_symbols)


def test_acquire_and_save_uses_verified_501_row_default(tmp_path) -> None:
    from pathlib import Path

    source_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "universe"
        / "source"
        / "nse-nifty500-captured-2026-11-05.csv"
    )
    saved_path = acquire_and_save_nifty500_snapshot(
        tmp_path,
        date(2026, 9, 30),
        downloader=lambda _: source_path.read_bytes(),
    )
    saved = pd.read_csv(saved_path)
    assert len(saved) == 501
    assert {"company_name", "industry", "series", "isin_code"} <= set(saved.columns)


def test_nse_downloader_retries_network_timeout_and_uses_browser_headers(monkeypatch) -> None:
    from urllib.error import URLError

    from nse_swing_bot.market_data import nse_sources

    sleeps: list[float] = []
    requests = []

    class FakeHeaders:
        def get_content_type(self):
            return "text/csv"

    class FakeResponse:
        status = 200
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"Company Name,Industry,Symbol,Series,ISIN Code\n"

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        if len(requests) == 1:
            raise URLError("read timed out")
        return FakeResponse()

    monkeypatch.setattr(nse_sources, "urlopen", fake_urlopen)
    monkeypatch.setattr(nse_sources.time, "sleep", sleeps.append)

    assert nse_sources._download_bytes(NIFTY_500_CSV_URL).startswith(b"Company Name")
    assert len(requests) == 2
    assert requests[0][1] == 60
    assert requests[0][0].get_header("User-agent") == nse_sources.NSE_USER_AGENT
    assert requests[0][0].get_header("Accept").startswith("text/csv")
    assert sleeps == [1.0]


def test_nse_downloader_rejects_html_instead_of_parsing_error_page(monkeypatch) -> None:
    from nse_swing_bot.market_data import nse_sources

    class FakeHeaders:
        def get_content_type(self):
            return "text/html"

    class FakeResponse:
        status = 200
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"<html>blocked</html>"

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        return FakeResponse()

    monkeypatch.setattr(nse_sources, "urlopen", fake_urlopen)
    with pytest.raises(ValueError, match="unexpected content type"):
        nse_sources._download_bytes(NIFTY_500_CSV_URL)
    assert len(calls) == 1


def test_nse_downloader_does_not_retry_permanent_http_errors(monkeypatch) -> None:
    from urllib.error import HTTPError

    from nse_swing_bot.market_data import nse_sources

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        raise HTTPError(NIFTY_500_CSV_URL, 403, "Forbidden", {}, None)

    monkeypatch.setattr(nse_sources, "urlopen", fake_urlopen)
    with pytest.raises(HTTPError, match="Forbidden"):
        nse_sources._download_bytes(NIFTY_500_CSV_URL)
    assert len(calls) == 1


def test_strategy_series_filter_requires_explicit_policy_and_preserves_source_universe() -> None:
    from pathlib import Path

    from nse_swing_bot.market_data.instruments import (
        normalize_nifty500_constituents,
        select_constituents_by_series,
    )

    source_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "universe"
        / "source"
        / "nse-nifty500-captured-2026-11-05.csv"
    )
    source = pd.read_csv(source_path, skip_blank_lines=False)
    universe = normalize_nifty500_constituents(
        source, date(2026, 9, 30), NIFTY_500_CSV_URL, expected_count=501
    )

    eq_only = select_constituents_by_series(universe, {"EQ"})
    eq_and_be = select_constituents_by_series(universe, {"EQ", "BE"})
    assert len(universe) == 501
    assert len(eq_only) == 496
    assert set(eq_only["series"]) == {"EQ"}
    assert len(eq_and_be) == 498
    assert len(universe) == 501

    with pytest.raises(ValueError, match="explicit series"):
        select_constituents_by_series(universe, set())

    with pytest.raises(ValueError, match="did not match"):
        select_constituents_by_series(universe, {"EQQ"})
