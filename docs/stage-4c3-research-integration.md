# Stage 4C-3 — Research-layer event integration

## Objective

Compose the existing Phase 1 signal frame with the Stage 4C-2 point-in-time
event diagnostics in a separate research/reporting output. This makes event
context inspectable without making it an input to the strategy.

## Contract

`build_research_event_frame(signal_frame, event_diagnostics)`:

- Requires the Phase 1 `signal` column and the complete Stage 4C-2 diagnostic
  column contract.
- Requires unique, timezone-aware DatetimeIndex values on both inputs.
- Requires exact index equality. It does not perform implicit reindexing,
  nearest-time matching, forward filling, or date-only joins.
- Rejects column-name collisions rather than overwriting strategy values.
- Selects only the documented diagnostic columns.
- Returns a new DataFrame and does not mutate either input.

## Safety boundary

The output is a reporting artifact only. It must not be passed to
`build_signal_frame`, trade management, order generation, or broker routing.
The Phase 1 signal column and all existing signal-frame columns are preserved
without recalculation. Event admission remains upstream and fail-closed;
unadmitted events remain excluded by Stage 4C-1/4C-2.

No changes are made to the entry, stop-loss, target, trailing-exit, or broker
execution logic. No backtest performance claim is made.

## Validation

Tests cover exact timestamp alignment, timezone requirements, missing columns,
column collisions, caller-input immutability, and equality of every Phase 1
signal-frame column before and after composition.
