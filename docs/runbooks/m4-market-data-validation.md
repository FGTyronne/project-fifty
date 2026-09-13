# M4 Market Data and Historical Validation Runbook

## Purpose

This runbook validates Project Fifty's real Alpaca market-data path before an autonomous paper
session is permitted to submit an order.

The workflow is intentionally read-only. It uses the paper API credentials for authentication and
asset metadata, and the Alpaca market-data API for bars and quotes. Neither validation script calls
`POST /v2/orders`.

## Workflow

Run the GitHub Actions workflow:

```text
alpaca-market-data-smoke
```

It uses only the existing encrypted repository secrets:

```text
ALPACA_PAPER_API_KEY
ALPACA_PAPER_API_SECRET
```

The workflow hard-codes:

```text
ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets
ALPACA_DATA_BASE_URL=https://data.alpaca.markets
ALPACA_DATA_FEED=iex
```

## Step 1 — metadata and data smoke

`scripts/alpaca_market_data_smoke.py`:

1. validates SPY and the bounded seed universe against Alpaca asset metadata;
2. removes inactive, non-tradable, non-US-equity, or non-fractionable candidates;
3. downloads 14 days of 5-minute IEX bars;
4. retrieves latest quotes;
5. fails if any accepted symbol has no bars or no quote;
6. prints `orders_submitted=0`.

## Step 2 — historical baseline validation

`scripts/alpaca_baseline_validation.py`:

1. downloads 45 days of 5-minute IEX history;
2. starts with USD 67.6725;
3. runs `RegimeAwareTechnicalStrategy` using next-bar-open execution;
4. models 0.1% slippage and zero explicit commission;
5. records ending NAV, total return, max drawdown, costs, trade count, and decision count;
6. repeats the baseline over isolated walk-forward windows;
7. writes `state/m4-baseline-validation.json`;
8. uploads that record as the `m4-baseline-validation` workflow artifact;
9. submits no paper order.

A negative return does not make the infrastructure test fail. The result is evidence about the
strategy, not a reason to conceal or tune away an unfavourable outcome. Strategy changes after the
result require a new version and a new out-of-sample evaluation.

## Paper-session preconditions

Do not enable autonomous paper order submission until all of the following are true:

- M4 unit/type/lint CI is green;
- the credentialed market-data smoke workflow is green;
- the historical validation artifact exists and has been reviewed;
- runtime authority is USD 67.6725, not Alpaca's simulated account balance;
- permitted symbols are explicitly configured;
- the broker state reconciles with Project Fifty's internal ledger before the session starts;
- unexpected broker positions or open orders force SAFE;
- the kill switch remains operational;
- the first paper campaign is explicitly labelled as experimental and non-live.

## Failure response

- authentication error: stop; verify paper credentials only;
- market-data 403: stop; confirm the requested feed is IEX;
- rate limit: stop/retry later; do not switch to an unauthorised data source silently;
- missing/stale data: do not generate new exposure;
- broker-state divergence: enter SAFE and reconcile;
- unknown execution state: query broker state by deterministic client order id before any retry.
