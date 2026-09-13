# Public trading framework review — 2026-09-13

## Purpose

Project Fifty should not reinvent mature trading-system patterns that already exist in public
frameworks. This review identifies reusable architecture and research ideas while separating
engineering maturity from unverified return claims.

No third-party source code is copied by this document. Architectural patterns are reimplemented
inside Project Fifty behind its own constitutional risk boundary. Any future direct code reuse must
retain the upstream licence and required notices.

## Bottom line

There is no credible public leaderboard proving a single "best performing AI trading bot" across
markets. Published returns are generally backtests, paper accounts, research experiments, or
self-reported results. They are useful evidence, not proof of future profitability.

The strongest route for Project Fifty is a hybrid:

1. **FinRL-X / FinRL-Trading** — target-portfolio-weight contract, modular strategy pipeline,
   point-in-time research discipline, Alpaca paper deployment examples.
2. **TauricResearch TradingAgents** — specialist LLM analysts, bull/bear debate, trader synthesis,
   portfolio-manager output, checkpointing and decision memory.
3. **NautilusTrader / QuantConnect LEAN** — event-driven research/live parity, explicit order state,
   risk-before-execution, reconciliation, broker adapters.
4. **Microsoft Qlib / TradeMaster** — model research, factor pipelines, walk-forward evaluation,
   benchmark comparison and systematic model testing.
5. **Freqtrade** — operational protections, look-ahead analysis, recursive-indicator analysis and
   hyperparameter-search workflow. Its GPL code is not copied into Project Fifty.

Project Fifty keeps its own deterministic constitutional firewall above every strategy or AI layer.
No external framework may use broker buying power as trading authority.

## Candidate review

### FinRL-X / FinRL-Trading

Repository: https://github.com/AI4Finance-Foundation/FinRL-Trading
Paper: https://arxiv.org/abs/2603.21330
Licence: Apache-2.0

Why it matters:

- AI-native, modular and explicitly deployment-consistent.
- The central interface is a target portfolio weight vector. Stock selection, allocation, timing and
  risk overlays can be swapped while downstream execution stays unchanged.
- Includes Alpaca paper/live integration, Pydantic configuration and pre-trade controls.
- Adaptive Rotation separates market regime, group strength, intra-group ranking, exceptions,
  portfolio construction and stop management.
- Point-in-time handling is explicit.

Reported evidence, not independently audited:

- README reports 2018-2025 Adaptive Rotation annualised return 22.32%, Sharpe 1.10 and max drawdown
  -21.46% versus QQQ Sharpe 0.81.
- README reports Oct 2025-Mar 2026 Alpaca paper ensemble return +19.76%, Sharpe 1.96 and max drawdown
  -12.22% while SPY and QQQ were negative over that stated interval.

What we adopt:

- A **TargetPortfolio** object as the sole strategy-to-execution portfolio contract.
- Separate selection -> scoring/allocation -> timing -> risk-overlay stages.
- A deterministic regime layer controlling *risk budget*, not inventing trade authority.
- Full decision audit output.
- Walk-forward-safe strategy evaluation.

What we do not adopt:

- FinRL-X's execution code uses broker portfolio value for sizing. Project Fifty must size from its
  internal constitutional capital envelope only.
- Its default minimum order sizes and whole-share assumptions do not fit a USD 67.6725 experiment.
- We will not import its broker layer because Project Fifty already has stricter idempotency,
  reconciliation and capital-isolation controls.

### TauricResearch TradingAgents

Repository: https://github.com/TauricResearch/TradingAgents
Paper: https://arxiv.org/abs/2412.20138
Licence: Apache-2.0

Why it matters:

- Analyst roles for fundamentals, sentiment, news and technical analysis.
- Bull and bear researchers challenge the analyst evidence.
- Trader synthesises an action; risk/portfolio roles review the proposal.
- Uses structured multi-agent orchestration, persistent decision logs and checkpoint resume.
- 2026 releases added point-in-time/look-ahead fixes, price grounding and structured outputs.

Caution:

- The paper reports superiority over baselines, but public issue #168 documented an attempted AAPL
  reproduction with materially negative results. Therefore TradingAgents is an **information and
  reasoning layer**, not a trusted alpha oracle.
- LLM non-determinism, token cost and latency make running the full agent society every few seconds
  inappropriate for a GBP 50 experiment.

What we adopt:

- Specialist evidence channels.
- Bull/bear adversarial review.
- A final structured portfolio recommendation.
- Decision memory and post-outcome reflection.
- Checkpoint/restart semantics.

Project Fifty modification:

- Run deterministic quantitative screening first.
- Invoke expensive AI analysis only for the small candidate set or when market regime changes.
- AI output is advisory to strategy composition and can only produce a Project Fifty domain object.
- The deterministic constitutional RiskEngine remains sovereign and cannot be bypassed by any agent.

### NautilusTrader

Repository: https://github.com/nautechsystems/nautilus_trader
Licence: LGPL-3.0

Why it matters:

