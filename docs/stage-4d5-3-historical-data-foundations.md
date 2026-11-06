# Stage 4D-5-3 — Historical data foundations

## Purpose and decision

Establish source-attributed exchange sessions and define the acceptance contracts for point-in-time universe identity and corporate-action reconciliation before any bulk OHLCV backfill.

**Status: calendar archive assembled and code-level validation added; historical membership and corporate-action factor evidence remain open.**

The study interval is **2021-11-06 through 2026-11-05**, inclusive. The repository archives full calendar-year holiday records for 2021–2026 so that the same source snapshot can be reused for boundary checks and later extensions.

## 1. NSE equity session calendar

### Inputs committed

- `data/market_calendar/nse-equity-holidays-2021-2026.csv`: NSE Capital Market segment holidays, including weekend-listed holidays for traceability. Each row retains its source URL.
- `data/market_calendar/nse-equity-special-sessions-2021-2026.csv`: explicitly authorized special live sessions, including Muhurat sessions and the 2026 Union Budget Sunday session. Each row retains its source URL.
- `src/nse_swing_bot/market_data/trading_calendar.py`: preserves per-row holiday source lineage and exposes `load_special_sessions_csv` with duplicate, blank-source and coverage checks.
- `tests/test_historical_calendar_foundations.py`: tests source lineage, regular closures, weekend behavior and explicit special-session inclusion.

### Official holiday circulars used

