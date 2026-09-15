from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from project_fifty.brokers.alpaca.broker import AlpacaPaperBroker
from project_fifty.brokers.alpaca.config import AlpacaPaperConfig
from project_fifty.config.settings import Settings
from project_fifty.control.persistence import LedgerBackedControlState
from project_fifty.domain.models import ExperimentMode, LedgerEvent
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
from project_fifty.strategies.contracts import StrategyContext, TargetPortfolio
from project_fifty.strategies.m9 import M9_TIMEFRAME, m9_rebalance_policy
from project_fifty.strategies.proposal_builder import ProposalBuilder
from project_fifty.strategies.single_market import SingleMarketTrendStrategy

INTERNAL_STARTING_CASH = Decimal("67.6725")
OWNER_LIFETIME_GBP = Decimal("50.00")
HISTORY_START = datetime(2020, 1, 2, tzinfo=UTC)
SYMBOL = "SPY"
MAX_M10_ORDER_NOTIONAL = Decimal("250")
RETIRE_ENV = "PROJECT_FIFTY_M10_RETIRE_TO_CASH"


class _InceptionBootstrapStrategy:
    """One-shot M10 adapter that evaluates the frozen M9 regime immediately."""

    strategy_id = SingleMarketTrendStrategy.strategy_id
    strategy_version = SingleMarketTrendStrategy.strategy_version

    def __init__(self, delegate: SingleMarketTrendStrategy) -> None:
        self._delegate = delegate

    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        return self._delegate.generate_inception_target(context)


class _RetireToCashStrategy:
    """Retire the M10 swing control without bypassing the normal execution boundary."""

    strategy_id = "m10-retire-to-cash"
    strategy_version = "1.0.0"

    def generate_target(self, context: StrategyContext) -> TargetPortfolio:
        return TargetPortfolio(
            as_of=context.as_of,
            currency=context.currency,
            weights={},
            cash_weight=Decimal("1"),
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            confidence=Decimal("1"),
            market_state_hash=context.market_state_hash,
            evidence={
                "selection": "RETIRE_M10_SWING_TO_CASH",
                "reason": "M10 does not satisfy Project Fifty day-trading mandate",
            },
        )


class _InceptionLedgerView:
    """Expose durable state while ignoring prior strategy-cycle markers.

    This view was introduced for the inception bootstrap. It is also appropriate for retirement:
    retirement must be allowed to retry a risk-reducing cash target even when the latest market bar
    has already been evaluated by the old swing strategy. Execution reports and every other durable
    event remain visible and all new events are appended to the real ledger.
    """

    def __init__(self, delegate: LocalAppendOnlyLedger) -> None:
        self._delegate = delegate

    def append(self, event_type: str, payload: dict[str, object]) -> LedgerEvent:
        return self._delegate.append(event_type, payload)

    def all_events(self) -> list[LedgerEvent]:
        return [
            event
            for event in self._delegate.all_events()
            if event.event_type != "strategy_cycle_completed"
        ]


def _env_flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


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


def _has_positive_fill(ledger: LocalAppendOnlyLedger) -> bool:
    for event in ledger.all_events():
        if event.event_type != "broker_execution_report":
            continue
        raw_quantity = event.payload.get("fill_quantity")
        if raw_quantity is None:
            continue
        try:
            if Decimal(str(raw_quantity)) > 0:
                return True
        except InvalidOperation as exc:
            raise RuntimeError("invalid fill quantity in durable M10 ledger") from exc
    return False


def _inception_bootstrap_required(ledger: LocalAppendOnlyLedger) -> bool:
    if any(
        event.event_type == "m10_inception_bootstrap_completed"
        for event in ledger.all_events()
    ):
        return False
    return not _has_positive_fill(ledger)


