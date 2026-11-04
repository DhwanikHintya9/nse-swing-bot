"""Official NSE index constituent source adapters.

The source is the CSV linked from NSE's Nifty 500 index page. Downloads are
injected in tests; callers must assign the date on which the snapshot became
effective and retain the returned provenance.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from io import BytesIO
from urllib.request import Request, urlopen

import pandas as pd

from nse_swing_bot.market_data.instruments import load_nifty500_constituents

NIFTY_500_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"


def download_nifty500_constituents(
    effective_date: date,
    downloader: Callable[[str], bytes] | None = None,
    expected_count: int = 500,
) -> pd.DataFrame:
    """Download and validate the official Nifty 500 CSV.

    No stale local fallback is attempted. Network or schema errors propagate so
    the caller can keep the previous approved snapshot and alert an operator.
    """
    fetch = downloader or _download_bytes
    payload = fetch(NIFTY_500_CSV_URL)
    if not payload:
        raise ValueError("NSE Nifty 500 download returned an empty response")
    frame = pd.read_csv(BytesIO(payload))
    symbols = load_nifty500_constituents(
        _frame_to_csv_bytes(frame),
        effective_date=effective_date,
        source_name=NIFTY_500_CSV_URL,
        expected_count=expected_count,
    )
    return symbols


def _frame_to_csv_bytes(frame: pd.DataFrame) -> BytesIO:
    """Adapt a parsed response to the shared, strict constituent validator."""
    buffer = BytesIO()
    frame.to_csv(buffer, index=False)
    buffer.seek(0)
    # The existing loader accepts a path, so this helper is not used directly.
    raise NotImplementedError("internal adapter should not be called")


def _download_bytes(url: str) -> bytes:
    request = Request(
        url,
        headers={"User-Agent": "nse-swing-bot/0.1 (market-data research)"},
    )
    with urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise OSError(f"NSE constituent download failed with HTTP {response.status}")
        return response.read()
