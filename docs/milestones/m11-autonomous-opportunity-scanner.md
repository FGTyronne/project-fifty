# M11 — Autonomous Multi-Asset Opportunity Scanner

Status: research foundation only. No M11 broker order submission is authorised.

Tracking issue: #29

## Purpose

M11 is the strategy-development track intended to move Project Fifty beyond the frozen M10 SPY/cash control. M10 continues unchanged as the operational reliability experiment. M11 develops a broad, cost-aware, intraday opportunity scanner that may eventually trade fractional long-only US cash equities and ETFs autonomously.

The target behaviour is not "trade every three minutes". The target behaviour is "evaluate opportunities every approximately three minutes and trade only when a prevalidated net edge survives liquidity, cost, risk and constitutional gates".

## Constitutional boundary

M11 does not change Project Fifty's authority. The experiment remains funded by one lifetime GBP 50 owner contribution. Broker buying power is not capital authority. M11 may not use margin, leverage, shorts, options contracts, futures, CFDs, leveraged/inverse ETFs, transfers or borrowing. The deterministic risk firewall remains sovereign over strategy output.

## Separation from M10

M10 and its ledger, workflow, state and frozen M9 strategy must not be modified by M11 research. M11 remains on a separate branch and later must use a separate research/paper workflow and durable state path. Historical validation must pass before M11 is admitted to Alpaca paper execution.

## Initial research universe

Universe version: `2026-09-14-v1`.

The initial universe is the explicit `M11_RESEARCH_SYMBOLS` tuple in `src/project_fifty/strategies/m11.py`. It contains 70 highly liquid large-cap US equities and unleveraged ETFs. SPY is reserved as the benchmark and is not a candidate. Universe membership is deterministic and versioned so backtests remain reproducible.

Before any paper deployment, every candidate must additionally pass broker metadata checks for active US equity status, tradability and fractional eligibility. A later universe revision requires a new version and fresh validation.

## First-pass scanner

The first implementation is intentionally explainable. It uses completed five-minute bars and combines:

- 15-minute momentum;
- 60-minute momentum;
- relative strength versus SPY;
- 2-hour breakout evidence;
- realised short-horizon volatility;
- average five-minute dollar volume.

The weighted directional opportunity estimate is converted to basis points. A candidate is rejected unless it clears both modelled round-trip friction and an additional minimum economic-edge buffer. It is also rejected if average dollar volume is below the predeclared liquidity floor or if its volatility-normalised score is too weak.

Initial predeclared parameters:

- short momentum: 3 five-minute bars;
- medium momentum: 12 five-minute bars;
- breakout lookback: 24 five-minute bars;
- volatility lookback: 20 five-minute bars;
- volume lookback: 20 five-minute bars;
- minimum average five-minute dollar volume: USD 1,000,000;
- modelled round-trip friction: 20 bps;
- additional minimum edge buffer: 10 bps;
- minimum volatility-normalised score: 0.75;
- volatility floor: 5 bps per five-minute bar.

These values are frozen for the first research pass. They are not a claim that the strategy is profitable.

## Initial portfolio-selection policy

The first M11 research tranche selects at most one long candidate at a time or cash. This deliberately keeps the capital-allocation problem interpretable while the account authority is approximately USD 67.67. Multi-position allocation may be researched later only if it is economically sensible at this capital scale.

If no candidate passes every gate, the correct target is 100% cash.

## Required validation before paper orders

M11 may not submit paper orders merely because its software works. The research harness must demonstrate the predeclared historical gates on point-in-time data with realistic costs. At minimum the evidence must include:

- separate development/validation/final holdout periods;
- walk-forward folds;
- no tuning on the final holdout;
- modeled spread/slippage and turnover;
- return and maximum drawdown;
- trade count and time in cash;
- win/loss and profit-factor diagnostics where sample size permits;
- comparison with cash, passive SPY and the frozen M9 control;
- stability across folds rather than one lucky period.

A profitable-looking backtest that depends on excessive turnover, leakage or one market regime fails.

## First engineering acceptance criteria

The foundation is complete when:

1. the universe is explicit and versioned;
2. ranking is deterministic;
3. liquidity filtering is deterministic;
4. economic-cost gating can reject otherwise positive signals;
5. the scanner can intentionally select cash;
6. candidate evidence is auditable;
7. tests cover ranking, tie-breaking, liquidity rejection and cost rejection;
8. no code path wires M11 to the M10 Alpaca paper workflow.

The next tranche after this foundation is a dedicated point-in-time multi-asset backtest and walk-forward validator. Only after that evidence exists will an M11 paper workflow be considered.
