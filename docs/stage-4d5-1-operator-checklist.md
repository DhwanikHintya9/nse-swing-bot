# Stage 4D-5-1 — Operator preflight checklist

Do not start a bulk historical download from this checklist. This is the five-symbol pilot gate only.

## Before running

- [ ] Confirm the active branch is `feature/stage-4b1-evidence-contracts` and PR #2 remains draft.
- [ ] Confirm local `.env` contains `KITE_API_KEY` and `KITE_ACCESS_TOKEN`; never paste either value into chat, logs, screenshots, or the repository.
- [ ] Use the archived universe source `data/universe/source/nse-nifty500-captured-2026-11-05.csv`, effective 2026-09-30. Its source CSV is not a current membership list and must not be relabelled with another effective date.
- [ ] Keep the default five-symbol pilot unless there is a documented reason to change it: RELIANCE, HDFCBANK, INFY, SUNPHARMA, LT. All must remain EQ series and resolve to one current NSE/EQ Kite instrument row.
- [ ] Supply an official NSE equity calendar CSV covering every date in the requested pilot window. The repository calendar currently covers 2026 only, so it cannot validate a full rolling 12-month window beginning in November 2025.
- [ ] Include official holiday dates and every special trading session in the calendar evidence. Supply special sessions with repeated `--special-session DATE=SOURCE` arguments when they are not represented in the CSV.
- [ ] Choose a completed-session end date. The requested interval must be wholly inside the calendar's declared coverage.
- [ ] Confirm the output directory is local and Git-ignored (`data/market_data` by default).

## Run

```bash
python scripts/kite_read_only_pilot.py \
  --calendar-csv /path/to/official-nse-equity-calendar.csv \
  --calendar-source "NSE official calendar; see archived source references" \
  --calendar-coverage-start 2025-11-06 \
  --calendar-coverage-end 2026-12-31 \
  --from-date 2025-11-06 \
  --to-date 2026-11-05
```

If the selected official calendar has a different coverage period, adjust all four date arguments consistently. Do not reuse this example as evidence that the dates have been verified.

## After running

- [ ] Confirm the command reports `Read-only mode: YES` and `Order endpoints called: 0`.
- [ ] Preserve the generated immutable manifest and all referenced Parquet/quarantine artifacts together.
- [ ] Verify the manifest SHA-256 using the project manifest verifier before sharing the evidence.
- [ ] Review every symbol's mapping, first/last candle, row count, missing sessions, unexpected dates, chunk completion, request/retry counters, snapshot hashes, and Parquet read-back status.
- [ ] Treat any nonzero exit code or `failed_or_incomplete` status as a failed pilot. Do not fill gaps or mark it accepted manually.
- [ ] Share only the non-secret manifest/report and sanitized errors. Never share `.env`, access tokens, API keys, request headers, or authenticated URLs.

## What a pass does not authorize

A successful five-symbol pilot validates only the acquisition mechanics and the requested date window for those five symbols. It does not prove five-year retention, historical constituent membership, full corporate-action adjustment, complete event coverage, or strategy profitability. Historical-depth probing and 500-symbol ingestion require a separate review and explicit gate. No performance evaluation or live trading is authorized by this pilot.
