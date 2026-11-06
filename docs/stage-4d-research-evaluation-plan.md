# Stage 4D — Research evaluation framework plan

## Purpose

Determine whether point-in-time corporate-event context contains measurable, repeatable information about the outcomes of the existing Phase 1 signals.

This stage is an evaluation exercise, not a strategy upgrade. It must compare the unchanged Phase 1 baseline with event-context slices without allowing event features to alter signal generation, entries, sizing, exits, or broker behavior.

## Starting point

Stage 4C now provides:
- admitted, point-in-time event intelligence;
- historical diagnostics reconstructed at each decision timestamp;
- a separate research frame joining those diagnostics to the unchanged Phase 1 signal frame; and
- immutable CSV/manifest export with research-only safety flags.

There is not yet a validated portfolio backtester or an event-feature performance evaluation framework in the `src/` package. The legacy root-level `backtest.py` is not an acceptable evaluation baseline: it uses different indicator calculations, only a small ticker sample, simplified trade accounting, and does not implement the current strategy's full execution and portfolio rules. Its printed performance figures must not be used as evidence.

## Research questions

1. Among unchanged Phase 1 signal observations, do event-context groups exhibit different subsequent return distributions?
2. Are any observed differences stable across chronological out-of-sample periods and market regimes?
3. Do results survive realistic data-quality controls and conservative transaction-cost assumptions?
4. Is the event dataset sufficiently complete and point-in-time reliable to support any conclusion?

A result may be inconclusive. The framework must make that outcome explicit rather than searching for a favorable threshold.

## Evaluation design

### A. Freeze the baseline

- Treat the Phase 1 signal column and strategy configuration as immutable inputs.
- Use the same universe, signal timestamps, price observations, and evaluation windows for every comparison.
- Never regenerate or filter Phase 1 signals using event columns.
- Preserve a baseline-only cohort so that observations with missing event coverage are visible rather than silently dropped.

### B. Point-in-time observation dataset

Each observation is keyed by `(symbol, decision_at)` and must bind:
- the exact Phase 1 signal and strategy/config version;
- the source candle snapshot identity and price-adjustment convention;
- the event diagnostics available at that exact decision timestamp;
- event evidence/admission snapshot identity;
- the universe snapshot and effective date; and
- the later outcome-label definition and price-data snapshot identity.

Reject duplicate keys, non-monotonic per-symbol timestamps, timezone-naive timestamps, mismatched indexes, future event information, and untraceable input artifacts.

### C. Outcome labels — descriptive research only

The first implementation should produce forward-looking descriptive labels at fixed, predeclared horizons (initially 5, 10, and 20 trading sessions) for Phase 1 signal observations.

Labels should include forward close-to-close return and, where reliable OHLC data exists, maximum favorable and adverse excursion. They must:
- use only observations strictly after the decision candle for the forward window;
- never backfill unavailable future prices;
- mark incomplete horizon windows as censored/missing, not zero;
- respect the configured exchange trading calendar;
- identify overlapping forward windows; and
- record whether prices are split/dividend adjusted.

These labels are not simulated fills, trade P&L, or a substitute for the full entry/exit/portfolio simulator. Do not describe them as strategy returns.

### D. Comparisons

Start with transparent, predeclared descriptive cohorts:
- Phase 1 signal observations with admitted event context;
- Phase 1 signal observations with no admitted event in the defined lookback;
- event taxonomy/materiality/direction cohorts only where sample sizes permit; and
- an explicit unknown/unassessed/missing-coverage cohort.

Report sample counts and coverage alongside medians, quantiles, dispersion, and win/loss proportions for each fixed horizon. Include confidence intervals or uncertainty estimates where appropriate. Do not tune event thresholds on the final holdout.

### E. Chronological validation

- Split by decision date, never random row sampling.
- Use expanding or rolling walk-forward development windows followed by untouched chronological holdouts.
- Keep all observations from the same decision date in the same split.
- Purge or embargo observations whose forward-label windows overlap a validation/holdout boundary.
- Report each period separately; do not rely only on pooled results.
- Treat regime sensitivity and multiple comparisons as first-class risks.

### F. Data and bias controls

Before interpreting results, document:
- survivorship and historical-universe limitations;
- corporate-action adjustment and delisting treatment;
- missing candles, stale prices, suspensions and trading halts;
- event-source coverage gaps and delayed/late filings;
- timezone, exchange-session and holiday-calendar handling;
- overlapping labels and cross-sectional dependence; and
- transaction costs/slippage limitations.

If a required control is not available, surface it as a limitation and prevent a stronger claim.

## Staged implementation

### Stage 4D-1 — Dataset and outcome-label contract
Define and test deterministic construction of point-in-time observations and forward descriptive labels. No performance conclusions.

### Stage 4D-2 — Descriptive cohort evaluator
Add predeclared cohort summaries, coverage/sample-size reporting, and uncertainty estimates. No threshold search or model fitting.

### Stage 4D-3 — Walk-forward evaluation protocol
Add chronological splits, overlap purging/embargo, period-level reports, and immutable manifests binding all input snapshots and configuration versions.

### Stage 4D-4 — Independent review and decision gate
Review data sufficiency, leakage controls, robustness, costs, and limitations. Decide whether further research is justified. Do not automatically promote event features into Phase 1.

## Non-negotiable safety constraints

- No edits to Phase 1 signal rules or `configs/strategy-v1.yaml`.
- No event feature may be used to create, suppress, rank, size, or manage a trade.
- No broker, order, paper-trading, or live-trading integration in Stage 4D.
- All outputs must be explicitly research-only and not production- or broker-execution-eligible.
- A green CI run proves software tests, not predictive value.
- No return, win-rate, or profit-factor claim is permitted without a separately validated execution simulator and independently reviewed data.

## Stage 4D-1 status

Implemented in `src/nse_swing_bot/research/outcomes.py` with the contract documented in `docs/stage-4d1-outcome-labels.md`. The implementation requires explicit split-and-dividend-adjusted OHLC provenance, uses NSE session offsets for 5/10/20-session forward labels, censors incomplete windows, reports overlapping label windows, and exports immutable hash-bound research-only artifacts. It does not alter Phase 1 signals or simulate trades.

The next increment is Stage 4D-2: descriptive cohort evaluation with coverage/sample-size reporting and uncertainty estimates. Do not tune thresholds or fit a predictive model in that increment.
