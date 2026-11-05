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

    frame["instrument_token"] = pd.to_numeric(
        frame["instrument_token"], errors="raise"
    ).astype("int64")
    frame["tick_size"] = pd.to_numeric(frame["tick_size"], errors="raise").astype("float64")
    frame["lot_size"] = pd.to_numeric(frame["lot_size"], errors="raise").astype("int64")
    if (
        (frame["instrument_token"] <= 0).any()
        or (frame["tick_size"] <= 0).any()
        or (frame["lot_size"] <= 0).any()
    ):
        raise ValueError("instrument tokens, tick sizes, and lot sizes must be positive")
    if frame["instrument_token"].duplicated().any():
        raise ValueError("NSE equity instrument tokens must be unique")
    if frame["tradingsymbol"].isna().any() or frame["tradingsymbol"].duplicated().any():
        raise ValueError("NSE equity trading symbols must be present and unique")

    return frame.sort_values("tradingsymbol").reset_index(drop=True)


def save_instrument_snapshot(
    frame: pd.DataFrame,
    root: Path,
    captured_at: datetime | None = None,
) -> Path:
    """Write a timestamped CSV snapshot; never overwrite a previous instrument master."""
    captured_at = captured_at or datetime.now(UTC)
    if captured_at.tzinfo is None:
        raise ValueError("captured_at must be timezone-aware")
    stamp = captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = root / "instruments" / f"nse-equities-{stamp}.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError("refusing to overwrite instrument snapshot: " + str(destination))
    frame.to_csv(destination, index=False)
    return destination


def normalize_nifty500_constituents(
    frame: pd.DataFrame,
    effective_date: date,
    source_name: str,
    expected_count: int | None = 501,
) -> pd.DataFrame:
    """Validate constituent rows and attach point-in-time source provenance."""
    if not source_name.strip():
        raise ValueError("source_name is required for universe provenance")
    symbol_column = next((c for c in frame.columns if c.lower() == "symbol"), None)
    if symbol_column is None:
        raise ValueError("constituent CSV must contain a Symbol column")
    symbols = frame[symbol_column].astype("string").str.strip().str.upper()
    if symbols.empty:
        raise ValueError("constituent CSV contains no symbols")
    if symbols.isna().any() or symbols.eq("").any():
        raise ValueError("constituent CSV contains blank or missing symbols")
    if symbols.duplicated().any():
        duplicates = sorted(symbols[symbols.duplicated(keep=False)].unique().tolist())
        raise ValueError(f"constituent CSV contains duplicate symbols: {', '.join(duplicates)}")
    if expected_count is not None and len(symbols) != expected_count:
        raise ValueError(
            f"expected {expected_count} unique constituents, received {len(symbols)}"
        )

    # Retain the source's descriptive and security-identity fields. Index
    # membership must not erase the series/ISIN needed for later eligibility
    # and instrument-master reconciliation.
    metadata_columns = {
        "company name": "company_name",
        "industry": "industry",
        "series": "series",
        "isin code": "isin_code",
    }
    result = pd.DataFrame({"symbol": symbols})
    source_columns = {str(column).strip().lower(): column for column in frame.columns}
    for source_name_column, output_column in metadata_columns.items():
        source_column = source_columns.get(source_name_column)
        if source_column is None:
            continue
        values = frame[source_column].astype("string").str.strip()
        if values.isna().any() or values.eq("").any():
            raise ValueError(f"constituent CSV contains blank or missing {output_column}")
        result[output_column] = values
        if output_column == "isin_code" and values.duplicated().any():
            raise ValueError("constituent CSV contains duplicate ISIN codes")

    result["effective_date"] = effective_date.isoformat()
    result["source"] = source_name.strip()
    return result.sort_values("symbol").reset_index(drop=True)


def load_nifty500_constituents(
    csv_path: Path,
    effective_date: date,
    source_name: str,
    expected_count: int | None = 501,
) -> pd.DataFrame:
    """Load an explicitly sourced constituent CSV; no guessed or hardcoded universe."""
    return normalize_nifty500_constituents(
        pd.read_csv(csv_path, skip_blank_lines=False), effective_date, source_name, expected_count
    )


def save_nifty500_snapshot(frame: pd.DataFrame, root: Path) -> Path:
    """Persist a dated universe snapshot without replacing an existing date."""
    required = {"symbol", "effective_date", "source"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"universe snapshot missing columns: {', '.join(sorted(missing))}")
    dates = frame["effective_date"].astype("string").drop_duplicates()
    if len(dates) != 1:
        raise ValueError("universe snapshot must contain exactly one effective date")
    effective_date = pd.Timestamp(dates.iloc[0]).date()
    if frame["symbol"].isna().any() or frame["symbol"].duplicated().any():
        raise ValueError("universe snapshot symbols must be present and unique")
    if frame["source"].isna().any() or frame["source"].astype("string").str.strip().eq("").any():
        raise ValueError("universe snapshot source provenance is required")
    destination = root / "universe" / f"nifty500-effective-{effective_date.isoformat()}.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError("refusing to overwrite universe snapshot: " + str(destination))
    frame.sort_values("symbol").to_csv(destination, index=False)
    return destination


def safe_symbol(symbol: str) -> str:
    """Make an exchange symbol safe for use as a directory name."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", symbol.strip())
    if not cleaned:
        raise ValueError("symbol cannot be empty")
    return cleaned
