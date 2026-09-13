from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

DEFAULT_SEED_SYMBOLS: tuple[str, ...] = (
    "AAPL",
    "AMZN",
    "GOOGL",
    "META",
    "MSFT",
    "NVDA",
    "QQQ",
    "TLT",
    "GLD",
    "XLU",
)
DEFAULT_BENCHMARK = "SPY"


class AssetLookup(Protocol):
    def get_asset(self, symbol: str) -> dict[str, object]: ...


class MarketUniverse(Protocol):
    """Minimal universe contract required by the autonomous session runner."""

    benchmark_symbol: str

    @property
    def all_symbols(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class SingleInstrumentUniverse:
    """A one-instrument universe for strategies such as M9's SPY/cash baseline."""

    benchmark_symbol: str = DEFAULT_BENCHMARK

    def __post_init__(self) -> None:
        normalized = self.benchmark_symbol.strip().upper()
        if not normalized:
            raise ValueError("benchmark symbol is required")
        object.__setattr__(self, "benchmark_symbol", normalized)

    @property
    def all_symbols(self) -> tuple[str, ...]:
        return (self.benchmark_symbol,)


@dataclass(frozen=True)
class CandidateUniverse:
    symbols: tuple[str, ...]
    benchmark_symbol: str

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("candidate universe must not be empty")
        if not self.benchmark_symbol:
            raise ValueError("benchmark symbol is required")
        if self.benchmark_symbol in self.symbols:
            raise ValueError("benchmark must not also be a candidate")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("candidate symbols must be unique")

    @property
    def all_symbols(self) -> tuple[str, ...]:
        return tuple(sorted((*self.symbols, self.benchmark_symbol)))


class AlpacaUniverseBuilder:
    """Validate a small liquid seed universe against Alpaca asset metadata.

    M4 intentionally does not scan thousands of securities. A bounded universe reduces data
    volume, false discoveries and overfitting while the strategy is still being validated.
    """

    def __init__(
        self,
        asset_lookup: AssetLookup,
        *,
        seed_symbols: tuple[str, ...] = DEFAULT_SEED_SYMBOLS,
        benchmark_symbol: str = DEFAULT_BENCHMARK,
    ) -> None:
        self._asset_lookup = asset_lookup
        self._seed_symbols = tuple(sorted({symbol.upper() for symbol in seed_symbols}))
        self._benchmark_symbol = benchmark_symbol.upper()
        if not self._seed_symbols:
            raise ValueError("seed_symbols must not be empty")

    def build(self) -> CandidateUniverse:
        benchmark = self._asset_lookup.get_asset(self._benchmark_symbol)
        if not self._valid_asset(benchmark, require_fractionable=False):
            raise RuntimeError("benchmark is not an active tradable US equity")

        accepted: list[str] = []
        for symbol in self._seed_symbols:
            if symbol == self._benchmark_symbol:
                continue
            asset = self._asset_lookup.get_asset(symbol)
            if self._valid_asset(asset, require_fractionable=True):
                accepted.append(symbol)

        if not accepted:
            raise RuntimeError("no seed symbols passed Alpaca tradable/fractionable checks")
        return CandidateUniverse(symbols=tuple(accepted), benchmark_symbol=self._benchmark_symbol)

    @staticmethod
    def _valid_asset(asset: dict[str, object], *, require_fractionable: bool) -> bool:
        if str(asset.get("status") or "").lower() != "active":
            return False
        if str(asset.get("class") or "").lower() != "us_equity":
            return False
        if not bool(asset.get("tradable")):
            return False
        if require_fractionable and not bool(asset.get("fractionable")):
            return False
        return True
