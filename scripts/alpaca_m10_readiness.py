from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from project_fifty.brokers.alpaca.broker import AlpacaPaperBroker
from project_fifty.brokers.alpaca.config import AlpacaPaperConfig
from project_fifty.domain.models import PortfolioState
from project_fifty.market_data.alpaca import AlpacaMarketDataConfig
from project_fifty.market_data.research import AlpacaResearchMarketDataClient
from project_fifty.market_data.state import market_state_hash
from project_fifty.strategies.contracts import StrategyContext
from project_fifty.strategies.m9 import M9_TIMEFRAME, m9_rebalance_policy
from project_fifty.strategies.proposal_builder import ProposalBuilder
from project_fifty.strategies.single_market import SingleMarketTrendStrategy

INTERNAL_STARTING_CASH = Decimal("67.6725")
HISTORY_START = datetime(2020, 1, 2, tzinfo=UTC)
SYMBOL = "SPY"


def _asset_ready(asset: dict[str, object]) -> bool:
    return (
        str(asset.get("status") or "").lower() == "active"
        and str(asset.get("class") or "").lower() == "us_equity"
        and bool(asset.get("tradable"))
        and bool(asset.get("fractionable"))
    )


def main() -> None:
    generated_at = datetime.now(UTC)
    paper_config = AlpacaPaperConfig.from_env()
    data_config = AlpacaMarketDataConfig.from_env()

    with AlpacaPaperBroker(paper_config) as broker:
        account = broker.get_account()
        clock = broker.get_clock()
        asset = broker.get_asset(SYMBOL)
        broker_portfolio = broker.get_portfolio()
        open_orders = broker.get_open_orders()

    broker_flat = not broker_portfolio.positions
    broker_open_orders_zero = not open_orders
    account_active = str(account.get("status") or "").upper() == "ACTIVE"
    spy_ready = _asset_ready(asset)

    with AlpacaResearchMarketDataClient(data_config) as market_data:
        history = market_data.get_bars(
            (SYMBOL,),
            start=HISTORY_START,
            end=generated_at,
            timeframe=M9_TIMEFRAME,
        )

    bars = history.get(SYMBOL, ())
    if len(bars) < 200:
        raise RuntimeError("insufficient completed SPY daily history for M10 readiness")
    latest = bars[-1]
    if latest.timestamp >= generated_at:
        raise RuntimeError("latest SPY bar is not safely completed")

    internal_portfolio = PortfolioState(
        cash=INTERNAL_STARTING_CASH,
        positions={},
        nav=INTERNAL_STARTING_CASH,
        currency="USD",
        as_of=latest.timestamp,
    )
    state_hash = market_state_hash(history=history)
    context = StrategyContext(
        as_of=latest.timestamp,
        currency="USD",
        portfolio=internal_portfolio,
        reference_prices={SYMBOL: latest.close},
        reference_price_timestamps={SYMBOL: latest.timestamp},
        market_state_hash=state_hash,
        history=history,
        benchmark_symbol=SYMBOL,
    )
    target = SingleMarketTrendStrategy().generate_target(context)
    proposals, plan = ProposalBuilder(
        rebalance_policy=m9_rebalance_policy(),
    ).build_with_plan(target=target, context=context)

    suppressed = []
    if plan is not None:
        suppressed = [
            {
                "symbol": instruction.symbol,
                "reason": instruction.reason.value,
            }
            for instruction in plan.suppressed
        ]

    readiness_checks = {
        "account_active": account_active,
        "broker_flat": broker_flat,
        "broker_open_orders_zero": broker_open_orders_zero,
        "spy_active_tradable_fractionable": spy_ready,
        "history_anchor_fixed": HISTORY_START.isoformat() == "2020-01-02T00:00:00+00:00",
        "history_sufficient": len(bars) >= 200,
        "zero_order_submission_path": True,
    }
    ready = all(readiness_checks.values())

    payload: dict[str, object] = {
        "generated_at_utc": generated_at.isoformat(),
        "paper_endpoint": paper_config.base_url,
        "data_feed": data_config.feed,
        "market_data_adjustment": AlpacaResearchMarketDataClient.adjustment,
        "history_start": HISTORY_START.isoformat(),
        "latest_completed_bar": latest.timestamp.isoformat(),
        "completed_bar_count": len(bars),
        "broker_market_open": bool(clock.get("is_open")),
        "internal_authority_usd": str(INTERNAL_STARTING_CASH),
        "broker_cash_or_buying_power_used_for_authority": False,
        "strategy_id": target.strategy_id,
        "strategy_version": target.strategy_version,
        "selection": target.evidence.get("selection", "UNKNOWN"),
        "raw_risk_state": target.evidence.get("raw_risk_state"),
        "scheduled": target.evidence.get("scheduled", "false"),
        "target_weights": {symbol: str(weight) for symbol, weight in target.weights.items()},
        "target_cash_weight": str(target.cash_weight),
        "proposal_count": len(proposals),
        "proposal_actions": [proposal.action.value for proposal in proposals],
        "suppressed": suppressed,
        "readiness_checks": readiness_checks,
        "ready": ready,
        "paper_orders_submitted": 0,
    }

    output = Path("state/m10-readiness.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("Project Fifty M10 paper readiness completed")
    print(f"ready={ready}")
    print(f"broker_market_open={bool(clock.get('is_open'))}")
    print(f"latest_completed_bar={latest.timestamp.isoformat()}")
    print(f"completed_bar_count={len(bars)}")
    print(f"selection={target.evidence.get('selection', 'UNKNOWN')}")
    print(f"raw_risk_state={target.evidence.get('raw_risk_state', 'UNKNOWN')}")
    print(f"scheduled={target.evidence.get('scheduled', 'false')}")
    print(f"proposal_count={len(proposals)}")
    print("paper_orders_submitted=0")

    if not ready:
        failed = sorted(key for key, value in readiness_checks.items() if not value)
        raise RuntimeError(f"M10 readiness failed: {','.join(failed)}")


if __name__ == "__main__":
    main()
