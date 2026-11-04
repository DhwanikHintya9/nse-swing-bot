"""Kite instrument-master snapshots and point-in-time NSE 500 universe inputs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

REQUIRED_INSTRUMENT_COLUMNS = {
    "instrument_token", "tradingsymbol", "name", "tick_size",
    "lot_size", "instrument_type", "segment", "exchange",
}


@dataclass(frozen=True)
class Instrument:
    instrument_token: int
    exchange: str
    tradingsymbol: str
    name: str
    tick_size: float
    lot_size: int
    instrument_type: str
    segment: str

    @property
    def key(self) -> str:
        return f"{self.exchange}:{self.tradingsymbol}"


def normalize_instrument_master(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Validate and retain only NSE cash-equity instruments from Kite's daily dump."""
    frame = pd.DataFrame(rows)
    missing = REQUIRED_INSTRUMENT_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"instrument master missing columns: {', '.join(sorted(missing))}")

    frame = frame.loc[
        (frame["exchange"] == "NSE")
        & (frame["segment"] == "NSE")
        & (frame["instrument_type"] == "EQ")
    ].copy()
    if frame.empty:
        raise ValueError("Kite instrument master contains no NSE cash-equity instruments")

    frame["instrument_token"] = pd.to_numeric(frame["instrument_token"], errors="raise").astype("int64")
    frame["tick_size"] = pd.to_numeric(frame["tick_size"], errors="raise").astype("float64")
    frame["lot_size"] = pd.to_numeric(frame["lot_size"], errors="raise").astype("int64")
    if (frame["instrument_token"] <= 0).any() or (frame["tick_size"] <= 0).any():
        raise ValueError("instrument tokens and tick sizes must be positive")
    if frame["tradingsymbol"].isna().any() or frame["tradingsymbol"].duplicated().any():
        raise ValueError("NSE equity trading symbols must be present and unique")

    return frame.sort_values("tradingsymbol").reset_index(drop=True)


def save_instrument_snapshot(frame: pd.DataFrame, root: Path, captured_at: datetime | None = None) -> Path:
    """Write a timestamped CSV snapshot; never overwrite a previous instrument master."""
    captured_at = captured_at or datetime.now(UTC)
    stamp = captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = root / "instruments" / f"nse-equities-{stamp}.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False)
    return destination


def load_nifty500_constituents(
    csv_path: Path,
    effective_date: date,
    source_name: str,
) -> pd.DataFrame:
    """Load an explicitly sourced constituent CSV; no guessed or hardcoded universe."""
    if not source_name.strip():
        raise ValueError("source_name is required for universe provenance")
    frame = pd.read_csv(csv_path)
    symbol_column = next((c for c in frame.columns if c.lower() == "symbol"), None)
    if symbol_column is None:
        raise ValueError("constituent CSV must contain a Symbol column")
    symbols = frame[symbol_column].astype("string").str.strip().str.upper()
    symbols = symbols.dropna().loc[lambda values: values.ne("")].drop_duplicates()
    if symbols.empty:
        raise ValueError("constituent CSV contains no valid symbols")

    return pd.DataFrame(
        {
            "symbol": symbols.sort_values().to_list(),
            "effective_date": effective_date.isoformat(),
            "source": source_name.strip(),
        }
    )


def safe_symbol(symbol: str) -> str:
    """Make an exchange symbol safe for use as a directory name."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", symbol.strip())
    if not cleaned:
        raise ValueError("symbol cannot be empty")
    return cleaned
