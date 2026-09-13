# Broker Evaluation Framework

Project Fifty must not choose a broker by popularity. The selected broker must make a £50 autonomous account technically and economically viable for a UK retail user.

## Hard eligibility gates

A candidate fails before scoring if any of the following cannot be verified from current primary documentation or direct account testing:

- legal availability to the owner as a UK retail client;
- official documented trading API for the intended live account/product;
- autonomous order placement permitted under the broker's terms and technical controls;
- no requirement for unauthorised leverage or borrowing;
- practical minimum order size for the £50 experiment;
- reliable account, order, fill and position reconciliation endpoints;
- secure authentication compatible with cloud deployment;
- no need to bypass broker restrictions or unsupported endpoints.

## Weighted scorecard

| Criterion | Weight |
|---|---:|
| UK live-account eligibility | 15% |
| Official execution API | 20% |
| Fractional/minimum order capability | 15% |
| Trading, FX and funding economics | 15% |
| Paper/sandbox environment | 10% |
| Order/fill/reconciliation quality | 10% |
| Security and permission controls | 5% |
| Market-data practicality | 5% |
| Cloud automation suitability | 5% |

Scores must be supported by evidence and dated because broker features and pricing change.

## Quantitative £50 economics

For each broker, calculate at minimum:

- smallest executable live order through the API;
- percentage of £50 consumed by that minimum order;
- funding fees;
- FX conversion fees;
- commissions;
- regulatory/venue fees where applicable;
- expected bid/ask spread for the intended universe;
- estimated slippage assumptions;
- round-trip cost at representative £2, £5, £10, £20 and £50 notionals where technically possible;
- whether fractional shares are supported specifically through the API, not merely in the retail UI;
- settlement/cash-availability constraints;
- any inactivity, custody, market-data or platform fees that matter at this scale.

## Technical proof-of-concept tests

Before selection, the paper/sandbox environment should demonstrate:

1. authentication and credential rotation approach;
2. instrument lookup;
3. quote/market-data retrieval;
4. account snapshot retrieval;
5. fractional/minimum-size order where relevant;
6. market and limit order handling as supported;
7. cancellation/replacement;
8. partial-fill handling where available;
9. position retrieval;
10. fill/trade history retrieval;
11. deterministic reconciliation after restart;
12. timeout and rate-limit behaviour;
13. idempotency or client-order-ID support;
14. separation of paper and live credentials;
15. cloud-hosted connectivity restrictions/allow-listing where available.

## Initial candidates

The first research pass should include, but not be limited to:

- Alpaca;
- Interactive Brokers;
- Saxo;
- IG where cash share-dealing API capability can be verified;
- other UK-accessible brokers discovered during current research.

Crypto venues should be evaluated separately and only if the constitutional asset universe later permits spot crypto.

## Selection rule

The highest score does not automatically win. A broker must first pass the hard gates and demonstrate that the expected economics do not make meaningful compounding mathematically implausible for a £50 account.

Final broker selection is a documented architecture decision record (ADR), not an informal preference.
