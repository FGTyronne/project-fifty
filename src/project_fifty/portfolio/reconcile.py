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

        for report in events:
            if report.report_id in seen_reports:
                continue
            seen_reports.add(report.report_id)
            if report.status != OrderStatus.FILLED:
                continue
            notional = report.fill_quantity * report.fill_price
            if report.side == OrderSide.BUY:
                cash -= notional + report.fee
                current = positions.get(report.symbol)
                if current is None:
                    positions[report.symbol] = Position(
                        symbol=report.symbol,
                        quantity=report.fill_quantity,
                        average_price=report.fill_price,
                    )
                else:
                    new_qty = current.quantity + report.fill_quantity
                    avg = (
                        (current.quantity * current.average_price)
                        + (report.fill_quantity * report.fill_price)
                    ) / new_qty
                    positions[report.symbol] = Position(
                        symbol=report.symbol,
                        quantity=new_qty,
                        average_price=avg,
                    )
            else:
                current = positions.get(report.symbol)
                if current is None or report.fill_quantity > current.quantity:
                    raise ValueError("event replay would create short position")
                cash += notional - report.fee
                left = current.quantity - report.fill_quantity
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
