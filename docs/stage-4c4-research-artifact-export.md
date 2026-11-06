# Stage 4C-4 — Immutable research artifact export

## Objective

Persist the Stage 4C-3 research-only signal/event frame as a reproducible CSV
artifact with a hash-bound JSON manifest.

## Contract

`export_research_event_frame(frame, output_dir, captured_at)`:

- Requires the complete Stage 4C-2 event diagnostic columns.
- Requires a non-empty, unique, strictly increasing, timezone-aware
  DatetimeIndex and a timezone-aware capture timestamp.
- Serializes tuple/list/dict diagnostic values as compact JSON, avoiding
  Python-specific repr encodings.
- Computes SHA-256 over the exact CSV bytes and records it in the manifest.
- Records row count, columns, decision timezone, capture timestamp and
  explicit research-only safety flags.
- Creates new files atomically and refuses to overwrite an existing artifact.

## Safety boundary

The manifest declares `production_eligible=false`,
`broker_execution_eligible=false`, and `strategy_signal_modified=false`.
This is an audit/reporting export only. It does not create orders, alter
strategy rules, or claim that event context improves performance.

## Validation

Tests verify CSV/manifest hash agreement, row count, preserved signal values,
JSON serialization of tuple fields, invalid input rejection and no-overwrite
behavior.