| Calendar year | NSE Capital Market circular |
|---|---|
| 2021 | [NSE/CMTR/46623](https://archives.nseindia.com/content/circulars/CMTR46623.pdf) |
| 2022 | [NSE/CMTR/50560](https://archives.nseindia.com/content/circulars/CMTR50560.pdf) |
| 2023 | [NSE/CMTR/54757](https://archives.nseindia.com/content/circulars/CMTR54757.pdf) |
| 2024 | [NSE/CMTR/59722](https://archives.nseindia.com/content/circulars/CMTR59722.pdf) |
| 2025 | [NSE/CMTR/65587](https://nsearchives.nseindia.com/content/circulars/CMTR65587.pdf) |
| 2026 | [NSE/CMTR/71775](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf) |

The 2026 ad-hoc Maharashtra municipal-election closure on 2026-01-15 is sourced separately from the [NSE exchange holiday page](https://www.nseindia.com/resources/exchange-communication-holidays). The 2026-02-01 Sunday live session is sourced from [NSE Circular NSE/CMTR/72349](https://nsearchives.nseindia.com/content/circulars/CMTR72349.pdf).

### Special sessions explicitly represented

- 2022-10-24 — Muhurat Trading
- 2023-11-12 — Muhurat Trading
- 2024-11-01 — Muhurat Trading
- 2025-10-21 — Muhurat Trading
- 2026-02-01 — Union Budget special live session
- 2026-11-08 — Muhurat Trading (outside the current five-year study end date)
- 2021-11-04 — Muhurat Trading (before the current five-year study start date)

The 2021–2025 Muhurat dates are identified by the asterisk and explicit note in each year's NSE holiday circular. The 2026-02-01 session is an explicit NSE live-session circular. Special sessions are not inferred from a weekday/weekend pattern: only rows in the special-session archive are added back to the calendar.

### Calendar semantics and limits

- Weekdays are candidate sessions, not proof of exchange operation.
- Official holiday rows remove sessions; weekend holiday rows remain in the archive but do not change the weekday baseline.
- A special-session row adds the date back even if it is a weekend or also appears in the holiday table.
- The calendar is an expected-session schedule. It does not prove a particular security traded, was not suspended, or has a candle.
- The holiday archive is built from annual circulars and the identified ad-hoc closure. Any additional emergency closure, unscheduled halt or one-off session discovered during acquisition must be added with its own official source and a regression test.
- The archive is not yet accepted as final until the new test suite runs in CI and a reviewer checks the CSV rows against the linked circulars.

## 2. Point-in-time Nifty 500 membership and security identity

### Source inventory

Official starting points:

- [Nifty 500 index page](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-500) exposes the current constituent download, methodology and factsheet. A current constituent file is not a historical membership source.
- [NSE Indices media / press-release archive](https://niftyindices.com/media) contains dated index inclusion, exclusion, replacement and corporate-action announcements.
- [NSE equity corporate filings and actions](https://www.nseindia.com/companies-listing/corporate-filings-actions) exposes symbol, series, purpose, face value, ex-date, record date and book-closure fields with a CSV download workflow.
- [Nifty equity index methodology](https://www.niftyindices.com/Methodology/Method_NIFTY_Equity_Indices.pdf) describes index construction and reconstitution. The currently published methodology must not be assumed to apply retroactively; archived methodology versions and effective dates are required.

### Required point-in-time dataset

The target artifact is an interval ledger, not a reconstructed list based on today's constituents:

`index_name, security_id, isin, symbol, series, membership_start, membership_end, effective_at, evidence_ref, evidence_sha256, confidence, notes`

Requirements:

1. Use ISIN as a key where supported, while retaining dated symbol and series aliases. Do not assume an ISIN or ticker remains unchanged through mergers, demergers, reissues or corporate actions.
2. Preserve dated constituent snapshots as primary anchors. Record each snapshot's publication/effective date, source URL, retrieval timestamp, raw bytes hash and row count.
3. Use official Nifty Indices press releases and NSE notices to resolve changes between snapshots and establish effective dates.
4. Record gaps explicitly. Do not interpolate a membership interval across an unobserved gap unless the intervening change history is independently evidenced.
5. Retain additions, removals, delistings, suspensions, mergers, demergers, scheme-of-arrangement events and symbol/ISIN changes as distinct events with source evidence.
6. Keep a separate unresolved identity queue. Never map a historical security to a current Kite instrument token based only on ticker text.
7. Preserve the methodology version and its effective interval for each reconstitution event.

Press releases are useful change evidence, but must not be treated as a complete substitute for dated constituent snapshots. Third-party reconstructions and Internet Archive captures may be used to discover candidate snapshot dates or missing source documents; they are not authoritative until the underlying archived NSE/Nifty Indices content, capture metadata and integrity are verified.

### Acceptance gate

No historical universe is accepted until:
- every interval has a traceable primary source or is explicitly marked unresolved;
- snapshot diffs reconcile to documented additions/removals, with unexplained differences isolated;
- symbol/ISIN changes have dated lineage evidence;
- constituent counts and duplicate security identities are checked per effective date;
- the historical coverage interval and all gaps are reported; and
- an independent review signs off on the reconstructed interval ledger.

## 3. Corporate-action factor evidence

### Source inventory and limitation

The NSE corporate filings page provides dated equity corporate-action fields and CSV export. The NSE investor-relations corporate-actions page also publishes selected historical attachment collections, but the visible annual dividend/bonus attachments are not, by themselves, a complete security-level factor ledger.

Kite's historical candles remain `provider_adjusted_unreconciled`. The provider's adjustment behavior is not a substitute for an independently verified factor ledger, particularly for ordinary cash dividends and events whose handling differs by provider. Do not apply a second adjustment to Kite prices without first determining exactly which events are already reflected.

### Required factor ledger

Target fields:

`security_id, isin, symbol_at_event, event_type, announcement_date, ex_date, record_date, effective_date, ratio_or_amount, currency, pre_event_face_value, post_event_face_value, price_factor, volume_factor, source_ref, source_sha256, provider_adjustment_status, reconciliation_status`

Event coverage must include at least:
- splits and face-value changes;
- bonus issues;
- rights issues;
- cash dividends, with ordinary and extraordinary dividends distinguished;
- mergers, demergers and scheme-of-arrangement distributions;
- delistings, suspensions and relistings; and
- ISIN or symbol changes that affect security continuity.

Each factor must be derived from the event terms and independently checked. Missing terms or ambiguous treatment must remain unresolved, not silently default to factor 1.0.

### Acceptance gate

Before labels or returns can use the historical OHLCV:
- each in-scope event has a primary exchange/issuer filing and a content hash;
- ex-date and effective-date semantics are explicit;
- price and volume adjustment factors are separately represented;
- dividend treatment is consistent with the declared research return convention;
- provider-adjusted candles are reconciled event-by-event or replaced with a documented raw-price source;
- delisting and terminal-price treatment is explicit; and
- independent reconciliation tests cover known split, bonus, rights, dividend and merger cases.

## 4. Next execution sequence

1. Run CI for the calendar archive/parser/tests and resolve any lint or test failures.
2. Review the six annual circulars against the committed holiday CSV; check ad-hoc closures and special-session circulars for the entire study interval.
3. Acquire dated Nifty 500 constituent snapshots and official change notices, then build the interval ledger with unresolved gaps preserved.
4. Acquire the security-level corporate-action event archive and derive a factor ledger with provider adjustment reconciliation.
5. Only after calendar, identity and adjustment gates pass, run intervening-year Kite availability probes for the five-symbol sample.
6. Authorize a bounded bulk backfill only after all preceding evidence gates pass.

## Safety

- No changes to Phase 1 signal rules or `configs/strategy-v1.yaml`.
- No order endpoint, broker execution, paper trading or live trading.
- No Parquet research dataset or outcome labels from `provider_adjusted_unreconciled` candles.
- Research evaluation remains blocked until all data acceptance gates are independently satisfied.
