# M10 — Controlled Autonomous Paper Phase

## Status

Predeclared immediately after M9 passed its frozen economic gate and before any M10 paper order is submitted.

M9 established that the deterministic `single-market-trend-baseline` v6.0.0 deserves progression to paper execution. M10 is not a strategy-search milestone. The M9 strategy parameters are frozen. The purpose is to prove that the complete autonomous runtime can operate the strategy safely against Alpaca paper trading under Project Fifty's internal capital authority.

No live-money deployment is authorised by M10.

## Objective

Run the frozen M9 SPY/cash strategy through the same deterministic constitutional firewall, execution kernel, idempotency controls, broker adapter, reconciliation path and append-only evidence trail intended for later live use.

The paper account's simulated cash and buying power must never enlarge Project Fifty's authority.

## Frozen strategy

Use `single-market-trend-baseline` v6.0.0 unchanged:

- SPY only;
- daily completed bars;
- scheduled strategy decision once every 21 completed SPY bars;
- risk-on iff close > 200-day SMA and 126-day return > 0;
- transition from cash to risk-on targets 100% of the Project Fifty internal capital envelope;
- persistent risk-on preserves the marked portfolio rather than mechanically rebalancing;
- risk-off targets 100% cash;
- no shorting, inverse products, leverage, margin or derivatives.

The M9 economic filter remains unchanged:

- minimum trade notional USD 5.00;
- minimum trade fraction 15% of internal NAV;
- full exits forceable.

## Paper capital authority

The paper broker may display a large simulated balance or buying-power figure. Those values are observational broker state only.

M10 internal authority is frozen to the Project Fifty prototype envelope:

- owner lifetime allocation basis: GBP 50.00;
- current research/paper USD inception envelope: USD 67.6725;
- maximum gross internal authority at paper inception: USD 67.6725;
- paper profits may increase subsequent internal NAV naturally;
- broker paper cash, margin and buying power cannot increase internal authority;
- no external deposits, transfers or recapitalisation paths exist in the runtime.

## Execution rules

All paper orders must originate from the autonomous Project Fifty runtime and pass this chain:

`completed market data -> frozen M9 strategy -> target portfolio -> economic rebalance -> TradeProposal/OrderIntent -> constitutional firewall -> Alpaca paper adapter -> reconciliation -> ledger`

Requirements:

- no manual broker order entry;
- no LLM direct broker credentials;
- deterministic client-order IDs;
- restart-safe idempotency;
- ambiguous submission timeout must query by client-order ID before any retry;
- cumulative fills reconciled as deltas only;
- outstanding BUY cash reserved internally across restart;
- cancellation releases reservation only after broker confirmation;
- broker/internal divergence forces SAFE mode;
- stale or incomplete market state cannot open exposure;
- kill switch remains independent of strategy logic.

## Initial acceptance sequence

Before any extended paper observation period, M10 must demonstrate one end-to-end controlled paper lifecycle using the frozen runtime:

1. reconcile a flat Project Fifty internal portfolio against the paper broker;
2. generate the current frozen M9 target autonomously from completed daily data;
3. if the target is cash, record a valid autonomous no-trade decision and do not manufacture a trade for testing;
4. if the target requires SPY exposure, size the order from internal NAV only and submit through the firewall;
5. reconcile acknowledgement, fills, cash reservation and resulting position;
6. on a later genuine risk-off transition, autonomously reduce/exit through the same path;
7. prove a restart between lifecycle stages does not duplicate an order or lose reservations;
8. preserve every decision and reconciliation event in the audit record.

A synthetic forced trade is prohibited. The strategy must be allowed to remain in cash until its real rule produces an executable state transition.

## Extended paper gate

After initial runtime acceptance, continue autonomous paper operation for at least:

- 40 US market sessions; and
- 8 calendar weeks;

unless a constitutional or reconciliation failure blocks the experiment earlier.

The observation period is for reliability and forward economic evidence. Historical M9 parameters remain frozen throughout.

## Hard gates before any consideration of live GBP 50 deployment

Every gate must pass:

1. zero constitutional violations;
2. zero unexplained broker positions;
3. zero duplicate economic orders;
4. zero unresolved reconciliation divergences;
5. restart/idempotency tests pass with outstanding and partially filled orders;
6. kill switch and SAFE-mode tests pass;
7. internal authority never exceeds Project Fifty NAV because of paper broker buying power;
8. all paper order quantities are fractional long-only SPY and economically bounded;
9. all decisions use completed, sufficiently fresh market data;
10. append-only audit evidence is complete for every autonomous decision;
11. at least 40 market sessions and 8 weeks of autonomous observation complete;
12. forward paper performance, costs, turnover and drawdown are reported against cash and passive SPY;
13. Ruff, strict Mypy and Pytest remain green.

Profit is not by itself a deployment gate. A profitable paper run with control failures fails M10.

## Explicit prohibitions

- no live-money order submission;
- no strategy parameter tuning during M10;
- no manual paper trade to make the test convenient;
- no leverage, margin reliance, shorts, inverse products, options, futures or derivatives;
- no transfers or funding actions;
- no use of paper broker buying power as capital authority;
- no LLM possession of broker secrets;
- no LLM-direct execution;
- no bypass of the constitutional firewall;
- no weakening of SAFE or DEAD semantics.

## Interpretation rule

Passing M10 would establish that the frozen M9 baseline can operate autonomously and safely in a broker paper environment for a meaningful observation period. It would still not prove future live profitability.

Any future GBP 50 live inception requires a separate explicit milestone, frozen broker suitability decision, verified UK live eligibility, funding/FX treatment, fresh security review and a new go/no-go gate.
