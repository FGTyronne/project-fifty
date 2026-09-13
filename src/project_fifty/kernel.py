from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
import json
import logging
from typing import Dict, Mapping, Optional, Protocol, Sequence, Tuple


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    ADD = "ADD"
    CANCEL = "CANCEL"


class ExecutionStatus(str, Enum):
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class TradeProposal:
    proposal_id: str
    symbol: str
    action: Action
    quantity: int = 0
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.proposal_id:
            raise ValueError("proposal_id is required")
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.quantity < 0:
            raise ValueError("quantity cannot be negative")
        if self.action in {Action.BUY, Action.SELL, Action.REDUCE, Action.ADD} and self.quantity <= 0:
            raise ValueError("quantity must be positive for executable actions")
        if self.action in {Action.HOLD, Action.CANCEL} and self.quantity != 0:
            raise ValueError("quantity must be 0 for HOLD and CANCEL")

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioState:
    cash: float
    positions: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cash < 0:
            raise ValueError("cash cannot be negative")
        for symbol, qty in self.positions.items():
            if qty < 0:
                raise ValueError(f"position for {symbol} cannot be negative")

    def position_of(self, symbol: str) -> int:
        return int(self.positions.get(symbol, 0))


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    proposal_id: str
    symbol: str
    action: Action
    quantity: int


@dataclass(frozen=True)
class ExecutionReport:
    intent_id: Optional[str]
    proposal_id: str
    symbol: str
    action: Action
    status: ExecutionStatus
    filled_quantity: int
    fill_price: Optional[float]
    message: str


@dataclass(frozen=True)
class KillSwitchState:
    tripped: bool = False
    reason: str = ""


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str


class Broker(Protocol):
    def quote(self, symbol: str) -> float:
        ...

    def execute(
        self,
        intent: OrderIntent,
        portfolio: PortfolioState,
    ) -> Tuple[ExecutionReport, PortfolioState]:
        ...


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "event"):
            payload["event"] = record.event
        if hasattr(record, "data"):
            payload["data"] = record.data
        return json.dumps(payload, sort_keys=True)


def build_logger(name: str = "project_fifty.kernel") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


class RiskEngine:
    def evaluate(
        self,
        proposal: TradeProposal,
        portfolio: PortfolioState,
        kill_switch: KillSwitchState,
        mark_price: float,
    ) -> RiskDecision:
        if kill_switch.tripped and proposal.action not in {Action.HOLD, Action.CANCEL}:
            return RiskDecision(False, f"kill switch is active: {kill_switch.reason}")

        if proposal.action in {Action.HOLD, Action.CANCEL}:
            return RiskDecision(True, "no-op action approved")

        if mark_price <= 0:
            return RiskDecision(False, "invalid market price")

        if proposal.action in {Action.BUY, Action.ADD}:
            notional = proposal.quantity * mark_price
            if notional > portfolio.cash:
                return RiskDecision(False, "insufficient cash")
            return RiskDecision(True, "approved")

        if proposal.action in {Action.SELL, Action.REDUCE}:
            if portfolio.position_of(proposal.symbol) < proposal.quantity:
                return RiskDecision(False, "insufficient position")
            return RiskDecision(True, "approved")

        return RiskDecision(False, "unsupported action")


