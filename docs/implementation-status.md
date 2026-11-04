# Implementation status

## Foundation — Stage 0 and Stage 1

This branch establishes a safe development foundation and the first shared strategy-core implementation.

### Included
- A src/ package layout and Python project metadata.
- One implementation of SMA, Wilder RSI, true range, and Wilder ATR.
- Daily-candle signal construction for the Phase 1 rules:
  - Close above SMA(50)
  - Wilder RSI(14) below 45
  - Current volume above the 20-session average, including the current candle
- Explicit minimum history and input integrity checks.
- Unit tests for indicator seeds, Wilder recurrence, edge cases, and signal inputs.

### Intentionally not included
- No Zerodha authentication, order placement, GTT creation, or live-trading entry point.
- No market-data ingestion or corporate-action adjustment pipeline.
- No portfolio backtester, position sizing, or dashboard migration yet.
- Existing root-level scripts remain unchanged as the historical baseline.

### Safety boundary
The strategy core accepts completed candles supplied by its caller. It does not fetch market data, infer whether a candle is complete, or execute trades. Live execution remains disabled until the separate data, risk, portfolio, broker, reconciliation, and paper-trading acceptance gates are implemented and tested.
