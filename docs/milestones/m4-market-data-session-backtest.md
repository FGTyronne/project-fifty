# M4 — Market Data, Backtest, and Autonomous Session Loop

## Objective

Connect Project Fifty's strategy contract to point-in-time market data and prove that the same
strategy can be evaluated historically and orchestrated continuously without creating a direct
strategy-to-broker path.

M4 does **not** authorise a paper order merely because the session runner exists. Paper execution
remains gated behind reconciliation, runtime configuration, historical evaluation, and a separate
paper-session acceptance step.

## Architecture

```text
Alpaca IEX market data (read only)
        |
        v
bounded candidate universe + SPY benchmark
        |
        v
completed bars + fresh quotes
        |
        v
StrategyContext + market_state_hash
        |
        v
RegimeAwareTechnicalStrategy
        |
        v
TargetPortfolio
        |
        v
ProposalBuilder
        |
        v
TradeProposal
        |
        v
RiskEngine -> ExecutionKernel -> BrokerAdapter
```

The strategy layer never receives Alpaca cash or buying power. The only portfolio authority it
receives is Project Fifty's internally reconstructed portfolio state, beginning from the frozen
USD 67.6725 paper inception.

## Bounded universe

Initial candidate seed:

- AAPL
- AMZN
- GOOGL
- META
- MSFT
- NVDA
- QQQ
- TLT
- GLD
- XLU

SPY is the benchmark and is not in the M4 trade-authorised list.

Candidates must be active, `us_equity`, tradable, and fractionable according to Alpaca metadata.
The bounded list is deliberate. M4 is validating the strategy/execution system, not searching
thousands of symbols for an accidental historical winner.

## Market-data contract

- endpoint: `https://data.alpaca.markets`
- stock historical bars: `/v2/stocks/bars`
- latest quotes: `/v2/stocks/quotes/latest`
- feed: `iex`
- currency: USD
- historical responses are paginated and deduplicated by timestamp
- all timestamps are timezone-aware and normalized to UTC
- strategies reject future bars and future reference prices
- live cycles reject missing/future/stale quotes
- current incomplete bar is excluded by cutting history at least one configured timeframe behind
  the cycle timestamp

## Backtest semantics

M4 uses a deliberately conservative next-bar model:

1. the strategy sees only bars at or before the decision timestamp;
2. it produces a target portfolio using the decision-bar close;
3. the target is executed at the **next benchmark bar open**;
4. sells/reductions are processed before new buys;
5. fractional positions are supported;
6. slippage and fees reduce NAV;
7. turnover, trade count, costs, NAV, and max drawdown are recorded.

This prevents a strategy from using a closing price and pretending it filled at that same close.

## Walk-forward evaluation

The evaluator repeatedly creates unseen test windows. A fresh strategy instance is created for
each window so strategy state cannot leak across tests. M4's deterministic baseline has no fitted
parameters, but this interface is intentionally compatible with later ML/RL models that do.

## Autonomous session semantics

The session runner:

- reads the Alpaca market clock;
- performs no strategy work while the market is closed;
- fetches only completed historical bars;
- requires fresh quotes;
- reconstructs Project Fifty's portfolio from the append-only ledger and current marks;
- generates a deterministic market-state hash;
- calls strategy -> target -> proposal builder;
- sends proposals only to the normal proposal handler / execution kernel;
- records the completed decision bar in the ledger;
- will not re-run the same decision bar after a process restart.

The runner owns no broker credentials and cannot submit an order directly.

## Runtime authority

The paper runtime must explicitly load:

```text
PROJECT_FIFTY_STARTING_CASH_GBP=50.00
PROJECT_FIFTY_ACCOUNT_CURRENCY=USD
PROJECT_FIFTY_AUTHORIZED_STARTING_CASH=67.6725
PROJECT_FIFTY_MAX_ORDER_NOTIONAL=67.6725
PROJECT_FIFTY_MAX_STALE_SECONDS=60
PROJECT_FIFTY_PERMITTED_SYMBOLS=AAPL,AMZN,GOOGL,META,MSFT,NVDA,QQQ,TLT,GLD,XLU
ALPACA_DATA_BASE_URL=https://data.alpaca.markets
ALPACA_DATA_FEED=iex
```

Alpaca's simulated account cash and buying power are never imported into these settings.

## Acceptance gates

M4 is complete only when:

1. Ruff, strict Mypy, and Pytest pass;
2. data pagination and parsing are tested with mocked Alpaca responses;
3. future/stale/missing market data fail safely;
4. candidate metadata filtering is tested;
5. next-bar execution is regression-tested;
6. transaction costs are reflected in backtest NAV;
7. walk-forward windows are isolated;
8. session restart cannot duplicate a completed decision bar;
9. a credentialed **read-only** Alpaca IEX smoke run succeeds;
10. a historical baseline evaluation is recorded before paper order enablement.

## Explicitly out of scope

- live-money trading
- leverage/margin/shorting/derivatives
- widening the universe based on backtest winners
- AI agents directly submitting trades
- using GitHub Actions as the permanent always-on production runtime
- claiming backtested profitability as evidence of future profit
