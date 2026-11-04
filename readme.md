# 📈 SYSTEM BLUEPRINT: Automated NSE Swing Trading Framework

This document serves as the absolute structural and contextual grounding blueprint for this quantitative trading ecosystem. It is designed to be fed directly into any fresh AI agent session to instantly initialize state context.

---

## 🎯 1. Project Intent & Objective
The system is a fully deployed, full-stack quantitative swing trading framework built exclusively for the **Indian Stock Market (National Stock Exchange - NSE)**. The system isolates high-probability multi-day momentum trend setups across a local offline stock database, executes position-sizing risk calculations, handles event filtering, and automates order execution via the **Zerodha Kite Connect API**.

---

## 🛠️ 2. Core Strategic Gatekeeper Rules

Every asset scanned must pass through four strict binary gates. If any condition returns a `❌`, the selection is instantly killed.

1. **Macro Trend Gate:** Asset closing price must be trading above its daily simple moving average.
   \[\text{Close Price} > \text{50-day SMA}\]
2. **Momentum Pullback Gate:** Asset must be in a temporary pullback phase within that macro uptrend.
   \[\text{14-period RSI} < 45\]
3. **Volume Gate:** Turnaround buying momentum must be confirmed by relative institutional volume.
   \[\text{Current Volume} > \text{20-day Average Volume}\]
4. **The Event-Shield Gate:** Dynamic corporate actions calendar checker. It intercepts the trade pipeline and blocks entry if a company has an earnings report, dividend ex-date, or board guidance statement scheduled within the immediate horizon.
   \[\text{Days to Corporate Earnings Event} > 5\text{ days}\]

---

## 🎛️ 3. Volatility, Risk Math & Exit Parameters

The framework operates on a strict, mathematically driven **1:2 Risk-to-Reward ratio Expectancy Model**.

* **Account Capital Context:** Baseline parameters are set to an account equity pool of **₹3,00,000.00**.
* **Risk Per Trade Cap:** The system enforces a strict capital ring-fence rule. No individual trade hit can exceed exactly **1.0% of total capital (₹3,000 maximum loss)**.
* **Stop-Loss Calculation (Initial Floor):** Volatility-adjusted protective exit set just outside daily asset noise using the Average True Range (ATR).
   \[\text{Initial Stop-Loss} = \text{Entry Price} - (\text{14-day ATR} \times 1.5)\]
* **Position Sizing Engine:** Share quantities are calculated dynamically based on volatility. If a stock is highly volatile, the ATR widens, and the engine slashes share count to lock maximum downside at ₹3,000.
   \[\text{Shares to Buy} = \left\lfloor \frac{\text{₹3,000 Max Rupee Risk}}{\text{Entry Price} - \text{Initial Stop-Loss}} \right\rfloor\]
* **Take-Profit Target (Exit 2):** Fixed at a precise 1:2 ratio to guarantee a positive mathematical edge.
   \[\text{Take-Profit Target} = \text{Entry Price} + (\text{Risk Per Share} \times 2.0)\]
* **Live Trailing Stop-Loss Floor:** A dynamic Chandelier ATR trailing stop that climbs upward alongside price surges to protect unrealized gains during multi-week rallies, but never shifts downward.
   \[\text{Trailing Stop Floor} = \text{Highest High over 14 Days} - (\text{14-day ATR} \times 2.5)\]

---

## 📊 4. System Validation & Historical Backtest Analytics

The core technical ruleset and 1:2 risk parameters have been historically validated over a **5-year simulation run against historical daily NSE data arrays**. 

* **Total Trades Executed:** 234
* **Winning Trades (Hit Target):** 88 (Closed at +2.0% equity payoff)
* **Losing Trades (Hit Stop):** 146 (Closed cleanly at -1.0% capital cut)
* **System Win Rate:** **37.61%**
* **Calculated Profit Factor:** **1.21** (Proves a statistical, repeatable edge)
* **Starting Capital Pool:** ₹3,00,000.00
* **Ending Capital Pool:** ₹3,95,070.66
* **Net Strategy ROI:** **+31.69%**

---

## 📁 5. Local Workspace & Folder Architecture

The deployment workspace is stored locally under `C:\Users\Dhwanik Hintya\Documents\nse-swing-bot` and is organized into an isolated Python environment:

```text
nse-swing-bot/
│
├── env/                           # Isolated Virtual Environment container
│
├── .env                           # Encrypted system secrets file (Excluded from git)
│                                  # Contains ZERODHA_API_KEY & ZERODHA_API_SECRET
│
├── ind_nifty500list.csv           # Offline database index file storing symbols
│
├── make_list.py                   # Offline database generator utility script
│
├── backtest.py                    # 5-Year historical portfolio vector test simulator
│
├── app.py                         # UI Dashboard (Streamlit layout + Plotly interactive charts)
│
└── bot.py                         # Live Broker execution router (Zerodha Kite order placer + GTT bracket engine)
```

---

## 🛠️ 6. Local Setup & Installation Process

To recreate or deploy this project environment on a local Windows machine, follow this sequential command sequence:

### Step 1: Open the Project Directory
Open PowerShell or Command Prompt and target your project root workspace:
```bash
cd "C:\Users\Dhwanik Hintya\Documents\nse-swing-bot"
```

### Step 2: Initialize & Activate the Python Virtual Environment
```bash
# Create the environment container
python -m venv env

# Activate the isolated environment wrapper
.\env\Scripts\activate
```

### Step 3: Install Required System Dependencies
Install the required quantitative analysis, broker connectivity, charting, and layout libraries:
```bash
pip install kiteconnect pandas numpy yfinance streamlit plotly python-dotenv
```

### Step 4: Configure the Secrets File (`.env`)
Create a file named `.env` in the root folder using Notepad or VS Code and input your Zerodha developer app credentials securely:
```env
ZERODHA_API_KEY="your_actual_api_key_here"
ZERODHA_API_SECRET="your_actual_api_secret_here"
```

### Step 5: Build the Offline Stock Database Spreadsheet
Execute the local generation utility script to parse your watchlist offline without web lookup blockades:
```bash
python make_list.py
```

### Step 6: Launch the Interface Dashboard
Run the Streamlit app. It will compile your layout and automatically launch a clean interactive local browser portal:
```bash
streamlit run app.py
```
*Note: If updating chart selections or changing dropdown entries clears your grid data, perform a hard page refresh using **`Ctrl + F5`** to align browser caches.*

---

## 🚀 7. Daily Production Routine & Live Execution Workflow

1. **The Morning Authentication (9:15 AM IST):** Launch `bot.py` via your active command shell. The script opens an interactive browser window to complete your manual Zerodha 2FA check, generating a seasonal `request_token` that you copy and paste back into the terminal.
2. **The Scanner Sweep:** The script automatically parses `ind_nifty500list.csv`, processes technical indicators, scans upcoming calendar fields, filters out assets matching the Event Shield block parameters, and prints clear entries.
3. **The Order Transmission:** Valid targets execute as standard long-term delivery orders (`PRODUCT_CNC`) at market opening price (`ORDER_TYPE_MARKET`) for the exact calculated share allotment.
4. **Server-Side Protection:** Instantly after completion, a secondary **Good Till Triggered (GTT) OCO (One-Cancels-the-Other)** bracket order payload is dropped directly onto Zerodha’s external servers. This locks your exits permanently at your initial stop-loss floor and your 1:2 profit target. **Once dropped, the trade is fully automated and you can shut down your machine.**
