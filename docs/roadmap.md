# Delivery Roadmap

Project Fifty progresses only when the preceding stage has produced its evidence and passed its gate.

## Stage 0 — Project specification

Deliverables:

- Constitution v0.1;
- architecture;
- broker evaluation framework;
- repository/security policy;
- Milestone 1 specification;
- testing and paper-to-live principles.

Gate: the authority boundary and development sequence are explicit enough that implementation cannot silently redefine the experiment.

## Stage 1 — Repository and engineering foundation

Deliverables:

- Python project scaffold;
- typed domain model;
- deterministic risk engine;
- simulated broker;
- execution state machine;
- append-only ledger;
- portfolio reconciliation;
- control modes/kill switch;
- CI, linting, typing and automated tests.

Gate: Milestone 1 acceptance criteria pass.

## Stage 2 — Broker investigation

Deliverables:

- current primary-source research;
- quantitative £50 cost model;
- paper-API technical probes;
- scored comparison;
- broker selection ADR or documented decision to defer if none is viable.

Gate: selected broker demonstrably supports the experiment's UK, API, minimum-size, security and economic requirements.

## Stage 3 — Market data

Deliverables:

- instrument metadata;
- market prices;
- historical data;
- spreads/volume/volatility where available;
- timestamping and staleness policies;
- data provenance.

Gate: integrity, failure and stale-data tests pass.

## Stage 4 — Paper execution

Deliverables:

- selected broker paper adapter;
- submission, cancellation, replacement;
- order/fill state machine;
- timeout recovery;
- restart reconciliation;
- broker contract tests.

Gate: no unexplained paper positions/orders and no duplicate execution under tested failures.

## Stage 5 — Deterministic risk firewall

Stage 1 already builds the constitutional kernel. Stage 5 hardens it against the selected broker and real instrument universe.

Gate: invariant/property tests, broker integration tests and failure injection demonstrate that no execution path bypasses risk validation.

## Stage 6 — Baseline strategy

Deliverables:

- simple non-AI strategy;
- cash benchmark;
- passive benchmark;
- cost-aware evaluation.

Gate: strategy is executable and measurable, not necessarily profitable.

## Stage 7 — AI research and decision engine

Deliverables:

- model-independent decision provider interface;
- research ingestion with provenance;
- structured proposal generation;
- prompt-injection and malformed-output defences;
- model/version logging.

Gate: AI cannot bypass constitutional controls and its output is fully schema constrained.

## Stage 8 — Backtesting and walk-forward evaluation

Deliverables:

- leakage-controlled backtests;
- realistic spread/fee/slippage assumptions;
- walk-forward/out-of-sample tests;
- sensitivity analysis;
- benchmark comparison.

Gate: strategy claims survive reasonable execution assumptions and are not based on obvious leakage/overfitting.

## Stage 9 — Extended autonomous paper trading

Deliverables:

- complete autonomous system operating in live market conditions with paper capital;
- infrastructure reliability statistics;
- decision/execution/reconciliation audit trail;
- benchmark reporting.

Initial target: at least eight weeks and approximately 40 normal market sessions before live launch, subject to enough operational incidents/conditions to validate the system.

Gate: engineering, security, trading and operational criteria all pass.

## Stage 10 — £50 live launch

Deliverables:

- frozen/tagged Constitution v1.0;
- verified live broker permissions;
- verified starting contribution and inception NAV;
- verified kill switch;
- live experiment inception event;
- public launch record without sensitive credentials/infrastructure details.

No additional experimental capital may be introduced after inception.

## Stage 11 — Autonomous operation

The owner monitors infrastructure and experiment integrity, not ordinary trade decisions.

The system trades, exits, resizes and holds cash autonomously within the constitution.

## Stage 12 — Long-run evaluation

Evaluate nominal return, drawdown, costs, survival, passive benchmark, baseline strategy and the statistical strength of any apparent AI contribution.

Failure and underperformance are valid experimental outcomes and must be published honestly.
