from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from project_fifty.brokers.alpaca.broker import AlpacaPaperBroker
from project_fifty.brokers.alpaca.config import AlpacaPaperConfig
from project_fifty.config.settings import Settings
from project_fifty.control.persistence import LedgerBackedControlState
from project_fifty.domain.models import ExperimentMode
from project_fifty.execution.kernel import ExecutionKernel
from project_fifty.ledger.local import LocalAppendOnlyLedger
from project_fifty.market_data.alpaca import AlpacaMarketDataConfig
from project_fifty.market_data.research import AlpacaResearchMarketDataClient
from project_fifty.market_data.universe import SingleInstrumentUniverse
from project_fifty.risk.engine import RiskEngine
from project_fifty.session.runner import (
    AutonomousSessionRunner,
    SessionConfig,
    SessionCycleResult,
)
from project_fifty.session.runtime_state import expected_position_quantities, pending_orders
from project_fifty.strategies.m9 import M9_TIMEFRAME, m9_rebalance_policy
from project_fifty.strategies.proposal_builder import ProposalBuilder
from project_fifty.strategies.single_market import SingleMarketTrendStrategy

INTERNAL_STARTING_CASH = Decimal("67.6725")
OWNER_LIFETIME_GBP = Decimal("50.00")
HISTORY_START = datetime(2020, 1, 2, tzinfo=UTC)
SYMBOL = "SPY"
MAX_M10_ORDER_NOTIONAL = Decimal("250")


def _validated_settings() -> Settings:
    settings = Settings.from_env()
    if settings.inception_contribution_gbp != OWNER_LIFETIME_GBP:
        raise RuntimeError("M10 owner lifetime allocation must remain GBP 50.00")
    if settings.account_currency != "USD":
        raise RuntimeError("M10 account currency must remain USD")
    if settings.authorized_starting_cash != INTERNAL_STARTING_CASH:
        raise RuntimeError("M10 internal starting authority must remain USD 67.6725")
    if settings.permitted_symbols != frozenset({SYMBOL}):
        raise RuntimeError("M10 permits SPY only")
    if settings.max_order_notional < INTERNAL_STARTING_CASH:
        raise RuntimeError("M10 order ceiling must permit the inception envelope")
    if settings.max_order_notional > MAX_M10_ORDER_NOTIONAL:
        raise RuntimeError("M10 order ceiling exceeds the predeclared prudential cap")
    return settings


def _count_submissions(ledger: LocalAppendOnlyLedger) -> int:
    return sum(
        1
        for event in ledger.all_events()
        if event.event_type == "broker_submission_attempt"
    )


