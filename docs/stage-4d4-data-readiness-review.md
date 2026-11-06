# Stage 4D-4 — Independent research-data readiness review

**Review disposition: BLOCKED — insufficient historical and point-in-time data to run a defensible evaluation.**

**Scope:** repository branch `feature/stage-4b1-evidence-contracts` at review time, plus the latest Stage 3C research artifacts in the ChatGPT Library. This is a data-readiness audit, not a market-performance analysis.

## Executive decision

Stages 4D-1 through 4D-3 provide software contracts for labels, descriptive cohorts and chronological splits. They do not create the underlying historical dataset.

The available artifacts are useful for a software smoke test and a small corporate-event evidence-recovery exercise. They are not sufficient for a five-year NSE 500 research study, a point-in-time event/no-event comparison, or any claim about strategy performance.

Do not run cohort statistics on the current event archive as if it represented complete market coverage. Do not interpret an empty event list as no event. Do not generate outcome labels from the three-candle smoke test. No strategy, signal, trade-management or broker changes are authorized by this review.

## Evidence inventory and findings

### 1. Historical OHLCV prices — BLOCKED

Repository inventory:
- No historical OHLCV Parquet/CSV snapshot is committed under `data/`.
- Stage 2 documents a Kite adapter and append-only Parquet store, but the implementation-status record explicitly says the application has no complete market-data ingestion/adjustment dataset yet.

Available operational smoke-test artifact:
- One Parquet artifact, `snapshot=20261106T023142035757Z.parquet`, is present in the Library (5,247 bytes).
- The Stage 3 operational-acceptance record documents that it contains three validated RELIANCE daily candles for 2026-11-02 through 2026-11-04, persisted and read back with an exact match.
- The companion instrument-master CSV is not price history. It contains instrument reference rows, not a historical OHLCV panel.

Readiness gap:
- No multi-year daily OHLCV history across the research universe.
- No evidence of 250-session warm-up coverage per symbol for Phase 1 indicators.
- No systematic missing-session, suspension, stale-price, delisting or symbol-change reconciliation at universe scale.

**Decision:** the smoke test proves the read-only persistence path for one symbol and three sessions only. It is not a research dataset.

### 2. Corporate-action adjustment — BLOCKED

The code has a fail-closed adjustment function requiring explicit positive price/volume factors, a verified flag, and both primary and secondary source references. This is a useful contract.

However:
- No populated corporate-action factor ledger or immutable factor snapshot is present in the repository data tree.
- The outcome-label metadata requires a declared split-and-dividend-adjusted price basis and snapshot IDs, but this is a caller attestation; it does not independently prove that the supplied candles were correctly adjusted.
- No end-to-end reconciliation artifact demonstrates raw candles + verified factors -> adjusted OHLCV for the historical universe.

**Decision:** do not set `price_basis=split_and_dividend_adjusted_ohlc` merely to satisfy the label builder. Each adjustment snapshot must be independently reconciled first.

### 3. Historical universe membership — BLOCKED

The repository contains one archived Nifty 500 source capture:
- Membership effective date: 2026-09-30.
- 501 source rows: 496 EQ, 2 BE and 3 RR.
- The raw source is preserved faithfully, including the unresolved `DUMMYHEG` placeholder-like identity flagged by the Stage 3 acceptance record.

The documentation explains that this is one effective-date snapshot, not historical membership. No dated constituent interval history, historical additions/exclusions across the intended evaluation period, or delisted-constituent coverage is present.

**Decision:** using the September 2026 membership list to backfill several prior years would create survivorship and look-ahead bias. The `DUMMYHEG` identity must remain quarantined from tradable eligibility until resolved from authoritative sources.

### 4. Trading calendar — BLOCKED for multi-year study

The committed calendar artifact covers 2026 only. Stage 3 documentation records the 2026 holiday list and a separately handled Muhurat session, but there is no archived multi-year session calendar covering a five-year study window.

**Decision:** obtain and version the complete official NSE equity session calendar, including special sessions, for every date in the selected research period. Do not infer holidays from weekdays.

### 5. Corporate-event archive — PARTIAL / NOT ADMISSIBLE AS COMPLETE COVERAGE

The latest Library migration snapshot (captured 2026-11-06T07:10:16Z) binds these inputs by SHA-256:
- `high-002-research-triage-v28.csv`: 200 rows, 200 unique source record IDs; SHA-256 `8f76d05f020ab88ea688c1c945dd8fd25ed8209f03af0dd63341aeecd4431ed4`.
- `high-002-canonical-events-v16.csv`: 63 rows, 63 unique canonical event IDs; SHA-256 `328b95b9459396619cc4026a3d62801e2e74b576028bb65ef3bee582bde1753b`.
- `high-002-stage3c-open-queue-v15.csv`: 25 companies; SHA-256 `8fd34a491508b7b102f4a2342b005b8eed1e8044b3ed3e9245035f6658de3d25`.
- Four explicit source-ID aliases; 59 canonical events link to exact source IDs and 4 use the documented aliases.

