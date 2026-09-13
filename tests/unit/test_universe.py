from project_fifty.market_data.universe import AlpacaUniverseBuilder


class FakeAssets:
    def __init__(self) -> None:
        self.assets = {
            "SPY": {
                "status": "active",
                "class": "us_equity",
                "tradable": True,
                "fractionable": True,
            },
            "AAPL": {
                "status": "active",
                "class": "us_equity",
                "tradable": True,
                "fractionable": True,
            },
            "MSFT": {
                "status": "active",
                "class": "us_equity",
                "tradable": True,
                "fractionable": False,
            },
            "OLD": {
                "status": "inactive",
                "class": "us_equity",
                "tradable": False,
                "fractionable": True,
            },
        }

    def get_asset(self, symbol: str) -> dict[str, object]:
        return self.assets[symbol]


def test_universe_keeps_only_active_tradable_fractionable_candidates() -> None:
    universe = AlpacaUniverseBuilder(
        FakeAssets(),
        seed_symbols=("MSFT", "AAPL", "OLD"),
        benchmark_symbol="SPY",
    ).build()

    assert universe.symbols == ("AAPL",)
    assert universe.benchmark_symbol == "SPY"
    assert universe.all_symbols == ("AAPL", "SPY")
