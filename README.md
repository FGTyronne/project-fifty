# project-fifty

a system that can autonomously decide to buy/sell, pass its decision through hard controls, execute against a simulated broker, and reconcile the result correctly. Once that works, we replace the simulated broker with a real broker's paper API.

## Milestone 1 (implemented)

This repository now includes a broker-independent autonomous trading kernel with:

- domain models for `TradeProposal`, `PortfolioState`, `OrderIntent`, and `ExecutionReport`
- deterministic `RiskEngine`
- `SimulatedBroker` for non-live execution only
- append-only ledger for audit events
- kill-switch state support
- structured JSON logging
- unit and property-based invariant tests

Excluded by design for milestone 1:

- real broker connections
- live credentials
- margin, leverage, shorting, derivatives, and transfers
