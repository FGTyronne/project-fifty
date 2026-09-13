from __future__ import annotations

from decimal import Decimal

from project_fifty.domain.models import (
    ExecutionReport,
    OrderSide,
    OrderStatus,
    PortfolioState,
    Position,
)


class PortfolioReconciler:
    @staticmethod
    def reconcile_from_broker(portfolio: PortfolioState) -> PortfolioState:
        return portfolio

    @staticmethod
    def replay_events(
        *,
        starting_cash: Decimal,
        events: list[ExecutionReport],
        mark_prices: dict[str, Decimal],
        currency: str,
    ) -> PortfolioState:
        cash = starting_cash
        positions: dict[str, Position] = {}
        seen_reports: set[str] = set()
        applied_quantity: dict[str, Decimal] = {}
        applied_gross: dict[str, Decimal] = {}
        applied_fee: dict[str, Decimal] = {}

        for report in events:
            if report.report_id in seen_reports:
                continue
            seen_reports.add(report.report_id)
            if report.currency != currency:
                raise ValueError("execution report currency does not match portfolio currency")
            if report.status not in {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED}:
                continue

            order_id = report.broker_order_id
            previous_quantity = applied_quantity.get(order_id, Decimal("0"))
            previous_gross = applied_gross.get(order_id, Decimal("0"))
            previous_fee = applied_fee.get(order_id, Decimal("0"))
            cumulative_quantity = report.fill_quantity
            cumulative_gross = cumulative_quantity * report.fill_price
            cumulative_fee = report.fee

            if cumulative_quantity < previous_quantity:
                raise ValueError("broker cumulative fill quantity regressed")
            if cumulative_gross < previous_gross:
                raise ValueError("broker cumulative fill notional regressed")
            if cumulative_fee < previous_fee:
                raise ValueError("broker cumulative fee regressed")

            delta_quantity = cumulative_quantity - previous_quantity
            delta_gross = cumulative_gross - previous_gross
            delta_fee = cumulative_fee - previous_fee

            applied_quantity[order_id] = cumulative_quantity
            applied_gross[order_id] = cumulative_gross
            applied_fee[order_id] = cumulative_fee

            if report.side == OrderSide.BUY:
                cash -= delta_gross + delta_fee
                if delta_quantity > 0:
                    delta_price = delta_gross / delta_quantity
                    current = positions.get(report.symbol)
                    if current is None:
                        positions[report.symbol] = Position(
                            symbol=report.symbol,
                            quantity=delta_quantity,
                            average_price=delta_price,
                        )
                    else:
                        new_qty = current.quantity + delta_quantity
                        avg = (
                            (current.quantity * current.average_price) + delta_gross
                        ) / new_qty
                        positions[report.symbol] = Position(
                            symbol=report.symbol,
                            quantity=new_qty,
                            average_price=avg,
                        )
            else:
                cash += delta_gross - delta_fee
                if delta_quantity > 0:
                    current = positions.get(report.symbol)
                    if current is None or delta_quantity > current.quantity:
                        raise ValueError("event replay would create short position")
                    left = current.quantity - delta_quantity
                    if left == 0:
                        del positions[report.symbol]
                    else:
                        positions[report.symbol] = Position(
                            symbol=report.symbol,
                            quantity=left,
                            average_price=current.average_price,
                        )

        nav = cash
        for symbol, position in positions.items():
            nav += position.quantity * mark_prices[symbol]

        return PortfolioState(cash=cash, positions=positions, nav=nav, currency=currency)
