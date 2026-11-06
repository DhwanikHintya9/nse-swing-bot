"""Five-symbol, read-only Kite daily OHLCV pilot with immutable evidence output."""

from __future__ import annotations

from datetime import UTC, date, datetime
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
from nse_swing_bot.market_data.parquet_store import ParquetCandleStore
from nse_swing_bot.market_data.quarantine import DataQualityQuarantine
from nse_swing_bot.market_data.trading_calendar import NSETradingCalendar
from nse_swing_bot.market_data.validation import CandleDataError, validate_daily_candles


def _resolve_pilot_instruments(
    universe: pd.DataFrame,
    instruments: pd.DataFrame,
    symbols: list[str],
) -> list[dict[str, Any]]:
    """Resolve five explicitly selected EQ constituents to unique current Kite rows."""
    normalized = [symbol.strip().upper() for symbol in symbols]
    if len(normalized) != 5 or any(not symbol for symbol in normalized):
        raise ValueError("pilot requires exactly five non-empty symbols")
    if len(set(normalized)) != 5:
        raise ValueError("pilot symbols must be unique")

    resolved: list[dict[str, Any]] = []
    for symbol in normalized:
        source_rows = universe.loc[universe["symbol"] == symbol]
        if len(source_rows) != 1:
            raise ValueError(f"{symbol} must resolve to exactly one archived universe row")
        source = source_rows.iloc[0]
        if str(source.get("series", "")).strip().upper() != "EQ":
            raise ValueError(f"{symbol} is not an EQ-series constituent; pilot policy is EQ only")
        isin = str(source.get("isin_code", "")).strip().upper()
        if not isin:
            raise ValueError(f"{symbol} has no source ISIN; refusing guessed identity")

        matches = instruments.loc[
            (instruments["exchange"] == "NSE")
            & (instruments["segment"] == "NSE")
            & (instruments["instrument_type"] == "EQ")
            & (instruments["tradingsymbol"] == symbol)
        ]
        if len(matches) != 1:
            raise ValueError(
                f"{symbol} must resolve to exactly one current NSE/EQ Kite instrument row"
            )
        instrument = matches.iloc[0]
        row_csv = instrument.to_frame().T.to_csv(index=False, lineterminator="\n").encode("utf-8")
        resolved.append(
            {
                "symbol": symbol,
                "isin": isin,
                "series": "EQ",
                "instrument": instrument.to_dict(),
                "instrument_master_row_sha256": __import__("hashlib").sha256(row_csv).hexdigest(),
                "universe_effective_date": str(source["effective_date"]),
                "universe_source": str(source["source"]),
            }
        )
    return resolved


def _coverage_summary(
    candles: pd.DataFrame,
    expected_sessions: pd.DatetimeIndex,
    start: date,
    end: date,
) -> dict[str, Any]:
    """Describe returned-session coverage without filling or dropping any date."""
    dates = pd.DatetimeIndex(candles.index).normalize()
    expected = pd.DatetimeIndex(expected_sessions).normalize()
    missing = expected.difference(dates)
    unexpected = dates.difference(expected)
    outside = dates[(dates < pd.Timestamp(start)) | (dates > pd.Timestamp(end))]
    return {
        "actual_first_date": dates.min().date().isoformat() if len(dates) else None,
        "actual_last_date": dates.max().date().isoformat() if len(dates) else None,
        "row_count": int(len(candles)),
        "duplicate_date_count": int(dates.duplicated().sum()),
        "missing_expected_sessions": [day.date().isoformat() for day in missing],
        "unexpected_returned_dates": [day.date().isoformat() for day in unexpected],
        "out_of_range_dates": [day.date().isoformat() for day in outside],
    }


