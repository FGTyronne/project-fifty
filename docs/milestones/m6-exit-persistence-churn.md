# M6 — Exit Persistence and Churn Suppression

## Status

Predeclared after the M5 frozen validation. Autonomous paper execution remains blocked until this milestone passes its economic and engineering gates.

## Why M6 exists

M5 changed the economic profile materially: its frozen holdout returned +7.13% with -4.31% max drawdown and beat the comparable SPY holdout. It still failed because routine position removal/replacement and rebalance activity remained too frequent: 225 trades over 430 decision points, modeled costs slightly above 5% of starting NAV, only 2/5 non-negative walk-forward windows and a negative median walk-forward return.

M6 must reduce ordinary strategy churn without weakening constitutional or immediate risk-reducing controls.

## Design principles

1. The 1Hour cadence selected on M5 development data is frozen for M6. Do not reopen cadence search.
2. M5's disclosed 2026-01-16 through 2026-09-13 dataset is no longer an untouched validation set and must not be used as the M6 final holdout.
3. Persistence logic must be deterministic, broker-independent and restart-safe.
4. Prefer persistence derived from point-in-time historical signals rather than process-memory counters that disappear on restart.
5. No strategy rule may override Constitution/RiskEngine decisions.
6. SHOCK / zero-risk-budget exits remain immediate.
7. Ordinary entry, exit and replacement decisions require confirmation.
8. Backtest and future autonomous execution must share the same economic trade/no-trade policy.

## Frozen M6 v3 candidate

The first M6 candidate is predeclared as follows. These are research parameters, not constitutional limits.

- strategy id: `regime-aware-technical-baseline`
- strategy version: `3.0.0`
- timeframe: `1Hour`
- entry score: `0.25`
- incumbent retention score: `0.05`
- challenger replacement margin: `0.10`
- entry confirmation: `2` consecutive decision bars
- routine exit confirmation: `3` consecutive decision bars below retention score
- replacement confirmation: `3` consecutive decision bars with challenger margin satisfied
- max positions: `2`
- economic no-trade band: `max(USD 3.00, 10% of current NAV)`
- immediate SHOCK/cash exit: enabled

Do not broad-grid-search these values against the final validation period. If a design defect forces a parameter change, document it before re-running a final holdout and use a new disjoint holdout.

## Required implementation

### Stateless/restart-safe confirmation

For each candidate symbol, calculate whether entry/exit/replacement conditions were satisfied on the required number of most recent completed decision bars using only information that would have existed at each bar. No future bars may enter a confirmation decision.

### Routine exits

An incumbent that falls below the retention score does not immediately exit. It remains held unless its score is below the retention threshold for three consecutive completed decision bars.

This rule does not apply when the strategy risk budget is zero. A SHOCK/zero-budget target must still move directly to cash.

### Entries

A new symbol must meet the entry threshold for two consecutive completed decision bars before entry.

### Replacements

A challenger may displace an otherwise retained incumbent only if its score exceeds the weakest incumbent by at least the replacement margin for three consecutive completed decision bars.

### Economic filter

Use the shared `EconomicRebalancePolicy` with:

- minimum_trade_notional = USD 3.00
- minimum_trade_fraction_of_nav = 0.10
- full exits force-permitted

The future autonomous proposal path and the backtest must use this identical policy.

### Diagnostics

Target evidence and/or rebalance diagnostics must make suppression reasons auditable, including at least:

- `ENTRY_UNCONFIRMED`
- `EXIT_UNCONFIRMED`
- `REPLACEMENT_UNCONFIRMED`
- `BELOW_ECONOMIC_THRESHOLD`
- `SHOCK_EXIT`

## Validation period

Use a fixed historical period ending before M5 begins. Target:

- M6 data end: no later than `2026-01-15T23:59:59Z`
- approximately 240 calendar days of preceding Alpaca IEX 1Hour history
- no overlap with the M5 dataset that began on 2026-01-16

Use a predeclared 70% development / 30% frozen holdout split inside the M6 dataset. The final 30% must be exposed once.

## Required reporting

Report at least:

- starting/ending NAV
- total net return
- max drawdown
- total modeled costs
- total turnover
- trades
- decision points and trade rate
- average cash weight
- walk-forward window returns and median
- cash baseline
- SPY buy-and-hold baseline with comparable entry friction
- zero-paper-order assertion

## M6 hard gate before autonomous paper trading

All must pass:

- Ruff, strict Mypy and Pytest green
- no lookahead or state leakage
- zero constitutional violations
- zero paper orders during validation
- positive frozen-holdout net return
- max drawdown no worse than -20%
- modeled costs <=5% of starting NAV
- trade rate <=21.33% of decision points (same minimum 75% reduction target relative to M4)
- at least 50% of walk-forward windows non-negative
- median walk-forward return >=0
- M6 trade count materially lower than M5 holdout trade count on a normalized decision-point basis
- cash and SPY comparisons reported honestly

Passing the hard gate permits the project to prepare a first tiny autonomous paper session; it does not permit live-money trading.

## Failure handling

If M6 fails, record the result. Do not weaken the gate after seeing the outcome. Diagnose the failure and create a separately versioned strategy/milestone with a new disjoint holdout if additional research is justified.
