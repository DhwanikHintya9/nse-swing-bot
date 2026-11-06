# Stage 4C — Official membership events and security identity

## Purpose

Keep three different facts separate:

1. **Issuer identity** — which legal company exists.
2. **Security identity** — which listed instrument is being tracked.
3. **Index membership** — whether that security is a Nifty 500 constituent during a dated interval.

An ISIN or NSE symbol is an identifier, not a permanent internal primary key. Both can change. The immutable snapshot files and the existing ISIN-keyed observed diff remain historical source records; this design adds separate ledgers and derived views rather than rewriting them.

## Identity rules

- Assign an internal `issuer_id` to a legal issuer and an internal `security_id` to a listed security.
- A name or symbol match is never sufficient to merge identities.
- Every ISIN and NSE symbol is stored as a dated identifier in `security-identifiers.csv`, with a source and validity interval.
- Use half-open validity intervals: `valid_from` is inclusive and `valid_to` is exclusive. Blank `valid_to` means no verified end date.
- A new ISIN can map to the same `security_id` only when primary issuer/exchange evidence establishes continuity.
- Preserve predecessor/successor relationships for mergers, demergers and other transformations. Do not collapse distinct successor securities into the predecessor.
- Corporate-action identity evidence does not, by itself, establish Nifty 500 membership continuity.

## Corporate-action interpretation

| Event | Identity treatment |
|---|---|
| Stock split | Normally same issuer and continuing security; record the old/new ISIN mapping and split ratio when supported by official evidence. |
| Bonus issue | Normally same issuer and continuing security; record the ratio and any identifier changes. |
| Symbol or issuer-name change | Usually same issuer/security; update dated identifiers or names, not the internal IDs. |
| Demerger | New resulting business receives a distinct issuer/security identity. Link it to the predecessor with a `demerged_into` / `spun_off_as` relationship. |
| Merger / amalgamation | Record predecessor and successor identities and the effective date. Do not assume a one-to-one continuation. |
| Delisting / relisting | Preserve the historical security identity and record listing-status events separately; a relisting does not automatically prove uninterrupted tradability or index membership. |

Tata Steel's 2022 10:1 split is a stock split, not a demerger. The old ISIN `INE081A01012` and new ISIN `INE081A01020` may share one internal `security_id` only through the documented split/identifier bridge. The bridge must retain its official source and effective date.

## Ledgers

### 1. `security-identifiers.csv`

One row per identifier assignment and validity interval:

- `security_id`, `issuer_id`
- `identifier_type` (for example `ISIN` or `NSE_SYMBOL`)
- `identifier_value`, `series`
- `valid_from`, `valid_to`
- `source_url`, `source_sha256`, `identity_status`, `notes`

An identifier must not map to two securities over an overlapping validity interval unless an explicitly reviewed exception explains the source semantics.

### 2. `security-identity-events.csv`

One row per evidenced identity/corporate-action relationship:

- `identity_event_id`, `event_type`, `effective_date`
- `predecessor_security_id`, `successor_security_id`
- `relationship` (for example `continues_as`, `split_into`, `merged_into`, `spun_off_as`)
- old/new ISIN and symbol fields, `ratio`
- `source_url`, `source_sha256`, `notes`

For a simple split with one continuing listed security, predecessor and successor may be the same internal `security_id`; the old/new identifiers are still recorded. For a demerger, predecessor and successor security IDs are distinct.

### 3. `official-membership-events.csv`

One row per explicit Nifty 500 constituent addition, removal, correction or revocation:

- `event_id`, `index_name`, `issuer_id`, `security_id`
- `isin_at_event`, `symbol_at_event`, `series`, `action`
- `announcement_date`, `published_at_utc`, `effective_date`
- `event_status`, `supersedes_event_id`
- `notice_url`, `notice_section`, `source_sha256`, `notes`

Only a Nifty 500-specific notice section can support an official membership event. A correction/revocation is retained as its own event and linked to the superseded event; historical rows are not overwritten.

## Date semantics and backtest safety

Keep these dates distinct:

- **announcement/publication date:** when the index decision became publicly knowable;
- **effective date:** when the membership or corporate action takes effect;
- **capture/recorded date:** when our pipeline acquired the source.

For point-in-time research, a strategy may only use information available by its decision timestamp. Never backdate knowledge from a later-discovered notice. Retain source bytes or immutable source documents and SHA-256 hashes for audit.

## Reconciliation pipeline

1. Preserve raw snapshots and the existing ISIN-keyed observed diff unchanged.
2. Verify and curate security identifier intervals and identity events from primary evidence.
3. Build a separate canonical-security snapshot view by resolving each snapshot's ISIN/symbol to a `security_id` valid on that snapshot date.
4. Compare canonical `security_id` sets to avoid falsely reporting a simple ISIN migration as an issuer/security entry or exit.
5. Keep the raw ISIN diff visible alongside the canonical view; never erase the identifier-level observation.
6. Build dated Nifty 500 membership intervals from official membership events and verified snapshots. Do not infer membership continuity solely from a corporate-action bridge.
7. Record unresolved or conflicting identity mappings explicitly and exclude them from research-ready outputs.

## Important current limitation

The existing `classify_membership_changes.py` registry is keyed by `(isin, change)` and intentionally only annotates rows in the observed snapshot diff. It is not a general event ledger and cannot represent a constituent that entered and left between snapshots, or a corporate-action identity transition that has no net membership change. Do not force those events into that registry. The three ledgers above are the next independent evidence layer.

## Acceptance gates

- Every identifier mapping has dated primary evidence and no unexplained overlapping assignment.
- Every identity relationship has a documented event type, direction, effective date and source.
- Every membership event has an explicit Nifty 500 notice section, publication/effective dates and source hash.
- Revoked/corrected notices remain traceable.
- Snapshot-level and canonical-security-level reconciliation outputs are both retained.
- Corporate-action adjustment factors for OHLCV are separately verified before performance research.
- Independent review signs off on identity links, membership events and temporal coverage.

Research readiness remains **NO** until the complete historical interval and independent-review gates pass.
