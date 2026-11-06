"""Chronological walk-forward splits with decision-date grouped purge/embargo."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ASSIGNMENT_COLUMNS = (
    "fold_id",
    "symbol",
    "decision_at",
    "horizon_sessions",
    "decision_session",
    "label_start_session",
    "label_end_session",
    "label_status",
    "partition",
    "label_eligible",
    "training_eligible",
    "partition_reason",
    "test_start",
    "test_end",
)


@dataclass(frozen=True)
class WalkForwardWindow:
    fold_id: str
    test_start: date
    test_end: date

    def __post_init__(self) -> None:
        if not self.fold_id.strip():
            raise ValueError("fold_id is required")
        if self.test_start > self.test_end:
            raise ValueError("test_start must be on or before test_end")


def _date_or_none(value: object, field: str) -> date | None:
    if value is None or pd.isna(value) or value == "":
        return None
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be a valid ISO date or null") from error


def _session_calendar(sessions: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if not isinstance(sessions, pd.DatetimeIndex) or sessions.empty:
        raise ValueError("sessions must be a non-empty DatetimeIndex")
    result = sessions
    if result.tz is not None:
        result = result.tz_convert("Asia/Kolkata").tz_localize(None)
    result = result.normalize()
    if result.hasnans or result.has_duplicates or not result.is_monotonic_increasing:
        raise ValueError("sessions must be valid, unique and strictly increasing")
    return result


def _parse_decision_at(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("every decision_at must be timezone-aware")
    return timestamp


def build_walk_forward_assignments(
    labels: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    windows: tuple[WalkForwardWindow, ...],
    calendar_snapshot_id: str,
    embargo_sessions: int = 5,
    min_train_sessions: int = 30,
) -> pd.DataFrame:
    """Assign expanding-window train/test partitions with grouped purging.

    If any complete label for a pre-test decision date reaches or crosses the
    test start, every symbol and horizon row for that decision date is purged.
    The embargo is then applied to the final N exchange sessions before test
    start. Censored rows retain their date partition but are never train-eligible.
    """
    if not calendar_snapshot_id.strip():
        raise ValueError("calendar_snapshot_id is required")
    if embargo_sessions < 0:
        raise ValueError("embargo_sessions cannot be negative")
    if min_train_sessions < 1:
        raise ValueError("min_train_sessions must be positive")
    if not windows:
        raise ValueError("at least one test window is required")
    if len({window.fold_id for window in windows}) != len(windows):
        raise ValueError("fold_id values must be unique")
    if tuple(sorted(windows, key=lambda item: item.test_start)) != windows:
        raise ValueError("test windows must be supplied in chronological order")
    for previous, current in zip(windows, windows[1:]):
        if current.test_start <= previous.test_end:
            raise ValueError("test windows must be non-overlapping")

    calendar = _session_calendar(sessions)
    session_positions = {item.date(): position for position, item in enumerate(calendar)}
    for window in windows:
        if window.test_start not in session_positions or window.test_end not in session_positions:
            raise ValueError("every test-window boundary must be an NSE trading session")

    required = {
        "symbol",
        "decision_at",
        "horizon_sessions",
        "label_start_session",
        "label_end_session",
        "label_status",
    }
    missing = required.difference(labels.columns)
    if missing:
        raise ValueError("labels missing required columns: " + ", ".join(sorted(missing)))
    if labels.empty:
        raise ValueError("labels must not be empty")

    frame = labels.loc[:, list(required)].copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    if (frame["symbol"].str.strip() == "").any():
        raise ValueError("label symbols cannot be blank")
    if frame["horizon_sessions"].isna().any():
        raise ValueError("label horizons cannot be null")
    horizons = pd.to_numeric(frame["horizon_sessions"], errors="raise")
    if (horizons % 1 != 0).any() or (horizons <= 0).any():
        raise ValueError("label horizons must be positive whole session counts")
    frame["horizon_sessions"] = horizons.astype(int)
    if not frame["label_status"].isin(["complete", "censored"]).all():
        raise ValueError("label status must be complete or censored")

    decisions = [_parse_decision_at(value) for value in frame["decision_at"]]
    frame["decision_at"] = [item.isoformat() for item in decisions]
    frame["_decision_date"] = [
        item.tz_convert("Asia/Kolkata").date() for item in decisions
    ]
    frame["_label_start"] = [
        _date_or_none(value, "label_start_session")
        for value in frame["label_start_session"]
    ]
    frame["_label_end"] = [
        _date_or_none(value, "label_end_session")
        for value in frame["label_end_session"]
    ]

    if frame.duplicated(["symbol", "decision_at", "horizon_sessions"]).any():
        raise ValueError("labels contain duplicate symbol/decision/horizon keys")

    for row in frame.itertuples(index=False):
        decision_date = row._asdict()["_decision_date"]
        if decision_date not in session_positions:
            raise ValueError("every decision_at must map to a session in the supplied calendar")
        decision_position = session_positions[decision_date]
        horizon = row.horizon_sessions
        expected_start = (
            calendar[decision_position + 1].date()
            if decision_position + 1 < len(calendar)
            else None
        )
        expected_end = (
            calendar[decision_position + horizon].date()
            if decision_position + horizon < len(calendar)
            else None
        )
        if row._asdict()["_label_start"] != expected_start:
            raise ValueError("label_start_session does not match the NSE calendar horizon")
        if row._asdict()["_label_end"] != expected_end:
            raise ValueError("label_end_session does not match the NSE calendar horizon")
        if row.label_status == "complete" and expected_end is None:
            raise ValueError("complete label cannot extend beyond calendar coverage")

    output_rows: list[dict[str, object]] = []
    for window in windows:
        test_start_position = session_positions[window.test_start]
        embargo_start_position = max(0, test_start_position - embargo_sessions)
        date_partitions: dict[date, tuple[str, str]] = {}
        for decision_date, group in frame.groupby("_decision_date", sort=True):
            if window.test_start <= decision_date <= window.test_end:
                date_partitions[decision_date] = ("test", "inside_test_window")
                continue
            if decision_date >= window.test_start:
                continue

            complete_ends = group.loc[
                group["label_status"] == "complete", "_label_end"
            ].dropna()
            if any(item >= window.test_start for item in complete_ends):
                date_partitions[decision_date] = (
                    "purged",
                    "date_group_has_label_window_reaching_test_start",
                )
                continue

            decision_position = session_positions[decision_date]
            if decision_position >= embargo_start_position:
                date_partitions[decision_date] = (
                    "embargoed",
                    "inside_pre_test_embargo_window",
                )
            else:
                date_partitions[decision_date] = ("train", "prior_chronological_history")

        for row in frame.itertuples(index=False):
            record = row._asdict()
            decision_date = record["_decision_date"]
            if decision_date not in date_partitions:
                continue
            partition, reason = date_partitions[decision_date]
            label_eligible = record["label_status"] == "complete"
            training_eligible = partition == "train" and label_eligible
            if partition in {"train", "test"} and not label_eligible:
                reason = "censored_label_not_eligible_for_return_statistics"
            output_rows.append(
                {
                    "fold_id": window.fold_id,
                    "symbol": record["symbol"],
                    "decision_at": record["decision_at"],
                    "horizon_sessions": record["horizon_sessions"],
                    "decision_session": decision_date.isoformat(),
                    "label_start_session": (
                        record["_label_start"].isoformat()
                        if record["_label_start"] is not None
                        else ""
                    ),
                    "label_end_session": (
                        record["_label_end"].isoformat()
                        if record["_label_end"] is not None
                        else ""
                    ),
                    "label_status": record["label_status"],
                    "partition": partition,
                    "label_eligible": label_eligible,
                    "training_eligible": training_eligible,
                    "partition_reason": reason,
                    "test_start": window.test_start.isoformat(),
                    "test_end": window.test_end.isoformat(),
                }
            )

        fold_rows = [item for item in output_rows if item["fold_id"] == window.fold_id]
        test_dates = {
            item["decision_session"] for item in fold_rows if item["partition"] == "test"
        }
        train_dates = {
            item["decision_session"]
            for item in fold_rows
            if item["partition"] == "train" and item["training_eligible"]
        }
        if not test_dates:
            raise ValueError(f"{window.fold_id} has no test observations")
        if len(train_dates) < min_train_sessions:
            raise ValueError(
                f"{window.fold_id} has only {len(train_dates)} eligible training sessions; "
                f"{min_train_sessions} required"
            )

    if not output_rows:
        raise ValueError("walk-forward windows produced no split assignments")
    result = pd.DataFrame(output_rows, columns=ASSIGNMENT_COLUMNS)
    return result.sort_values(
        ["fold_id", "decision_session", "symbol", "horizon_sessions"],
        kind="stable",
        ignore_index=True,
    )


def _write_immutable(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".walk-forward-", dir=path.parent)
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


def export_walk_forward_assignments(
    assignments: pd.DataFrame,
    windows: tuple[WalkForwardWindow, ...],
    output_dir: Path,
    calendar_snapshot_id: str,
    source_label_artifact_sha256: str,
    embargo_sessions: int,
    min_train_sessions: int,
    captured_at: datetime,
) -> tuple[Path, Path]:
    """Write immutable split assignments and a hash-bound research manifest."""
    if tuple(assignments.columns) != ASSIGNMENT_COLUMNS:
        raise ValueError("assignments do not match the walk-forward schema")
    if assignments.empty:
        raise ValueError("assignments must not be empty")
    if not calendar_snapshot_id.strip():
        raise ValueError("calendar_snapshot_id is required")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", source_label_artifact_sha256):
        raise ValueError("source_label_artifact_sha256 must be a 64-character SHA-256 hex digest")
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    if embargo_sessions < 0 or min_train_sessions < 1:
        raise ValueError("invalid walk-forward split configuration")

    output_dir.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=list(ASSIGNMENT_COLUMNS), lineterminator="\n"
    )
    writer.writeheader()
    for record in assignments.to_dict(orient="records"):
        writer.writerow(record)
    csv_bytes = buffer.getvalue().encode("utf-8")
    digest = hashlib.sha256(csv_bytes).hexdigest()
    timestamp = captured_at.strftime("%Y%m%dT%H%M%S%f%z")
    stem = f"walk-forward-splits-{timestamp}-{digest[:12]}"
    csv_path = output_dir / f"{stem}.csv"
    manifest_path = output_dir / f"{stem}.manifest.json"
    manifest = {
        "schema_version": 1,
        "artifact_type": "research_only_walk_forward_split_assignments",
        "captured_at": captured_at.isoformat(),
        "calendar_snapshot_id": calendar_snapshot_id,
        "source_label_artifact_sha256": source_label_artifact_sha256.lower(),
        "embargo_sessions": embargo_sessions,
        "min_train_sessions": min_train_sessions,
        "windows": [asdict(window) for window in windows],
        "row_count": len(assignments),
        "columns": list(ASSIGNMENT_COLUMNS),
        "csv_filename": csv_path.name,
        "csv_sha256": digest,
        "production_eligible": False,
        "broker_execution_eligible": False,
        "strategy_signal_modified": False,
        "model_fitted": False,
    }
    manifest["windows"] = [
        {
            "fold_id": item.fold_id,
            "test_start": item.test_start.isoformat(),
            "test_end": item.test_end.isoformat(),
        }
        for item in windows
    ]
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_immutable(csv_path, csv_bytes)
    _write_immutable(manifest_path, manifest_bytes)
    return csv_path, manifest_path
