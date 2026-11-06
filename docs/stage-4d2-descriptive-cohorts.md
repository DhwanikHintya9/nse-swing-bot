# Stage 4D-2 — Descriptive event-cohort evaluation

## Objective

Compare the forward outcome distributions of unchanged Phase 1 signal observations across predeclared, point-in-time event-context cohorts. This is descriptive research only; it does not establish causality or predictive value.

## Inputs

### Research frame

One symbol's Stage 4C-3 research frame, indexed by unique, strictly increasing, timezone-aware decision timestamps. Required columns:
- `signal` (non-null boolean);
- `event_count_30d`;
- `has_high_materiality_event_30d`;
- `unassessed_impact_count_30d`;
- `positive_event_count_30d`;
- `negative_event_count_30d`; and
- `mixed_event_count_30d`.

Only rows with the unchanged Phase 1 `signal=True` enter signal-outcome cohorts. The evaluator never changes or recomputes that column.

### Point-in-time coverage frame

A separate frame with the exact same index, containing:
- `coverage_complete_30d` (non-null boolean);
- `coverage_snapshot_id`;
- `covered_from` and `covered_through` (ISO dates);
- `captured_at` (timezone-aware timestamp).

A coverage row is complete only when its snapshot was captured no later than the decision timestamp and its declared range covers at least the 30 calendar days ending on the decision date. Incomplete or unavailable coverage is retained as its own cohort. A zero event count is never interpreted as no event unless the coverage contract is complete.

### Forward outcome labels

The Stage 4D-1 output, keyed by `(symbol, decision_at, horizon_sessions)`. Every Phase 1 signal observation must have exactly one row per supplied horizon. Censored labels remain in counts but are excluded from return statistics.

## Predeclared cohorts

For each horizon:
1. `all_phase1_signals` — the baseline cohort, including incomplete event coverage.
2. `event_coverage_complete` — signal observations with a complete point-in-time 30-day event-coverage window.
3. `event_coverage_incomplete_or_unavailable` — observations where the event-coverage contract is not complete.
4. `admitted_event_present_30d` — complete coverage and at least one admitted event in the 30-day feature window.
5. `no_admitted_event_in_complete_30d_window` — complete coverage and zero admitted events in the window.
6. `high_materiality_event_present_30d` — complete coverage and a high-materiality event feature.
7. `unassessed_impact_present_30d` — complete coverage and at least one unassessed impact.
8. `positive_impact_assessed_30d`, `negative_impact_assessed_30d`, and `mixed_impact_assessed_30d` — complete coverage and the corresponding assessed direction count above zero.

Event-context cohorts are not mutually exclusive. Do not compare their counts as if they partitioned the baseline.

## Statistics

For every cohort/horizon, report:
- total observations;
- complete and censored label counts;
- label completion rate;
- whether complete sample count meets the configured descriptive minimum;
- mean, median, 10th/25th/75th/90th percentiles of forward close return;
- positive-return proportion and a Wilson 95% interval;
- deterministic bootstrap 95% interval for the median;
- median maximum favorable excursion; and
- median maximum adverse excursion.

No p-values, significance claims, optimized thresholds, causal claims, or model fitting are included. Confidence intervals quantify sampling uncertainty only; they do not correct for overlapping labels, cross-sectional dependence, selection bias or multiple comparisons.

## Validation and fail-closed rules

- Require exact index equality across research and coverage frames.
- Require timezone-aware, unique, strictly increasing decision timestamps.
- Require non-null boolean Phase 1 signal and coverage flags.
- Validate coverage capture time and coverage date range for every row marked complete.
- Require complete label-key coverage for every Phase 1 signal observation and horizon; reject duplicates, symbol mismatches and unsupported label statuses.
- Keep censored labels in the denominator and report them explicitly.
- Require complete event coverage before assigning an observation to event-present or no-admitted-event cohorts.
- Do not treat missing/unassessed impact as neutral or negative.

## Output

A deterministic cohort summary DataFrame with one row per cohort/horizon. The evaluator is pure and does not mutate inputs. Artifact export and chronological holdout evaluation are reserved for Stage 4D-3.

## Safety boundary

This evaluator does not modify Phase 1 signals, select thresholds, rank trades, produce entries/exits, simulate fills or interact with a broker. Results are descriptive and research-only. Any apparent cohort difference is a hypothesis for later validation, not evidence that event context improves the strategy.
