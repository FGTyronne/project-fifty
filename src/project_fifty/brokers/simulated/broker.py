from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from project_fifty.domain.models import (
    BrokerOrder,
    ExecutionReport,
    OrderIntent,
    OrderSide,
    OrderStatus,
    PortfolioState,
    Position,
)


class SimulatedBroker:
    def __init__(
        self,
        *,
        starting_cash: Decimal,
        currency: str = "USD",
        fee_rate: Decimal = Decimal("0.001"),
        slippage_rate: Decimal = Decimal("0.001"),
        fail_with_unknown: bool = False,
        reported_buying_power: Decimal | None = None,
    ) -> None:
        self._cash = starting_cash
        self._currency = currency
        self._positions: dict[str, Position] = {}
        self._orders_by_key: dict[str, ExecutionReport] = {}
        self._broker_orders: dict[str, BrokerOrder] = {}
        self._last_price: dict[str, Decimal] = {"TEST": Decimal("1")}
        self._fee_rate = fee_rate
        self._slippage_rate = slippage_rate
        self._fail_with_unknown = fail_with_unknown
        self._reported_buying_power = reported_buying_power or (starting_cash * Decimal("4"))

    @property
    def reported_buying_power(self) -> Decimal:
        return self._reported_buying_power

    def set_mark_price(self, symbol: str, price: Decimal) -> None:
        self._last_price[symbol] = price

    def get_portfolio(self) -> PortfolioState:
        nav = self._cash
        for symbol, position in self._positions.items():
            nav += position.quantity * self._last_price.get(symbol, position.average_price)
        return PortfolioState(
            cash=self._cash,
            positions=self._positions,
            nav=nav,
            currency=self._currency,
        )

    def get_open_orders(self) -> list[BrokerOrder]:
        terminal = {OrderStatus.FILLED, OrderStatus.CANCELLED}
        return [o for o in self._broker_orders.values() if o.status not in terminal]

    def cancel(self, broker_order_id: str) -> BrokerOrder:
        order = self._broker_orders[broker_order_id]
        if order.status in {OrderStatus.FILLED, OrderStatus.CANCELLED}:
            return order
        cancelled = order.model_copy(update={"status": OrderStatus.CANCELLED})
        self._broker_orders[broker_order_id] = cancelled
        return cancelled

    def submit(self, intent: OrderIntent) -> ExecutionReport:
        if intent.idempotency_key in self._orders_by_key:
            return self._orders_by_key[intent.idempotency_key]

        if self._fail_with_unknown:
            broker_order = BrokerOrder(
                broker_order_id=str(uuid4()),
                idempotency_key=intent.idempotency_key,
                symbol=intent.symbol,
                side=intent.side,
                quantity=intent.quantity,
                status=OrderStatus.UNKNOWN,
            )
            self._broker_orders[broker_order.broker_order_id] = broker_order
            report = ExecutionReport(
                report_id=str(uuid4()),
                broker_order_id=broker_order.broker_order_id,
                idempotency_key=intent.idempotency_key,
                symbol=intent.symbol,
                side=intent.side,
                status=OrderStatus.UNKNOWN,
                fill_quantity=Decimal("0"),
                fill_price=intent.reference_price,
                fee=Decimal("0"),
                slippage=Decimal("0"),
                currency=self._currency,
                message="ambiguous submission",
            )
            self._orders_by_key[intent.idempotency_key] = report
            return report

        slippage_multiplier = Decimal("1") + self._slippage_rate
        if intent.side == OrderSide.SELL:
            slippage_multiplier = Decimal("1") - self._slippage_rate

        fill_price = intent.reference_price * slippage_multiplier
        notional = fill_price * intent.quantity
        fee = notional * self._fee_rate
        slippage = abs(fill_price - intent.reference_price) * intent.quantity

        position = self._positions.get(intent.symbol)
        if intent.side == OrderSide.BUY:
            total_cost = notional + fee
            if total_cost > self._cash:
                raise ValueError("insufficient cash")
            self._cash -= total_cost
            if position is None:
                self._positions[intent.symbol] = Position(
                    symbol=intent.symbol,
                    quantity=intent.quantity,
                    average_price=fill_price,
                )
            else:
                new_qty = position.quantity + intent.quantity
                avg_price = (
                    (position.quantity * position.average_price)
                    + (intent.quantity * fill_price)
                ) / new_qty
                self._positions[intent.symbol] = Position(
                    symbol=intent.symbol,
                    quantity=new_qty,
                    average_price=avg_price,
                )
        else:
            if position is None or intent.quantity > position.quantity:
                raise ValueError("short selling forbidden")
            proceeds = notional - fee
            self._cash += proceeds
            remainder = position.quantity - intent.quantity
            if remainder == 0:
                del self._positions[intent.symbol]
            else:
                self._positions[intent.symbol] = Position(
                    symbol=intent.symbol,
                    quantity=remainder,
                    average_price=position.average_price,
                )

        broker_order = BrokerOrder(
            broker_order_id=str(uuid4()),
            idempotency_key=intent.idempotency_key,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            status=OrderStatus.FILLED,
        )
        self._broker_orders[broker_order.broker_order_id] = broker_order

        report = ExecutionReport(
            report_id=str(uuid4()),
            broker_order_id=broker_order.broker_order_id,
            idempotency_key=intent.idempotency_key,
            symbol=intent.symbol,
            side=intent.side,
            status=OrderStatus.FILLED,
            fill_quantity=intent.quantity,
            fill_price=fill_price,
            fee=fee,
            slippage=slippage,
            currency=self._currency,
        )
        self._orders_by_key[intent.idempotency_key] = report
        self._last_price[intent.symbol] = fill_price
        return report