Coverage observations from the 200-row triage:
- 151 distinct symbols.
- Broadcast timestamps are present for all 200 rows, spanning 2026-10-15 through 2026-11-05 (22 calendar dates).
- Only 74 rows have an `event_type`; only 34 have an `event_date`; only 7 have an `announcement_url`; 49 have a secondary-source URL.
- All 200 legacy `review_status` values remain `pending` by design.
- Seven rows carry a `primary_source_verified` verification status. This is not equivalent to formal Stage 4 evidence admission.

Canonical-event observations:
- 63 event records across 26 symbols, with event dates from 2026-10-15 through 2027-01-01.
- The canonical ledger stores event dates and source record IDs, but not a normalized timezone-aware announcement timestamp, event taxonomy, assessed direction, materiality, or an as-of coverage record.
- Source-ID linkage is useful lineage, but it does not by itself establish evidence admission or complete negative coverage.

Queue and admission state:
- 25 tracked companies: 13 resolved, 7 partial quarantine and 5 open quarantine.
- Every queue row remains `eligible_for_signal_pipeline=false`.
- The migration snapshot declares `evidence_admission=not_evaluated` and `production_eligible=false`.
- The repository's event and coverage templates contain headers only; there is no populated complete-coverage manifest.
- The separate seven-item evidence-capture queue is still awaiting original bytes / not captured / pending review.

Important distinction: "resolved" in the 25-company Stage 3C evidence queue is a research-triage disposition, not a declaration that every event is admitted. The current archive is a selected announcement review sample, not a complete 501-symbol event archive.

**Decision:** preserve these artifacts as a valuable pilot evidence set, but do not use them to label symbols/dates as having no event. The current Stage 4C feature pipeline requires explicit evidence-admission results and assessed impact records that are not yet present in this migration snapshot.

### 6. Evaluation and execution realism — NOT READY

The Stage 4D plan itself records that there is no validated portfolio backtester. The legacy root-level `backtest.py` is explicitly not an acceptable baseline because it uses different indicator calculations, a small ticker sample and simplified trade accounting.

Even after labels and cohort summaries become computable, they will remain descriptive forward-price outcomes—not strategy P&L. Any later performance claim needs a separately validated simulator covering the already-decided entry, stop, target, trailing, partial-fill, portfolio and cost rules.

## Readiness scorecard

| Requirement | Current evidence | Decision |
|---|---|---|
| Multi-year daily OHLCV across the universe | One RELIANCE, three-session smoke test | Blocked |
| Verified split/dividend adjustment factors | Code contract; no populated factor archive | Blocked |
| Historical point-in-time Nifty 500 membership | One 2026-09-30 snapshot | Blocked |
| Multi-year NSE session calendar | 2026 only | Blocked |
| Point-in-time event archive with complete coverage | 200 selected filings / 63 events / 25-company queue | Partial; not complete |
| Formal evidence admission and impact assessments | Migration says `not_evaluated` | Blocked |
| Validated portfolio execution simulator | Not implemented | Blocked for P&L claims |

## Required data-acquisition sequence

Do these in order; do not fit a model or calculate performance while earlier gates are open.

1. **Freeze the study window and security identity policy.** Recommended initial scope: five full years ending at the latest date for which all required inputs can be reconciled. Use exchange + trading symbol with ISIN and dated instrument-master lineage; preserve renamed, merged and delisted securities.
2. **Reconstruct historical universe membership.** Archive official dated Nifty 500 constituent snapshots and every effective-date addition/exclusion notice across the full period. Build membership intervals; do not backfill using the current list. Explicitly quarantine unresolved identities such as DUMMYHEG.
3. **Acquire raw daily OHLCV.** Use an authorized provider and immutable per-symbol/date snapshots. Validate all expected sessions, OHLC invariants, duplicates, gaps, zero-volume/suspension periods, stale prices, symbol changes and delistings. Retain source request metadata and checksums.
4. **Build and independently verify corporate-action factors.** Capture splits, bonuses, rights and cash dividends with ex-dates, explicit price/volume factors, primary and independent corroborating sources, and document hashes. Reconcile adjusted candles against independent reference values around every action.
5. **Extend the official NSE session calendar.** Cover the full study period, including special sessions, with source references and an immutable snapshot ID.
6. **Build point-in-time event coverage.** For each symbol/date, preserve raw broadcast timestamp, explicitly normalized IST announcement timestamp, event/effective date separately, original filing bytes/hash, fact-level page excerpts, taxonomy, evidence-admission result, and any impact assessment with its own assessed-at timestamp. Create complete coverage manifests only after the full symbol/date window is reconciled against the required sources.
7. **Run a data acceptance report before Stage 4D evaluation.** Publish per-symbol date coverage, missing-session rates, corporate-action reconciliation results, universe interval coverage, event coverage completeness, primary-evidence admission rates, and excluded/quarantined rows. Bind all inputs by hashes.

## Stage 4D-4 gate decision

**Do not proceed to Stage 4D-5 performance evaluation yet.** First acquire and reconcile the data above. Stage 4D-1/2/3 software remains research-only and can be smoke-tested with synthetic fixtures, but real-world cohort and holdout outputs would currently be incomplete and potentially biased.

This review changes documentation only. It does not modify Phase 1 signals, strategy configuration, trade management, broker code, or live-trading state.
