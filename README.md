# Project Fifty

**Project Fifty** is a public engineering and research experiment testing whether a fully autonomous trading system can compound a single lifetime allocation of **£50** without recapitalisation.

The system is intended to research markets, generate trading decisions, open and close positions, resize exposure, rotate assets, hold cash, and manage its portfolio without trade-by-trade human approval. Human involvement is limited to ownership, infrastructure administration, constitutional changes before live launch, and an emergency kill switch.

## Core experiment

- Starting owner contribution: **£50**
- Additional experimental capital after live inception: **prohibited**
- Human approval for ordinary trades: **none**
- Autonomous entries and exits: **permitted**
- Autonomous position resizing and strategy switching: **permitted within constitutional limits**
- Leverage, margin, short selling, CFDs, futures and options: **prohibited in the first live constitution**
- Access to any owner assets outside the designated Project Fifty account: **prohibited**
- Cash is a valid position
- Doing nothing is a valid autonomous decision
- Failure is not hidden or redefined after the fact

## Current status

**DEVELOPMENT — Stage 0 / Milestone 1 specification**

No live brokerage account is connected. No live trading is enabled.

## Engineering principle

The trading agent may adapt its strategy, but it may not expand its own authority. AI-generated trade decisions must pass through deterministic validation before reaching an execution adapter. The complete system remains autonomous because valid orders are executed automatically without owner approval.

The initial architecture is deliberately broker-agnostic and model-agnostic. Brokerage providers and AI models are adapters behind stable internal interfaces.

## Roadmap

0. Project specification and constitution
1. Repository and engineering foundation
2. UK broker investigation and quantitative evaluation
3. Market-data layer
4. Paper execution engine
5. Deterministic risk firewall
6. Non-AI baseline strategy
7. AI research and decision engine
8. Backtesting and walk-forward evaluation
9. Extended autonomous paper trading
10. £50 live inception
11. Autonomous operation
12. Long-run evaluation against passive and non-AI benchmarks

## Public repository policy

This repository is intended to contain source code, tests, architecture, methodology, constitutional documents and sanitised experiment reporting.

It must never contain broker credentials, model API keys, database credentials, private keys, live account identifiers, secret webhook URLs, recovery credentials or other sensitive operational material.

Live deployment secrets and sensitive operational controls must remain outside this public repository.

## Important

This is an experimental own-account software project, not an investment fund, financial promotion, investment recommendation or investment advisory service. Project Fifty is designed for the owner's designated experimental account only.

## Licence

No open-source licence has yet been selected. Until one is added, normal copyright applies.
