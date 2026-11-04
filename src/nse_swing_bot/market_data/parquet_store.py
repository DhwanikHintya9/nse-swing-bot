"""Append-only Parquet snapshots for raw daily candles."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from nse_swing_bot.market_data.instruments import safe_symbol
from nse_swing_bot.market_data.validation import validate_daily_candles


class ParquetCandleStore:
    """Persist immutable raw candle snapshots and read the latest value per date."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write_snapshot(
        self,
        symbol: str,
        candles: pd.DataFrame,
        captured_at: datetime | None = None,
    ) -> list[Path]:
        captured_at = captured_at or datetime.now(UTC)
        captured_at = captured_at.astimezone(UTC)
        validated = validate_daily_candles(candles)
        paths: list[Path] = []

        for year, partition in validated.groupby(validated.index.year):
            stamp = captured_at.strftime("%Y%m%dT%H%M%S%fZ")
            destination = (
                self.root
                / "raw"
                / "daily"
                / f"symbol={safe_symbol(symbol)}"
                / f"year={year}"
                / f"snapshot={stamp}.parquet"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise FileExistsError("refusing to overwrite raw snapshot: " + str(destination))
            output = partition.reset_index()
            output["captured_at_utc"] = captured_at
            output["symbol"] = symbol
            output.to_parquet(destination, index=False)
            paths.append(destination)

        return paths

    def read_latest(self, symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        base = self.root / "raw" / "daily" / f"symbol={safe_symbol(symbol)}"
        if not base.exists():
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        frames = [pd.read_parquet(path) for path in base.glob("year=*/snapshot=*.parquet")]
        if not frames:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        combined = pd.concat(frames, ignore_index=True)
        combined["date"] = pd.to_datetime(combined["date"])
        combined["captured_at_utc"] = pd.to_datetime(combined["captured_at_utc"], utc=True)
        combined = combined.sort_values(["date", "captured_at_utc"])
        latest = combined.drop_duplicates(subset=["date"], keep="last").set_index("date")
        if start is not None:
            latest = latest.loc[latest.index >= pd.Timestamp(start)]
        if end is not None:
            latest = latest.loc[latest.index <= pd.Timestamp(end)]
        return latest[["open", "high", "low", "close", "volume"]].sort_index()
