"""Atomic JSON checkpoints for validated historical candle chunks."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


class JsonChunkCheckpointStore:
    """Persist validated chunks so a restarted sync does not refetch good data."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(
        self, instrument_token: int, start: date, end: date, chunk_days: int
    ) -> Path:
        if instrument_token <= 0 or chunk_days < 1:
            raise ValueError("instrument_token and chunk_days must be positive")
        if start > end:
            raise ValueError("checkpoint start must be on or before end")
        return (
            self.root
            / f"token={instrument_token}"
            / f"range={start.isoformat()}_{end.isoformat()}_chunk={chunk_days}.json"
        )

    def load(
        self, instrument_token: int, start: date, end: date, chunk_days: int
    ) -> list[dict[str, Any]] | None:
        path = self._path(instrument_token, start, end, chunk_days)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("checkpoint payload must be a JSON object")
        if payload.get("instrument_token") != instrument_token:
            raise ValueError("checkpoint instrument token mismatch")
        if payload.get("start") != start.isoformat() or payload.get("end") != end.isoformat():
            raise ValueError("checkpoint date range mismatch")
        if payload.get("chunk_days") != chunk_days:
            raise ValueError("checkpoint chunk size mismatch")
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError("checkpoint records must be a list")
        return records

    def save(
        self,
        instrument_token: int,
        start: date,
        end: date,
        chunk_days: int,
        records: list[dict[str, Any]],
    ) -> Path:
        path = self._path(instrument_token, start, end, chunk_days)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "instrument_token": instrument_token,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "chunk_days": chunk_days,
            "records": records,
        }
        fd, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, default=str, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise
        return path

    def delete(
        self, instrument_token: int, start: date, end: date, chunk_days: int
    ) -> None:
        """Remove a corrupt or no-longer-valid cached chunk."""
        self._path(instrument_token, start, end, chunk_days).unlink(missing_ok=True)
