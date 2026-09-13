from decimal import Decimal

from project_fifty.config.settings import Settings


def test_settings_from_env_loads_frozen_paper_authority_and_symbols(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PROJECT_FIFTY_STARTING_CASH_GBP", "50.00")
    monkeypatch.setenv("PROJECT_FIFTY_ACCOUNT_CURRENCY", "USD")
    monkeypatch.setenv("PROJECT_FIFTY_AUTHORIZED_STARTING_CASH", "67.6725")
    monkeypatch.setenv("PROJECT_FIFTY_MAX_ORDER_NOTIONAL", "67.6725")
    monkeypatch.setenv("PROJECT_FIFTY_MAX_STALE_SECONDS", "60")
    monkeypatch.setenv("PROJECT_FIFTY_PERMITTED_SYMBOLS", "aapl, MSFT,nvda")

    settings = Settings.from_env()

    assert settings.inception_contribution_gbp == Decimal("50.00")
    assert settings.authorized_starting_cash == Decimal("67.6725")
    assert settings.max_order_notional == Decimal("67.6725")
    assert settings.max_stale_seconds == 60
    assert settings.permitted_symbols == frozenset({"AAPL", "MSFT", "NVDA"})
