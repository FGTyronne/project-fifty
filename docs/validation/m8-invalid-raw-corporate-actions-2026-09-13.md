# M8 Validation Run — INVALID due to raw corporate-action data

## Status

**INVALID — not an economic pass/fail result.**

Workflow run: `34764535767`

Frozen run head: `dcf2d5b57bd904f7091a6f271b95fcfd4ca329d2`

Paper orders submitted: **0**.

The M8 strategy parameters and gates were predeclared before this run and are not being changed in response to it.

## What happened

The first M8 historical replay used the existing `AlpacaMarketDataClient`, which hard-coded `adjustment=raw` for historical bars. That is unsuitable for a multi-month backtest that does not independently process corporate-action quantity changes.

The M8 period crosses NVIDIA's June 2024 ten-for-one forward stock split. NVIDIA is in Project Fifty's fixed candidate universe. A raw series contains the split price discontinuity while the current backtest engine leaves simulated position quantity unchanged. That can create a fictitious roughly 90% price loss in a held position even though a real shareholder would receive the corresponding split-adjusted quantity.

Alpaca's historical-bars API explicitly distinguishes raw bars from split-adjusted/corporate-action-adjusted bars. Therefore this replay violated the intended economic meaning of the backtest and cannot be used to judge v5.

## Invalid run output

For traceability only, the invalid run reported:

- requested history: 2023-09-01 through 2024-09-20
- holdout start: 2024-05-29
- starting NAV: USD 67.6725
- ending NAV: USD 25.9092246462
- apparent holdout return: **-61.7138%**
- apparent max drawdown: **-64.2987%**
- modelled costs: USD 0.1763999332
- trades: 10 / 79 decision points
- apparent trade rate: 12.6582%
- walk-forward windows: 3/3 non-negative
- walk-forward median: +1.3130%
- SPY buy-and-hold: +8.2303%

These figures are preserved only as evidence of the invalid replay. They must not be quoted as M8 strategy performance.

## Corrective action

The correction is restricted to historical data integrity:

1. add a research/backtest market-data path that requests split-adjusted historical bars;
2. add automated tests proving the adjustment request survives long-history windowing;
3. keep every M8 strategy parameter, economic threshold, dataset boundary and hard gate unchanged;
4. rerun the same frozen v5 design once after the data correction;
5. record that corrected run as the first valid M8 economic result.

The disclosed period is being reused only because the first run was technically invalid, not because its economic outcome was disappointing. No strategy or gate tuning is permitted between the invalid and corrected replay.

## Remaining modelling limitation

Split-adjusted bars fix the specific quantity/price discontinuity that invalidated this run. The current backtest still does not model every corporate-action cash flow or security reorganisation explicitly. M8's corrected validation must continue to disclose the fixed-universe survivorship/selection limitation and any remaining corporate-action limitations.