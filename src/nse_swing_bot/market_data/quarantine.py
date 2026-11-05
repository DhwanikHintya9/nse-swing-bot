"""Immutable quarantine for raw market-data payloads that fail validation."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from nse_swing_bot.market_data.instruments import safe_symbol


class DataQualityQuarantine:
    def __init__(self, root: Path) -> None:
        self.root = root

    def store(
        self,
        symbol: str,
        start: date,
        end: date,
        reason: str,
        candles: pd.DataFrame,
        captured_at: datetime | None = None,
    ) -> Path:
        if not reason.strip():
            raise ValueError("quarantine reason is required")
        captured_at = captured_at or datetime.now(UTC)
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        stamp = captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        directory = self.root / f"symbol={safe_symbol(symbol)}"
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"quarantine-{stamp}.json"
        if destination.exists():
            raise FileExistsError("refusing to overwrite quarantine record: " + str(destination))
        payload: dict[str, Any] = {
            "symbol": symbol,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "reason": reason,
            "captured_at_utc": captured_at.astimezone(UTC).isoformat(),
            "records": [
                {"date": str(index), **row}
                for index, row in candles.to_dict(orient="index").items()
            ],
        }
        fd, temporary = tempfile.mkstemp(prefix=".quarantine-", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, default=str, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise
        return destination
