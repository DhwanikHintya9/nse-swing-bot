import os
import sys
import datetime
import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from kiteconnect import KiteConnect

# ==========================================
# ⚙️ CONFIGURATION & SYSTEM PARAMETERS
# ==========================================
load_dotenv()

API_KEY = os.getenv("ZERODHA_API_KEY")
API_SECRET = os.getenv("ZERODHA_API_SECRET")

if not API_KEY or not API_SECRET:
    print("❌ Critical Error: Credentials missing from .env file.")
    sys.exit()

ACCOUNT_SIZE = 300000     # Total trading capital in ₹
RISK_PER_TRADE = 1.0     # Risk precisely 1% of capital (₹3,000) per trade

# ==========================================
# 🔐 ZERODHA INITIALIZATION & AUTH
# ==========================================
kite = KiteConnect(api_key=API_KEY)

print("1. Copy and paste this URL into your browser to authorize:")
print(kite.login_url())

request_token = input("\n2. Paste the 'request_token' from the redirected URL here: ").strip()

try:
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    kite.set_access_token(data["access_token"])
    print("✅ Session active. Secure Scanner online.\n")
except Exception as e:
    print(f"❌ Authentication failed: {e}")
    sys.exit()

# ==========================================
# 📊 OFFLINE WATCHLIST & SHIELD ENGINE
# ==========================================
def load_local_tickers():
    local_file = "ind_nifty500list.csv"
    if os.path.exists(local_file):
        df_nse = pd.read_csv(local_file)
        return [str(symbol).strip() + ".NS" for symbol in df_nse['Symbol']]
    return ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "SBIN.NS"]

def scan_and_shield_asset(ticker):
    """Processes technical indicators and cross-checks the corporate calendar."""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y", interval="1d")
        if len(df) < 50: return None
        
        # 1. Technical Math
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['Vol_Avg_20'] = df['Volume'].rolling(window=20).mean()
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['RSI_14'] = 100 - (100 / (1 + (gain / loss)))
        
        ranges = pd.concat([df['High']-df['Low'], abs(df['High']-df['Close'].shift()), abs(df['Low']-df['Close'].shift())], axis=1)
        df['ATR_14'] = ranges.max(axis=1).rolling(window=14).mean()
        
        latest = df.iloc[-1]
        
        # 2. Corporate Calendar Shield Verification
        days_to_earnings = 999
        try:
            cal = stock.calendar
            if cal is not None and 'Earnings Date' in cal:
                next_earnings_date = cal['Earnings Date']
                if isinstance(next_earnings_date, (datetime.date, datetime.datetime)):
                    if hasattr(next_earnings_date, 'date'):
                        next_earnings_date = next_earnings_date.date()
                    days_to_earnings = (next_earnings_date - datetime.date.today()).days
        except:
            pass
            
        # 3. Strategy Core Gates
        rule_trend = latest['Close'] > latest['SMA_50']
        rule_rsi = latest['RSI_14'] < 45
        rule_vol = latest['Volume'] > latest['Vol_Avg_20']
        
        # Shield triggers an block if earnings are within 5 days
        rule_shield_passed = days_to_earnings > 5 or days_to_earnings < 0
        
        if rule_trend and rule_rsi and rule_vol:
            kite_symbol = ticker.replace(".NS", "")
            if not rule_shield_passed:
                print(f"🛑 [SHIELD BLOCK] {kite_symbol} matched technical setups but has earnings in {days_to_earnings} days. Order canceled.")
                return None
                
            risk_per_share = latest['ATR_14'] * 1.5
            shares = np.floor((ACCOUNT_SIZE * (RISK_PER_TRADE / 100.0)) / risk_per_share)
            
            return {
                "kite_symbol": kite_symbol,
                "qty": int(shares),
                "price": round(latest['Close'], 2),
                "sl_trigger": round(latest['Close'] - risk_per_share, 1),
                "target_trigger": round(latest['Close'] + (risk_per_share * 2.0), 1)
            }
    except Exception as e:
        pass
    return None

# ==========================================
# ⚡ LIVE EXECUTION LOOP
# ==========================================
WATCHLIST = load_local_tickers()
print(f"📡 Initiating secure execution loop across {len(WATCHLIST)} assets...")

for stock_ticker in WATCHLIST:
    setup = scan_and_shield_asset(stock_ticker)
    
    if setup and setup['qty'] > 0:
        print(f"\n🚀 Clear Entry Setup Verified for {setup['kite_symbol']}! Executing live order routing...")
        try:
            # 1. Place Primary Delivery Buy Order (CNC Equity)
            order_id = kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=kite.EXCHANGE_NSE,
                tradingsymbol=setup['kite_symbol'],
                transaction_type=kite.TRANSACTION_TYPE_BUY,
                quantity=setup['qty'],
                product=kite.PRODUCT_CNC,       # CNC = Cash & Carry Delivery
                order_type=kite.ORDER_TYPE_MARKET
            )
            print(f"🎯 Buy Order Placed Successfully! ID: {order_id}")
            
            # 2. Attach Long-Term Server-Side GTT Bracket (Stop-Loss and Target OCO)
            gtt_id = kite.place_gtt(
                trigger_type=kite.GTT_TYPE_OCO,
                tradingsymbol=setup['kite_symbol'],
                exchange=kite.EXCHANGE_NSE,
                trigger_values=[setup['sl_trigger'], setup['target_trigger']],
                last_price=setup['price'],
                orders=[
                    {
                        "exchange": kite.EXCHANGE_NSE,
                        "tradingsymbol": setup['kite_symbol'],
                        "transaction_type": kite.TRANSACTION_TYPE_SELL,
                        "quantity": setup['qty'],
                        "product": kite.PRODUCT_CNC,
                        "order_type": kite.ORDER_TYPE_LIMIT,
                        "price": setup['sl_trigger']
                    },
                    {
                        "exchange": kite.EXCHANGE_NSE,
                        "tradingsymbol": setup['kite_symbol'],
                        "transaction_type": kite.TRANSACTION_TYPE_SELL,
                        "quantity": setup['qty'],
                        "product": kite.PRODUCT_CNC,
                        "order_type": kite.ORDER_TYPE_LIMIT,
                        "price": setup['target_trigger']
                    }
                ]
            )
            print(f"🛡️ Server-Side GTT Exit Bracket Dropped! ID: {gtt_id}")
            print(f"   ↳ [Stop Loss: ₹{setup['sl_trigger']}] | [Target (1:2): ₹{setup['target_trigger']}]")
            
        except Exception as e:
            print(f"❌ Execution failure on {setup['kite_symbol']}: {e}")

print("\n🏁 Secure Live Order Routing sequence complete.")
