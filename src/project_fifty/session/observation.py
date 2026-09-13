from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from project_fifty.domain.models import ExecutionReport, LedgerEvent, OrderStatus

_FILL_STATES = {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED}
_ZERO = Decimal("0")
_ONE = Decimal("1")


@dataclass(frozen=True)
class ForwardObservationMetrics:
    sessions: int
    observation_start_utc: datetime | None
    latest_snapshot_utc: datetime | None
    calendar_days: int
    current_nav: Decimal | None
    project_return: Decimal | None
    cash_return: Decimal | None
    spy_buy_hold_return: Decimal | None
    max_drawdown: Decimal | None
    turnover_notional: Decimal
    turnover_ratio: Decimal
    modeled_fees: Decimal
    observed_slippage: Decimal
    filled_orders: int
    cash_sessions: int
    cash_session_fraction: Decimal | None
    session_gate_met: bool
    calendar_gate_met: bool

    @property
    def extended_time_gate_met(self) -> bool:
        return self.session_gate_met and self.calendar_gate_met

    def as_json(self) -> dict[str, object]:
        return {
            "sessions": self.sessions,
            "observation_start_utc": (
                self.observation_start_utc.isoformat() if self.observation_start_utc else None
            ),
            "latest_snapshot_utc": (
                self.latest_snapshot_utc.isoformat() if self.latest_snapshot_utc else None
            ),
            "calendar_days": self.calendar_days,
            "current_nav": _decimal_or_none(self.current_nav),
            "project_return": _decimal_or_none(self.project_return),
            "cash_return": _decimal_or_none(self.cash_return),
            "spy_buy_hold_return": _decimal_or_none(self.spy_buy_hold_return),
            "max_drawdown": _decimal_or_none(self.max_drawdown),
            "turnover_notional": str(self.turnover_notional),
            "turnover_ratio": str(self.turnover_ratio),
            "modeled_fees": str(self.modeled_fees),
            "observed_slippage": str(self.observed_slippage),
            "filled_orders": self.filled_orders,
            "cash_sessions": self.cash_sessions,
            "cash_session_fraction": _decimal_or_none(self.cash_session_fraction),
            "session_gate_met": self.session_gate_met,
            "calendar_gate_met": self.calendar_gate_met,
            "extended_time_gate_met": self.extended_time_gate_met,
        }


def calculate_forward_metrics(
    *,
    events: list[LedgerEvent],
    starting_nav: Decimal,
    generated_at: datetime | None = None,
) -> ForwardObservationMetrics:
    if not starting_nav.is_finite() or starting_nav <= 0:
        raise ValueError("starting_nav must be finite and positive")
    now = (generated_at or datetime.now(UTC)).astimezone(UTC)
    snapshots = _observation_snapshots(events)
    execution_reports = [
        ExecutionReport.model_validate(event.payload)
        for event in events
        if event.event_type == "broker_execution_report"
    ]
    turnover, fees, slippage, filled_orders = _execution_metrics(execution_reports)

    if not snapshots:
        return ForwardObservationMetrics(
            sessions=0,
            observation_start_utc=None,
            latest_snapshot_utc=None,
            calendar_days=0,
            current_nav=None,
            project_return=None,
            cash_return=None,
            spy_buy_hold_return=None,
            max_drawdown=None,
            turnover_notional=turnover,
            turnover_ratio=turnover / starting_nav,
            modeled_fees=fees,
            observed_slippage=slippage,
            filled_orders=filled_orders,
            cash_sessions=0,
            cash_session_fraction=None,
            session_gate_met=False,
            calendar_gate_met=False,
        )

    navs = [starting_nav, *[snapshot.nav for snapshot in snapshots]]
    current_nav = snapshots[-1].nav
    project_return = current_nav / starting_nav - _ONE
    first_spy = snapshots[0].spy_mark
    latest_spy = snapshots[-1].spy_mark
    spy_return = latest_spy / first_spy - _ONE
    max_drawdown = _max_drawdown(navs)
    cash_sessions = sum(1 for snapshot in snapshots if not snapshot.position_quantities)
    start = snapshots[0].as_of
    latest = snapshots[-1].as_of
    calendar_days = max((now - start).days, 0)
    sessions = len(snapshots)

    return ForwardObservationMetrics(
        sessions=sessions,
        observation_start_utc=start,
        latest_snapshot_utc=latest,
        calendar_days=calendar_days,
        current_nav=current_nav,
        project_return=project_return,
        cash_return=_ZERO,
        spy_buy_hold_return=spy_return,
        max_drawdown=max_drawdown,
        turnover_notional=turnover,
        turnover_ratio=turnover / starting_nav,
        modeled_fees=fees,
        observed_slippage=slippage,
        filled_orders=filled_orders,
        cash_sessions=cash_sessions,
        cash_session_fraction=Decimal(cash_sessions) / Decimal(sessions),
        session_gate_met=sessions >= 40,
        calendar_gate_met=calendar_days >= 56,
    )


