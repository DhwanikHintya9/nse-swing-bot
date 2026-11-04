import os
import pandas as pd
import numpy as np
import yfinance as yf

# ==========================================
# ⚙️ BACKTEST CONFIGURATION
# ==========================================
START_CAPITAL = 300000.0  # Initial Portfolio size (₹)
RISK_PER_TRADE_PCT = 1.0  # Risk precisely 1% of equity per trade
REWARD_RATIO = 2.0        # 2:1 Profit Target matrix

def load_local_tickers():
    local_file = "ind_nifty500list.csv"
    if os.path.exists(local_file):
        df_nse = pd.read_csv(local_file)
        return [str(symbol).strip() + ".NS" for symbol in df_nse['Symbol']]
    return ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "SBIN.NS"]

# ==========================================
# ⚙️ SIMULATION MATRIX LOGIC
# ==========================================
def run_backtest_simulation():
    watchlist = load_local_tickers()
    
    total_trades = 0
    winning_trades = 0
    losing_trades = 0
    current_equity = START_CAPITAL
    
    print("=" * 80)
    print(f"⏳ RUNNING 5-YEAR STRATEGY BACKTEST (Starting Capital: ₹{START_CAPITAL:,})")
    print("=" * 80)
    
    for ticker in watchlist[:20]: # Testing top 20 tokens for speedy execution
        try:
            # Fetch 5 years of historical daily candles
            df = yf.Ticker(ticker).history(period="5y", interval="1d")
            if len(df) < 100: continue
            
            # Reconstruct Strategy Indicators
            df['SMA_50'] = df['Close'].rolling(window=50).mean()
            df['Vol_Avg_20'] = df['Volume'].rolling(window=20).mean()
            
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            df['RSI_14'] = 100 - (100 / (1 + (gain / (loss + 1e-10))))
            
            ranges = pd.concat([df['High']-df['Low'], abs(df['High']-df['Close'].shift()), abs(df['Low']-df['Close'].shift())], axis=1)
            df['ATR_14'] = ranges.max(axis=1).rolling(window=14).mean()
            
            # Identify Signal Event Points
            df['Rule_Trend'] = df['Close'] > df['SMA_50']
            df['Rule_RSI'] = df['RSI_14'] < 45
            df['Rule_Vol'] = df['Volume'] > df['Vol_Avg_20']
            df['Signal'] = df['Rule_Trend'] & df['Rule_RSI'] & df['Rule_Vol']
            
            # Step through time series to simulate active trades
            in_position = False
            entry_price = 0
            stop_loss = 0
            take_profit = 0
            
            for i in range(50, len(df)):
                current_row = df.iloc[i]
                
                if not in_position:
                    # Evaluate Entry Setup
                    if df.iloc[i-1]['Signal']: # Entry trigger on previous day setup match
                        in_position = True
                        entry_price = current_row['Open']
                        risk_per_share = df.iloc[i-1]['ATR_14'] * 1.5
                        if risk_per_share <= 0: risk_per_share = entry_price * 0.02
                        
                        stop_loss = entry_price - risk_per_share
                        take_profit = entry_price + (risk_per_share * REWARD_RATIO)
                else:
                    # Evaluate Active Position Exits
                    if current_row['Low'] <= stop_loss:
                        # Hit Stop Loss (Loss Event)
                        in_position = False
                        losing_trades += 1
                        total_trades += 1
                        current_equity -= (current_equity * (RISK_PER_TRADE_PCT / 100.0))
                    elif current_row['High'] >= take_profit:
                        # Hit Take Profit (Win Event)
                        in_position = False
                        winning_trades += 1
                        total_trades += 1
                        current_equity += ((current_equity * (RISK_PER_TRADE_PCT / 100.0)) * REWARD_RATIO)
                        
        except Exception as e:
            continue
            
    # Calculate Final System Metrics
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    profit_factor = (winning_trades * REWARD_RATIO) / max(losing_trades, 1)
    net_return_pct = ((current_equity - START_CAPITAL) / START_CAPITAL) * 100
    
    print("\n🏁 FINAL STRATEGY PERFORMANCE METRICS:")
    print("-" * 50)
    print(f"📊 Total Simulated Trades: {total_trades}")
    print(f"✅ Winning Trades: {winning_trades} | 🛑 Losing Trades: {losing_trades}")
    print(f"🎯 Strategy Win Rate: {win_rate:.2f}%")
    print(f"⚖️ Profit Factor (Reward Matrix Edge): {profit_factor:.2f}")
    print("-" * 50)
    print(f"💰 Starting Account Equity: ₹{START_CAPITAL:,.2f}")
    print(f"🚀 Final Simulated Capital: ₹{current_equity:,.2f}")
    print(f"📈 Net Return on Investment (ROI): {net_return_pct:+.2f}%")
    print("-" * 50)

if __name__ == "__main__":
    run_backtest_simulation()
