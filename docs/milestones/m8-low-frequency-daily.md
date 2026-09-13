# M8 — Low-Frequency Daily Strategy Reset

## Status

Predeclared before any M8 holdout is fetched or evaluated.

M7 rejected the hypothesis that additional intraday regime persistence would solve Project Fifty's remaining economic weakness. M8 therefore changes the research architecture rather than tuning another confirmation count against disclosed data.

Autonomous paper execution remains blocked during M8 validation.

## Objective

Test whether a deliberately low-frequency, long-holding-period strategy can produce positive net returns with very low transaction friction on a Project Fifty-sized account.

M8 is intentionally simple. It is not an attempt to optimise the M4–M7 intraday strategy. It is a fresh deterministic baseline whose turnover is constrained by construction.

## Frozen candidate design

Strategy identity: `low-frequency-momentum-baseline` v5.0.0.

Market data and cadence:

- Alpaca IEX daily bars only (`1Day`).
- No intraday bars.
- A normal allocation decision may occur only once every 5 completed benchmark bars.
- The 5-bar schedule is derived solely from the completed benchmark history length, so it is deterministic and restart-safe.
- On non-decision bars the strategy must preserve the current portfolio weights exactly and therefore request no ordinary rebalance.

Universe:

- Use the existing bounded Project Fifty seed universe and SPY benchmark.
- Do not scan or optimise across thousands of securities.
- The validation report must explicitly note that the current fixed universe creates survivorship-selection limitations when replayed historically.

Risk-on gate at a scheduled decision:

- SPY close must be above its 100-day simple moving average.
- SPY 63-trading-day total return must be positive.
- If either condition fails, target 100% cash.

Candidate eligibility:

- candidate close above its 50-day simple moving average;
- candidate 63-trading-day total return > 0;
- rank eligible candidates by 63-day total return, descending, symbol as deterministic tie-break.

Portfolio construction:

- maximum 1 risk position;
- target initial risk allocation 70% NAV and cash 30%;
- if no candidate is eligible, hold cash;
- if an incumbent remains eligible, retain it unless the best challenger exceeds the incumbent's 63-day return by at least 0.05 (5 percentage points);
- if the incumbent is retained, preserve its current weight rather than mechanically resetting it to 70%;
- if entering or replacing, the new position target is 70%;
- if the benchmark risk gate fails or the incumbent becomes ineligible and no valid replacement exists, exit to cash.

This is a state-independent target rule: current holdings come only from `StrategyContext.portfolio`, and all signal history comes only from completed point-in-time bars.

## Economic filter

Use the shared broker-independent economic rebalance policy with:

- minimum trade notional: USD 5.00;
- minimum trade fraction: 15% of current NAV;
- full exits remain forceable.

This filter must be identical in backtest validation and any future autonomous session path using M8.

## Backtest mechanics

- starting paper-envelope cash: USD 67.6725;
- next-bar-open execution;
- 0.10% slippage each side;
- no lookahead;
- no commission assumption unless Alpaca economics require one before final paper deployment;
- fractional positions permitted in replay;
- no leverage, margin reliance, shorting, derivatives or transfers.

## Untouched validation period

M8 must use a new period that does not overlap M7, M6 or M5:

- fixed history start: `2023-09-01T00:00:00Z`;
- fixed history end: `2024-09-20T23:59:59Z`;
- daily bars only;
- 70% development / 30% untouched holdout split determined from SPY bar count;
- reject any returned bar at or after `2024-09-21T00:00:00Z`.

Do not tune v5 against the untouched 30% holdout after it is observed. If v5 fails, record the failure and move to a separately predeclared experiment or stop the strategy line.

## Walk-forward validation

Within the fixed M8 dataset, evaluate repeated point-in-time test windows using fresh strategy instances. No state may leak between windows.

Report at minimum:

- starting and ending NAV;
- net total return;
- max drawdown;
- trade count;
- decision points and trade rate;
- turnover;
- modelled costs;
- average cash weight;
- walk-forward returns and median;
- cash baseline;
- SPY buy-and-hold with comparable entry friction;
- zero paper-order count.

## Hard gate before any first autonomous paper session

Every gate must pass:

1. frozen holdout net return > 0;
2. max drawdown no worse than -20%;
3. modelled costs <= 2% of starting NAV;
4. trade rate <= 10% of decision points;
5. at least 50% of walk-forward windows non-negative;
6. median walk-forward return >= 0;
7. no lookahead or state leakage;
8. zero constitutional violations;
9. zero paper orders during validation;
10. Ruff, strict Mypy and Pytest green.

SPY comparison is mandatory and must be reported honestly. M8 is not permitted to redefine success after seeing whether SPY outperformed it.

## Explicit prohibitions

- no parameter sweep or brute-force optimisation;
- no reuse of M5, M6 or M7 disclosed holdouts as an untouched M8 holdout;
- no real-money trading;
- no paper order submission during validation;
- no leverage, margin reliance, shorts, derivatives or transfers;
- no broker buying-power authority;
- no LLM direct execution;
- no weakening of constitutional or deterministic risk controls;
- no changing M8 gates after holdout disclosure.

## Interpretation rule

M8 is a falsifiable test of a different economic architecture, not a promise of profitability. A pass would permit consideration of a tightly controlled autonomous paper phase; it would not prove live profitability. A failure must remain visible and must not be retroactively optimised away.