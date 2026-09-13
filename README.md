# Project Fifty

**Project Fifty** is a public engineering and research experiment testing whether a fully autonomous trading system can compound a single lifetime allocation of **£50** without recapitalisation.

## Current status

**DEVELOPMENT — Stage 2 / Alpaca paper integration implemented and mock-tested**

The broker-independent autonomous kernel is merged on `main`. The current development branch adds an Alpaca **paper-only** adapter. No live trading is enabled and no real credentials are stored in this repository.

Authenticated read-only paper connectivity and the first controlled paper order remain external acceptance gates before M2 is complete.

## Autonomous kernel

Project Fifty currently includes:

- typed domain models (`TradeProposal`, `PortfolioState`, `Position`, `OrderIntent`, `BrokerOrder`, `ExecutionReport`, `RiskDecision`, `LedgerEvent`, `ExperimentMode`);
- deterministic constitutional risk validation before broker submission;
- an internal capital envelope that is independent of broker cash or buying power;
- replaceable broker adapters;
- deterministic simulated execution;
- restart-safe idempotency and order recovery;
- asynchronous order-state handling and capital reservation;
- cumulative partial-fill reconciliation without double-counting;
- end-to-end cancellation handling;
- tamper-evident append-only ledger persistence;
- deterministic portfolio replay and reconciliation;
- control modes (`NORMAL`, `DEFENSIVE`, `SAFE`, `DEAD`) and kill-switch enforcement;
- terminal `DEAD` experiment state;
- structured logging and broker request-ID audit support.

## Alpaca paper adapter

The M2 adapter is deliberately restricted to:

```text
https://paper-api.alpaca.markets
```

It supports:

- paper account and market-clock retrieval;
- asset `tradable` and `fractionable` validation;
- fractional quantity orders;
- deterministic `client_order_id` generation;
- order recovery by broker order ID or client order ID;
- open-order and position retrieval;
- cancellation;
- ambiguous-timeout recovery without blind resubmission;
- Alpaca `X-Request-ID` persistence;
- quantity-aware broker/internal state checks that force `SAFE` on divergence.

The adapter contains no funding, transfer, margin, short-selling, derivatives or live-trading path.

Alpaca's simulated paper balance and buying power are reconciliation data only. They **cannot expand Project Fifty's constitutional capital authority**.

## Quickstart

```bash
python -m pip install -e .[dev]
ruff check .
mypy
pytest -q
```

## Read-only Alpaca paper connectivity

Paper credentials must be supplied at runtime only. Never commit them.

```text
ALPACA_PAPER_API_KEY=<runtime secret>
ALPACA_PAPER_API_SECRET=<runtime secret>
ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets
```

Once those variables are available to the local/runtime process:

```bash
python scripts/alpaca_paper_connectivity.py
```

The connectivity command only reads account and market-clock state. It cannot submit or cancel an order and does not print account identifiers or credentials.

See `docs/runbooks/alpaca-paper.md` for the controlled paper-testing sequence.

## M1 deterministic demonstration

The original M1 autonomous demonstration is covered by:

- `tests/integration/test_kernel.py::test_demo_flow_hold_buy_reduce_exit`

The M2 suite extends this with broker contract tests and asynchronous execution tests covering reserved capital, restart recovery, partial fills, cancellation and broker-state divergence.

## Security

Never commit real credentials. `.env.example` intentionally contains variable names and non-secret defaults only. Local `.env` files, `state/`, `secrets/`, keys and common credential files are ignored.

## Licence

No open-source licence has yet been selected. Until one is added, normal copyright applies.
