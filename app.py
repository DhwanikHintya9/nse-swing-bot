import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import os
import datetime
from dotenv import load_dotenv

load_dotenv()

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="NSE Trailing-Stop Radar", page_icon="📊", layout="wide")

st.title("📊 NSE Automated Swing Trading Dashboard (with Trailing Stop)")
st.markdown("---")

# --- SIDEBAR CONTROL PORTAL ---
st.sidebar.header("🎛️ Risk Management Setup")
ACCOUNT_SIZE = st.sidebar.number_input("Total Trading Capital (₹)", min_value=10000, value=300000, step=10000)
RISK_PER_TRADE = st.sidebar.slider("Risk Per Trade (%)", min_value=0.25, max_value=5.0, value=1.0, step=0.25)
RISK_RUPEES = ACCOUNT_SIZE * (RISK_PER_TRADE / 100.0)

st.sidebar.metric("Allowed Risk Per Trade", f"₹{RISK_RUPEES:,.2f}")

def load_local_tickers():
    local_file = "ind_nifty500list.csv"
    if os.path.exists(local_file):
        df_nse = pd.read_csv(local_file)
        return [str(symbol).strip() + ".NS" for symbol in df_nse['Symbol']]
    return ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "SBIN.NS"]

WATCHLIST = load_local_tickers()

# --- MATHEMATICAL MATRIX ENGINE ---
def analyze_asset_with_trailing(ticker):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y", interval="1d")
        if len(df) < 50: return None, None
        
        # 1. Base Strategy Indicators
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['Vol_Avg_20'] = df['Volume'].rolling(window=20).mean()
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        df['RSI_14'] = 100 - (100 / (1 + (gain / (loss + 1e-10))))
        
        ranges = pd.concat([df['High']-df['Low'], abs(df['High']-df['Close'].shift()), abs(df['Low']-df['Close'].shift())], axis=1)
        df['ATR_14'] = ranges.max(axis=1).rolling(window=14).mean()
        
        # 2. Dynamic Chandelier Trailing Stop Calculation
        # It calculates the highest high over the last 14 days and subtracts 2.5x ATR
        df['Highest_High_14'] = df['High'].rolling(window=14).max()
        df['Trailing_Stop_Raw'] = df['Highest_High_14'] - (df['ATR_14'] * 2.5)
        
        # Ensure the trailing stop can only move up, never down
        trailing_stops = []
        current_max_stop = 0
        for i in range(len(df)):
            raw_stop = df['Trailing_Stop_Raw'].iloc[i]
            if pd.isna(raw_stop):
                trailing_stops.append(np.nan)
            else:
                if df['Close'].iloc[i] < current_max_stop:
                    current_max_stop = raw_stop # Trend broken, reset trailing stop
                else:
                    current_max_stop = max(raw_stop, current_max_stop)
                trailing_stops.append(current_max_stop)
        df['Trailing_Stop'] = trailing_stops

        latest = df.iloc[-1]
        
        # 3. Calendar Event Shield
        days_to_earnings = 999
        earnings_date_str = "No Event Scheduled"
        try:
            cal = stock.calendar
            if cal is not None and 'Earnings Date' in cal:
                next_earnings_date = cal['Earnings Date']
                if isinstance(next_earnings_date, list) and len(next_earnings_date) > 0:
                    next_earnings_date = next_earnings_date[0]
                if isinstance(next_earnings_date, (datetime.date, datetime.datetime)):
                    if hasattr(next_earnings_date, 'date'):
                        next_earnings_date = next_earnings_date.date()
                    days_to_earnings = (next_earnings_date - datetime.date.today()).days
                    earnings_date_str = next_earnings_date.strftime("%Y-%m-%d")
        except:
            pass
            
        rule_trend = latest['Close'] > latest['SMA_50']
        rule_rsi = latest['RSI_14'] < 45
        rule_vol = latest['Volume'] > latest['Vol_Avg_20']
        rule_shield_passed = days_to_earnings > 5 or days_to_earnings < 0
        
        signal = rule_trend and rule_rsi and rule_vol and rule_shield_passed
        
        risk_per_share = latest['ATR_14'] * 1.5
        shares = np.floor(RISK_RUPEES / risk_per_share) if risk_per_share > 0 else 0
        
        row_metrics = {
            "Symbol": ticker.replace(".NS", ""),
            "Current Price (₹)": round(latest['Close'], 2),
            "RSI (14)": round(latest['RSI_14'], 1),
            "Above 50 SMA": "✅" if rule_trend else "❌",
            "RSI Pullback": "✅" if rule_rsi else "❌",
            "High Volume": "✅" if rule_vol else "❌",
            "Event Shield": "🛡️ SECURE" if rule_shield_passed else f"🚨 BLOCKED ({days_to_earnings} D)",
            "Signal Status": "🔥 BUY" if signal else ("🛑 SHIELD BLOCK" if (rule_trend and rule_rsi and rule_vol and not rule_shield_passed) else "⏳ Scan"),
            "Entry Point (₹)": round(latest['Close'], 2) if signal else "-",
            "Initial Stop Loss (₹)": round(latest['Close'] - risk_per_share, 2) if signal else "-",
            "Live Trailing Floor (₹)": round(latest['Trailing_Stop'], 2),
            "Allocated Shares": int(shares) if signal else "-"
        }
        return row_metrics, df
    except:
        return None, None

