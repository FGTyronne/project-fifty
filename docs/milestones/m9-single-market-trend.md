# M9 — Single-Market Trend / Cash Baseline

## Status

Predeclared before any M9 holdout is fetched or evaluated.

M8 materially reduced transaction friction but its cross-sectional stock-selection layer still failed the frozen out-of-sample economic gate. M9 removes stock selection entirely and asks a narrower question: can a very-low-turnover timing rule on one broad-market instrument produce a robust positive result for a Project Fifty-sized account?

Autonomous paper execution remains blocked during M9 research and validation.

## Objective

Isolate market-timing / exposure-control value from stock-picking noise.

M9 is a deterministic non-AI quantitative baseline. It is intentionally simpler than M8 and is not allowed to search across securities or parameter combinations.

## Frozen candidate design

Strategy identity: `single-market-trend-baseline` v6.0.0.

Instrument:

- SPY only for the US-paper prototype;
- no alternative candidate ranking or rotation;
- no sector, single-stock or crypto exposure.

Market data and cadence:

- Alpaca IEX split-adjusted daily bars (`1Day`) for research/backtesting;
- ordinary decisions only once every 21 completed SPY bars;
- the schedule is derived only from completed history length and is restart-safe;
- on non-decision bars, preserve the marked current portfolio exactly;
- on a scheduled decision, if the current risk state has not changed, preserve the marked current portfolio rather than mechanically rebalancing.

Risk-on state:

Both conditions must hold on the completed decision bar:

1. SPY close > 200-day simple moving average;
2. SPY 126-trading-day total return > 0.

When both hold and the portfolio is in cash, target 100% SPY.

When both hold and SPY is already held, preserve the current marked portfolio exactly.

Risk-off state:

If either condition fails on a scheduled decision, target 100% cash. A full risk-off exit remains forceable by the economic rebalance policy.

There is no short state, inverse exposure, leverage, margin usage or derivative overlay.

## Economic filter

Keep the M8 shared broker-independent filter unchanged to isolate the removal of stock selection:

- minimum trade notional: USD 5.00;
- minimum trade fraction: 15% of current NAV;
- full exits forceable.

Because M9 trades only on state transitions, this filter should normally be non-binding for entries and exits; it remains part of the future autonomous proposal path and replay path identically.

## Backtest mechanics

- starting research envelope: USD 67.6725;
- next-bar-open execution;
- 0.10% slippage each side;
- zero commission assumption unless broker economics require otherwise before paper deployment;
- fractional SPY permitted in replay;
- no lookahead;
- no state leakage between walk-forward windows;
- split-adjusted historical bars;
- no leverage, margin reliance, shorting, derivatives or transfers.

## New untouched validation period

M9 must use a period wholly earlier than M8:

- fixed history start: `2020-01-02T00:00:00Z`;
- fixed history end: `2023-08-31T23:59:59Z`;
- daily bars only;
- 70% development / 30% untouched holdout split from SPY bar count;
- reject any bar at or after `2023-09-01T00:00:00Z`.

This period deliberately includes multiple regimes, including the 2020 shock and the 2022 bear market in the overall research sample. The untouched 30% remains unavailable for parameter changes after disclosure.

Do not tune v6 against the frozen holdout once observed.

## Walk-forward validation

Use fresh strategy instances and point-in-time history only.

Predeclared walk-forward geometry:

- 252-bar training context;
- 63-bar test windows;
- 63-bar step.

Report holdout-aligned windows separately.

## Required reporting

At minimum:

- starting and ending NAV;
- net return;
- maximum drawdown;
- trade count;
- decision points and trade rate;
- turnover;
- modelled costs;
- average cash weight;
- time/risk state diagnostics where practical;
- walk-forward returns and median;
- cash baseline;
- SPY buy-and-hold return with comparable entry friction;
- SPY buy-and-hold maximum drawdown;
- zero paper-order count.

The SPY comparison is mandatory and must not be hidden if passive exposure performs better.

## Hard gate before any first autonomous paper session

Every gate must pass:

1. frozen holdout net return > 0;
2. maximum drawdown no worse than -20%;
3. modelled costs <= 1% of starting NAV;
4. trade rate <= 5% of decision points;
5. at least 50% of holdout-aligned walk-forward windows non-negative;
6. median holdout-aligned walk-forward return >= 0;
7. at least one autonomous risk-state transition occurs in the frozen holdout;
8. no lookahead or state leakage;
9. zero constitutional violations;
10. zero paper orders during validation;
11. Ruff, strict Mypy and Pytest green.

SPY buy-and-hold is a benchmark, not a pass/fail gate for M9. A positive M9 result that lags passive SPY must still be reported as such and does not by itself establish alpha or AI skill.

## Explicit prohibitions

- no parameter sweep or brute-force optimisation;
- no cross-sectional stock selection;
- no use of M5-M8 disclosed holdouts as an untouched M9 holdout;
- no change to the frozen 200-day SMA, 126-day momentum, 21-bar cadence, or economic filter after holdout disclosure;
- no real-money trading;
- no paper order submission during validation;
- no leverage, margin reliance, shorts, inverse products, derivatives or transfers;
- no broker buying-power authority;
- no LLM direct execution;
- no weakening of constitutional controls;
- no changing M9 gates after seeing the holdout.

## Interpretation rule

A pass would establish only that a simple, low-turnover deterministic baseline deserves a controlled autonomous paper phase. It would not establish live profitability, alpha, or an AI advantage.

A fail should be treated seriously. If even the single-market baseline cannot clear the predeclared robustness gate, Project Fifty should reconsider whether continued historical strategy search adds value rather than creating data-mining risk.