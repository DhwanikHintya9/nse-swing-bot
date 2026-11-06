# Stage 4D-1 — Point-in-time outcome labels

## Objective

Create a deterministic, research-only label dataset for existing Phase 1 decision timestamps. Labels describe what adjusted prices did after a decision candle. They are not simulated fills, strategy P&L, or trade recommendations.

## Implementation

Module: `src/nse_swing_bot/research/outcomes.py`

Public API:
- `OutcomePriceMetadata`
- `build_forward_outcome_labels(...)`
- `export_forward_outcome_labels(...)`

The builder returns one row per `(symbol, decision_at, horizon_sessions)`. Default horizons are 5, 10, and 20 NSE trading sessions.

## Input contract

### Adjusted OHLCV

The candle DataFrame must:
- use a unique, strictly increasing DatetimeIndex;
- contain valid positive OHLC prices and non-negative volume;
- contain no non-finite or missing OHLCV values;
- use the declared symbol's daily candles; and
- contain only dates present in the supplied NSE trading calendar.

The builder deliberately does not adjust prices. The caller must first create the outcome-price series from immutable raw candle snapshots using verified corporate-action factors and provide matching provenance metadata.

### Required metadata

`OutcomePriceMetadata` binds the labels to:
- symbol;
- source candle snapshot ID;
- corporate-action snapshot ID;
- NSE calendar snapshot ID;
- price basis `split_and_dividend_adjusted_ohlc`;
- adjustment method `verified_split_and_dividend_factors`;
- outcome as-of date;
- calendar coverage start/end; and
- timezone-aware artifact capture timestamp.

Raw Kite OHLCV is not an accepted price basis. The metadata declaration is an explicit caller attestation; the label builder does not independently prove that a vendor or adjustment snapshot actually contains every split/dividend adjustment. That remains a data-provenance acceptance requirement.

The adjustment convention is an ex-post outcome-label convention. Adjusted prices are used only to describe subsequent outcomes; these labels and their future-known adjustment metadata must never be joined into decision-time features.

### Decision times and calendar

- Decision timestamps must be timezone-aware, unique and strictly increasing.
- Decision timestamps are mapped to local NSE dates in `Asia/Kolkata`.
- Each decision date must be an exchange session and have a corresponding decision-session candle.
- The supplied session calendar must be unique, strictly increasing, within its declared coverage and no later than the outcome as-of date.
- The calendar, not observed candle-row offsets or calendar-day arithmetic, determines each horizon.

## Label definitions

For a decision close (C_0), and the next (N) NSE sessions:

- `forward_close_return`: (C_N / C_0 - 1)
- `max_favorable_excursion`: (max(High_1, ldots, High_N) / C_0 - 1)
- `max_adverse_excursion`: (min(Low_1, ldots, Low_N) / C_0 - 1)

Values are fractions, so `0.05` means +5%. Excursions are descriptive OHLC path measures, not executable fill prices. They do not account for gaps, spread, liquidity, slippage, taxes or brokerage.

### Censoring

A horizon is marked `censored` with null metrics if:
- the supplied exchange calendar does not extend through the full horizon; or
- any expected forward session is missing a candle.

The builder never skips a missing session, forward-fills a price, or substitutes zero. A missing decision-session candle is a hard input error.

### Overlapping windows

`overlapping_label_count` counts other supplied decision observations for the same symbol and horizon whose planned forward-session windows overlap. This is a diagnostic only. It does not remove observations or correct statistical dependence. Stage 4D-3 must use these window boundaries to purge/embargo overlapping labels across validation boundaries.

## Output artifact

`export_forward_outcome_labels` writes an immutable CSV and JSON sidecar manifest. The manifest records the input snapshot IDs, price basis, adjustment method, calendar coverage, row count, ordered columns and CSV SHA-256. It explicitly declares:
- `production_eligible=false`;
- `broker_execution_eligible=false`;
- `strategy_signal_modified=false`; and
- `labels_are_simulated_trades=false`.

Files are created without overwrite. If manifest creation fails after CSV creation, the CSV remains for operator inspection; the pair is not transactional.

## Validation

Tests cover:
- exact horizon session selection and return/MFE/MAE calculations;
- missing intermediate candle censoring;
- insufficient calendar coverage censoring;
- session-offset behavior rather than observed-row offsets;
- overlapping label windows;
- rejection of raw price basis, naive timestamps, missing decision candles, out-of-calendar candles and invalid horizons;
- immutable export, SHA-256 agreement, research-only flags and provenance mismatch.

## Safety boundary and limitations

This stage does not create a Phase 1 signal, rank signals, fit a model, compare cohorts, simulate orders, or calculate portfolio returns. No event feature is used to change the baseline. A declared adjusted-price basis is not a substitute for independent corporate-action reconciliation. Delisting treatment, survivorship bias, historical-universe membership and execution costs remain explicit research limitations.
