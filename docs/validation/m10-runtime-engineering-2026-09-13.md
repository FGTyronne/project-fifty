# M10 autonomous paper runtime engineering evidence — 2026-09-13

## Scope

This record covers the M10 runtime engineering and credentialed smoke gate only. It does not declare the full M10 milestone complete. The predeclared 40 US market sessions / 8 calendar weeks observation gate and genuine future strategy transitions remain time-dependent.

## Frozen strategy and authority

- strategy: `single-market-trend-baseline` v6.0.0, unchanged from M9;
- instrument: SPY only;
- owner lifetime allocation basis: GBP 50.00;
- internal paper inception authority: USD 67.6725;
- broker cash and buying power are observational only and never enter sizing authority;
- no live-money path is enabled.

## Runtime controls completed

The M10 runtime now provides:

- fixed-history-anchor decision scheduling consistent with the frozen M9 bar-count cadence;
- 100% target sizing that reserves its own estimated slippage/cost envelope instead of overspending internal cash;
- deterministic Alpaca client-order identity and existing M2 ambiguous-timeout recovery;
- append-only target audit, including valid no-trade targets;
- restart reconstruction of non-terminal orders and cumulative fill-delta positions;
- pending-order reconciliation before any fresh strategy decision;
- a hard block on fresh strategy action while a prior economic order remains non-terminal;
- broker/internal position and open-order guard before strategy execution;
- broker divergence -> SAFE with SAFE persisted to the hash-chained ledger across restart;
- DEAD remains terminal across restart;
- runtime kill-switch state remains independent of strategy logic;
- durable M10 ledger/state carried between ephemeral GitHub runners by a fail-closed workflow artifact chain;
- weekday autonomous paper schedule at 15:05 UTC, with workflow concurrency preventing overlapping runs.

## Credentialed Sunday smoke

One temporary branch-only push trigger was used to exercise the complete credentialed runtime without changing strategy state or manufacturing a trade. The temporary trigger was removed immediately after the run and is not part of the merge candidate.

Workflow run: `34768437577`

Result:

- job: `autonomous-paper-cycle` — success;
- paper credentials injected from GitHub Actions secrets and remained masked;
- Alpaca paper endpoint only;
- previous-state restore correctly selected genesis because no completed main-branch M10 runtime exists yet;
- control mode: `NORMAL`;
- broker/internal guard: passed (job continued through the deterministic runtime);
- market open: `false` (Sunday);
- strategy proposals: `0`;
- approved orders: `0`;
- rejected orders: `0`;
- paper submissions this run: `0`;
- skip reason: `market_closed`;
- durable state artifact uploaded successfully.

Artifact: `m10-runtime-state`, ID `10320084608`

Artifact digest: `sha256:24e24f16a9c8914132b8f00331b9ed28ea3eb355c7ab09633728614629717b62`

This is the correct Sunday result. M10 explicitly prohibits synthetic forced trades.

## Prior current-target evidence

The separate authenticated M10 readiness run `34766298585` had already demonstrated current frozen-target generation from completed daily data while the paper account was flat:

- latest completed bar: `2026-09-11T04:00:00+00:00`;
- 1,540 completed daily SPY bars available from the frozen history anchor;
- target selection: `NOT_SCHEDULED`;
- target: 100% cash;
- proposal count: 0;
- paper orders submitted: 0.

Together, the readiness run and the credentialed runtime smoke demonstrate the valid flat/no-trade branch of the initial M10 lifecycle without manufacturing exposure.

## Engineering gate interpretation

The runtime is ready to begin the forward autonomous paper observation phase once merged to `main`. The first main-branch scheduled run will create the durable genesis state for the observation chain, and subsequent runs will restore the most recent completed main-branch runtime artifact or fail closed if that state is unavailable.

M10 must remain open until the remaining predeclared gates are observed in real forward operation, including any genuine SPY entry/fill and later genuine risk-off exit, zero control failures, and completion of at least 40 US market sessions and 8 calendar weeks.
