"""Read-only Kite ingestion smoke test with validated local Parquet persistence."""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from kiteconnect import KiteConnect

from nse_swing_bot.market_data.checkpoints import JsonChunkCheckpointStore
from nse_swing_bot.market_data.kite_adapter import KiteMarketDataAdapter
from nse_swing_bot.market_data.parquet_store import ParquetCandleStore
from nse_swing_bot.market_data.quarantine import DataQualityQuarantine
from nse_swing_bot.market_data.service import MarketDataService


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=project_root / ".env", override=True)

    parser = argparse.ArgumentParser(
        description=(
            "Fetch one NSE symbol from Kite, validate it, persist an immutable Parquet "
            "snapshot, and verify the persisted rows. This script never places orders."
        )
    )
    parser.add_argument("--symbol", required=True, help="NSE trading symbol to ingest")
    parser.add_argument(
        "--from-date", type=date.fromisoformat, required=True, help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--to-date", type=date.fromisoformat, required=True, help="End date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=project_root / "data" / "market_data",
        help="Local data root (default: data/market_data; Git-ignored)",
    )
    parser.add_argument(
        "--chunk-days", type=int, default=365, help="Maximum calendar days per Kite request"
    )
    args = parser.parse_args()

    if args.from_date > args.to_date:
        parser.error("--from-date must be on or before --to-date")
    if args.chunk_days < 1:
        parser.error("--chunk-days must be positive")

    api_key = os.environ.get("KITE_API_KEY")
    access_token = os.environ.get("KITE_ACCESS_TOKEN")
    if not api_key or not access_token:
        parser.error(
            "run scripts/kite_read_only_login.py first to create local Kite credentials"
        )

    data_root = args.data_dir
    if not data_root.is_absolute():
        data_root = project_root / data_root

    client = KiteConnect(api_key=api_key)
    client.set_access_token(access_token)
    client.profile()

    store = ParquetCandleStore(data_root / "parquet")
    adapter = KiteMarketDataAdapter(
        client,
        checkpoint_store=JsonChunkCheckpointStore(data_root / "checkpoints"),
    )
    service = MarketDataService(
        adapter=adapter,
        store=store,
        snapshot_root=data_root / "snapshots",
        quarantine=DataQualityQuarantine(data_root / "quarantine"),
    )

    instruments, instrument_snapshot = service.refresh_instrument_master()
    symbol = args.symbol.strip().upper()
    matches = instruments.loc[instruments["tradingsymbol"] == symbol]
    if len(matches) != 1:
        parser.error(f"{symbol} did not resolve to exactly one NSE cash-equity instrument")

    paths, fetched = service.sync_daily_history_with_data(
        matches.iloc[0],
        args.from_date,
        args.to_date,
        chunk_days=args.chunk_days,
    )
    persisted = store.read_latest(
        f"NSE:{symbol}", args.from_date.isoformat(), args.to_date.isoformat()
    )

    try:
        pd.testing.assert_frame_equal(
            persisted, fetched, check_dtype=False, check_freq=False, check_exact=False,
            rtol=1e-10, atol=1e-10,
        )
    except AssertionError as error:
        raise RuntimeError(
            "Parquet read-back does not match the validated Kite candle payload"
        ) from error

    if persisted.empty:
        raise RuntimeError("no candles were available to verify after Parquet persistence")

    print("Kite authentication: OK")
    print(f"NSE cash-equity instruments normalized: {len(instruments)}")
    print(f"Instrument snapshot: {instrument_snapshot.relative_to(project_root)}")
    print(f"Validated Kite candles: {len(fetched)}")
    print(f"Persisted Parquet snapshots: {len(paths)}")
    print(f"Persisted candles read back: {len(persisted)}")
    print(f"Verified range: {persisted.index.min().date()} to {persisted.index.max().date()}")
    print("Parquet read-back matches validated Kite candles: YES")
    print("Order endpoints called: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
