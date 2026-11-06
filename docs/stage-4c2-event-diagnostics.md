# Stage 4C-2 — Historical event diagnostics

## Purpose

Provide a research-only adapter that reconstructs event features independently
at each historical decision timestamp. It is designed for point-in-time
validation and diagnostics, not to modify the Phase 1 entry strategy.

## Interface

`build_event_diagnostics(symbol, decision_times, records, admission_results)`
returns a pandas DataFrame indexed by the exact supplied decision timestamps.
The output contains the Stage 4C-1 admitted-event counts, next effective-event
proximity, impact-assessment counts, materiality flag, taxonomy counts and
admitted event IDs.

## Temporal and admission controls

- Decision timestamps must be timezone-aware, non-null, strictly increasing
  and unique.
- Each output row independently calls the Stage 4C-1 as-of projection.
- Announcements after a decision timestamp are excluded from that row.
- Impact assessments recorded after a decision timestamp remain unassessed in
  that row and become visible only at later timestamps.
- An event without an eligible upstream evidence-admission result is excluded.
- Symbol matching is exact after trim and uppercase normalization.

## Deliberate separation

This module does not import or call `build_signal_frame`. It does not read,
modify or append columns to price candles, and it does not alter RSI, trend,
volume, entry, stop-loss, target or trailing-exit rules. Consumers must
explicitly join diagnostics in a research/reporting layer and preserve the
decision timestamp as the as-of key.

## Validation boundary

Tests cover sequential announcement visibility, delayed assessment visibility,
ineligible-event exclusion, symbol isolation and invalid time sequences.
Passing these tests establishes deterministic adapter behavior; it does not
establish that any historical Stage 3C event is admitted or that event features
improve trading performance. No backtest performance claim is made.