# --- PERSISTENT STATE STORAGE ---
if "results" not in st.session_state:
    st.session_state.results = None
if "charts" not in st.session_state:
    st.session_state.charts = None

if st.button(f"📡 Execute Scan Across Watchlist ({len(WATCHLIST)} Equities)"):
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    scanned_rows = []
    charts_pool = {}
    total = len(WATCHLIST)
    
    for idx, stock in enumerate(WATCHLIST):
        status_text.text(f"Scanning target {idx+1}/{total}: {stock}")
        progress_bar.progress((idx + 1) / total)
        
        row, hist = analyze_asset_with_trailing(stock)
        if row is not None:
            scanned_rows.append(row)
            charts_pool[row["Symbol"]] = hist
            
    status_text.text("🎉 Comprehensive market scan completed successfully!")
    if scanned_rows:
        st.session_state.results = pd.DataFrame(scanned_rows)
        st.session_state.charts = charts_pool

# --- RENDER PANELS ---
if st.session_state.results is not None:
    df_results = st.session_state.results
    charts_pool = st.session_state.charts
    
    buy_signals = df_results[df_results['Signal Status'] == "🔥 BUY"]
    
    if not buy_signals.empty:
        st.success(f"🚀 Found {len(buy_signals)} Active Trade Setup Allocations!")
        st.dataframe(buy_signals[["Symbol", "Current Price (₹)", "Entry Point (₹)", "Initial Stop Loss (₹)", "Live Trailing Floor (₹)", "Allocated Shares"]], use_container_width=True)
        
    st.subheader("📊 Full Market Matrix")
    st.dataframe(df_results, use_container_width=True)
    
    # --- CHART VISUAL OVERLAYS ---
    st.markdown("---")
    st.subheader("🔍 Interactive Technical Candlestick Analysis")
    selected_symbol = st.selectbox("Pick a stock token to view trend lines:", list(charts_pool.keys()))
    
    if selected_symbol and selected_symbol in charts_pool:
        chart_df = charts_pool[selected_symbol].tail(90)
        
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'], name='Price'))
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['SMA_50'], line=dict(color='orange', width=1.5), name='50 Day SMA'))
        
        # NEW: Trailing Stop Line Overlay
        fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['Trailing_Stop'], line=dict(color='crimson', width=2, dash='dot'), name='ATR Trailing Stop Floor'))
        
        fig.update_layout(title=f"{selected_symbol} Technical Trend Overlay (With Trailing Stop Line)", yaxis_title="Price (₹)", xaxis_title="Date", xaxis_rangeslider_visible=False, height=500, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
