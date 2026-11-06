# Stage 4D-5-2 — Historical-depth availability probe

## Purpose

Measure whether Kite returns daily candles for the five-symbol pilot universe at the five-year boundary. This is a bounded provider-retention probe, not a historical data backfill and not a research-data acceptance step.

## Fixed probe

- Symbols: RELIANCE, HDFCBANK, INFY, SUNPHARMA, LT.
- Requested interval: 2021-11-06 through 2022-11-05 (inclusive).
- Interval: daily candles.
- Chunk size: 365 calendar days, sequential requests only.
- Identity input: archived Nifty 500 source captured 2026-11-05, effective 2026-09-30, plus the current NSE/EQ Kite instrument master.

The 2026-effective universe source is used only to select and map the same five current symbols. It does not establish that those securities had the same symbol/ISIN identity throughout 2021-2022. Historical identity continuity remains unverified.

## Output and interpretation

Run:

```bash
python scripts/kite_historical_depth_probe.py
```

The CLI reads local `.env` / environment credentials and never prints or writes credential values. It writes an immutable SHA-256-bound manifest beneath the Git-ignored `data/market_data/depth_probe` directory.

For each symbol, the manifest records:
- requested range and exact chunk boundaries;
- current Kite token and instrument-master row fingerprint;
- source ISIN and effective date inherited from the archived universe snapshot;
- returned row count, earliest/latest returned candle dates, duplicate count and deterministic returned-frame SHA-256;
- endpoint call/retry telemetry and outcome status.

No Parquet research snapshot is published. The adapter's isolated probe checkpoint cache is retained under the depth-probe output root so the request can be resumed without contaminating the recent-window pilot checkpoints.

A `completed` probe means only that all five bounded requests returned valid non-empty candle frames. It does **not** mean every expected NSE session is present. No historical NSE calendar is applied in this probe, so row counts are availability evidence, not coverage certification. No missing dates are filled.

## Decision rules

1. If all five symbols return data beginning on or before 2021-11-06 and extending through the requested end, record that Kite has demonstrated availability across this sampled five-year-boundary interval for the current token mappings. This still does not prove historical ISIN continuity or full session coverage.
2. If any symbol begins after the requested start, returns no data, or fails, do not widen to 500 symbols. Record the symbol-specific limitation and run a separately bounded earlier/later diagnostic only if needed.
3. If all five pass, next assemble official NSE session calendars for the full five-year study window, then probe the intervening years and historical instrument/universe identity evidence before any bulk backfill.
4. Do not use these provider-adjusted candles for Stage 4D outcome labels until corporate-action reconciliation is independently complete.

## Safety

- Read-only historical endpoint only; zero order endpoints.
- No Phase 1 strategy, signal, trade-management, broker-routing or live-trading changes.
- No event-feature evaluation, backtest, or performance claim is authorized.
- Adjustment basis remains `provider_adjusted_unreconciled`.
