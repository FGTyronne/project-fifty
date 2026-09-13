from datetime import UTC, datetime
from decimal import Decimal

from project_fifty.market_data.alpaca import MarketQuote


def test_two_sided_non_crossed_quote_is_actionable() -> None:
    quote = MarketQuote(
        symbol="AAPL",
        bid=Decimal("100"),
        ask=Decimal("100.10"),
        timestamp=datetime(2026, 9, 14, 15, 0, tzinfo=UTC),
    )

    assert quote.is_actionable is True
    assert quote.midpoint == Decimal("100.05")


def test_one_sided_closed_market_quote_is_observable_but_not_actionable() -> None:
    quote = MarketQuote(
        symbol="AAPL",
        bid=Decimal("100"),
        ask=Decimal("0"),
        timestamp=datetime(2026, 9, 11, 20, 0, tzinfo=UTC),
    )

    assert quote.is_actionable is False
    assert quote.midpoint == Decimal("100")


def test_crossed_quote_is_never_actionable() -> None:
    quote = MarketQuote(
        symbol="AAPL",
        bid=Decimal("101"),
        ask=Decimal("100"),
        timestamp=datetime(2026, 9, 14, 15, 0, tzinfo=UTC),
    )

    assert quote.is_actionable is False
