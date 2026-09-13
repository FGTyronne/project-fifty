from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from urllib.parse import quote

import httpx

from project_fifty.brokers.alpaca.config import AlpacaPaperConfig
from project_fifty.control.state import ControlState
from project_fifty.domain.models import (
    BrokerOrder,
    ExecutionReport,
    ExperimentMode,
    OrderIntent,
    OrderSide,
    OrderStatus,
    PortfolioState,
    Position,
)

JsonObject = dict[str, Any]


class AlpacaPaperBroker:
    """Paper-only Alpaca adapter behind Project Fifty's constitutional kernel."""

    def __init__(
        self,
        config: AlpacaPaperConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )
        client_base_url = str(self._client.base_url).rstrip("/")
        if client_base_url != config.base_url:
            if self._owns_client:
                self._client.close()
            raise ValueError("HTTP client must target the configured Alpaca paper endpoint")
        self._client.headers.update(
            {
                "APCA-API-KEY-ID": config.api_key.get_secret_value(),
                "APCA-API-SECRET-KEY": config.api_secret.get_secret_value(),
                "Accept": "application/json",
            }
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "AlpacaPaperBroker":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @staticmethod
    def client_order_id(idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
        return f"pf-{digest}"

    def health_check(self) -> bool:
        self.get_account()
        self.get_clock()
        return True

    def get_account(self) -> JsonObject:
        response = self._request("GET", "/v2/account")
        response.raise_for_status()
        return self._json_object(response)

    def get_clock(self) -> JsonObject:
        response = self._request("GET", "/v2/clock")
        response.raise_for_status()
        return self._json_object(response)

    def get_asset(self, symbol: str) -> JsonObject:
        response = self._request("GET", f"/v2/assets/{quote(symbol, safe='')}")
        response.raise_for_status()
        return self._json_object(response)

    def get_portfolio(self) -> PortfolioState:
        account = self.get_account()
        positions_raw = self._get_positions_raw()
        positions: dict[str, Position] = {}
        for raw in positions_raw:
            symbol = self._required_str(raw, "symbol")
            quantity = self._decimal(raw.get("qty"))
            if quantity < 0:
                raise ValueError("short broker position violates Project Fifty constitution")
            positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                average_price=self._decimal(raw.get("avg_entry_price")),
            )

        return PortfolioState(
            cash=self._decimal(account.get("cash")),
            positions=positions,
            nav=self._decimal(account.get("equity")),
            currency=self._config.currency,
        )

    def get_open_orders(self) -> list[BrokerOrder]:
        return [self._to_broker_order(order) for order in self._get_open_orders_raw()]

    def get_order_by_client_order_id(
        self,
        idempotency_key: str,
        *,
        reference_price: Decimal = Decimal("0"),
    ) -> ExecutionReport | None:
        client_order_id = self.client_order_id(idempotency_key)
        response = self._request(
            "GET",
            "/v2/orders:by_client_order_id",
            params={"client_order_id": client_order_id},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        order = self._json_object(response)
        return self._to_execution_report(
            order,
            idempotency_key=idempotency_key,
            reference_price=reference_price,
        )

    def submit(self, intent: OrderIntent) -> ExecutionReport:
        if intent.currency != self._config.currency:
            raise ValueError("order currency does not match Alpaca paper account currency")

        existing = self.get_order_by_client_order_id(
            intent.idempotency_key,
            reference_price=intent.reference_price,
        )
        if existing is not None:
            return existing

        asset = self.get_asset(intent.symbol)
        if not bool(asset.get("tradable")):
            raise ValueError(f"instrument is not tradable: {intent.symbol}")
        if self._is_fractional(intent.quantity) and not bool(asset.get("fractionable")):
            raise ValueError(f"instrument is not fractionable: {intent.symbol}")

        if intent.side == OrderSide.SELL:
            broker_quantity = self._get_position_quantity(intent.symbol)
            if broker_quantity < intent.quantity:
                raise ValueError("sell order would exceed broker position")

        payload: JsonObject = {
            "symbol": intent.symbol,
            "qty": self._format_decimal(intent.quantity),
            "side": intent.side.value.lower(),
            "type": "market",
            "time_in_force": "day",
            "client_order_id": self.client_order_id(intent.idempotency_key),
        }

        try:
            response = self._request("POST", "/v2/orders", json_body=payload)
        except httpx.TimeoutException:
            recovered = self.get_order_by_client_order_id(
                intent.idempotency_key,
                reference_price=intent.reference_price,
            )
            if recovered is not None:
                return recovered
            return self._unknown_report(intent, "ambiguous timeout; no blind resubmission")

        response.raise_for_status()
        return self._to_execution_report(
            self._json_object(response),
            idempotency_key=intent.idempotency_key,
            reference_price=intent.reference_price,
        )

    def cancel(self, broker_order_id: str) -> BrokerOrder:
        before = self._get_order_raw(broker_order_id)
        response = self._request("DELETE", f"/v2/orders/{quote(broker_order_id, safe='')}")
        if response.status_code not in {204, 422}:
            response.raise_for_status()

        after = self._get_order_raw(broker_order_id, allow_missing=True) or before
        broker_order = self._to_broker_order(after)
        if response.status_code == 422 and broker_order.status not in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        }:
            response.raise_for_status()
        return broker_order

    def guard_broker_state(
        self,
        control: ControlState,
        *,
        expected_position_symbols: set[str],
        expected_open_client_order_ids: set[str],
    ) -> bool:
        broker_position_symbols = {
            self._required_str(position, "symbol") for position in self._get_positions_raw()
        }
        broker_open_client_ids = {
            self._required_str(order, "client_order_id") for order in self._get_open_orders_raw()
        }
        consistent = (
            broker_position_symbols == expected_position_symbols
            and broker_open_client_ids == expected_open_client_order_ids
        )
        if consistent:
            return True
        if control.mode != ExperimentMode.DEAD:
            control.transition_mode(ExperimentMode.SAFE)
        return False

    def _get_positions_raw(self) -> list[JsonObject]:
        response = self._request("GET", "/v2/positions")
        response.raise_for_status()
        return self._json_object_list(response)

    def _get_position_quantity(self, symbol: str) -> Decimal:
        response = self._request("GET", f"/v2/positions/{quote(symbol, safe='')}")
        if response.status_code == 404:
            return Decimal("0")
        response.raise_for_status()
        return self._decimal(self._json_object(response).get("qty"))

    def _get_open_orders_raw(self) -> list[JsonObject]:
        response = self._request("GET", "/v2/orders", params={"status": "open"})
        response.raise_for_status()
        return self._json_object_list(response)

    def _get_order_raw(
        self,
        broker_order_id: str,
        *,
        allow_missing: bool = False,
    ) -> JsonObject | None:
        response = self._request("GET", f"/v2/orders/{quote(broker_order_id, safe='')}")
        if allow_missing and response.status_code == 404:
            return None
        response.raise_for_status()
        return self._json_object(response)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: JsonObject | None = None,
    ) -> httpx.Response:
        response = self._client.request(method, path, params=params, json=json_body)
        self._record_request_id(method=method, path=path, response=response)
        return response

    def _record_request_id(self, *, method: str, path: str, response: httpx.Response) -> None:
        log_path = self._config.request_log_path
        if log_path is None:
            return
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "request_id": response.headers.get("X-Request-ID"),
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _to_broker_order(self, order: JsonObject) -> BrokerOrder:
        order_id = self._required_str(order, "id")
        client_order_id = str(order.get("client_order_id") or order_id)
        quantity = self._decimal(order.get("qty") or order.get("filled_qty") or "0")
        return BrokerOrder(
            broker_order_id=order_id,
            idempotency_key=client_order_id,
            symbol=self._required_str(order, "symbol"),
            side=self._parse_side(order.get("side")),
            quantity=quantity,
            status=self._map_status(order.get("status")),
        )

    def _to_execution_report(
        self,
        order: JsonObject,
        *,
        idempotency_key: str,
        reference_price: Decimal,
    ) -> ExecutionReport:
        broker_order_id = self._required_str(order, "id")
        status = self._map_status(order.get("status"))
        fill_quantity = self._decimal(order.get("filled_qty") or "0")
        fill_price_raw = order.get("filled_avg_price")
        fill_price = (
            self._decimal(fill_price_raw)
            if fill_price_raw not in {None, ""}
            else reference_price
        )
        slippage = Decimal("0")
        if fill_quantity > 0 and reference_price > 0:
            slippage = abs(fill_price - reference_price) * fill_quantity
        report_id = ":".join(
            ["alpaca", broker_order_id, status.value, self._format_decimal(fill_quantity)]
        )
        return ExecutionReport(
            report_id=report_id,
            broker_order_id=broker_order_id,
            idempotency_key=idempotency_key,
            symbol=self._required_str(order, "symbol"),
            side=self._parse_side(order.get("side")),
            status=status,
            fill_quantity=fill_quantity,
            fill_price=fill_price,
            fee=Decimal("0"),
            slippage=slippage,
            currency=self._config.currency,
            message=f"client_order_id={order.get('client_order_id', '')}",
        )

    def _unknown_report(self, intent: OrderIntent, message: str) -> ExecutionReport:
        client_order_id = self.client_order_id(intent.idempotency_key)
        return ExecutionReport(
            report_id=f"alpaca-unknown-{client_order_id}",
            broker_order_id=f"unknown:{client_order_id}",
            idempotency_key=intent.idempotency_key,
            symbol=intent.symbol,
            side=intent.side,
            status=OrderStatus.UNKNOWN,
            fill_quantity=Decimal("0"),
            fill_price=intent.reference_price,
            fee=Decimal("0"),
            slippage=Decimal("0"),
            currency=self._config.currency,
            message=message,
        )

    @staticmethod
    def _map_status(value: object) -> OrderStatus:
        status = str(value or "").lower()
        if status in {"accepted", "new", "pending_new", "accepted_for_bidding", "pending_replace"}:
            return OrderStatus.ACKNOWLEDGED
        if status == "partially_filled":
            return OrderStatus.PARTIALLY_FILLED
        if status == "filled":
            return OrderStatus.FILLED
        if status == "pending_cancel":
            return OrderStatus.CANCEL_PENDING
        if status in {"canceled", "cancelled", "expired", "replaced", "done_for_day"}:
            return OrderStatus.CANCELLED
        if status in {"rejected", "suspended"}:
            return OrderStatus.REJECTED
        return OrderStatus.UNKNOWN

    @staticmethod
    def _parse_side(value: object) -> OrderSide:
        normalized = str(value or "").upper()
        try:
            return OrderSide(normalized)
        except ValueError as exc:
            raise ValueError(f"unexpected Alpaca order side: {value!r}") from exc

    @staticmethod
    def _is_fractional(quantity: Decimal) -> bool:
        return quantity != quantity.to_integral_value()

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        return format(value, "f")

    @staticmethod
    def _decimal(value: object) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid decimal value from Alpaca: {value!r}") from exc
        if not parsed.is_finite():
            raise ValueError("non-finite decimal value from Alpaca")
        return parsed

    @staticmethod
    def _required_str(data: JsonObject, key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"missing or invalid Alpaca field: {key}")
        return value

    @staticmethod
    def _json_object(response: httpx.Response) -> JsonObject:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("expected Alpaca JSON object")
        return cast(JsonObject, data)

    @staticmethod
    def _json_object_list(response: httpx.Response) -> list[JsonObject]:
        data = response.json()
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise ValueError("expected Alpaca JSON object list")
        return cast(list[JsonObject], data)
