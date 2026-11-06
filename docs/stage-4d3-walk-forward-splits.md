# Stage 4D-3 — Chronological walk-forward split contract

## Objective

Create reproducible chronological development/test assignments for the Stage 4D research observations. The split builder must prevent future outcome windows from leaking across a test boundary and must keep every symbol/horizon observation from the same decision date in the same partition.

## Input

The combined forward-label table from Stage 4D-1, containing:
- `symbol`;
- timezone-aware ISO `decision_at`;
- positive integer `horizon_sessions`;
- `label_start_session` and `label_end_session`;
- `label_status` (`complete` or `censored`).

A source-attributed NSE session calendar and explicit, ordered test windows are required. Test-window endpoints must be sessions. Windows are inclusive, chronological and non-overlapping.

## Split rules

- Expanding-window training: all eligible history before each test window is considered.
- Test rows are all observations whose local NSE decision date falls within the inclusive test window.
- Purging is decision-date grouped: if any complete label from a pre-test decision date ends on or after the test start, every symbol/horizon row for that decision date is assigned to `purged`.
- Embargo is applied after purging: the final configured number of NSE sessions before test start are assigned to `embargoed`, even if their label windows end before test start.
- Remaining pre-test decision dates are assigned to `train`.
- Rows with censored labels retain their date's partition but have `training_eligible=false`; they are never silently converted to zero or included in return statistics.
- Test observations are retained even when their labels are censored; those rows have `training_eligible=false` and must remain in test coverage reporting.
- All symbols and horizons sharing a decision date receive the same partition. This is stricter than purging each horizon independently and prevents same-date cross-sectional leakage.
- A fold is rejected if it has no test observations or fewer than the configured number of unique training decision sessions with at least one complete label.

## Output

A deterministic split-assignment table with one row per fold and input label key. It records partition, label eligibility, training eligibility, test-window boundaries and purge/embargo reason.

The immutable export includes:
- CSV with the split assignments;
- JSON manifest with the exact ordered test windows, embargo/minimum-training settings, session-calendar snapshot ID, source label artifact SHA-256, output CSV SHA-256, row count and schema; and
- explicit research-only safety flags.

## Validation

Tests cover:
- strictly chronological, non-overlapping test windows;
- all symbols/horizons at one decision date remaining in one partition;
- horizon-aware purge grouped across the date;
- session-count embargo;
- censored label retention without training eligibility;
- exact session/calendar and label-boundary validation;
- insufficient training/test coverage rejection;
- deterministic hash-bound immutable export.

## Safety boundary

This stage creates split assignments only. It does not fit a model, select thresholds, evaluate predictive performance, modify Phase 1 signals, simulate trades, or connect to a broker. No holdout results may be used to revise the same evaluation design and then be reported as untouched holdout evidence.