def run_kite_daily_pilot(
    client: Any,
    *,
    universe_csv: Path,
    universe_effective_date: date,
    universe_source: str,
    calendar_csv: Path,
    calendar_source: str,
    calendar_coverage_start: date,
    calendar_coverage_end: date,
    start: date,
    end: date,
    symbols: list[str],
    data_root: Path,
    chunk_days: int = 365,
    special_sessions: dict[date, str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Run the read-only pilot. Authentication is supplied by the caller."""
    if start > end:
        raise ValueError("start must be on or before end")
    if chunk_days < 1:
        raise ValueError("chunk_days must be positive")
    data_root = Path(data_root).resolve()
    started = datetime.now(UTC)

    universe_bytes_sha256 = sha256_file(universe_csv)
    raw_universe = pd.read_csv(universe_csv, skip_blank_lines=False)
    universe = normalize_nifty500_constituents(
        raw_universe,
        effective_date=universe_effective_date,
        source_name=universe_source,
        expected_count=501,
    )
    calendar_bytes_sha256 = sha256_file(calendar_csv)
    calendar = NSETradingCalendar.from_csv(
        calendar_csv,
        source=calendar_source,
        coverage_start=calendar_coverage_start,
        coverage_end=calendar_coverage_end,
        special_sessions=special_sessions,
    )
    expected_sessions = calendar.sessions(start, end)
    if expected_sessions.empty:
        raise ValueError("calendar produced no expected sessions for the requested range")

    adapter = KiteMarketDataAdapter(
        client,
        checkpoint_store=JsonChunkCheckpointStore(data_root / "checkpoints"),
    )
    raw_instruments = adapter.fetch_nse_instruments()
    instruments = normalize_instrument_master(raw_instruments)
    instrument_snapshot = save_instrument_snapshot(instruments, data_root / "snapshots")
    instrument_snapshot_sha256 = sha256_file(instrument_snapshot)

    selected = _resolve_pilot_instruments(universe, instruments, symbols)
    store = ParquetCandleStore(data_root / "parquet")
    quarantine = DataQualityQuarantine(data_root / "quarantine")
    symbol_results: list[dict[str, Any]] = []

    for item in selected:
        symbol = item["symbol"]
        instrument = pd.Series(item["instrument"])
        result: dict[str, Any] = {
            "symbol": symbol,
            "isin": item["isin"],
            "series": item["series"],
            "universe_effective_date": item["universe_effective_date"],
            "universe_source": item["universe_source"],
            "instrument_token": int(instrument["instrument_token"]),
            "instrument_master_row_sha256": item["instrument_master_row_sha256"],
            "requested_start_date": start.isoformat(),
            "requested_end_date": end.isoformat(),
            "snapshot_files": [],
            "readback_verified": False,
            "status": "failed",
        }
        try:
            candles = adapter.fetch_daily_candles(
                int(instrument["instrument_token"]),
                start,
                end,
                chunk_days=chunk_days,
                expected_sessions=None,
            )
            validated = validate_daily_candles(candles)
            coverage = _coverage_summary(validated, expected_sessions, start, end)
            result.update(coverage)
            if coverage["out_of_range_dates"]:
                raise ValueError("provider returned candles outside the requested date range")

            paths = store.write_snapshot(f"NSE:{symbol}", validated)
            result["snapshot_files"] = [
                {
                    "path": str(path.relative_to(data_root)),
                    "bytes": path.stat().st_size,
                    "row_count": int(len(pd.read_parquet(path))),
                    "sha256": sha256_file(path),
                }
                for path in paths
            ]
            persisted = store.read_latest(
                f"NSE:{symbol}", start.isoformat(), end.isoformat()
            )
            pd.testing.assert_frame_equal(
                persisted,
                validated,
                check_dtype=False,
                check_freq=False,
                check_exact=False,
                rtol=1e-10,
                atol=1e-10,
            )
            result["readback_verified"] = True
            result["status"] = (
                "accepted"
                if not coverage["missing_expected_sessions"]
                and not coverage["unexpected_returned_dates"]
                and not coverage["out_of_range_dates"]
                and len(validated) > 0
                else "incomplete"
            )
        except CandleDataError as error:
            quarantine_path = quarantine.store(
                f"NSE:{symbol}", start, end, str(error), error.raw_candles
            )
            result["quarantine_path"] = str(quarantine_path.relative_to(data_root))
            result["error_type"] = type(error).__name__
        except Exception as error:
            result["error_type"] = type(error).__name__
            result["error_category"] = (
                "coverage_or_validation"
                if isinstance(error, (ValueError, AssertionError))
                else "acquisition_or_persistence"
            )
        symbol_results.append(result)

    completed = datetime.now(UTC)
    pilot_status = (
        "accepted"
        if len(symbol_results) == 5
        and all(result["status"] == "accepted" for result in symbol_results)
        else "failed_or_incomplete"
    )
    stamp = completed.strftime("%Y%m%dT%H%M%S%fZ")
    manifest_payload: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": f"kite-daily-pilot-{stamp}",
        "run_started_at_utc": started.isoformat(),
        "run_completed_at_utc": completed.isoformat(),
        "provider": "kite_connect",
        "endpoint_class": "historical",
        "interval": "day",
        "continuous": False,
        "oi": False,
        "read_only": True,
        "orders_endpoint_calls": 0,
        "production_eligible": False,
        "adjustment_status": "provider_adjusted_unreconciled",
        "pilot_status": pilot_status,
        "requested_start_date": start.isoformat(),
        "requested_end_date": end.isoformat(),
        "chunk_days": chunk_days,
        "universe_source": {
            "file_name": universe_csv.name,
            "sha256": universe_bytes_sha256,
            "effective_date": universe_effective_date.isoformat(),
            "source": universe_source,
            "source_row_count": int(len(universe)),
        },
        "calendar_source": {
            "file_name": calendar_csv.name,
            "sha256": calendar_bytes_sha256,
            "source": calendar_source,
            "coverage_start": calendar_coverage_start.isoformat(),
            "coverage_end": calendar_coverage_end.isoformat(),
            "expected_session_count": int(len(expected_sessions)),
            "special_sessions": {
                day.isoformat(): source
                for day, source in sorted((special_sessions or {}).items())
            },
        },
        "instrument_master": {
            "path": str(instrument_snapshot.relative_to(data_root)),
            "sha256": instrument_snapshot_sha256,
            "bytes": instrument_snapshot.stat().st_size,
            "row_count": int(len(instruments)),
            "captured_at_utc": started.isoformat(),
        },
        "symbols": symbol_results,
        "limitations": [
            "Kite's current instrument master does not independently expose the archived ISIN lineage used here.",
            "Symbol-to-ISIN association is inherited from the dated universe source; exact symbol-to-current-token matching is not proof of historical identity continuity.",
            "Kite historical OHLC is provider-adjusted under Zerodha's published corporate-action policy; adjustment factors are not independently reconciled in this pilot.",
            "Ordinary cash dividends below the provider's extraordinary-dividend threshold may not be reflected; no Stage 4D split-and-dividend adjustment claim is made.",
            "A successful recent-window pilot does not establish five-year retention or historical universe completeness.",
        ],
    }
    manifest = build_acquisition_manifest(manifest_payload)
    manifest_path = data_root / "manifests" / f"{manifest['manifest_id']}.json"
    write_acquisition_manifest(manifest, manifest_path)
    return manifest_path, manifest
