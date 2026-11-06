"""Run a five-symbol, read-only Kite daily OHLCV acquisition pilot."""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from kiteconnect import KiteConnect

from nse_swing_bot.market_data.pilot import run_kite_daily_pilot

DEFAULT_SYMBOLS = "RELIANCE,HDFCBANK,INFY,SUNPHARMA,LT"
UNIVERSE_SOURCE = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
DEFAULT_SPECIAL_SESSIONS = {
    date(2026, 2, 1): "https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf",
}


def _special_session(value: str) -> tuple[date, str]:
    try:
        raw_date, source = value.split("=", 1)
        parsed_date = date.fromisoformat(raw_date)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "special session must be DATE=SOURCE, for example 2026-11-08=NSE notice URL"
        ) from error
    if not source.strip():
        raise argparse.ArgumentTypeError("special-session source cannot be blank")
    return parsed_date, source.strip()


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path, override=False)
    # The login helper writes a matched API-key/access-token pair to .env.
    # Prefer that pair over inherited shell variables, which may be stale.
    file_env = dotenv_values(env_path)

    parser = argparse.ArgumentParser(
        description=(
            "Acquire a five-symbol NSE EQ daily-candle pilot from Kite. "
            "Read-only: no order endpoints are used."
        )
    )
    parser.add_argument(
        "--universe-csv",
        type=Path,
        default=project_root / "data/universe/source/nse-nifty500-captured-2026-11-05.csv",
    )
    parser.add_argument(
        "--universe-effective-date",
        type=date.fromisoformat,
        default=date(2026, 9, 30),
    )
    parser.add_argument("--universe-source", default=UNIVERSE_SOURCE)
    parser.add_argument(
        "--calendar-csv",
        type=Path,
        default=project_root / "data/market_calendar/nse-equity-holidays-2025-2026.csv",
    )
    parser.add_argument(
        "--calendar-source",
        default=(
            "NSE Capital Market Segment 2025 Circular 170/2024 and NSE official "
            "2026 equity holiday page; per-row source URLs are in the calendar CSV"
        ),
    )
    parser.add_argument(
        "--calendar-coverage-start", type=date.fromisoformat, default=date(2025, 1, 1)
    )
    parser.add_argument(
        "--calendar-coverage-end", type=date.fromisoformat, default=date(2026, 12, 31)
    )
    parser.add_argument("--from-date", type=date.fromisoformat, default=date(2025, 11, 6))
    parser.add_argument("--to-date", type=date.fromisoformat, default=date(2026, 11, 5))
    parser.add_argument(
        "--symbols",
        default=DEFAULT_SYMBOLS,
        help="Exactly five comma-separated EQ symbols",
    )
    parser.add_argument("--chunk-days", type=int, default=365)
    parser.add_argument(
        "--special-session",
        action="append",
        type=_special_session,
        default=[],
        metavar="DATE=SOURCE",
        help="Explicit NSE special session; may be supplied more than once",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=project_root / "data/market_data",
        help="Local Git-ignored output root (default: data/market_data)",
    )
    args = parser.parse_args()

    if args.from_date > args.to_date:
        parser.error("--from-date must be on or before --to-date")
    if args.calendar_coverage_start > args.calendar_coverage_end:
        parser.error("calendar coverage start must be on or before its end")
    if args.chunk_days < 1:
        parser.error("--chunk-days must be positive")
    symbols = [value.strip().upper() for value in args.symbols.split(",")]
    if len(symbols) != 5 or len(set(symbols)) != 5 or any(not value for value in symbols):
        parser.error("--symbols must contain exactly five unique, non-empty symbols")
    if len(dict(args.special_session)) != len(args.special_session):
        parser.error("--special-session cannot contain duplicate dates")
    special_sessions = dict(DEFAULT_SPECIAL_SESSIONS)
    special_sessions.update(dict(args.special_session))

    api_key = file_env.get("KITE_API_KEY") or os.environ.get("KITE_API_KEY")
    access_token = file_env.get("KITE_ACCESS_TOKEN") or os.environ.get("KITE_ACCESS_TOKEN")
    if not api_key or not access_token:
        parser.error(
            "KITE_API_KEY and KITE_ACCESS_TOKEN must be configured locally; "
            "run scripts/kite_read_only_login.py if needed"
        )

    universe_csv = (
        args.universe_csv
        if args.universe_csv.is_absolute()
        else project_root / args.universe_csv
    )
    calendar_csv = (
        args.calendar_csv
        if args.calendar_csv.is_absolute()
        else project_root / args.calendar_csv
    )
    data_root = (
        args.data_dir if args.data_dir.is_absolute() else project_root / args.data_dir
    )
    for required_path in (universe_csv, calendar_csv):
        if not required_path.is_file():
            parser.error(f"required source file does not exist: {required_path}")

    client = KiteConnect(api_key=api_key)
    client.set_access_token(access_token)
    manifest_path, manifest = run_kite_daily_pilot(
        client,
        universe_csv=universe_csv,
        universe_effective_date=args.universe_effective_date,
        universe_source=args.universe_source,
        calendar_csv=calendar_csv,
        calendar_source=args.calendar_source,
        calendar_coverage_start=args.calendar_coverage_start,
        calendar_coverage_end=args.calendar_coverage_end,
        start=args.from_date,
        end=args.to_date,
        symbols=symbols,
        data_root=data_root,
        chunk_days=args.chunk_days,
        special_sessions=special_sessions,
    )

    print(f"Pilot status: {manifest['pilot_status']}")
    print(f"Manifest: {manifest_path}")
    print(f"Manifest SHA-256: {manifest['manifest_sha256']}")
    for result in manifest["symbols"]:
        print(
            f"{result['symbol']}: {result['status']} "
            f"(rows={result.get('row_count', 0)}, "
            f"missing_sessions={len(result.get('missing_expected_sessions', []))})"
        )
    print("Read-only mode: YES")
    print("Order endpoints called: 0")
    print("Adjustment status: provider_adjusted_unreconciled")
    return 0 if manifest["pilot_status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
