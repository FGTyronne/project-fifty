# Milestone 1 — Autonomous Trading Kernel

## Objective

Build the smallest robust broker-independent system that can autonomously generate simulated trading decisions, validate them, execute permitted simulated orders, reconcile state and reconstruct portfolio history without any human trade approval.

This milestone deliberately excludes real broker connectivity and AI market intelligence. Its purpose is to prove that autonomy, execution discipline, state management and constitutional controls work before sophistication is introduced.

## Required capabilities

The system must support a simulated account with £50 starting capital and autonomous actions:

- BUY;
- SELL;
- HOLD;
- ADD;
- REDUCE;
- CANCEL.

Every action that could change broker state must pass through the deterministic risk engine.

## Required implementation

### Domain models

Implement typed, validated models for at least:

- `TradeProposal`;
- `PortfolioState`;
- `Position`;
- `OrderIntent`;
- `BrokerOrder`;
- `ExecutionReport`;
- `RiskDecision`;
- `LedgerEvent`;
- `ExperimentMode`.

Use decimal-safe monetary representation. Do not use binary floating-point for authoritative currency/accounting calculations.

### Risk engine

Implement deterministic validation including at least:

- schema validity;
- permitted action;
- permitted instrument placeholder/universe check;
- non-negative and finite quantities/notionals;
- sufficient cash/equity;
- no leverage;
- no short position creation;
- order notional within constitutional limits;
- valid/available reference price;
- stale price rejection;
- duplicate proposal/order protection;
- experiment mode restrictions;
- kill-switch enforcement;
- estimated-cost presence and sanity;
- explicit rejection reasons.

The decision provider must not be able to bypass this engine.

### Simulated broker

Implement an in-memory or deterministic local simulated broker conforming to the broker adapter contract.

It must support:

- account snapshot;
- positions;
- open orders;
- order submission;
- cancellation;
- fills;
- configurable transaction cost/slippage behaviour;
- deterministic test mode.

The broker adapter must be replaceable without changing portfolio/risk/domain logic.

### Execution engine

Implement an explicit order lifecycle/state machine. Support idempotency keys so the same approved order cannot accidentally create duplicate exposure.

The engine must treat ambiguous submission results as `UNKNOWN` rather than blindly resubmitting.

### Ledger

Implement an append-only event ledger interface and a simple durable/local implementation suitable for M1 tests.

Record at minimum:

- proposal created;
- risk approved/rejected;
- order intent created;
- broker submission attempt;
- acknowledgement/rejection;
- fill/partial fill where supported;
- cancellation;
- reconciliation result;
- portfolio/NAV snapshot;
- mode/kill-switch transition.

Historical events must not be mutated in place.

### Portfolio reconciliation

After execution, reconstruct/refresh portfolio state from the simulated broker and verify internal accounting.

The test suite must demonstrate that portfolio state can be reconstructed deterministically from the recorded event history or from a documented combination of event history plus authoritative broker snapshot.

### Control state

Implement `NORMAL`, `DEFENSIVE`, `SAFE`, and `DEAD` modes plus a kill switch.

For M1:

- `NORMAL` allows constitutionally valid simulated exposure changes;
- `SAFE` and kill-switch state prohibit new exposure;
- `DEAD` is terminal;
- transitions must be explicitly logged.

### Observability

Provide structured logs suitable for machine analysis. Logs must not contain secrets.

### Configuration

Provide non-secret typed configuration and `.env.example`. No real credentials are required or permitted in M1.

## Technology baseline

Preferred:

- Python 3.12+;
- `uv` and `pyproject.toml`;
- Pydantic v2;
- pytest;
- Hypothesis for property/invariant tests;
- Ruff;
- Pyright or mypy;
- standard-library logging or structured JSON logging with minimal dependencies.

Do not introduce Kafka, Kubernetes, distributed orchestration, a vector database or other infrastructure unnecessary for M1.

## Minimum repository structure

```text
src/project_fifty/
  domain/
  risk/
  execution/
  brokers/
    base.py
    simulated/
  portfolio/
  ledger/
  control/
  config/
  observability/

tests/
  unit/
  property/
  integration/
  replay/
```

## Required invariant tests

The automated suite must prove at least the following:

1. A £500 purchase cannot execute against a £50 account.
2. A rejected proposal never calls the broker submission method.
3. The same idempotency key cannot create two live orders/fills.
4. A SELL cannot create a short position.
5. Negative, NaN or infinite monetary/quantity input cannot reach execution.
6. New exposure cannot be opened while the kill switch is active.
7. New exposure cannot be opened in `SAFE` or `DEAD` mode.
8. `DEAD` cannot transition automatically back to an active mode.
9. Stale market/reference data is rejected according to configured policy.
10. A valid small purchase can execute and update cash/position state correctly.
11. A valid reduction/exit can execute autonomously.
12. Simulated fees/slippage reduce NAV correctly.
13. Duplicate/replayed events do not silently corrupt portfolio state.
14. An ambiguous execution result does not cause an automatic duplicate resubmission.
15. All rejections provide deterministic reason codes.

Property-based tests should attempt broad generated input ranges rather than relying only on hand-written examples.

## Demonstration scenario

A deterministic demonstration should be available from tests or an example command:

```text
Start cash: £50.00
Decision: HOLD -> no order
Decision: BUY £7.50 of TEST -> risk PASS -> simulated fill
Decision: REDUCE 40% -> risk PASS -> simulated sell
Decision: EXIT remainder -> risk PASS -> simulated sell
Final cash/NAV -> reconciled and logged
```

No human approval occurs between proposal, validation and simulated execution.

## Explicit non-goals

Do not:

- connect a real brokerage;
- add live credentials;
- add margin/leverage/shorting/derivatives;
- build an LLM trading strategy;
- optimise for profitability;
- add production cloud infrastructure;
- weaken the constitutional firewall for convenience.

## Acceptance gate

Milestone 1 is complete only when:

- the repository installs cleanly from documented commands;
- formatting/lint/type checks pass;
- unit, property and integration tests pass;
- the autonomous simulated trading loop runs end-to-end;
- invalid proposals cannot reach simulated execution;
- valid approved proposals execute without human approval;
- state and ledger reconciliation are deterministic;
- no secrets or live broker code are present;
- implementation decisions and known limitations are documented.

Only after this gate should Project Fifty proceed to formal broker evaluation and real paper-API integration.
