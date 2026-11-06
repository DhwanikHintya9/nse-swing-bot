"""Bounded historical-depth availability probe; not a research-data backfill."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from nse_swing_bot.market_data.acquisition_manifest import (
    build_acquisition_manifest,
    sha256_file,
    write_acquisition_manifest,
)
from nse_swing_bot.market_data.checkpoints import JsonChunkCheckpointStore
from nse_swing_bot.market_data.instruments import (
    normalize_instrument_master,
    normalize_nifty500_constituents,
    save_instrument_snapshot,
)
from nse_swing_bot.market_data.kite_adapter import KiteMarketDataAdapter
from nse_swing_bot.market_data.pilot import _resolve_pilot_instruments, _stats_delta
from nse_swing_bot.market_data.request_control import KiteRequestExecutor
from nse_swing_bot.market_data.validation import CandleDataError, validate_daily_candles


def _request_ranges(start: date, end: date, chunk_days: int) -> list[dict[str, str]]:
    ranges: list[dict[str, str]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=chunk_days - 1))
        ranges.append({"start": cursor.isoformat(), "end": chunk_end.isoformat()})
        cursor = chunk_end + timedelta(days=1)
    return ranges


def run_kite_historical_depth_probe(
    client: Any,
    *,
    universe_csv: Path,
    universe_effective_date: date,
    universe_source: str,
    start: date,
    end: date,
    symbols: list[str],
    data_root: Path,
    chunk_days: int = 365,
) -> tuple[Path, dict[str, Any]]:
    """Probe a bounded historical interval and report returned depth without claiming completeness."""
    if start > end:
        raise ValueError("start must be on or before end")
    if chunk_days < 1:
        raise ValueError("chunk_days must be positive")
    normalized_symbols = [symbol.strip().upper() for symbol in symbols]
    if len(normalized_symbols) != 5 or len(set(normalized_symbols)) != 5 or any(not s for s in normalized_symbols):
        raise ValueError("probe requires exactly five unique, non-empty symbols")

    data_root = Path(data_root).resolve()
    started = datetime.now(UTC)
    universe_hash = sha256_file(universe_csv)
    universe = normalize_nifty500_constituents(
        pd.read_csv(universe_csv, skip_blank_lines=False),
        effective_date=universe_effective_date,
        source_name=universe_source,
        expected_count=501,
    )

    requests = KiteRequestExecutor()
    adapter = KiteMarketDataAdapter(
        client,
        request_executor=requests,
        checkpoint_store=JsonChunkCheckpointStore(data_root / "checkpoints"),
    )
    instrument_rows = adapter.fetch_nse_instruments()
    instruments = normalize_instrument_master(instrument_rows)
    instrument_captured_at = datetime.now(UTC)
    instrument_path = save_instrument_snapshot(
        instruments, data_root / "snapshots", captured_at=instrument_captured_at
    )
    instrument_hash = sha256_file(instrument_path)
    instrument_stats = requests.snapshot_stats()

    mapping_error: str | None = None
    try:
        selected = _resolve_pilot_instruments(universe, instruments, normalized_symbols)
    except ValueError as error:
        selected = []
        mapping_error = str(error)

    symbol_results: list[dict[str, Any]] = []
    if mapping_error:
        symbol_results = [
            {
                "symbol": symbol,
                "status": "mapping_failed",
                "error_type": "InstrumentMappingError",
                "error_reason": mapping_error,
                "returned_rows": 0,
            }
            for symbol in normalized_symbols
        ]

    for item in selected:
        symbol = item["symbol"]
        token = int(item["instrument"]["instrument_token"])
        before = requests.snapshot_stats()
        result: dict[str, Any] = {
            "symbol": symbol,
            "isin_from_universe_snapshot": item["isin"],
            "universe_effective_date": item["universe_effective_date"],
            "universe_source": item["universe_source"],
            "current_instrument_token": token,
            "instrument_master_row_sha256": item["instrument_master_row_sha256"],
            "requested_start_date": start.isoformat(),
            "requested_end_date": end.isoformat(),
            "request_chunks": _request_ranges(start, end, chunk_days),
            "returned_rows": 0,
            "status": "failed",
        }
        try:
            frame = adapter.fetch_daily_candles(
                token, start, end, chunk_days=chunk_days, expected_sessions=None
            )
            validated = validate_daily_candles(frame)
            if validated.empty:
                result["status"] = "no_data"
            else:
                date_index = pd.DatetimeIndex(validated.index).normalize()
                payload = validated.to_csv(
                    index=True, index_label="date", lineterminator="\n",
                    date_format="%Y-%m-%d %H:%M:%S",
                ).encode("utf-8")
                result.update(
                    {
                        "status": "data_returned",
                        "returned_rows": int(len(validated)),
                        "earliest_returned_date": date_index.min().date().isoformat(),
                        "latest_returned_date": date_index.max().date().isoformat(),
                        "duplicate_dates": int(date_index.duplicated().sum()),
                        "returned_data_sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
        except CandleDataError as error:
            result["error_type"] = type(error).__name__
            result["error_reason"] = str(error)
            result["status"] = "no_data" if error.raw_candles.empty else "invalid_data"
        except Exception as error:
            result["error_type"] = type(error).__name__
            result["error_reason"] = str(error)
            result["status"] = "request_failed"
        result["request_stats"] = _stats_delta(before, requests.snapshot_stats())
        symbol_results.append(result)

    completed = datetime.now(UTC)
    statuses = [row["status"] for row in symbol_results]
    probe_status = (
        "completed"
        if len(statuses) == 5 and all(status == "data_returned" for status in statuses)
        else "incomplete"
    )
    stamp = completed.strftime("%Y%m%dT%H%M%S%fZ")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": f"kite-historical-depth-probe-{stamp}",
        "run_started_at_utc": started.isoformat(),
        "run_completed_at_utc": completed.isoformat(),
        "provider": "kite_connect",
        "endpoint_class": "historical",
        "interval": "day",
        "read_only": True,
        "orders_endpoint_calls": 0,
        "production_eligible": False,
        "adjustment_status": "provider_adjusted_unreconciled",
        "probe_status": probe_status,
        "requested_start_date": start.isoformat(),
        "requested_end_date": end.isoformat(),
        "chunk_days": chunk_days,
        "universe_source": {
            "file_name": universe_csv.name,
            "sha256": universe_hash,
            "effective_date": universe_effective_date.isoformat(),
            "source": universe_source,
        },
        "instrument_master": {
            "path": str(instrument_path.relative_to(data_root)),
            "sha256": instrument_hash,
            "captured_at_utc": instrument_captured_at.isoformat(),
            "row_count": int(len(instruments)),
        },
        "instrument_master_request_stats": instrument_stats,
        "symbols": symbol_results,
        "interpretation": [
            "This is an availability probe for the requested bounded interval, not a completeness or continuity certification.",
            "No NSE calendar was applied; returned row counts must not be interpreted as complete trading-session coverage.",
            "The current instrument master and 2026-effective universe snapshot do not prove historical symbol/ISIN continuity in 2021-2022.",
            "Kite prices remain provider_adjusted_unreconciled; no corporate-action adjustment claim is made.",
            "No Parquet research dataset or outcome labels are produced by this probe.",
        ],
    }
    manifest = build_acquisition_manifest(payload)
    destination = data_root / "manifests" / f"{manifest['manifest_id']}.json"
    write_acquisition_manifest(manifest, destination)
    return destination, manifest
