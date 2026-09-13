# System Architecture

## Architectural objective

Project Fifty must be fully autonomous in ordinary trading while keeping strategy intelligence, deterministic controls, broker execution, state and credentials separated.

The system is designed around one principle:

> The autonomous system may decide and execute, but no component may bypass the constitutional firewall.

## Logical flow

```text
MARKET / RESEARCH SOURCES
          |
          v
+-----------------------------+
| Research & Market Data      |
| prices, filings, news,      |
| context, provenance         |
+-------------+---------------+
              |
              v
+-----------------------------+
| Intelligence Plane          |
| signals, strategies, AI,    |
| model adapters              |
+-------------+---------------+
              |
              | TradeProposal
              v
+=============================+
| Constitutional Firewall     |
| deterministic validation    |
| exposure / cost / state     |
| stale-data / permissions    |
+=============+===============+
              |
              | approved OrderIntent
              v
+-----------------------------+
| Execution Plane             |
| broker adapter, order FSM,  |
| idempotency, reconciliation |
+-------------+---------------+
              |
              v
           BROKER
              |
              v
+-----------------------------+
| Ledger + Portfolio State    |
+-------------+---------------+
              |
              v
+-----------------------------+
| Evaluation / Monitoring     |
+-----------------------------+
```

## Security domains

### 1. Research plane

Responsibilities:

- ingest market data;
- ingest permitted research/news/filings;
- normalise provenance and timestamps;
- expose information to the intelligence plane.

It must treat all external content as untrusted data. Text from a webpage, filing or social source can never directly alter configuration, credentials, permissions or execution state.

### 2. Intelligence plane

Responsibilities:

- candidate generation;
- signal generation;
- strategy selection;
- AI reasoning/orchestration;
- creation of machine-readable `TradeProposal` objects.

It may decide BUY, SELL, HOLD, ADD, REDUCE or CANCEL within the system's approved vocabulary. It cannot send arbitrary natural-language instructions to a broker.

It must not possess live broker credentials.

### 3. Constitutional firewall

Responsibilities:

- schema validation;
- permitted instrument checks;
- available-capital checks;
- exposure limits;
- cost/edge checks;
- stale-data checks;
- market/portfolio state-version checks;
- duplicate/idempotency protection;
- operating-mode enforcement;
- constitutional instrument restrictions;
- rejection logging.

Every executable order must pass through this layer. The runtime must not expose an alternate execution path.

### 4. Execution plane

Responsibilities:

- translate approved internal order intents to broker-specific payloads;
- submit/cancel/replace orders;
- track acknowledgements, rejections, partial fills and fills;
- recover from timeouts without duplicate execution;
- reconcile broker and internal state;
- expose execution reports back to the ledger/portfolio services.

Only this domain may hold live broker trading credentials.

### 5. State and audit plane

Responsibilities:

- append-only event ledger;
- portfolio state;
- NAV calculation;
- execution history;
- decision history;
- benchmark state;
- experiment lifecycle state.

The system should be reconstructable from durable events plus authoritative broker reconciliation.

### 6. Control plane

Responsibilities:

- owner kill switch;
- runtime health state;
- deployment state;
- constitutional version;
- emergency safe mode;
- infrastructure observability.

The AI may observe its operating mode but cannot grant itself additional permissions.

## Domain interfaces

Broker and model providers must be replaceable behind project-owned interfaces.

Suggested core types:

- `TradeProposal`
- `RiskDecision`
- `OrderIntent`
- `BrokerOrder`
- `ExecutionReport`
- `Position`
- `PortfolioState`
- `MarketSnapshot`
- `ResearchBundle`
- `LedgerEvent`
- `ExperimentState`

Suggested provider interfaces:

```python
class DecisionProvider(Protocol):
    async def generate_proposals(
        self,
        market_state: MarketState,
        portfolio: PortfolioState,
        research: ResearchBundle,
    ) -> list[TradeProposal]: ...

class BrokerAdapter(Protocol):
    async def get_account(self) -> AccountSnapshot: ...
    async def get_positions(self) -> list[Position]: ...
    async def get_open_orders(self) -> list[BrokerOrder]: ...
    async def submit(self, intent: OrderIntent) -> BrokerOrder: ...
    async def cancel(self, broker_order_id: str) -> BrokerOrder: ...
    async def get_fills(self) -> list[ExecutionReport]: ...
```

The core application must never depend directly on one broker's vocabulary.

## Decision schema

A trade proposal should contain at least:

- proposal ID;
- decision timestamp;
- strategy ID/version;
- instrument and asset class;
- action/direction;
- target allocation or target position;
- order type and relevant price constraints;
- reference price and data timestamp;
- expected holding period;
- thesis and bear case;
- estimated upside/downside;
- estimated transaction cost and slippage;
- expected return after costs;
- confidence/score;
- invalidation condition;
- exit conditions/reason;
- alternatives considered, including cash;
- evidence/provenance IDs;
- portfolio-state version/hash;
- market-state version/hash.

Model confidence is informational at first and must not control sizing until empirically calibrated.

## Event-driven state machine

The canonical lifecycle is:

`OBSERVE -> RESEARCH -> PROPOSE -> VALIDATE -> EXECUTE/REJECT -> RECONCILE -> RECORD -> EVALUATE`

An execution order requires explicit transitions. Typical states include:

`CREATED -> VALIDATED -> SUBMITTING -> ACKNOWLEDGED -> PARTIALLY_FILLED -> FILLED`

and failure/cancellation states such as:

`REJECTED`, `CANCEL_PENDING`, `CANCELLED`, `UNKNOWN`.

`UNKNOWN` broker state must not be solved by blindly retrying submission.

## Process separation

Initial deployment may be simple, but logical privilege separation should be retained:

```text
project-fifty-agent
  model/research credentials
  no live broker secret

project-fifty-core
  risk + execution + reconciliation
  broker credential
  no ability for LLM output to bypass validation

project-fifty-db
  durable state
```

Microservice complexity is not required initially. Clear module boundaries and process-level secret separation are sufficient for early stages.

## Proposed source layout

```text
src/project_fifty/
  domain/
  market_data/
  research/
  signals/
  strategies/
  portfolio/
  risk/
  execution/
  brokers/
  ledger/
  evaluation/
  benchmarks/
  agent/
  observability/
  control/
  config/
```

Tests should be separated into unit, property/invariant, integration, broker-contract, replay, chaos/failure-injection and regression suites.
