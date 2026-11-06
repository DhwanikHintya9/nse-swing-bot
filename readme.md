# NSE Swing Bot

A research-first NSE swing-trading system. The repository is being developed in
stages, with explicit separation between market-data handling, strategy
research, corporate-event evidence, and any future execution capability.

> **Current status:** The implemented foundation includes market-data utilities,
> Phase 1 signal calculations, trade-management components, Stage 3 universe /
> calendar support, Stage 4B evidence-admission tooling, and Stage 4C
> research-only event diagnostics and artifact export. This is **not a
> production-ready or live-trading system**. Broker order execution and
> production deployment are not enabled by the Stage 4B/4C work.

## What is implemented

### Phase 1 signal rules

`src/nse_swing_bot/strategy.py` calculates indicators and long-entry signals
from completed daily OHLCV candles:

- Trend: close above the 50-period simple moving average.
- Pullback: 14-period Wilder RSI below 45.
- Volume confirmation: current volume above its 20-period average.
- Minimum history: 250 completed candles.

The strategy module calculates signals; it does not place broker orders.
Trade-management behavior is implemented separately and should be evaluated
against its own tests and documented contracts.

### Stage 3 — Universe and event calendar

Stage 3 provides NSE universe/calendar support and a read-only adapter for
legacy Stage 3C snapshots. The adapter preserves source rows and does not
promote quarantined or unreviewed records.

### Stage 4B — Evidence admission

Stage 4B adds fail-closed evidence workflows, including source capture and
integrity checks, provenance, operator review, ZIP-member lineage, bounded
PDF inspection, exact excerpt verification, and artifact-aware admission
preflight.

Integrity checks and extracted text do not independently prove source
authenticity, completeness, or event truth. Admission remains subject to the
documented evidence policy and operator-review requirements.

### Stage 4C — Research-only event intelligence

Stage 4C adds:

1. Point-in-time event feature projection.
2. Historical diagnostics reconstructed at each decision timestamp.
3. Exact-index composition with Phase 1 signal output in a separate research
   frame.
4. Immutable CSV export with a SHA-256-bound JSON manifest.

The research frame is for analysis and reporting only. It does not alter
signals, strategy thresholds, trade management, or broker execution. Event
features must not be interpreted as evidence of predictive value without a
separate, properly designed out-of-sample evaluation.

## Strategy parameters and safety

The Phase 1 signal conditions above are the current signal implementation.
Other execution and risk parameters must be taken from their corresponding
source modules and tests; do not infer live operational behavior from this
README.

The following are explicitly **not established by the Stage 4B/4C work**:

- Production deployment or unattended live trading.
- A validated five-year portfolio backtest or any claimed return / profit
  factor.
- Guaranteed order placement, broker-side protective orders, or live account
  risk enforcement.
- Predictive benefit from corporate-event diagnostics.

Never commit broker credentials, access tokens, session tokens, or other
secrets. Keep local credentials outside version control and rotate any
credential that may have been exposed.

## Development setup

Requires Python 3.12 or later.

```bash
python -m venv .venv
```

On Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

On macOS/Linux:

```bash
source .venv/bin/activate
```

Install the project and development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run the validation suite:

```bash
pytest
ruff check .
```

## Stage documentation

Detailed contracts and limitations are documented alongside the implementation:

- `docs/stage-3-operational-acceptance.md`
- `docs/stage-4b3-provenance-ingestion.md`
- `docs/stage-4b4-primary-source-capture.md`
- `docs/stage-4b5-capture-integrity-verification.md`
- `docs/stage-4b7-operator-review.md`
- `docs/stage-4b9-zip-package-inventory.md`
- `docs/stage-4b10-zip-member-capture.md`
- `docs/stage-4b11-pdf-inspection.md`
- `docs/stage-4b12-pdf-artifact-integration.md`
- `docs/stage-4b13-evidence-admission-preflight.md`
- `docs/stage-4c1-event-intelligence.md`
- `docs/stage-4c2-event-diagnostics.md`
- `docs/stage-4c3-research-integration.md`
- `docs/stage-4c4-research-artifact-export.md`

## Development workflow

Work is developed on feature branches and validated by GitHub Actions. Keep
research, evidence admission, and execution boundaries explicit. Do not merge a
draft pull request or enable live execution merely because unit tests pass;
those require separate review, operational validation, and explicit approval.
