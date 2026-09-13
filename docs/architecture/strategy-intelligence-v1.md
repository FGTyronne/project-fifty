# Strategy and intelligence architecture v1

## Objective

Provide a fast path from mature public trading-system patterns to a Project Fifty-specific strategy
layer without weakening the constitutional risk boundary.

The architecture borrows ideas from FinRL-X, TradingAgents, Qlib, TradeMaster, LEAN, NautilusTrader
and Freqtrade. Third-party strategy/AI components are never allowed to submit broker orders directly.

## Core contract: target portfolio

Project Fifty adopts the FinRL-X-style weight contract as the boundary between strategy reasoning and
execution planning.

A strategy returns a `TargetPortfolio` containing:

- timestamp / point-in-time market-state identity;
- quote currency;
- non-negative symbol target weights;
- explicit cash weight;
- strategy/model version;
- confidence and evidence metadata.

Target weights express desired exposure only. They do not grant execution authority.

The `ProposalBuilder` compares the target with Project Fifty's internally authorised portfolio and
creates one or more `TradeProposal` objects. Those proposals then follow the existing path:

`TradeProposal -> RiskEngine -> approved OrderIntent -> ExecutionKernel -> BrokerAdapter`

## Hybrid decision stack

### 1. Point-in-time data plane

Every feature must be derived only from data whose publication/market timestamp is <= the decision
cutoff. Data vendors are adapters; strategies do not call broker endpoints directly.

Required initial data:

- OHLCV bars for the permitted liquid universe;
- benchmark bars;
- Alpaca asset metadata / tradable / fractionable flags;
- market clock;
- later: corporate fundamentals, macro and news/sentiment feeds.

### 2. Quantitative feature plane

Compute a deliberately small set of orthogonal signal families rather than hundreds of correlated
indicators.

Initial families:

- trend structure;
- short and medium momentum;
- volatility and drawdown;
- overextension / mean-reversion state;
- volume/liquidity confirmation;
- breakout / range location.

Each family emits a normalized `SignalScore` in [-1, +1] plus evidence. A family can abstain when its
inputs are stale or insufficient.

### 3. Market-regime overlay

Inspired by FinRL-X Adaptive Rotation. Regime controls how much risk the strategy is willing to ask
for; it does not bypass Project Fifty's constitutional limits.

Initial states:

- `RISK_ON` — normal strategy budget;
- `NEUTRAL` — smaller gross target and higher cash floor;
- `RISK_OFF` — strongly reduced exposure;
- `SHOCK` — request cash/exit and block new strategy exposure.

Inputs should include benchmark trend, recent drawdown, realised volatility and, when available,
volatility-index information. A fast shock detector can override a slower structural regime.

### 4. Candidate ranking

A deterministic screener ranks the permitted universe before any expensive AI call. This reduces
LLM cost and prevents the language model from inventing the trade universe.

Ranking output includes:

- composite quantitative score;
- liquidity/spread filter outcome;
- regime-adjusted score;
- reason codes;
- data timestamp.

Only the top small candidate set proceeds to AI research.

### 5. AI research council

Inspired by TradingAgents, but deliberately smaller and cheaper.

Default roles:

- `TechnicalResearcher` — explains quantitative evidence and failure cases;
- `ContextResearcher` — news/fundamental/macro context when available;
- `BullResearcher` — strongest evidence for the trade;
- `BearResearcher` — strongest invalidation / downside case;
- `PortfolioResearcher` — synthesises a structured recommendation.

The research council receives candidates selected by deterministic code. It cannot choose arbitrary
symbols, broker APIs, leverage, margin or transfers.

Its output is structured evidence used by `StrategyComposer`; it is not a broker instruction.

### 6. Strategy composer

Combines deterministic baseline scores, optional statistical/ML models and AI research into one
`TargetPortfolio`.

Initial weighting policy:

- deterministic quantitative baseline is always present;
- AI may increase/decrease conviction only inside configured bounds;
- a negative bear/invalidation result can veto a candidate at the strategy layer;
- confidence is logged, but does not directly scale risk until calibration demonstrates that higher
  confidence predicts better outcomes;
- cash remains a first-class target.

### 7. Proposal builder

The proposal builder converts portfolio-weight differences into Project Fifty `TradeProposal`s using
only the internally authorised portfolio state and current point-in-time prices.

It must never use Alpaca `cash`, `equity` or `buying_power` to decide permitted size.

The builder prioritises reductions/exits before new exposure and may suppress economically trivial
orders where spread/slippage overwhelms expected edge.

### 8. Constitutional firewall and execution

Existing Project Fifty RiskEngine and ExecutionKernel remain sovereign.

The strategy/AI layer cannot:

- change the GBP 50 lifetime contribution or frozen paper envelope;
- enable margin, leverage, shorts, options, futures or CFDs;
- submit a broker order directly;
- alter credentials or endpoint permissions;
- revive DEAD;
- suppress reconciliation or audit events.

## Evaluation stack

Borrowing from Qlib, TradeMaster and Freqtrade, every candidate strategy/model is promoted through a
research pipeline rather than a single backtest.

Required gates:

1. point-in-time data contract;
2. automated look-ahead perturbation test;
3. indicator startup-window / recursive-stability test;
4. realistic transaction-cost model;
5. train/validation/test separation;
6. walk-forward evaluation;
7. benchmark comparison;
8. repeated-run / parameter-stability analysis;
9. paper execution/reconciliation;
10. promotion record containing exact strategy/model/config hashes.

## Recommended first autonomous strategy

Do not start Monday with a nine-agent LLM system and no baseline. Start with a deterministic
regime-aware momentum/mean-reversion ensemble, then run AI as a bounded research overlay.

Why:

- deterministic decisions are reproducible;
- the first paper campaign will test the broker/session runner as much as alpha;
- we need a non-AI benchmark to measure whether the AI adds value;
- a GBP 50 experiment cannot economically support excessive LLM calls on every market tick.

The initial system should reevaluate on a moderate cadence (for example completed 5-minute bars),
while risk/reconciliation logic runs continuously. Cadence can be changed after profiling.

## Future extensions

- Qlib-style supervised alpha models and cross-sectional ranking;
- FinRL/TradeMaster-style RL allocation/timing after robust offline validation;
- FinMem-style layered decision memory;
- alternative-data/news sentiment;
- model ensemble and online performance weighting;
- additional broker adapters and venues after separate constitutional approval.