- Production-grade deterministic event-driven architecture.
- Same strategy/execution semantics in simulation and live operation.
- Explicit Strategy -> RiskEngine -> ExecutionEngine -> ExecutionClient flow.
- Strong order state, duplicate-fill handling, reconciliation and reducing/halted trading states.

What we adopt conceptually, without copying LGPL source:

- Event-driven state transitions.
- Risk-before-submit invariant.
- Reconciliation as a first-class continuous process.
- Duplicate fill/order identity rules.
- NORMAL/DEFENSIVE/SAFE modes analogous to active/reducing/halted semantics.

Project Fifty already implements much of this and remains deliberately smaller.

### QuantConnect LEAN

Repository: https://github.com/QuantConnect/Lean
Licence: Apache-2.0

Why it matters:

- Mature modular engine for research, backtesting and live brokerage integration.
- Event-driven architecture and pluggable models.
- Large contributor base and broad market/broker abstractions.

What we adopt:

- Research/live interface parity.
- Modular alpha, portfolio, risk and execution boundaries.
- Benchmark-first evaluation.

What we do not adopt:

- Replacing the Python Project Fifty kernel with LEAN/C# would add more integration work than it
  removes for this experiment.

### Microsoft Qlib

Repository: https://github.com/microsoft/qlib
Licence: MIT

Why it matters:

- Mature AI-oriented quant research platform.
- Loose-coupled data, model, strategy, portfolio, risk and execution modules.
- Supports supervised ML, market-dynamics modelling and reinforcement learning.

What we adopt:

- Strict separation of feature/data research from execution.
- Reproducible experiment records and model comparison.
- Cross-sectional ranking/factor evaluation before allowing a model to influence capital.

### TradeMaster

Repository: https://github.com/TradeMaster-NTU/TradeMaster
Licence: MIT

Why it matters:

- Financial-RL model zoo and systematic evaluation instead of judging a model on one return number.
- PRUDEX-style evaluation emphasises profitability, risk, reliability and robustness.

What we adopt:

- Multi-metric model promotion gates.
- Repeated-run/rank-distribution thinking rather than single lucky backtests.

### Freqtrade

Repository: https://github.com/freqtrade/freqtrade
Licence: GPL-3.0

Why it matters:

- Very mature autonomous-bot operating loop.
- Optuna-based hyperparameter search.
- Explicit look-ahead-bias analysis and recursive-indicator analysis.
- Cooldown, max-drawdown and repeated-stop protections.

What we adopt conceptually only:

- Automated look-ahead checks.
- Startup-window/recursive-indicator stability tests.
- Strategy cooldown and drawdown guards.
- Hyperparameter optimisation restricted to training windows, followed by untouched validation.

Do not copy GPL source into Project Fifty unless the repository licence strategy is deliberately
changed and reviewed.

## Project Fifty hybrid architecture decision

The strategy/intelligence path becomes:

```text
point-in-time market data
        |
        v
quantitative feature + regime layer
        |
        v
candidate ranking / deterministic baseline
        |
        +--------------------------+
        |                          |
        v                          v
AI research council          classical/ML models
(technical/news/etc.)       (factor / ML / RL)
        |                          |
        +------------+-------------+
                     v
             StrategyComposer
                     |
                     v
              TargetPortfolio
                     |
                     v
          ProposalBuilder / diff
                     |
                     v
           TradeProposal objects
                     |
                     v
     PROJECT FIFTY RISK ENGINE
                     |
                     v
          ExecutionKernel -> Broker
```

The critical design rule is that **TargetPortfolio is strategy intent, not execution authority**.
Only the Project Fifty RiskEngine can approve an OrderIntent.

## First-strategy policy

For initial autonomous paper sessions, use a deterministic baseline with a small number of orthogonal
signal families rather than every indicator available:

- trend / moving-average structure;
- medium and short momentum;
- volatility / drawdown regime;
- RSI-style overextension;
- volume/liquidity confirmation;
- breakout/mean-reversion context.

Highly correlated indicators should not receive independent votes merely because they have different
names. A MACD signal and two moving-average crossovers are largely overlapping trend information.

The AI layer can add fundamental/news/sentiment context and challenge the quantitative thesis, but it
must not override stale-data, capital, instrument, exposure, or execution-state controls.

## Model/strategy promotion gates

A candidate strategy is not promoted because it has the highest in-sample return. It must pass:

- point-in-time/look-ahead checks;
- realistic spread, slippage and fee assumptions;
- walk-forward / untouched out-of-sample testing;
- minimum trade/sample count;
- benchmark comparison;
- max-drawdown and tail-loss constraints;
- parameter stability checks;
- replay/restart determinism;
- paper execution and reconciliation checks.

For AI models, also record model/version, prompt/configuration, tool/data sources and temperature or
reasoning settings so a historical decision can be reproduced as closely as possible.

## Reuse policy

- Apache-2.0 / MIT components may be directly reused when useful, with required copyright/licence
  notices and attribution.
- LGPL components may be linked/used under their terms, but Project Fifty currently prefers clean-room
  reimplementation of the architectural pattern rather than copying engine code.
- GPL source is reference-only unless Project Fifty deliberately accepts GPL obligations.
- Public performance claims are never treated as guaranteed returns.
