# Nifty 500 universe source capture — 2026-09-30 effective membership

## Snapshot identity

- Index: Nifty 500
- Membership effective date: **2026-09-30** (changes effective from close of 2026-09-29)
- Source capture date: **2026-11-05**
- Source CSV: [NSE archived constituent file](https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv)
- NSE index page: https://www.nseindia.com/static/products-services/indices-nifty500-index
- Archived raw response body: `data/universe/source/nse-nifty500-captured-2026-11-05.csv`

## Why 2026-09-30 is the effective date

1. NSE Indices' [reconstitution calendar](https://www.niftyindices.com/resources/index-rebalancing-schedule) states that Nifty 500 is reconstituted semi-annually on the last working day of March and September.
2. NSE Indices' [10 August 2026 press release](https://niftyindices.com/Press_Release/ind_prs10082026.pdf) explicitly lists the Nifty 500 replacements and says the changes take effect on 2026-09-30 (close of 2026-09-29).
3. NSE Indices' [13 July 2026 criteria revision](https://niftyindices.com/Press_Release/ind_prs13072026.pdf) makes REITs eligible for Nifty equity indices from the next scheduled reconstitution. The September 30 review is therefore the first scheduled review to apply that eligibility change.

The CSV itself has no effective-date column. The date above is assigned from the official reconstitution schedule and the specific September 2026 Nifty 500 replacement notice, not from the HTTP Last-Modified header.

## Download response metadata checked on 2026-11-05

- HEAD response: HTTP 200
- Content-Type: `text/csv`
- Last-Modified: `Thu, 05 Nov 2026 03:30:52 GMT`
- ETag: `W/"32765-1793849452127"`
- Response Date header observed: `Thu, 05 Nov 2026 09:52:11 GMT`

These are source-capture metadata, not the index membership effective date.

## CSV integrity and reconciliation

The archived body contains 501 data rows and five columns: Company Name, Industry, Symbol, Series, and ISIN Code.

- 501 unique symbols
- 501 unique company names
- 501 unique ISINs
- No blank values in the five source columns
- Series distribution: 496 EQ, 2 BE, 3 RR
- All 27 Nifty 500 additions in the August 10, 2026 NSE Indices notice are present.
- All 27 Nifty 500 exclusions in that notice are absent.

The source file's 501 rows are retained exactly. The index is named Nifty 500, but this published file contains 501 security rows. No row has been silently deleted to force the count to 500. The downloader currently treats 501 as the observed source baseline and fails closed if the row count changes. Reconfirm the count against a fresh NSE file and notice before changing that baseline.

## Security-series policy

The source's series values are retained as published. NSE's [Legend of Series](https://www.nseindia.com/static/market-data/legend-of-series) defines:
- `EQ`: fully paid equity shares / ETFs in rolling settlement
- `BE` / `BZ`: fully paid equity shares / ETFs in trade-for-trade settlement; the exchange states that netting off is not allowed in this segment
- `RR`: units of REITs

In this capture, HFCL and STLTECH are `BE`; BAGMANE, BIRET, and EMBASSY are `RR`. The source data preserves these distinctions.

This archive records index membership, not strategy eligibility. The data layer now exposes `select_constituents_by_series(frame, allowed_series)`, which requires an explicit allowlist and never changes the archived source universe. A conservative initial swing-strategy baseline would be `EQ` only, with `BE` and `RR` excluded until their settlement/liquidity and event treatment are separately approved. That is a recommended strategy policy, not an automatic ingestion rule.

## Reproducibility

The archived CSV is the raw source body supplied from the successful NSE download. The application normalizer adds the effective date and source URL when producing an immutable normalized snapshot. Do not infer an effective date from Last-Modified or capture time.
