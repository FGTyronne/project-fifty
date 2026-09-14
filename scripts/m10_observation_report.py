from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from project_fifty.config.settings import Settings
from project_fifty.domain.models import ExecutionReport
from project_fifty.ledger.local import LocalAppendOnlyLedger
from project_fifty.market_data.alpaca import AlpacaMarketDataClient, AlpacaMarketDataConfig
from project_fifty.portfolio.reconcile import PortfolioReconciler
from project_fifty.session.observation import calculate_forward_metrics

INTERNAL_STARTING_CASH = Decimal("67.6725")
SYMBOL = "SPY"
FUTURE_QUOTE_TOLERANCE_SECONDS = 30


def _latest_completed_cycle(ledger: LocalAppendOnlyLedger) -> dict[str, object] | None:
    for event in reversed(ledger.all_events()):
        if event.event_type == "strategy_cycle_completed":
            return event.payload
    return None


def _snapshot_exists(ledger: LocalAppendOnlyLedger, decision_bar_time: str) -> bool:
    return any(
        event.event_type == "forward_observation_snapshot"
        and event.payload.get("decision_bar_time") == decision_bar_time
        for event in ledger.all_events()
    )


def _execution_reports(ledger: LocalAppendOnlyLedger) -> list[ExecutionReport]:
    return [
        ExecutionReport.model_validate(event.payload)
        for event in ledger.all_events()
        if event.event_type == "broker_execution_report"
    ]


def _append_snapshot_if_needed(
    *,
    ledger: LocalAppendOnlyLedger,
    settings: Settings,
    now: datetime,
) -> None:
    cycle = _latest_completed_cycle(ledger)
    if cycle is None:
        return
    raw_bar = cycle.get("decision_bar_time")
    if not isinstance(raw_bar, str) or not raw_bar:
        raise ValueError("strategy cycle is missing decision_bar_time")
    if _snapshot_exists(ledger, raw_bar):
        return

    data_config = AlpacaMarketDataConfig.from_env()
    with AlpacaMarketDataClient(data_config) as market_data:
        quote = market_data.get_latest_quotes((SYMBOL,)).get(SYMBOL)
    if quote is None or not quote.is_actionable:
        raise RuntimeError("cannot mark M10 observation without an actionable SPY quote")

    future_cutoff = now + timedelta(seconds=FUTURE_QUOTE_TOLERANCE_SECONDS)
    if quote.timestamp > future_cutoff:
        raise RuntimeError("SPY observation quote is materially from the future")
    observation_time = max(now, quote.timestamp)
    if (observation_time - quote.timestamp).total_seconds() > settings.max_stale_seconds:
        raise RuntimeError("SPY observation quote is stale")

    portfolio = PortfolioReconciler.replay_events(
        starting_cash=settings.authorized_starting_cash,
        events=_execution_reports(ledger),
        mark_prices={SYMBOL: quote.midpoint},
        currency=settings.account_currency,
    )
    ledger.append(
        "forward_observation_snapshot",
        {
            "as_of": observation_time.isoformat(),
            "decision_bar_time": raw_bar,
            "nav": str(portfolio.nav),
            "cash": str(portfolio.cash),
            "position_quantities": {
                symbol: str(position.quantity)
                for symbol, position in portfolio.positions.items()
            },
            "spy_mark": str(quote.midpoint),
            "spy_quote_time": quote.timestamp.isoformat(),
            "currency": portfolio.currency,
        },
    )


def main() -> None:
    now = datetime.now(UTC)
    settings = Settings.from_env()
    if settings.authorized_starting_cash != INTERNAL_STARTING_CASH:
        raise RuntimeError("M10 observation report requires the frozen USD 67.6725 authority")
    if settings.account_currency != "USD":
        raise RuntimeError("M10 observation report requires USD")

    state_dir = Path(os.getenv("PROJECT_FIFTY_STATE_DIR", "state"))
    ledger_path = state_dir / "m10-ledger.jsonl"
    if not ledger_path.exists():
        raise RuntimeError("M10 durable ledger does not exist")
    ledger = LocalAppendOnlyLedger(ledger_path)

    _append_snapshot_if_needed(ledger=ledger, settings=settings, now=now)
    metrics = calculate_forward_metrics(
        events=ledger.all_events(),
        starting_nav=INTERNAL_STARTING_CASH,
        generated_at=now,
    )
    payload: dict[str, object] = {
        "generated_at_utc": now.isoformat(),
        "strategy_id": "single-market-trend-baseline",
        "strategy_version": "6.0.0",
        "starting_nav_usd": str(INTERNAL_STARTING_CASH),
        "cash_benchmark_definition": "0% return; no interest assumed",
        "spy_benchmark_definition": "passive SPY price return from first forward snapshot",
        "small_sample_warning": (
            "Sharpe, Sortino and alpha are intentionally omitted until the sample is meaningful."
        ),
        **metrics.as_json(),
    }

    report_path = state_dir / "m10-observation-report.json"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("Project Fifty M10 forward observation report updated")
    print(f"sessions={metrics.sessions}")
    print(f"calendar_days={metrics.calendar_days}")
    print(f"project_return={metrics.project_return}")
    print(f"spy_buy_hold_return={metrics.spy_buy_hold_return}")
    print(f"max_drawdown={metrics.max_drawdown}")
    print(f"filled_orders={metrics.filled_orders}")
    print(f"extended_time_gate_met={metrics.extended_time_gate_met}")


if __name__ == "__main__":
    main()
