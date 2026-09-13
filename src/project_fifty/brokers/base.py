from __future__ import annotations

from typing import Protocol

from project_fifty.domain.models import BrokerOrder, ExecutionReport, OrderIntent, PortfolioState


class BrokerAdapter(Protocol):
    def get_portfolio(self) -> PortfolioState: ...

    def get_open_orders(self) -> list[BrokerOrder]: ...

    def submit(self, intent: OrderIntent) -> ExecutionReport: ...

    def cancel(self, broker_order_id: str) -> BrokerOrder: ...
