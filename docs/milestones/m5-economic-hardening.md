# M5 — Strategy economic hardening

## Why M5 exists

M4 proved that Project Fifty can retrieve and replay real Alpaca IEX market data, but the first baseline was economically unusable: 2,132 trades across 2,499 decision points, $30.38 of modelled costs on a $67.6725 capital envelope, -41.45% total return and 20/20 negative walk-forward windows.

M5 addresses that failure before any autonomous paper order is allowed.

## Objective

Build a cost-aware, persistent, low-turnover deterministic strategy path that prefers inactivity unless a portfolio change is economically meaningful. Historical replay and the future autonomous paper session must share the same rebalance decision rules so backtest economics cannot be improved by controls that disappear in execution.

## Design principles

1. **Cash and no-trade are first-class actions.** A fresh signal does not imply a trade.
2. **Incumbency has value.** Existing positions should persist while still acceptable; a challenger must be materially better before causing a rotation.
3. **Risk reduction has priority.** SHOCK/cash exits and constitutionally necessary reductions cannot be blocked merely to save transaction costs.
4. **No confidence-to-sizing shortcut.** Strategy confidence remains diagnostic until calibrated.
5. **No broker buying-power authority.** The internal Project Fifty capital envelope remains sovereign.
6. **No in-sample optimisation theatre.** Use predeclared coarse variants and unseen walk-forward/holdout evaluation rather than a large parameter search.
7. **Backtest/live parity.** Economic rebalance controls must be shared code, not duplicated approximations.

## Required implementation

### 1. Shared economic rebalance policy

Introduce a broker-independent policy between desired target weights and executable proposals/instructions. It must be usable by both `ProposalBuilder`/session execution and `BacktestEngine`.

At minimum it must support:

- minimum trade notional;
- minimum trade fraction of current NAV (no-trade band);
- target-weight hysteresis / incumbent retention;
- challenger replacement margin;
- configurable rebalance cadence;
- deterministic ordering of risk reductions before new exposure;
- explicit reason codes for suppressed trades;
- risk-reducing override for full exits/SHOCK state;
- no short creation and no increase beyond target/constitutional capital.

### 2. Lower-turnover strategy behaviour

Version the deterministic baseline rather than silently changing v1.0.0.

Predeclared defaults for the first M5 candidate should be conservative rather than tuned to the M4 sample. Suggested starting values:

- candidate entry score: 0.25;
- incumbent retention/exit score: 0.05;
- challenger replacement margin: 0.10 score points;
- no-trade band: max($2.00, 7.5% of current NAV);
- maximum positions: 2;
- strategy decision cadence candidate: 30 minutes and 1 hour, not 5-minute rebalancing.

These are research defaults, not constitutional limits. M5 may reject them if broader validation shows they are poor, but changes must be documented before the final holdout run.

### 3. Backtest/live parity

The historical engine must execute only the instructions that the shared economic policy would have allowed at the decision timestamp. Execution remains next-bar-open with explicit cost/slippage modelling. No same-bar lookahead.

### 4. Benchmarks

Every M5 validation record must report at least:

- cash baseline;
- SPY buy-and-hold baseline using comparable inception/end timestamps and explicit entry friction;
- Project Fifty deterministic strategy;
- trade count, turnover/costs and time in cash.

### 5. Validation horizon

Use a materially longer history than M4 where Alpaca IEX permits it. Prefer approximately 180–365 calendar days at 30-minute or 1-hour cadence so runtime remains practical.

Keep a final holdout segment unseen by any parameter-selection logic. Large brute-force searches are prohibited.

## M5 paper-execution gate

Autonomous paper execution remains blocked unless a final M5 validation record demonstrates all of the following on the predeclared holdout/walk-forward evaluation:

1. no lookahead or state leakage;
2. zero constitutional violations;
3. materially lower turnover than M4;
4. modelled costs no greater than 5% of starting NAV over the validation horizon;
5. positive net total return for the Project Fifty strategy over the final validation horizon;
6. at least 50% of walk-forward test windows non-negative and median walk-forward return >= 0;
7. maximum drawdown no worse than 20%;
8. benchmark results reported honestly even if SPY/cash outperform;
9. no paper orders submitted during validation;
10. Ruff, strict Mypy and Pytest green.

Passing these gates does not prove alpha or justify live money. It only permits the next stage: a tiny autonomous Alpaca **paper** session behind the existing constitutional kernel.

## Explicit non-goals

M5 must not:

- enable real-money trading;
- submit Alpaca paper orders merely to improve a validation metric;
- introduce leverage, margin reliance, shorting, derivatives or transfers;
- weaken the deterministic risk engine;
- optimise against broker buying power;
- use an LLM as a direct execution authority;
- conceal or rewrite the failed M4 result.
