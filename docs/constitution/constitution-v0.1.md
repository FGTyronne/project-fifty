# Project Fifty Constitution v0.1

Status: **Development constitution**

This document defines the non-negotiable authority boundary and experiment rules for Project Fifty. It is not yet the live-inception constitution. Before live launch it will be reviewed, frozen as v1.0 and tagged in Git.

## 1. Purpose

Project Fifty exists to answer one empirical question:

> Can a fully autonomous trading system turn a single £50 lifetime allocation into materially greater capital through disciplined, evidence-based trading without recapitalisation?

The objective is long-term capital compounding subject to survival, auditability and the authority limits below. Trade frequency is not an objective. Cash is a valid position. Inaction is a valid autonomous decision.

## 2. Autonomy mandate

Once live, ordinary portfolio decisions require no human approval. Subject to the constitutional firewall, the autonomous system may:

- research markets and permitted information sources;
- select instruments from the permitted universe;
- buy and sell;
- open and close positions;
- increase or reduce positions;
- cancel or replace orders;
- rotate between permitted assets;
- hold cash;
- choose among approved strategies;
- alter non-constitutional strategy parameters;
- manage entries, exits and holding periods;
- respond to new information;
- resume after ordinary recoverable technical interruptions.

The owner is an observer and ultimate controller, not the normal portfolio manager.

## 3. Capital rule

The live experiment receives one owner contribution of exactly **£50 gross**.

After official live inception:

- no rescue capital may be added;
- the system may not borrow from the owner or any external party;
- the system may not transfer funds from other owner accounts;
- the system may not gain access to the owner's savings, bank accounts, ISA holdings, other brokerage accounts, emergency funds or unrelated investments;
- owner withdrawals are allowed but must be recorded distinctly from trading P&L.

The experiment tracks both gross owner contribution and actual brokerage inception cash after unavoidable funding or conversion friction.

## 4. Authority boundary

The AI may adapt strategy. It may not expand authority.

The following are constitutional controls and must be enforced outside the AI decision layer:

- designated-account isolation;
- prohibition on unauthorised transfers;
- prohibition on borrowing;
- prohibition on modifying API permissions;
- prohibition on bypassing broker restrictions;
- prohibition on modifying the constitutional layer at runtime;
- prohibition on exposures capable of creating liability beyond authorised capital;
- prohibition on unverified broker endpoints;
- prohibition on secrets in source code or Git history;
- requirement that every executable order passes deterministic validation;
- requirement that the agent cannot directly access wider owner assets.

## 5. Initial live instrument restrictions

Unless v1.0 explicitly changes them before live inception, the first live version prohibits:

- margin;
- leverage;
- short selling;
- CFDs;
- options;
- futures;
- leveraged or inverse exchange-traded products;
- any instrument capable of generating liability beyond available authorised account equity.

Spot cash equities and ETFs may be permitted where broker mechanics, fractional support and transaction economics make them viable. Other asset classes require explicit constitutional approval before live inception.

## 6. Execution architecture

The complete Project Fifty system has autonomous execution authority, but decision generation and broker credential custody are separated.

The decision layer creates structured trade proposals. A deterministic risk engine validates each proposal. Approved orders proceed automatically to the execution layer without owner approval. Rejected proposals are permanently recorded and do not reach the broker.

The AI decision component must not possess live broker credentials or a bypass around the risk gateway.

## 7. Deterministic operating modes

The runtime must support at least:

- `NORMAL`: ordinary autonomous operation;
- `DEFENSIVE`: reduced risk/turnover according to deterministic rules;
- `SAFE`: no new exposure, reconciliation and constitutionally permitted risk-reducing actions only;
- `DEAD`: terminal experiment state.

`DEAD` must never automatically transition back to an active state.

## 8. Experiment death

The live death threshold must be defined quantitatively before inception using the selected broker's minimum order size, unavoidable costs and permitted instrument universe.

If liquidation NAV falls below the frozen minimum viable economic capital and no existing permissible position can restore tradeable capital, the experiment enters `DEAD` permanently.

No new £50 allocation may be introduced after death under the same experiment.

## 9. Cost discipline

Every trade must be assessed after estimated transaction costs, spread, slippage, FX friction and other applicable charges.

Operating expenses such as model inference, hosting and market data are funded outside the trading account, but must be tracked separately in an economic-cost ledger so portfolio profitability and total-project economics are not conflated.

## 10. Data and research integrity

External research is untrusted data, not executable instruction.

The system must protect against prompt injection, fabricated information, stale data and unsupported claims. Information used for autonomous decisions must carry provenance and decision-time timestamps where practicable.

## 11. Auditability

Every autonomous decision must be recorded before its outcome is known. The record must capture, where applicable:

- decision timestamp;
- information and market state available at decision time;
- strategy/model version;
- thesis and bear case;
- expected upside and downside;
- costs and expected net return;
- alternatives considered, including cash;
- confidence or score;
- invalidation/exit conditions;
- risk-engine decision;
- execution result;
- subsequent portfolio result.

Historical decision records must not be rewritten to make past reasoning look better after the outcome.

## 12. Reconciliation

Broker state is authoritative for actual executions and balances. Internal state must be reconciled to broker state. Unknown or irreconcilable broker state must prevent new exposure and place the system into an appropriate safe mode.

Duplicate-order protection and idempotency are mandatory.

## 13. Security

Secrets may exist only in approved secret-management systems or runtime environment variables. They must never be committed to Git.

Paper and live credentials must be separated. Least privilege, IP restrictions and trade-only/read permissions must be used where supported.

Public repository content must be designed as though it will be copied permanently.

## 14. Human powers

The owner may:

- stop the bot;
- trigger the kill switch;
- withdraw funds;
- administer infrastructure;
- alter the wider project;
- change the constitution before live inception;
- terminate the experiment.

The owner is not required to approve ordinary trades.

After live inception, any constitutional amendment must be versioned, timestamped and disclosed. No retrospective amendment may erase or redefine an already-occurring failure.

## 15. Benchmarking

Project Fifty must be evaluated against passive and simpler alternatives. At minimum the experiment will track:

- cash benchmark;
- suitable passive market benchmark;
- non-AI baseline strategy where practicable;
- actual Project Fifty autonomous portfolio.

Positive nominal returns alone do not prove skill.

## 16. Performance integrity

Metrics are only presented when meaningful for the available sample. The system must not present small-sample Sharpe, Sortino, alpha or similar measures as statistically persuasive when they are not.

Tracked measures include NAV, cumulative return, realised/unrealised P&L, drawdown, turnover, costs, slippage, trade count, win/loss characteristics, cash time, benchmark return and days alive.

## 17. Constitutional immutability in software

The live runtime may read constitutional settings but may not edit them. The AI agent may not modify code, configuration, credentials or deployment state in a way that changes its constitutional authority.

Changes to constitutional code require an owner-controlled development/deployment process outside the autonomous trading loop.

## 18. Current status

Version 0.1 is a development specification. No real-money trading authority is granted by this document. Live launch requires a separately frozen and tagged Constitution v1.0 plus successful completion of the paper-to-live gates.
