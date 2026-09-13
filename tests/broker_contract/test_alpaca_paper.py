from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from project_fifty.brokers.alpaca.broker import AlpacaPaperBroker
from project_fifty.brokers.alpaca.config import PAPER_BASE_URL, AlpacaPaperConfig
from project_fifty.config.settings import Settings
from project_fifty.control.state import ControlState
from project_fifty.domain.models import (
    ExperimentMode,
    OrderIntent,
    OrderSide,
    OrderStatus,
    RejectionReason,
    TradeAction,
)
from project_fifty.execution.kernel import ExecutionKernel
from project_fifty.ledger.local import LocalAppendOnlyLedger
from project_fifty.risk.engine import RiskEngine
from tests.conftest import make_proposal


def _config(tmp_path: Path | None = None) -> AlpacaPaperConfig:
    return AlpacaPaperConfig(
        api_key=SecretStr("paper-key"),
        api_secret=SecretStr("paper-secret"),
        request_log_path=(tmp_path / "requests.jsonl") if tmp_path else None,
    )


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(base_url=PAPER_BASE_URL, transport=httpx.MockTransport(handler))


def _asset(symbol: str = "AAPL", *, fractionable: bool = True) -> dict[str, object]:
    return {
        "id": "asset-1",
        "symbol": symbol,
        "tradable": True,
        "fractionable": fractionable,
    }


def _order(
    *,
    order_id: str = "order-1",
    client_order_id: str,
    symbol: str = "AAPL",
    side: str = "buy",
    status: str = "filled",
    qty: str = "0.25",
    filled_qty: str = "0.25",
    filled_avg_price: str | None = "20.10",
) -> dict[str, object]:
    return {
        "id": order_id,
        "client_order_id": client_order_id,
        "symbol": symbol,
        "side": side,
        "status": status,
        "qty": qty,
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price,
    }


def test_live_endpoint_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AlpacaPaperConfig(
            api_key=SecretStr("key"),
            api_secret=SecretStr("secret"),
            base_url="https://api.alpaca.markets",
        )


