"""Point-in-time forward outcome labels for research observations.

Labels describe subsequent adjusted-price paths. They are not simulated fills,
trade P&L, or inputs to Phase 1 signal generation.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from nse_swing_bot.market_data.validation import validate_daily_candles

PRICE_BASIS = "split_and_dividend_adjusted_ohlc"
ADJUSTMENT_METHOD = "verified_split_and_dividend_factors"
OUTCOME_COLUMNS = (
    "symbol",
    "decision_at",
    "horizon_sessions",
    "label_start_session",
    "label_end_session",
    "forward_close_return",
    "max_favorable_excursion",
    "max_adverse_excursion",
    "label_status",
    "label_reason",
    "overlapping_label_count",
    "source_candle_snapshot_id",
    "corporate_action_snapshot_id",
    "calendar_snapshot_id",
    "price_basis",
    "adjustment_method",
    "outcome_as_of_date",
)


@dataclass(frozen=True)
class OutcomePriceMetadata:
    """Provenance contract for ex-post, corporate-action-adjusted OHLC prices."""

    symbol: str
    source_candle_snapshot_id: str
    corporate_action_snapshot_id: str
    calendar_snapshot_id: str
    price_basis: str
    adjustment_method: str
    outcome_as_of_date: date
    calendar_coverage_start: date
    calendar_coverage_end: date
    captured_at: datetime

    def __post_init__(self) -> None:
        for field in (
            "symbol",
            "source_candle_snapshot_id",
            "corporate_action_snapshot_id",
            "calendar_snapshot_id",
        ):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} is required")
        if self.price_basis != PRICE_BASIS:
            raise ValueError(f"price_basis must be {PRICE_BASIS!r}")
        if self.adjustment_method != ADJUSTMENT_METHOD:
            raise ValueError(f"adjustment_method must be {ADJUSTMENT_METHOD!r}")
        if self.calendar_coverage_start > self.calendar_coverage_end:
            raise ValueError("calendar coverage range is inverted")
        if not (
            self.calendar_coverage_start
            <= self.outcome_as_of_date
            <= self.calendar_coverage_end
        ):
            raise ValueError("outcome_as_of_date must fall within calendar coverage")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")


def _calendar_index(
    sessions: pd.DatetimeIndex,
    metadata: OutcomePriceMetadata,
) -> pd.DatetimeIndex:
    if not isinstance(sessions, pd.DatetimeIndex) or sessions.empty:
        raise ValueError("sessions must be a non-empty DatetimeIndex")
    result = sessions
    if result.tz is not None:
        result = result.tz_convert("Asia/Kolkata").tz_localize(None)
    result = result.normalize()
    if result.hasnans or result.has_duplicates or not result.is_monotonic_increasing:
        raise ValueError("sessions must be valid, unique, and strictly increasing")
    if result[0].date() < metadata.calendar_coverage_start:
        raise ValueError("sessions begin before declared calendar coverage")
    if result[-1].date() > metadata.calendar_coverage_end:
        raise ValueError("sessions exceed declared calendar coverage")
    if result[-1].date() > metadata.outcome_as_of_date:
        raise ValueError("calendar sessions extend beyond outcome_as_of_date")
    return result


def _decision_index(decision_times: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if not isinstance(decision_times, pd.DatetimeIndex) or decision_times.empty:
        raise ValueError("decision_times must be a non-empty DatetimeIndex")
    if decision_times.tz is None:
        raise ValueError("decision_times must be timezone-aware")
    if decision_times.hasnans or decision_times.has_duplicates:
        raise ValueError("decision_times must be valid and unique")
    if not decision_times.is_monotonic_increasing:
        raise ValueError("decision_times must be strictly increasing")
    return decision_times


def _overlap_counts(intervals: list[tuple[int, int] | None]) -> list[int]:
    """Count other same-horizon label windows that overlap each planned window."""
    valid = [item for item in intervals if item is not None]
    starts = sorted(item[0] for item in valid)
    ends = sorted(item[1] for item in valid)
    counts: list[int] = []
    for interval in intervals:
        if interval is None:
            counts.append(0)
            continue
        start, end = interval
        count = bisect_right(starts, end) - bisect_left(ends, start) - 1
        counts.append(count)
    return counts


def build_forward_outcome_labels(
    symbol: str,
    adjusted_candles: pd.DataFrame,
    decision_times: pd.DatetimeIndex,
    sessions: pd.DatetimeIndex,
    metadata: OutcomePriceMetadata,
    horizons: tuple[int, ...] = (5, 10, 20),
) -> pd.DataFrame:
    """Build fixed-horizon forward labels using the NSE session calendar.

    Every horizon advances by exchange sessions, never calendar days or
    observed-row offsets. If any required forward session lacks a candle, the
    entire horizon is censored; no missing candle is skipped or imputed.

    Returns one row per (symbol, decision_at, horizon_sessions). Returns and
    excursions are fractions (0.05 means +5%). MFE/MAE are measured against
    the decision candle close using subsequent adjusted highs/lows.
    """
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol or normalized_symbol != metadata.symbol.strip().upper():
        raise ValueError("symbol must match the outcome metadata symbol")
    decisions = _decision_index(decision_times)
    calendar = _calendar_index(sessions, metadata)

    if not horizons or any(not isinstance(value, int) or value <= 0 for value in horizons):
        raise ValueError("horizons must contain positive integer session counts")
    if len(set(horizons)) != len(horizons):
        raise ValueError("horizons must be unique")
    ordered_horizons = tuple(sorted(horizons))

    if not isinstance(adjusted_candles.index, pd.DatetimeIndex):
        raise ValueError("adjusted_candles must use a DatetimeIndex")
    if adjusted_candles.index.tz is not None:
        candle_index = adjusted_candles.index.tz_convert("Asia/Kolkata").tz_localize(None)
    else:
        candle_index = adjusted_candles.index
    if candle_index.has_duplicates or not candle_index.is_monotonic_increasing:
        raise ValueError("adjusted candle dates must be unique and strictly increasing")

    candles = validate_daily_candles(adjusted_candles)
    if not candles.index.isin(calendar).all():
        raise ValueError("adjusted candle dates must belong to the supplied NSE calendar")
    candle_by_date = {stamp: row for stamp, row in candles.iterrows()}
    calendar_positions = {stamp: position for position, stamp in enumerate(calendar)}

    decision_dates = decisions.tz_convert("Asia/Kolkata").normalize().tz_localize(None)
    if not decision_dates.isin(calendar).all():
        raise ValueError("every decision timestamp must map to an NSE trading session")
    if not decision_dates.isin(candles.index).all():
        raise ValueError("every decision timestamp must have a decision-session candle")
    if any(value.date() > metadata.outcome_as_of_date for value in decision_dates):
        raise ValueError("decision timestamp is after outcome_as_of_date")

    row_specs: list[dict[str, Any]] = []
    for decision_at, decision_date in zip(decisions, decision_dates, strict=True):
        decision_position = calendar_positions[decision_date]
        decision_close = float(candle_by_date[decision_date]["close"])
        for horizon in ordered_horizons:
            start_position = decision_position + 1
            end_position = decision_position + horizon
            start_session = (
                calendar[start_position].date().isoformat()
                if start_position < len(calendar)
                else None
            )
            end_session = (
                calendar[end_position].date().isoformat()
                if end_position < len(calendar)
                else None
            )
            reason = ""
            future_dates: list[pd.Timestamp] = []
            if end_position >= len(calendar):
                reason = "calendar_window_unavailable"
            else:
                future_dates = list(calendar[start_position : end_position + 1])
                missing_dates = [item for item in future_dates if item not in candle_by_date]
                if missing_dates:
                    reason = "missing_forward_candle"

            forward_return: float | None = None
            mfe: float | None = None
            mae: float | None = None
            if not reason:
                future = pd.DataFrame([candle_by_date[item] for item in future_dates])
                forward_return = float(future.iloc[-1]["close"] / decision_close - 1.0)
                mfe = float(future["high"].max() / decision_close - 1.0)
                mae = float(future["low"].min() / decision_close - 1.0)

            row_specs.append(
                {
                    "symbol": normalized_symbol,
                    "decision_at": decision_at.isoformat(),
                    "horizon_sessions": horizon,
                    "label_start_session": start_session,
                    "label_end_session": end_session,
                    "forward_close_return": forward_return,
                    "max_favorable_excursion": mfe,
                    "max_adverse_excursion": mae,
                    "label_status": "complete" if not reason else "censored",
                    "label_reason": reason,
                    "overlapping_label_count": 0,
                    "source_candle_snapshot_id": metadata.source_candle_snapshot_id,
                    "corporate_action_snapshot_id": metadata.corporate_action_snapshot_id,
                    "calendar_snapshot_id": metadata.calendar_snapshot_id,
                    "price_basis": metadata.price_basis,
                    "adjustment_method": metadata.adjustment_method,
                    "outcome_as_of_date": metadata.outcome_as_of_date.isoformat(),
                    "_interval": (
                        (start_position, end_position) if end_position < len(calendar) else None
                    ),
                }
            )

    for horizon in ordered_horizons:
        positions = [
            index
            for index, row in enumerate(row_specs)
            if row["horizon_sessions"] == horizon
        ]
        counts = _overlap_counts([row_specs[index]["_interval"] for index in positions])
        for index, count in zip(positions, counts, strict=True):
            row_specs[index]["overlapping_label_count"] = count

    for row in row_specs:
        row.pop("_interval")

    result = pd.DataFrame(row_specs, columns=OUTCOME_COLUMNS)
    if result.empty:
        raise ValueError("no outcome labels were produced")
    return result


def _write_immutable(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".outcome-label-", dir=path.parent)
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


def export_forward_outcome_labels(
    labels: pd.DataFrame,
    metadata: OutcomePriceMetadata,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write immutable CSV labels and a provenance/hash manifest."""
    if tuple(labels.columns) != OUTCOME_COLUMNS:
        raise ValueError("labels do not match the forward outcome schema")
    if labels.empty:
        raise ValueError("labels must contain at least one row")
    if labels.duplicated(["symbol", "decision_at", "horizon_sessions"]).any():
        raise ValueError("labels contain duplicate observation/horizon keys")
    if set(labels["symbol"]) != {metadata.symbol.strip().upper()}:
        raise ValueError("label symbols do not match outcome metadata")
    for column, expected in (
        ("source_candle_snapshot_id", metadata.source_candle_snapshot_id),
        ("corporate_action_snapshot_id", metadata.corporate_action_snapshot_id),
        ("calendar_snapshot_id", metadata.calendar_snapshot_id),
        ("price_basis", metadata.price_basis),
        ("adjustment_method", metadata.adjustment_method),
        ("outcome_as_of_date", metadata.outcome_as_of_date.isoformat()),
    ):
        if set(labels[column]) != {expected}:
            raise ValueError(f"label provenance mismatch for {column}")

    output_dir.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(OUTCOME_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for record in labels.to_dict(orient="records"):
        normalized = {}
        for key, value in record.items():
            if value is None or (isinstance(value, float) and not np.isfinite(value)):
                normalized[key] = ""
            elif isinstance(value, (np.integer,)):
                normalized[key] = int(value)
            elif isinstance(value, (np.floating,)):
                normalized[key] = float(value)
            else:
                normalized[key] = value
        writer.writerow(normalized)
    csv_bytes = buffer.getvalue().encode("utf-8")
    digest = hashlib.sha256(csv_bytes).hexdigest()
    timestamp = metadata.captured_at.strftime("%Y%m%dT%H%M%S%f%z")
    stem = f"forward-outcomes-{timestamp}-{digest[:12]}"
    csv_path = output_dir / f"{stem}.csv"
    manifest_path = output_dir / f"{stem}.manifest.json"
    manifest = {
        "schema_version": 1,
        "artifact_type": "research_only_forward_outcome_labels",
        "metadata": {
            **asdict(metadata),
            "outcome_as_of_date": metadata.outcome_as_of_date.isoformat(),
            "calendar_coverage_start": metadata.calendar_coverage_start.isoformat(),
            "calendar_coverage_end": metadata.calendar_coverage_end.isoformat(),
            "captured_at": metadata.captured_at.isoformat(),
        },
        "row_count": len(labels),
        "columns": list(OUTCOME_COLUMNS),
        "csv_filename": csv_path.name,
        "csv_sha256": digest,
        "production_eligible": False,
        "broker_execution_eligible": False,
        "strategy_signal_modified": False,
        "labels_are_simulated_trades": False,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_immutable(csv_path, csv_bytes)
    _write_immutable(manifest_path, manifest_bytes)
    return csv_path, manifest_path
