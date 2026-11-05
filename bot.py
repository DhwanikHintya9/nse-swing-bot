import os
import sys
import datetime
from getpass import getpass

import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from kiteconnect import KiteConnect

# ==========================================
# CONFIGURATION & SYSTEM PARAMETERS
# ==========================================
# This development scanner is paper-only. Live order routing is intentionally disabled.
load_dotenv()

API_KEY = os.getenv("ZERODHA_API_KEY")
API_SECRET = os.getenv("ZERODHA_API_SECRET")

if not API_KEY or not API_SECRET:
    print("Critical Error: Credentials missing from .env file.")
    sys.exit(1)

ACCOUNT_SIZE = 300000
RISK_PER_TRADE = 1.0

# ==========================================
# KITE SESSION AUTHENTICATION
# ==========================================
kite = KiteConnect(api_key=API_KEY)

print("Copy and paste this URL into your browser to authorize:")
print(kite.login_url())
request_token = getpass("Paste the redirected request_token (input hidden): ").strip()

try:
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    kite.set_access_token(data["access_token"])
    print("Session active. Paper-only scanner online.\n")
except Exception as exc:
    print(f"Authentication failed ({type(exc).__name__}).")
    sys.exit(1)


def load_local_tickers() -> list[str]:
    local_file = "ind_nifty500list.csv"
    if os.path.exists(local_file):
        frame = pd.read_csv(local_file)
        return [str(symbol).strip() + ".NS" for symbol in frame["Symbol"]]
    return ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "SBIN.NS"]


def scan_and_shield_asset(ticker: str) -> dict[str, int | float | str] | None:
    """Calculate a paper signal and apply the prototype earnings check."""
    try:
        stock = yf.Ticker(ticker)
        frame = stock.history(period="1y", interval="1d")
        if len(frame) < 50:
            return None

        frame["SMA_50"] = frame["Close"].rolling(window=50).mean()
        frame["Vol_Avg_20"] = frame["Volume"].rolling(window=20).mean()

        delta = frame["Close"].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        frame["RSI_14"] = 100 - (100 / (1 + (gain / loss)))

        ranges = pd.concat(
            [
                frame["High"] - frame["Low"],
                abs(frame["High"] - frame["Close"].shift()),
                abs(frame["Low"] - frame["Close"].shift()),
            ],
            axis=1,
        )
        frame["ATR_14"] = ranges.max(axis=1).rolling(window=14).mean()
        latest = frame.iloc[-1]

        days_to_earnings = 999
        try:
            calendar = stock.calendar
            if calendar is not None and "Earnings Date" in calendar:
                earnings_date = calendar["Earnings Date"]
                if isinstance(earnings_date, (datetime.date, datetime.datetime)):
                    if hasattr(earnings_date, "date"):
                        earnings_date = earnings_date.date()
                    days_to_earnings = (earnings_date - datetime.date.today()).days
        except Exception:
            pass

        rule_trend = latest["Close"] > latest["SMA_50"]
        rule_rsi = latest["RSI_14"] < 45
        rule_volume = latest["Volume"] > latest["Vol_Avg_20"]
        shield_passed = days_to_earnings > 5 or days_to_earnings < 0

        if rule_trend and rule_rsi and rule_volume:
            kite_symbol = ticker.replace(".NS", "")
            if not shield_passed:
                print(
                    f"[SHIELD BLOCK] {kite_symbol} matched the technical rules but "
                    f"has earnings in {days_to_earnings} days."
                )
                return None

            risk_per_share = latest["ATR_14"] * 1.5
            if not np.isfinite(risk_per_share) or risk_per_share <= 0:
                return None
            quantity = int(np.floor((ACCOUNT_SIZE * (RISK_PER_TRADE / 100.0)) / risk_per_share))
            return {
                "kite_symbol": kite_symbol,
                "qty": quantity,
                "price": round(float(latest["Close"]), 2),
                "sl_trigger": round(float(latest["Close"] - risk_per_share), 1),
                "target_trigger": round(float(latest["Close"] + (risk_per_share * 2.0)), 1),
            }
    except Exception:
        return None
    return None


# ==========================================
# PAPER-ONLY SCAN LOOP — NO ORDER ENDPOINTS
# ==========================================
watchlist = load_local_tickers()
print(f"Scanning {len(watchlist)} assets in paper-only mode. Live order routing is disabled.")

for stock_ticker in watchlist:
    setup = scan_and_shield_asset(stock_ticker)
    if setup and setup["qty"] > 0:
        print(
            f"[PAPER SIGNAL] {setup['kite_symbol']} | quantity={setup['qty']} | "
            f"reference price={setup['price']} | stop={setup['sl_trigger']} | "
            f"target={setup['target_trigger']}"
        )

print("Paper-only scan complete. No orders or GTTs were submitted.")