def test_health_check_uses_paper_headers_and_logs_request_ids(tmp_path: Path) -> None:
    seen_headers: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(
            (
                request.headers["APCA-API-KEY-ID"],
                request.headers["APCA-API-SECRET-KEY"],
            )
        )
        if request.url.path == "/v2/account":
            return httpx.Response(
                200,
                json={"cash": "100000", "equity": "100000", "buying_power": "400000"},
                headers={"X-Request-ID": "req-account"},
            )
        if request.url.path == "/v2/clock":
            return httpx.Response(
                200,
                json={"is_open": False, "timestamp": "2026-09-13T10:00:00Z"},
                headers={"X-Request-ID": "req-clock"},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _client(handler)
    broker = AlpacaPaperBroker(_config(tmp_path), client=client)
    assert broker.health_check() is True
    assert seen_headers == [("paper-key", "paper-secret"), ("paper-key", "paper-secret")]

    records = [json.loads(line) for line in (tmp_path / "requests.jsonl").read_text().splitlines()]
    assert [record["request_id"] for record in records] == ["req-account", "req-clock"]
    client.close()


def test_fractional_buy_uses_exact_qty_only() -> None:
    submitted: list[dict[str, object]] = []
    intent = OrderIntent.create(
        idempotency_key="logical-order-1",
        proposal_id="proposal-1",
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=Decimal("0.25"),
        reference_price=Decimal("20"),
        currency="USD",
    )
    client_order_id = AlpacaPaperBroker.client_order_id(intent.idempotency_key)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/orders:by_client_order_id":
            return httpx.Response(404, json={"message": "order not found"})
        if request.url.path == "/v2/assets/AAPL":
            return httpx.Response(200, json=_asset())
        if request.method == "POST" and request.url.path == "/v2/orders":
            payload = json.loads(request.content.decode("utf-8"))
            submitted.append(payload)
            return httpx.Response(200, json=_order(client_order_id=client_order_id))
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _client(handler)
    broker = AlpacaPaperBroker(_config(), client=client)
    report = broker.submit(intent)

    assert report.status == OrderStatus.FILLED
    assert report.fill_quantity == Decimal("0.25")
    assert len(submitted) == 1
    assert submitted[0]["qty"] == "0.25"
    assert "notional" not in submitted[0]
    assert submitted[0]["type"] == "market"
    assert submitted[0]["time_in_force"] == "day"
    assert submitted[0]["client_order_id"] == client_order_id
    client.close()


def test_fractional_order_rejected_for_non_fractionable_asset() -> None:
    post_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        if request.url.path == "/v2/orders:by_client_order_id":
            return httpx.Response(404, json={"message": "order not found"})
        if request.url.path == "/v2/assets/AAPL":
            return httpx.Response(200, json=_asset(fractionable=False))
        if request.method == "POST":
            post_calls += 1
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _client(handler)
    broker = AlpacaPaperBroker(_config(), client=client)
    intent = OrderIntent.create(
        idempotency_key="fractional-block",
        proposal_id="proposal",
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=Decimal("0.25"),
        reference_price=Decimal("20"),
        currency="USD",
    )
    with pytest.raises(ValueError, match="not fractionable"):
        broker.submit(intent)
    assert post_calls == 0
    client.close()


def test_existing_client_order_id_prevents_duplicate_submission() -> None:
    post_calls = 0
    intent = OrderIntent.create(
        idempotency_key="restart-safe-order",
        proposal_id="proposal",
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=Decimal("0.25"),
        reference_price=Decimal("20"),
        currency="USD",
    )
    client_order_id = AlpacaPaperBroker.client_order_id(intent.idempotency_key)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        if request.url.path == "/v2/orders:by_client_order_id":
            return httpx.Response(200, json=_order(client_order_id=client_order_id))
        if request.method == "POST":
            post_calls += 1
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _client(handler)
    broker = AlpacaPaperBroker(_config(), client=client)
    report = broker.submit(intent)
    assert report.status == OrderStatus.FILLED
    assert post_calls == 0
    client.close()


def test_ambiguous_timeout_queries_broker_before_any_resubmission() -> None:
    lookup_calls = 0
    post_calls = 0
    intent = OrderIntent.create(
        idempotency_key="timeout-order",
        proposal_id="proposal",
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=Decimal("0.25"),
        reference_price=Decimal("20"),
        currency="USD",
    )
    client_order_id = AlpacaPaperBroker.client_order_id(intent.idempotency_key)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal lookup_calls, post_calls
        if request.url.path == "/v2/orders:by_client_order_id":
            lookup_calls += 1
            if lookup_calls == 1:
                return httpx.Response(404, json={"message": "order not found"})
            return httpx.Response(200, json=_order(client_order_id=client_order_id))
        if request.url.path == "/v2/assets/AAPL":
            return httpx.Response(200, json=_asset())
        if request.method == "POST" and request.url.path == "/v2/orders":
            post_calls += 1
            raise httpx.ReadTimeout("ambiguous timeout", request=request)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _client(handler)
    broker = AlpacaPaperBroker(_config(), client=client)
    report = broker.submit(intent)
    assert report.status == OrderStatus.FILLED
    assert lookup_calls == 2
    assert post_calls == 1
    client.close()


def test_cancel_fetches_final_broker_state() -> None:
    get_calls = 0
    client_order_id = AlpacaPaperBroker.client_order_id("cancel-me")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_calls
        if request.method == "GET" and request.url.path == "/v2/orders/order-1":
            get_calls += 1
            status = "new" if get_calls == 1 else "canceled"
            return httpx.Response(
                200,
                json=_order(
                    client_order_id=client_order_id,
                    status=status,
                    filled_qty="0",
                    filled_avg_price=None,
                ),
            )
        if request.method == "DELETE" and request.url.path == "/v2/orders/order-1":
            return httpx.Response(204)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _client(handler)
    broker = AlpacaPaperBroker(_config(), client=client)
    cancelled = broker.cancel("order-1")
    assert cancelled.status == OrderStatus.CANCELLED
    assert get_calls == 2
    client.close()


def test_large_broker_buying_power_does_not_expand_internal_authority(
    settings: Settings,
) -> None:
    post_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        if request.url.path == "/v2/account":
            return httpx.Response(
                200,
                json={"cash": "100000", "equity": "100000", "buying_power": "400000"},
            )
        if request.url.path == "/v2/positions":
            return httpx.Response(200, json=[])
        if request.method == "POST":
            post_calls += 1
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _client(handler)
    broker = AlpacaPaperBroker(_config(), client=client)
    assert broker.get_portfolio().cash == Decimal("100000")

    project_settings = settings.model_copy(
        update={
            "authorized_starting_cash": Decimal("50"),
            "max_order_notional": Decimal("1000"),
        }
    )
    kernel = ExecutionKernel(
        settings=project_settings,
        risk_engine=RiskEngine(project_settings),
        broker=broker,
        ledger=LocalAppendOnlyLedger(),
        control=ControlState(),
    )
    proposal = make_proposal(
        proposal_id="too-large",
        key="too-large",
        action=TradeAction.BUY,
        qty=Decimal("6"),
        price=Decimal("10"),
        notional=Decimal("60"),
    )
    decision, report = kernel.handle_proposal(proposal)
    assert decision.approved is False
    assert decision.reason == RejectionReason.INSUFFICIENT_CASH
    assert report is None
    assert post_calls == 0
    client.close()


def test_unexpected_broker_state_forces_safe_mode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/positions":
            return httpx.Response(
                200,
                json=[{"symbol": "AAPL", "qty": "1", "avg_entry_price": "20"}],
            )
        if request.url.path == "/v2/orders":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _client(handler)
    broker = AlpacaPaperBroker(_config(), client=client)
    control = ControlState()
    consistent = broker.guard_broker_state(
        control,
        expected_position_symbols=set(),
        expected_open_client_order_ids=set(),
    )
    assert consistent is False
    assert control.mode == ExperimentMode.SAFE
    client.close()
