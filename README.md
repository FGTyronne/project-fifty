# Project Fifty

**Project Fifty** is a public engineering and research experiment testing whether a fully autonomous trading system can compound a single lifetime allocation of **£50** without recapitalisation.

## Current status

**DEVELOPMENT — Stage 1 / Milestone 1 kernel implemented (simulated only)**

No live brokerage account is connected. No live trading is enabled.

## Milestone 1 autonomous kernel

This repository now includes a broker-independent autonomous trading kernel with:

- typed domain models (`TradeProposal`, `PortfolioState`, `Position`, `OrderIntent`, `BrokerOrder`, `ExecutionReport`, `RiskDecision`, `LedgerEvent`, `ExperimentMode`);
- deterministic constitutional risk validation;
- replaceable broker adapter protocol and deterministic simulated broker;
- explicit execution flow with idempotency protection;
- append-only local ledger implementation;
- deterministic portfolio replay/reconciliation utilities;
- control modes (`NORMAL`, `DEFENSIVE`, `SAFE`, `DEAD`) and kill-switch enforcement;
- structured JSON logging helpers.

## Quickstart

```bash
python -m pip install -e .[dev]
ruff check .
mypy
pytest -q
```

## Deterministic demonstration

The required M1 autonomous demonstration is covered by:

- `tests/integration/test_kernel.py::test_demo_flow_hold_buy_reduce_exit`

Scenario:

- start cash `£50.00`;
- `HOLD` (no order);
- autonomous `BUY £7.50 TEST`;
- autonomous `REDUCE 40%`;
- autonomous `EXIT` remainder;
- reconciled final NAV and immutable ordered ledger history.

## Design limitations (intentional for M1)

- Simulated broker fills synchronously for deterministic tests.
- Instrument universe is a minimal configured placeholder (`TEST`) for constitutional guardrail verification.
- `CANCEL` action is modelled but not exercised with partial/live order-book simulation in M1.

## Security

Never commit real credentials. `.env.example` intentionally contains no secrets.

## Licence

No open-source licence has yet been selected. Until one is added, normal copyright applies.