@dataclass(frozen=True)
class _Snapshot:
    as_of: datetime
    decision_bar_time: datetime
    nav: Decimal
    spy_mark: Decimal
    position_quantities: dict[str, Decimal]


def _observation_snapshots(events: list[LedgerEvent]) -> list[_Snapshot]:
    by_bar: dict[datetime, _Snapshot] = {}
    for event in events:
        if event.event_type != "forward_observation_snapshot":
            continue
        payload = event.payload
        as_of = _datetime(payload.get("as_of"), "snapshot as_of")
        decision_bar = _datetime(payload.get("decision_bar_time"), "decision_bar_time")
        nav = _decimal(payload.get("nav"), "snapshot nav")
        spy_mark = _decimal(payload.get("spy_mark"), "SPY mark")
        if nav < 0 or spy_mark <= 0:
            raise ValueError("observation snapshot contains invalid economic values")
        raw_positions = payload.get("position_quantities", {})
        if not isinstance(raw_positions, dict):
            raise ValueError("observation position quantities must be an object")
        positions = {
            str(symbol): _decimal(quantity, f"position quantity {symbol}")
            for symbol, quantity in raw_positions.items()
        }
        if any(quantity < 0 for quantity in positions.values()):
            raise ValueError("observation snapshot contains a short position")
        by_bar[decision_bar] = _Snapshot(
            as_of=as_of,
            decision_bar_time=decision_bar,
            nav=nav,
            spy_mark=spy_mark,
            position_quantities=positions,
        )
    return [by_bar[key] for key in sorted(by_bar)]


def _execution_metrics(
    reports: list[ExecutionReport],
) -> tuple[Decimal, Decimal, Decimal, int]:
    final_qty: dict[str, Decimal] = {}
    final_gross: dict[str, Decimal] = {}
    final_fee: dict[str, Decimal] = {}
    final_slippage: dict[str, Decimal] = {}
    seen_report_ids: set[str] = set()

    for report in reports:
        if report.report_id in seen_report_ids:
            continue
        seen_report_ids.add(report.report_id)
        if report.status not in _FILL_STATES:
            continue
        order_id = report.broker_order_id
        previous_qty = final_qty.get(order_id, _ZERO)
        if report.fill_quantity < previous_qty:
            raise ValueError("broker cumulative fill quantity regressed")
        gross = report.fill_quantity * report.fill_price
        if gross < final_gross.get(order_id, _ZERO):
            raise ValueError("broker cumulative fill notional regressed")
        if report.fee < final_fee.get(order_id, _ZERO):
            raise ValueError("broker cumulative fee regressed")
        final_qty[order_id] = report.fill_quantity
        final_gross[order_id] = gross
        final_fee[order_id] = report.fee
        final_slippage[order_id] = report.slippage

    turnover = sum(final_gross.values(), start=_ZERO)
    fees = sum(final_fee.values(), start=_ZERO)
    slippage = sum(final_slippage.values(), start=_ZERO)
    filled_orders = sum(1 for quantity in final_qty.values() if quantity > 0)
    return turnover, fees, slippage, filled_orders


def _max_drawdown(navs: list[Decimal]) -> Decimal:
    peak = navs[0]
    worst = _ZERO
    for nav in navs:
        if nav > peak:
            peak = nav
        if peak <= 0:
            continue
        drawdown = nav / peak - _ONE
        if drawdown < worst:
            worst = drawdown
    return worst


def _datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing {field}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(value: object, field: str) -> Decimal:
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _decimal_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