def _write_summary(
    *,
    path: Path,
    generated_at: datetime,
    control_mode: ExperimentMode,
    broker_consistent: bool,
    pending_count: int,
    submissions_this_run: int,
    result: SessionCycleResult | None,
    retire_to_cash: bool,
) -> None:
    payload: dict[str, object] = {
        "generated_at_utc": generated_at.isoformat(),
        "control_mode": control_mode.value,
        "broker_consistent": broker_consistent,
        "pending_order_count": pending_count,
        "paper_submissions_this_run": submissions_this_run,
        "internal_starting_authority_usd": str(INTERNAL_STARTING_CASH),
        "broker_buying_power_used_for_authority": False,
        "strategy_id": (
            _RetireToCashStrategy.strategy_id
            if retire_to_cash
            else SingleMarketTrendStrategy.strategy_id
        ),
        "strategy_version": (
            _RetireToCashStrategy.strategy_version
            if retire_to_cash
            else SingleMarketTrendStrategy.strategy_version
        ),
        "m10_retire_to_cash": retire_to_cash,
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
    retire_to_cash = _env_flag(RETIRE_ENV)
    state_dir = Path(os.getenv("PROJECT_FIFTY_STATE_DIR", "state"))
    ledger_path = state_dir / "m10-ledger.jsonl"
    summary_path = state_dir / "m10-runtime-summary.json"
    ledger = LocalAppendOnlyLedger(ledger_path)
    control = LedgerBackedControlState.restore(
        ledger=ledger,
        kill_switch_active=settings.kill_switch,
    )
    submissions_before = _count_submissions(ledger)
    runtime_strategy_id = (
        _RetireToCashStrategy.strategy_id
        if retire_to_cash
        else SingleMarketTrendStrategy.strategy_id
    )
    runtime_strategy_version = (
        _RetireToCashStrategy.strategy_version
        if retire_to_cash
        else SingleMarketTrendStrategy.strategy_version
    )

    ledger.append(
        "paper_runtime_started",
        {
            "as_of": now.isoformat(),
            "strategy_id": runtime_strategy_id,
            "strategy_version": runtime_strategy_version,
            "control_mode": control.mode.value,
            "kill_switch_active": control.kill_switch_active,
            "m10_retire_to_cash": retire_to_cash,
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
                retire_to_cash=retire_to_cash,
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
                retire_to_cash=retire_to_cash,
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
                retire_to_cash=retire_to_cash,
            )
            print("Project Fifty M10: pending broker order; no new strategy action")
            return

        if retire_to_cash:
            strategy = _RetireToCashStrategy()
            bootstrap_required = False
            runner_ledger = _InceptionLedgerView(ledger)
            rebalance_policy = None
            ledger.append(
                "m10_retirement_mode",
                {
                    "as_of": now.isoformat(),
                    "selection": "RETIRE_M10_SWING_TO_CASH",
                    "reason": "M10 failed the intended day-trading product mandate",
                },
            )
        else:
            base_strategy = SingleMarketTrendStrategy()
            bootstrap_required = _inception_bootstrap_required(ledger)
            strategy = (
                _InceptionBootstrapStrategy(base_strategy)
                if bootstrap_required
                else base_strategy
            )
            runner_ledger = _InceptionLedgerView(ledger) if bootstrap_required else ledger
            rebalance_policy = m9_rebalance_policy()
            if bootstrap_required:
                ledger.append(
                    "m10_inception_bootstrap_started",
                    {
                        "as_of": now.isoformat(),
                        "strategy_id": base_strategy.strategy_id,
                        "strategy_version": base_strategy.strategy_version,
                        "reason": "establish_initial_economic_state",
                        "cadence_override": "inception_only",
                    },
                )

        runner = AutonomousSessionRunner(
            settings=settings,
            universe=SingleInstrumentUniverse(SYMBOL),
            market_data=market_data,
            market_clock=broker,
            strategy=strategy,
            proposal_builder=ProposalBuilder(
                min_order_notional=Decimal("5.00"),
                estimated_slippage_rate=Decimal("0.001"),
                rebalance_policy=rebalance_policy,
            ),
            proposal_handler=kernel,
            ledger=runner_ledger,
            config=SessionConfig(
                timeframe=M9_TIMEFRAME,
                timeframe_seconds=86400,
                history_start=HISTORY_START,
                history_days=3650,
                poll_seconds=60,
            ),
        )
        result = runner.run_cycle(now=now)

        if bootstrap_required and result.market_open and result.skipped_reason is None:
            bootstrap_succeeded = result.rejected_count == 0 and result.suppressed_count == 0
            ledger.append(
                (
                    "m10_inception_bootstrap_completed"
                    if bootstrap_succeeded
                    else "m10_inception_bootstrap_incomplete"
                ),
                {
                    "as_of": now.isoformat(),
                    "decision_bar_time": (
                        result.decision_bar_time.isoformat()
                        if result.decision_bar_time is not None
                        else None
                    ),
                    "proposal_count": result.proposal_count,
                    "approved_count": result.approved_count,
                    "rejected_count": result.rejected_count,
                    "suppressed_count": result.suppressed_count,
                    "submissions_this_run": _count_submissions(ledger) - submissions_before,
                },
            )

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
            "m10_retire_to_cash": retire_to_cash,
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
        retire_to_cash=retire_to_cash,
    )

    print("Project Fifty M10 autonomous paper cycle completed")
    print(f"control_mode={control.mode.value}")
    print(f"m10_retire_to_cash={retire_to_cash}")
    print(f"market_open={result.market_open}")
    print(f"decision_bar_time={result.decision_bar_time}")
    print(f"proposal_count={result.proposal_count}")
    print(f"approved_count={result.approved_count}")
    print(f"rejected_count={result.rejected_count}")
    print(f"paper_submissions_this_run={submissions_after - submissions_before}")
    print(f"skipped_reason={result.skipped_reason}")


if __name__ == "__main__":
    main()