def _write_summary(
    *,
    path: Path,
    generated_at: datetime,
    control_mode: ExperimentMode,
    broker_consistent: bool,
    pending_count: int,
    submissions_this_run: int,
    result: SessionCycleResult | None,
) -> None:
    payload: dict[str, object] = {
        "generated_at_utc": generated_at.isoformat(),
        "control_mode": control_mode.value,
        "broker_consistent": broker_consistent,
        "pending_order_count": pending_count,
        "paper_submissions_this_run": submissions_this_run,
        "internal_starting_authority_usd": str(INTERNAL_STARTING_CASH),
        "broker_buying_power_used_for_authority": False,
        "strategy_id": SingleMarketTrendStrategy.strategy_id,
        "strategy_version": SingleMarketTrendStrategy.strategy_version,
    }
    if result is not None:
        payload["cycle"] = {
            "market_open": result.market_open,
            "decision_bar_time": (
                result.decision_bar_time.isoformat()
                if result.decision_bar_time is not None
                else None
            ),
            "proposal_count": result.proposal_count,
            "approved_count": result.approved_count,
            "rejected_count": result.rejected_count,
            "suppressed_count": result.suppressed_count,
            "skipped_reason": result.skipped_reason,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    now = datetime.now(UTC)
    settings = _validated_settings()
    state_dir = Path(os.getenv("PROJECT_FIFTY_STATE_DIR", "state"))
    ledger_path = state_dir / "m10-ledger.jsonl"
    summary_path = state_dir / "m10-runtime-summary.json"
    ledger = LocalAppendOnlyLedger(ledger_path)
    control = LedgerBackedControlState.restore(
        ledger=ledger,
        kill_switch_active=settings.kill_switch,
    )
    submissions_before = _count_submissions(ledger)

    ledger.append(
        "paper_runtime_started",
        {
            "as_of": now.isoformat(),
            "strategy_id": SingleMarketTrendStrategy.strategy_id,
            "strategy_version": SingleMarketTrendStrategy.strategy_version,
            "control_mode": control.mode.value,
            "kill_switch_active": control.kill_switch_active,
        },
    )

    paper_config = AlpacaPaperConfig.from_env()
    data_config = AlpacaMarketDataConfig.from_env()

    with AlpacaPaperBroker(paper_config) as broker, AlpacaResearchMarketDataClient(
        data_config
    ) as market_data:
        kernel = ExecutionKernel(
            settings=settings,
            risk_engine=RiskEngine(settings),
            broker=broker,
            ledger=ledger,
            control=control,
        )

        for pending in pending_orders(ledger):
            report = broker.get_order_by_client_order_id(
                pending.idempotency_key,
                reference_price=pending.reference_price,
            )
            if report is not None:
                kernel.reconcile_execution_report(report)

        still_pending = pending_orders(ledger)
        expected_positions = expected_position_quantities(ledger)
        expected_open_client_ids = {
            broker.client_order_id(item.idempotency_key) for item in still_pending
        }
        broker_consistent = broker.guard_broker_state(
            control,
            expected_positions=expected_positions,
            expected_open_client_order_ids=expected_open_client_ids,
        )
        ledger.append(
            "broker_state_guard",
            {
                "as_of": now.isoformat(),
                "consistent": broker_consistent,
                "expected_positions": {
                    symbol: str(quantity) for symbol, quantity in expected_positions.items()
                },
                "expected_open_order_count": len(expected_open_client_ids),
                "control_mode": control.mode.value,
            },
        )

        if not broker_consistent:
            _write_summary(
                path=summary_path,
                generated_at=now,
                control_mode=control.mode,
                broker_consistent=False,
                pending_count=len(still_pending),
                submissions_this_run=_count_submissions(ledger) - submissions_before,
                result=None,
            )
            raise RuntimeError("broker/internal divergence forced M10 SAFE mode")

        if control.mode == ExperimentMode.DEAD:
            _write_summary(
                path=summary_path,
                generated_at=now,
                control_mode=control.mode,
                broker_consistent=True,
                pending_count=len(still_pending),
                submissions_this_run=_count_submissions(ledger) - submissions_before,
                result=None,
            )
            raise RuntimeError("Project Fifty is DEAD and cannot resume this experiment")

        if still_pending:
            ledger.append(
                "paper_runtime_skipped",
                {
                    "as_of": now.isoformat(),
                    "reason": "pending_order_reconciliation",
                    "pending_order_count": len(still_pending),
                },
            )
            _write_summary(
                path=summary_path,
                generated_at=now,
                control_mode=control.mode,
                broker_consistent=True,
                pending_count=len(still_pending),
                submissions_this_run=_count_submissions(ledger) - submissions_before,
                result=None,
            )
            print("Project Fifty M10: pending broker order; no new strategy action")
            return

        runner = AutonomousSessionRunner(
            settings=settings,
            universe=SingleInstrumentUniverse(SYMBOL),
            market_data=market_data,
            market_clock=broker,
            strategy=SingleMarketTrendStrategy(),
            proposal_builder=ProposalBuilder(
                min_order_notional=Decimal("5.00"),
                estimated_slippage_rate=Decimal("0.001"),
                rebalance_policy=m9_rebalance_policy(),
            ),
            proposal_handler=kernel,
            ledger=ledger,
            config=SessionConfig(
                timeframe=M9_TIMEFRAME,
                timeframe_seconds=86400,
                history_start=HISTORY_START,
                history_days=3650,
                poll_seconds=60,
            ),
        )
        result = runner.run_cycle(now=now)

    submissions_after = _count_submissions(ledger)
    ledger.append(
        "paper_runtime_completed",
        {
            "as_of": now.isoformat(),
            "market_open": result.market_open,
            "decision_bar_time": (
                result.decision_bar_time.isoformat() if result.decision_bar_time else None
            ),
            "proposal_count": result.proposal_count,
            "approved_count": result.approved_count,
            "rejected_count": result.rejected_count,
            "submissions_this_run": submissions_after - submissions_before,
            "skipped_reason": result.skipped_reason,
            "control_mode": control.mode.value,
        },
    )
    _write_summary(
        path=summary_path,
        generated_at=now,
        control_mode=control.mode,
        broker_consistent=True,
        pending_count=0,
        submissions_this_run=submissions_after - submissions_before,
        result=result,
    )

    print("Project Fifty M10 autonomous paper cycle completed")
    print(f"control_mode={control.mode.value}")
    print(f"market_open={result.market_open}")
    print(f"decision_bar_time={result.decision_bar_time}")
    print(f"proposal_count={result.proposal_count}")
    print(f"approved_count={result.approved_count}")
    print(f"rejected_count={result.rejected_count}")
    print(f"paper_submissions_this_run={submissions_after - submissions_before}")
    print(f"skipped_reason={result.skipped_reason}")


if __name__ == "__main__":
    main()
