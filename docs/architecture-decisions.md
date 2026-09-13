# Architecture decisions (Milestone 1)

1. **Broker independence first**
   - The kernel depends on a broker protocol (`quote` and `execute`) and is wired with a `SimulatedBroker` implementation only.
2. **Deterministic risk controls**
   - Risk approval is pure and deterministic from `TradeProposal`, `PortfolioState`, kill-switch state, and mark price.
3. **No unsupported trading features**
   - Margin, leverage, shorting, derivatives, and transfers are intentionally not modeled.
4. **Append-only reconciliation trail**
   - Proposals, intents, and execution reports are persisted as immutable ledger entries.
5. **Structured operational telemetry**
   - Kernel events are emitted as JSON logs to simplify downstream ingestion.
