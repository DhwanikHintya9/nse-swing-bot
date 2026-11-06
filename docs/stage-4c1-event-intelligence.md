# Stage 4C-1 — Point-in-time event intelligence projection

## Objective

Introduce a normalized event-intelligence view without changing the Phase 1
entry strategy or allowing research-only events into production-facing features.

## Separation of concerns

The implementation keeps three dimensions independent:

1. **Evidence admission** — whether the existing Stage 4B preflight accepts the
   source package and its operator review.
2. **Event classification** — taxonomy, subclass, announcement time and
   effective time.
3. **Market-impact assessment** — optional direction and materiality recorded
   separately with an assessment timestamp and rationale.

A P1 document can be perfectly verified while its market impact remains
unknown. The module does not infer sentiment or materiality from event wording.

## Point-in-time rules

- An event is visible only when announced_at <= as_of.
- A record contributes only when its upstream EvidenceAdmissionResult is
  present and eligible=True.
- An impact assessment contributes only when assessed_at <= as_of.
- A future announcement or future assessment is excluded from historical
  features, preventing look-ahead leakage.
- Effective-date proximity is a separate calendar feature; it does not imply
  positive or negative impact.
- All timestamps must be timezone-aware. Calendar windows are evaluated in the
  caller's as-of timezone.

## Initial feature contract

The projection exposes admitted event counts over 7- and 30-calendar-day
windows, days to the next effective event, a high-materiality flag, direction
counts, an unassessed-impact count, taxonomy counts, and admitted event IDs.
Unknown impact remains explicitly unassessed; it is not converted to neutral.

## Explicit non-goals

- No event sentiment model or automatic materiality scoring.
- No changes to build_signal_frame, RSI, trend, volume, entry, stop-loss,
  target, or trailing-exit logic.
- No production admission of Stage 3C quarantined events.
- No broker integration, order routing, or live trading.
- No automatic adjustment of price history from narrative event records.

## Integration boundary

This is a read-only feature projection. A later integration stage may attach
its output to research reports or signal diagnostics after a separately
reviewed policy decision. Until then, the existing signal frame remains
unchanged and the feature projection is not consumed by the entry rule.
