"""Immutable CSV export for research-only signal/event diagnostic frames."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from nse_swing_bot.events.diagnostics import DIAGNOSTIC_COLUMNS

TUPLE_COLUMNS = frozenset({"taxonomy_counts_30d", "admitted_event_ids"})


def _json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    return value


def _serialize_cell(column: str, value: Any) -> str:
    if value is None or value is pd.NA:
        return ""
    if not isinstance(value, (list, tuple, dict)) and pd.isna(value):
        return ""
    if column in TUPLE_COLUMNS or isinstance(value, (list, tuple, dict)):
        return json.dumps(
            _json_value(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
    if isinstance(value, (bool,)):
        return "true" if value else "false"
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("research artifact cannot contain non-finite numeric values")
        return repr(value)
    return str(value)


def _write_immutable(path: Path, content: bytes) -> None:
    """Atomically create a new file; fail rather than overwrite an existing artifact."""
    descriptor, temporary = tempfile.mkstemp(prefix=".research-artifact-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    Path(temporary).unlink(missing_ok=True)


def export_research_event_frame(
    frame: pd.DataFrame,
    output_dir: Path,
    captured_at: datetime,
) -> tuple[Path, Path]:
    """Write a research-only CSV and hash manifest without overwriting artifacts.

    The frame must contain the full event diagnostic contract and a unique,
    timezone-aware DatetimeIndex. Tuple-valued diagnostic fields are encoded
    as compact JSON arrays, not Python repr strings. A deterministic content
    digest is included in both filenames and the manifest.
    """
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("research frame index must be a timezone-aware DatetimeIndex")
    if frame.index.has_duplicates or frame.index.hasnans:
        raise ValueError("research frame index must be unique and cannot contain NaT")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("research frame index must be strictly increasing")
    missing = set(DIAGNOSTIC_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(
            f"research frame is missing event diagnostics: {', '.join(sorted(missing))}"
        )
    if not len(frame):
        raise ValueError("research frame must contain at least one row")
    if frame.columns.has_duplicates:
        raise ValueError("research frame columns must be unique")

    output_dir.mkdir(parents=True, exist_ok=True)
    columns = ["decision_at", *[str(column) for column in frame.columns]]
    lines = [",".join(json.dumps(column, ensure_ascii=False) for column in columns)]
    for timestamp, row in frame.iterrows():
        values = [timestamp.isoformat()]
        values.extend(_serialize_cell(str(column), row[column]) for column in frame.columns)
        lines.append(",".join(json.dumps(value, ensure_ascii=False) for value in values))
    csv_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    digest = hashlib.sha256(csv_bytes).hexdigest()
    timestamp_label = captured_at.strftime("%Y%m%dT%H%M%S%f%z")
    stem = f"research-events-{timestamp_label}-{digest[:12]}"
    csv_path = output_dir / f"{stem}.csv"
    manifest_path = output_dir / f"{stem}.manifest.json"
    manifest = {
        "schema_version": 1,
        "artifact_type": "research_only_signal_event_diagnostics",
        "captured_at": captured_at.isoformat(),
        "decision_timezone": str(frame.index.tz),
        "row_count": len(frame),
        "columns": columns,
        "csv_filename": csv_path.name,
        "csv_sha256": digest,
        "production_eligible": False,
        "broker_execution_eligible": False,
        "strategy_signal_modified": False,
    }
    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
    manifest_bytes = (manifest_json + "\n").encode("utf-8")
    _write_immutable(csv_path, csv_bytes)
    try:
        _write_immutable(manifest_path, manifest_bytes)
    except Exception:
        # Do not remove a successfully created CSV: immutable artifacts are
        # retained for operator inspection if manifest creation fails.
        raise
    return csv_path, manifest_path