class SimulatedBroker:
    def __init__(self, market_prices: Mapping[str, float]):
        self._market_prices = dict(market_prices)

    def quote(self, symbol: str) -> float:
        price = self._market_prices.get(symbol)
        if price is None or price <= 0:
            raise ValueError(f"invalid or missing simulated market price for {symbol}")
        return float(price)

    def execute(
        self,
        intent: OrderIntent,
        portfolio: PortfolioState,
    ) -> Tuple[ExecutionReport, PortfolioState]:
        if intent.action in {Action.HOLD, Action.CANCEL}:
            status = ExecutionStatus.CANCELLED if intent.action == Action.CANCEL else ExecutionStatus.FILLED
            message = "cancelled" if intent.action == Action.CANCEL else "hold executed"
            report = ExecutionReport(
                intent_id=intent.intent_id,
                proposal_id=intent.proposal_id,
                symbol=intent.symbol,
                action=intent.action,
                status=status,
                filled_quantity=0,
                fill_price=None,
                message=message,
            )
            return report, portfolio

        fill_price = self.quote(intent.symbol)
        positions = dict(portfolio.positions)

        if intent.action in {Action.BUY, Action.ADD}:
            cash = portfolio.cash - (intent.quantity * fill_price)
            positions[intent.symbol] = positions.get(intent.symbol, 0) + intent.quantity
        elif intent.action in {Action.SELL, Action.REDUCE}:
            cash = portfolio.cash + (intent.quantity * fill_price)
            remaining = positions.get(intent.symbol, 0) - intent.quantity
            if remaining > 0:
                positions[intent.symbol] = remaining
            else:
                positions.pop(intent.symbol, None)
        else:
            raise ValueError(f"unsupported action for broker execution: {intent.action}")

        next_portfolio = PortfolioState(cash=float(cash), positions=positions)
        report = ExecutionReport(
            intent_id=intent.intent_id,
            proposal_id=intent.proposal_id,
            symbol=intent.symbol,
            action=intent.action,
            status=ExecutionStatus.FILLED,
            filled_quantity=intent.quantity,
            fill_price=fill_price,
            message="filled",
        )
        return report, next_portfolio


@dataclass(frozen=True)
class LedgerEntry:
    sequence: int
    event_type: str
    data: Mapping[str, object]
    recorded_at: str


class AppendOnlyLedger:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    @property
    def entries(self) -> Sequence[LedgerEntry]:
        return tuple(self._entries)

    def append(self, event_type: str, data: Mapping[str, object]) -> LedgerEntry:
        entry = LedgerEntry(
            sequence=len(self._entries) + 1,
            event_type=event_type,
            data=dict(data),
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self._entries.append(entry)
        return entry


class AutonomousTradingKernel:
    def __init__(
        self,
        risk_engine: RiskEngine,
        broker: Broker,
        ledger: AppendOnlyLedger,
        kill_switch: KillSwitchState | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._risk_engine = risk_engine
        self._broker = broker
        self._ledger = ledger
        self._kill_switch = kill_switch or KillSwitchState()
        self._logger = logger or build_logger()
        self._intent_seq = 0

    def set_kill_switch(self, state: KillSwitchState) -> None:
        self._kill_switch = state

    def process_proposal(
        self,
        proposal: TradeProposal,
        portfolio: PortfolioState,
    ) -> Tuple[ExecutionReport, PortfolioState]:
        self._ledger.append("trade_proposal", proposal.to_dict())
        self._logger.info(
            "received proposal",
            extra={"event": "trade_proposal", "data": proposal.to_dict()},
        )

        mark_price = 1.0
        if proposal.action not in {Action.HOLD, Action.CANCEL}:
            mark_price = self._broker.quote(proposal.symbol)

        decision = self._risk_engine.evaluate(proposal, portfolio, self._kill_switch, mark_price)
        if not decision.approved:
            report = ExecutionReport(
                intent_id=None,
                proposal_id=proposal.proposal_id,
                symbol=proposal.symbol,
                action=proposal.action,
                status=ExecutionStatus.REJECTED,
                filled_quantity=0,
                fill_price=None,
                message=decision.reason,
            )
            self._ledger.append("execution_report", asdict(report))
            self._logger.info(
                "proposal rejected",
                extra={"event": "execution_report", "data": asdict(report)},
            )
            return report, portfolio

        self._intent_seq += 1
        intent = OrderIntent(
            intent_id=f"intent-{self._intent_seq:08d}",
            proposal_id=proposal.proposal_id,
            symbol=proposal.symbol,
            action=proposal.action,
            quantity=proposal.quantity,
        )
        self._ledger.append("order_intent", asdict(intent))

        report, next_portfolio = self._broker.execute(intent, portfolio)
        self._ledger.append("execution_report", asdict(report))
        self._logger.info(
            "proposal executed",
            extra={"event": "execution_report", "data": asdict(report)},
        )
        return report, next_portfolio
