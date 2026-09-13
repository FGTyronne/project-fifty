# M7 — Regime and Exposure Persistence

## Status

Predeclared after the frozen M6 validation. Autonomous paper execution remains blocked until this milestone passes every engineering and economic gate.

## Why M7 exists

M6 solved most of the ordinary entry/exit/replacement churn problem. On its disjoint holdout, costs fell to USD 1.56, trade rate fell to 23.82%, 3/5 walk-forward windows were non-negative, median walk-forward return became positive, and max drawdown remained only -3.15%.

Two gates still failed: the holdout return was -0.11%, and trade rate remained above the 21.33% ceiling.

The v3 strategy still maps every raw regime observation directly to a gross exposure budget: risk-on 70%, neutral 40%, risk-off 15%, shock 0%. Short-lived regime changes can therefore cause portfolio-wide partial reductions/additions even when selected holdings have not changed. M7 isolates this remaining source of churn.

## Controlled experiment

M7 changes only regime/exposure persistence.

The following M6 components are frozen unchanged:

- strategy signal families
- entry score: 0.25
- incumbent retention score: 0.05
- challenger replacement margin: 0.10
- entry confirmation: 2 consecutive completed bars
- routine exit confirmation: 3 consecutive completed bars
- replacement confirmation: 3 consecutive completed bars
- max positions: 2
- timeframe: 1Hour
- economic no-trade band: max(USD 3.00, 10% of current NAV)
- full exits force-permitted
- next-bar-open replay and 0.10% modeled slippage

This avoids attributing any M7 result to a bundle of simultaneous parameter changes.

## Frozen M7 v4 regime policy

Strategy id remains `regime-aware-technical-baseline`.

Strategy version: `4.0.0`.

Raw regimes retain the published detector from earlier strategy versions. M7 adds an effective-regime layer using only completed benchmark bars.

### Immediate adverse transitions

- raw `SHOCK` -> effective `SHOCK` immediately; target budget 0%
- raw `RISK_OFF` -> effective `RISK_OFF` immediately; target budget 15%

Risk reduction must not wait for persistence confirmation.

### Re-risking and positive exposure transitions

- effective `RISK_ON` requires the latest **3 consecutive raw regimes** to all be `RISK_ON`
- following any recent `RISK_OFF` or `SHOCK`, exposure may recover above risk-off only after **3 consecutive raw regimes** that are neither `RISK_OFF` nor `SHOCK`
- when that recovery condition passes but the 3-bar `RISK_ON` condition does not, effective regime is `NEUTRAL` (40% budget)
- an isolated or unconfirmed `RISK_ON` observation therefore remains `NEUTRAL`

The effective regime must be recomputable from point-in-time benchmark history. No process-memory counters or hidden state are permitted.

## Restart safety and no lookahead

For each of the most recent confirmation bars, calculate the raw regime using only benchmark bars available through that completed timestamp. No future bar may enter an earlier regime decision.

Replaying the same history after process restart must yield the same effective regime and target portfolio.

## Required diagnostics

Strategy evidence must expose at least:

- `raw_regime`
- `effective_regime`
- recent raw regime sequence used for confirmation
- `RISK_ON_UNCONFIRMED` when a positive transition is withheld
- `RECOVERY_UNCONFIRMED` when re-risking after an adverse state is withheld
- `SHOCK_EXIT` for immediate shock de-risking

## Validation dataset

M7 must not reuse M5 or M6 as an untouched holdout.

Use the fixed disjoint dataset:

- start: `2024-09-21T23:59:59Z`
- end: `2025-05-19T23:59:59Z`
- timeframe: 1Hour
- source: Alpaca IEX
- development / frozen holdout: 70% / 30%

Any bar at or after `2025-05-20T00:00:00Z` must make the M7 validation abort.

The final 30% holdout is exposed once. Do not broad-search parameters against it.

## Required reporting

Report at least:

- development and frozen-holdout starting/ending NAV
- total net return
- maximum drawdown
- modeled costs
- total turnover
- trades
- decision points and trade rate
- average cash weight
- walk-forward returns, non-negative fraction and median
- cash baseline
- SPY buy-and-hold with comparable entry friction
- zero-paper-order assertion

## M7 hard gate before autonomous paper trading

All must pass:

- Ruff, strict Mypy and Pytest green
- no lookahead or state leakage
- deterministic restart-safe effective regime
- zero constitutional violations
- zero paper orders during validation
- positive frozen-holdout net return
- maximum drawdown no worse than -20%
- modeled costs <=5% of starting NAV
- trade rate <=21.33% of decision points
- at least 50% of walk-forward windows non-negative
- median walk-forward return >=0
- normalized trade rate lower than M6's 23.82%
- cash and SPY comparisons reported honestly

Passing M7 permits preparation of a first tiny autonomous **paper** trading session. It does not permit real-money trading.

## Failure handling

If any M7 gate fails, freeze and publish the result exactly as observed. Do not relax the gate or change v4 parameters after seeing the holdout. Any further strategy research requires a new version and a new disjoint holdout.
