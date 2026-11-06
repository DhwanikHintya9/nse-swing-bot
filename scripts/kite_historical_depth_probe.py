"""Run a five-symbol, read-only historical-depth availability probe."""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from kiteconnect import KiteConnect

from nse_swing_bot.market_data.depth_probe import run_kite_historical_depth_probe

DEFAULT_SYMBOLS = "RELIANCE,HDFCBANK,INFY,SUNPHARMA,LT"
UNIVERSE_SOURCE = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path, override=False)
    file_env = dotenv_values(env_path)

    parser = argparse.ArgumentParser(
        description=(
            "Probe a bounded historical daily-candle interval for five NSE EQ symbols. "
            "Read-only: no order endpoints are used; this does not certify coverage."
        )
    )
    parser.add_argument(
        "--universe-csv",
        type=Path,
        default=project_root / "data/universe/source/nse-nifty500-captured-2026-11-05.csv",
    )
    parser.add_argument("--universe-effective-date", type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument("--universe-source", default=UNIVERSE_SOURCE)
    parser.add_argument("--from-date", type=date.fromisoformat, default=date(2021, 11, 6))
    parser.add_argument("--to-date", type=date.fromisoformat, default=date(2022, 11, 5))
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--chunk-days", type=int, default=365)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=project_root / "data/market_data/depth_probe",
        help="Local Git-ignored probe output root",
    )
    args = parser.parse_args()

    if args.from_date > args.to_date:
        parser.error("--from-date must be on or before --to-date")
    if args.chunk_days < 1:
        parser.error("--chunk-days must be positive")
    symbols = [value.strip().upper() for value in args.symbols.split(",")]
    if len(symbols) != 5 or len(set(symbols)) != 5 or any(not value for value in symbols):
        parser.error("--symbols must contain exactly five unique, non-empty symbols")

    api_key = file_env.get("KITE_API_KEY") or os.environ.get("KITE_API_KEY")
    access_token = file_env.get("KITE_ACCESS_TOKEN") or os.environ.get("KITE_ACCESS_TOKEN")
    if not api_key or not access_token:
        parser.error(
            "KITE_API_KEY and KITE_ACCESS_TOKEN must be configured locally; "
            "run scripts/kite_read_only_login.py if needed"
        )

    universe_csv = (
        args.universe_csv if args.universe_csv.is_absolute() else project_root / args.universe_csv
    )
    data_root = args.data_dir if args.data_dir.is_absolute() else project_root / args.data_dir
    if not universe_csv.is_file():
        parser.error(f"required source file does not exist: {universe_csv}")

    client = KiteConnect(api_key=api_key)
    client.set_access_token(access_token)
    manifest_path, manifest = run_kite_historical_depth_probe(
        client,
        universe_csv=universe_csv,
        universe_effective_date=args.universe_effective_date,
        universe_source=args.universe_source,
        start=args.from_date,
        end=args.to_date,
        symbols=symbols,
        data_root=data_root,
        chunk_days=args.chunk_days,
    )

    print(f"Probe status: {manifest['probe_status']}")
    print(f"Manifest: {manifest_path}")
    print(f"Manifest SHA-256: {manifest['manifest_sha256']}")
    for result in manifest["symbols"]:
        print(
            f"{result['symbol']}: {result['status']} "
            f"(rows={result.get('returned_rows', 0)}, "
            f"first={result.get('earliest_returned_date', 'n/a')}, "
            f"last={result.get('latest_returned_date', 'n/a')})"
        )
    print("Read-only mode: YES")
    print("Order endpoints called: 0")
    print("Adjustment status: provider_adjusted_unreconciled")
    print("Coverage certification: NOT PERFORMED")
    return 0 if manifest["probe_status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
