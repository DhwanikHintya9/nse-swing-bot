import pandas as pd

# List of prominent Nifty 500 tickers across sectors
symbols = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", 
    "TATAMOTORS", "AXISBANK", "LT", "HINDUNILVR", "BAJAJFINSV", "MARUTI", "SUNPHARMA",
    "TITAN", "ULTRACEMCO", "ADANIENT", "JSWSTEEL", "POWERGRID", "NTPC", "M&M",
    "TATASTEEL", "HCLTECH", "KOTAKBANK", "COALINDIA", "ASIANPAINT", "ONGC", "WIPRO",
    "BAJFINANCE", "ADANIPORTS", "GRASIM", "TECHM", "EICHERMOT", "HINDALCO", "NESTLEIND",
    "APOLLOHOSP", "DRREDDY", "CIPLA", "BPCL", "BRITANNIA", "DIVISLAB", "TATACONSUM",
    "HEROMOTOCO", "INDUSINDBK", "SHRIRAMFIN", "JIOFIN", "ZOMATO", "HAL", "BEL",
    "TRENTS", "TATACHEM", "POLYCAB", "IRFC", "PFC", "RECLTD", "DLF", "VBL"
]

# Generate and save the local CSV structure
df = pd.DataFrame({"Symbol": symbols})
df.to_csv("ind_nifty500list.csv", index=False)
print("✅ Local 'ind_nifty500list.csv' generated perfectly with high-liquidity market tickers!")
