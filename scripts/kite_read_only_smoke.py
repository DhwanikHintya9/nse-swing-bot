"""Run a read-only Kite Connect smoke test; this script never places orders."""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from kiteconnect import KiteConnect

from nse_swing_bot.market_data.instruments import normalize_instrument_master
from nse_swing_bot.market_data.kite_adapter import KiteMarketDataAdapter


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=project_root / ".env", override=True)

    parser = argparse.ArgumentParser(
        description="Validate Kite authentication, NSE instruments, and daily candles."
    )
    parser.add_argument("--symbol", required=True, help="NSE trading symbol to test")
    parser.add_argument(
        "--from-date", type=date.fromisoformat, required=True, help="Start date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--to-date", type=date.fromisoformat, required=True, help="End date (YYYY-MM-DD)"
    )
    args = parser.parse_args()

    if args.from_date > args.to_date:
        parser.error("--from-date must be on or before --to-date")

    api_key = os.environ.get("KITE_API_KEY")
    access_token = os.environ.get("KITE_ACCESS_TOKEN")
    if not api_key or not access_token:
        parser.error(
            "run scripts/kite_read_only_login.py first to create local Kite credentials"
        )

    client = KiteConnect(api_key=api_key)
    client.set_access_token(access_token)

    # Profile is read-only and confirms that the local token is accepted.
    client.profile()
    adapter = KiteMarketDataAdapter(client)
    raw_instruments = adapter.fetch_nse_instruments()
    instruments = normalize_instrument_master(raw_instruments)

    symbol = args.symbol.strip().upper()
    matches = instruments.loc[instruments["tradingsymbol"] == symbol]
    if len(matches) != 1:
        parser.error(f"{symbol} did not resolve to exactly one NSE cash-equity instrument")

    token = int(matches.iloc[0]["instrument_token"])
    candles = adapter.fetch_daily_candles(token, args.from_date, args.to_date)
    if candles.empty:
        parser.error(f"Kite returned no daily candles for {symbol} in the requested range")

    print("Kite authentication: OK")
    print(f"NSE cash-equity instruments normalized: {len(instruments)}")
    print(f"Read-only historical candles for {symbol}: {len(candles)}")
    print(f"Returned range: {candles.index.min().date()} to {candles.index.max().date()}")
    print("Order endpoints called: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
