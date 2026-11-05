"""Official NSE index constituent source adapters.

The source is the CSV linked from NSE's Nifty 500 index page. Downloads are
injected in tests; callers must assign the date on which the snapshot became
effective and retain the returned provenance.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from email.utils import parsedate_to_datetime
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from nse_swing_bot.market_data.instruments import (
    normalize_nifty500_constituents,
    save_nifty500_snapshot,
)

NIFTY_500_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
NIFTY_500_REQUIRED_COLUMNS = {"company name", "industry", "symbol", "series", "isin code"}
# Verified against the official NSE CSV response on 2026-11-05. Keep this
# explicit so an unexpected membership-count change fails closed for review.
NIFTY_500_EXPECTED_COUNT = 501
NSE_DOWNLOAD_TIMEOUT_SECONDS = 60
NSE_DOWNLOAD_MAX_ATTEMPTS = 3
NSE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/156.0.0.0 Safari/537.36"
)
TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}


def download_nifty500_constituents(
    effective_date: date,
    downloader: Callable[[str], bytes] | None = None,
    expected_count: int = NIFTY_500_EXPECTED_COUNT,
) -> pd.DataFrame:
    """Download and validate the official Nifty 500 CSV.

    No stale local fallback is attempted. Network or schema errors propagate so
    the caller can keep the previous approved snapshot and alert an operator.
    """
    fetch = downloader or _download_bytes
    payload = fetch(NIFTY_500_CSV_URL)
    if not payload:
        raise ValueError("NSE Nifty 500 download returned an empty response")
    frame = pd.read_csv(BytesIO(payload), skip_blank_lines=False)
    available_columns = {str(column).strip().lower() for column in frame.columns}
    missing_columns = NIFTY_500_REQUIRED_COLUMNS.difference(available_columns)
    if missing_columns:
        raise ValueError(
            "NSE Nifty 500 CSV missing columns: " + ", ".join(sorted(missing_columns))
        )
    return normalize_nifty500_constituents(
        frame,
        effective_date=effective_date,
        source_name=NIFTY_500_CSV_URL,
        expected_count=expected_count,
    )


def acquire_and_save_nifty500_snapshot(
    root: Path,
    effective_date: date,
    downloader: Callable[[str], bytes] | None = None,
    expected_count: int = NIFTY_500_EXPECTED_COUNT,
) -> Path:
    """Acquire the official list and persist a dated immutable snapshot."""
    constituents = download_nifty500_constituents(
        effective_date, downloader=downloader, expected_count=expected_count
    )
    return save_nifty500_snapshot(constituents, root)


def _retry_after_seconds(error: HTTPError, attempt: int) -> float:
    value = error.headers.get("Retry-After") if error.headers else None
    if value:
        try:
            return min(max(float(value), 0.0), 30.0)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    return 1.0
                from datetime import UTC, datetime

                return min(max((retry_at - datetime.now(UTC)).total_seconds(), 0.0), 30.0)
            except (TypeError, ValueError, OverflowError):
                pass
    return float(2**attempt)


def _download_bytes(url: str) -> bytes:
    """Fetch CSV with a browser-compatible request and bounded transient retries."""
    request = Request(
        url,
        headers={
            "User-Agent": NSE_USER_AGENT,
            "Accept": "text/csv,application/csv;q=0.9,*/*;q=0.8",
        },
    )
    for attempt in range(NSE_DOWNLOAD_MAX_ATTEMPTS):
        try:
            with urlopen(request, timeout=NSE_DOWNLOAD_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise ValueError(f"NSE constituent download failed with HTTP {status}")
                content_type = response.headers.get_content_type()
                if content_type != "text/csv":
                    raise ValueError(
                        f"NSE constituent download returned unexpected content type: {content_type}"
                    )
                payload = response.read()
                if not payload:
                    raise ValueError("NSE Nifty 500 download returned an empty response")
                return payload
        except HTTPError as error:
            if (
                error.code not in TRANSIENT_HTTP_STATUSES
                or attempt + 1 == NSE_DOWNLOAD_MAX_ATTEMPTS
            ):
                raise
            time.sleep(_retry_after_seconds(error, attempt))
        except (TimeoutError, URLError, OSError):
            if attempt + 1 == NSE_DOWNLOAD_MAX_ATTEMPTS:
                raise
            time.sleep(float(2**attempt))
    raise OSError("NSE constituent download failed after bounded retries")
