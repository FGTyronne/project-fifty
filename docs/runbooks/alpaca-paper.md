# Alpaca Paper Trading Runbook

## Purpose

This runbook covers Project Fifty's first external broker integration using Alpaca **paper trading only**.

It does not authorise live trading. The M2 adapter hard-fails if configured with the Alpaca live trading base URL.

## Security boundary

Never place real API credentials in:

- source code;
- `.env.example`;
- Git commits or Git history;
- GitHub issues or pull-request comments;
- screenshots;
- chat messages;
- test fixtures.

Use runtime environment variables or an approved secret manager. The repository ignores `.env`, `.env.*`, `state/`, `secrets/` and common credential/key files.

Required runtime variables:

```text
ALPACA_PAPER_API_KEY=<runtime secret>
ALPACA_PAPER_API_SECRET=<runtime secret>
ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets
```

Optional request-ID audit path:

```text
ALPACA_PAPER_REQUEST_LOG=state/alpaca-request-ids.jsonl
```

The adapter persists Alpaca `X-Request-ID` values when present. This local state path must not be committed.

## Project Fifty capital authority

Alpaca's paper balance and buying power do **not** define Project Fifty's authority.

The internal constitutional envelope is configured separately:

```text
PROJECT_FIFTY_ACCOUNT_CURRENCY=USD
PROJECT_FIFTY_AUTHORIZED_STARTING_CASH=<frozen GBP-50 equivalent in USD>
PROJECT_FIFTY_MAX_ORDER_NOTIONAL=<constitutional limit>
```

Before the autonomous paper experiment begins, create an inception record containing:

1. the constitutional owner allocation: `GBP 50.00`;
2. the GBP/USD conversion rate used for the paper experiment;
3. the conversion timestamp and rate source;
4. the resulting USD paper capital envelope;
5. the Project Fifty constitution version and Git commit SHA.

Once that paper inception amount is frozen, do not replace it with Alpaca's reported `$100,000` paper cash or `$400,000` buying power. Broker balances exist for reconciliation and anomaly detection only.

## Step 1: read-only authentication test

Install the development environment, provide the paper credentials through the runtime environment, then run:

```bash
python scripts/alpaca_paper_connectivity.py
```

This script can only call account and market-clock endpoints. It does not submit, replace or cancel orders.

Expected output contains only sanitised operational fields such as:

```json
{
  "environment": "paper",
  "account_status": "ACTIVE",
  "market_open": false,
  "paper_cash": "100000",
  "paper_buying_power": "400000"
}
```

The exact simulated balances may differ. Account identifiers and credentials must not be printed.

## Step 2: read-only broker verification

Before the first paper order, verify:

- account authentication succeeds;
- market clock succeeds;
- selected instrument exists;
- selected instrument reports `tradable=true`;
- a fractional order is only permitted when `fractionable=true`;
- broker state contains no unexpected positions or open orders;
- Project Fifty remains in `NORMAL` mode;
- the internal capital envelope is loaded and independent of broker buying power.

Any unexpected position, open order or quantity divergence must move Project Fifty to `SAFE` and block new exposure until reconciled.

## Step 3: first paper execution test

Only after Steps 1 and 2 pass should the first paper order be attempted.

The order must travel through the normal autonomous path:

```text
TradeProposal
    -> deterministic RiskEngine
    -> exact OrderIntent
    -> AlpacaPaperBroker
    -> broker acknowledgement/fill
    -> reconciliation
    -> append-only ledger
```

No manual broker order and no direct LLM-to-broker shortcut is permitted.

Use a fractionable, liquid instrument and the smallest economically meaningful test exposure allowed by the frozen Project Fifty paper capital envelope.

## Order safety rules

- The risk engine validates the exact order representation submitted to Alpaca.
- Project Fifty uses deterministic `client_order_id` values derived from logical idempotency identities.
- A restart must recover an existing broker order instead of creating a duplicate.
- An ambiguous submission timeout triggers broker lookup before any possible retry.
- Outstanding BUY orders reserve internal Project Fifty cash even while merely acknowledged or partially filled.
- Reservations survive restart.
- Partial fills are reconciled cumulatively so they cannot be double-counted.
- Cancellation releases reserved capital only after broker cancellation is confirmed.
- Currency mismatch, unknown logical order, identity drift or invalid state transition forces fail-safe behaviour.

## Step 4: autonomous exit test

After a successful paper entry and reconciliation, test an autonomous reduction or full exit through exactly the same risk and execution path.

Confirm:

- Project Fifty cannot sell more than the internally reconciled position;
- broker position and internal position converge;
- realised cash is reconstructed correctly;
- no second order is created during restart/recovery;
- final NAV can be reconstructed from the ledger.

## M2 completion gate

M2 is complete only when all of the following are true:

1. repository CI is green;
2. read-only authenticated paper connectivity succeeds;
3. the live endpoint guard is proven;
4. the frozen £50-equivalent paper capital envelope is recorded;
5. an autonomous paper BUY is risk-approved and submitted;
6. acknowledgement/fill is recovered and reconciled;
7. duplicate/restart protection is demonstrated;
8. autonomous reduction/exit is demonstrated;
9. no credentials have entered Git history;
10. no live trading capability is enabled.
