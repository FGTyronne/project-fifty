from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable

from project_fifty.domain.models import PortfolioState, Position
from project_fifty.market_data.state import market_state_hash
from project_fifty.strategies.contracts import MarketBar, StrategyContext, StrategyProvider
from project_fifty.strategies.rebalance import EconomicRebalancePolicy, RebalancePlan

_ZERO = Decimal("0")
_ONE = Decimal("1")
_CASH_EPSILON = Decimal("1e-12")


@dataclass(frozen=True)
class BacktestConfig:
    starting_cash: Decimal = Decimal("67.6725")
    currency: str = "USD"
    warmup_bars: int = 60
    fee_rate: Decimal = Decimal("0")
    slippage_rate: Decimal = Decimal("0.001")

    def __post_init__(self) -> None:
        if not self.starting_cash.is_finite() or self.starting_cash <= 0:
            raise ValueError("starting_cash must be finite and positive")
        if self.warmup_bars < 2:
            raise ValueError("warmup_bars must be >= 2")
        for value in (self.fee_rate, self.slippage_rate):
            if not value.is_finite() or value < 0 or value >= 1:
                raise ValueError("cost rates must be finite and in [0, 1)")


@dataclass(frozen=True)
class BacktestPoint:
    decision_time: datetime
    execution_time: datetime
    nav: Decimal
    cash: Decimal
    turnover: Decimal
    costs: Decimal
    positions: dict[str, Decimal]


@dataclass(frozen=True)
class BacktestResult:
    starting_nav: Decimal
    ending_nav: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    total_costs: Decimal
    trade_count: int
    points: tuple[BacktestPoint, ...]
    total_turnover: Decimal = _ZERO
    average_cash_weight: Decimal = _ZERO


@dataclass(frozen=True)
class WalkForwardConfig:
    train_bars: int = 120
    test_bars: int = 20
    step_bars: int = 20

    def __post_init__(self) -> None:
        if min(self.train_bars, self.test_bars, self.step_bars) <= 0:
            raise ValueError("walk-forward window sizes must be positive")


@dataclass(frozen=True)
class WalkForwardWindow:
    test_start: datetime
    test_end: datetime
    result: BacktestResult


class BacktestEngine:
    """Next-bar-open replay with fractional positions and explicit costs.

    Strategy decisions see bars only through `decision_time`. When an economic rebalance policy is
    supplied it is evaluated at the decision timestamp, then only approved rebalance instructions
    may execute at the next bar open. This preserves no-lookahead behaviour while sharing the same
    trade/no-trade rules with the future autonomous session.
    """

    def __init__(
        self,
        strategy: StrategyProvider,
        config: BacktestConfig | None = None,
        rebalance_policy: EconomicRebalancePolicy | None = None,
    ) -> None:
        self._strategy = strategy
        self._config = config or BacktestConfig()
        self._rebalance_policy = rebalance_policy

    def run(
        self,
        *,
        history: dict[str, tuple[MarketBar, ...]],
        benchmark_symbol: str,
        evaluation_start: datetime | None = None,
    ) -> BacktestResult:
        benchmark = history.get(benchmark_symbol, ())
        if len(benchmark) < self._config.warmup_bars + 1:
            raise ValueError("insufficient benchmark history for backtest")
        self._validate_history(history)

        cash = self._config.starting_cash
        positions: dict[str, Position] = {}
        points: list[BacktestPoint] = []
        total_costs = _ZERO
        total_turnover = _ZERO
        cash_weight_sum = _ZERO
        trade_count = 0
        peak_nav = self._config.starting_cash
        max_drawdown = _ZERO

        for index in range(self._config.warmup_bars - 1, len(benchmark) - 1):
            decision_time = benchmark[index].timestamp
            execution_time = benchmark[index + 1].timestamp
            if evaluation_start is not None and decision_time < evaluation_start:
                continue

            decision_history = {
                symbol: tuple(bar for bar in bars if bar.timestamp <= decision_time)
                for symbol, bars in history.items()
            }
            latest_decision_bars = {
                symbol: bars[-1]
                for symbol, bars in decision_history.items()
                if bars
            }
            if benchmark_symbol not in latest_decision_bars:
                continue

            decision_prices = {
                symbol: bar.close for symbol, bar in latest_decision_bars.items()
            }
            marked = self._portfolio_state(
                cash=cash,
                positions=positions,
                prices=decision_prices,
                as_of=decision_time,
            )
            state_hash = market_state_hash(history=decision_history)
            context = StrategyContext(
                as_of=decision_time,
                currency=self._config.currency,
                portfolio=marked,
                reference_prices=decision_prices,
                reference_price_timestamps={
                    symbol: bar.timestamp for symbol, bar in latest_decision_bars.items()
                },
                market_state_hash=state_hash,
                history=decision_history,
                benchmark_symbol=benchmark_symbol,
            )
            target = self._strategy.generate_target(context)
            plan = (
                self._rebalance_policy.plan(target=target, context=context)
                if self._rebalance_policy is not None
                else None
            )

            execution_bars: dict[str, MarketBar] = {}
            for symbol, bars in history.items():
                bar = self._bar_at(bars, execution_time)
                if bar is not None:
                    execution_bars[symbol] = bar
            if benchmark_symbol not in execution_bars:
                continue

            open_prices = {symbol: bar.open for symbol, bar in execution_bars.items()}
            pre_rebalance = self._portfolio_state(
                cash=cash,
                positions=positions,
                prices=open_prices,
                as_of=execution_time,
            )
            cash, positions, turnover, costs, trades = self._rebalance(
                cash=cash,
                positions=positions,
                nav=pre_rebalance.nav,
                target_weights=target.weights,
                prices=open_prices,
                plan=plan,
            )
            total_costs += costs
            total_turnover += turnover
            trade_count += trades

            close_prices = {symbol: bar.close for symbol, bar in execution_bars.items()}
            end_state = self._portfolio_state(
                cash=cash,
                positions=positions,
                prices=close_prices,
                as_of=execution_time,
            )
            peak_nav = max(peak_nav, end_state.nav)
            if peak_nav > 0:
                drawdown = end_state.nav / peak_nav - _ONE
                max_drawdown = min(max_drawdown, drawdown)
            if end_state.nav > _ZERO:
                cash_weight_sum += end_state.cash / end_state.nav
            points.append(
                BacktestPoint(
                    decision_time=decision_time,
                    execution_time=execution_time,
                    nav=end_state.nav,
                    cash=end_state.cash,
                    turnover=turnover,
                    costs=costs,
                    positions={
                        symbol: position.quantity
                        for symbol, position in end_state.positions.items()
                    },
                )
            )

        ending_nav = points[-1].nav if points else self._config.starting_cash
        average_cash_weight = (
            cash_weight_sum / Decimal(len(points)) if points else _ONE
        )
        return BacktestResult(
            starting_nav=self._config.starting_cash,
            ending_nav=ending_nav,
            total_return=ending_nav / self._config.starting_cash - _ONE,
            max_drawdown=max_drawdown,
            total_costs=total_costs,
            trade_count=trade_count,
            points=tuple(points),
            total_turnover=total_turnover,
            average_cash_weight=average_cash_weight,
        )

    def _rebalance(
        self,
        *,
        cash: Decimal,
        positions: dict[str, Position],
        nav: Decimal,
        target_weights: dict[str, Decimal],
        prices: dict[str, Decimal],
        plan: RebalancePlan | None,
    ) -> tuple[Decimal, dict[str, Position], Decimal, Decimal, int]:
        updated = dict(positions)
        turnover = _ZERO
        costs = _ZERO
        trades = 0
        symbols = sorted(set(updated) | set(target_weights))

        # Sell/reduce first, mirroring Project Fifty's live proposal ordering.
        for symbol in symbols:
            if not self._instruction_allows(symbol=symbol, plan=plan):
                continue
            price = prices.get(symbol)
            position = updated.get(symbol)
            if price is None or position is None:
                continue
            target_value = nav * target_weights.get(symbol, _ZERO)
            current_value = position.quantity * price
            if current_value <= target_value:
                continue
            quantity = min((current_value - target_value) / price, position.quantity)
            fill_price = price * (_ONE - self._config.slippage_rate)
            notional = quantity * fill_price
            fee = notional * self._config.fee_rate
            cash += notional - fee
            turnover += notional
            costs += fee + quantity * (price - fill_price)
            trades += 1
            remainder = position.quantity - quantity
            if remainder <= _ZERO:
                updated.pop(symbol, None)
            else:
                updated[symbol] = Position(
                    symbol=symbol,
                    quantity=remainder,
                    average_price=position.average_price,
                )

        for symbol in symbols:
            if not self._instruction_allows(symbol=symbol, plan=plan):
                continue
            price = prices.get(symbol)
            target_weight = target_weights.get(symbol, _ZERO)
            if price is None or target_weight <= _ZERO:
                continue
            position = updated.get(symbol)
            current_quantity = position.quantity if position is not None else _ZERO
            current_value = current_quantity * price
            target_value = nav * target_weight
            if current_value >= target_value:
                continue
            fill_price = price * (_ONE + self._config.slippage_rate)
            desired_quantity = (target_value - current_value) / fill_price
            if desired_quantity <= _ZERO:
                continue
            denominator = fill_price * (_ONE + self._config.fee_rate)
            affordable_quantity = cash / denominator if denominator > 0 else _ZERO
            quantity = min(desired_quantity, affordable_quantity)
            if quantity <= _ZERO:
                continue
            notional = quantity * fill_price
            fee = notional * self._config.fee_rate
            total_cost = notional + fee
            cash = self._clamp_cash(cash - total_cost)
            turnover += notional
            costs += fee + quantity * (fill_price - price)
            trades += 1
            if position is None:
                updated[symbol] = Position(
                    symbol=symbol,
                    quantity=quantity,
                    average_price=fill_price,
                )
            else:
                new_quantity = position.quantity + quantity
                average_price = (
                    position.quantity * position.average_price + quantity * fill_price
                ) / new_quantity
                updated[symbol] = Position(
                    symbol=symbol,
                    quantity=new_quantity,
                    average_price=average_price,
                )

        return cash, updated, turnover, costs, trades

    def _portfolio_state(
        self,
        *,
        cash: Decimal,
        positions: dict[str, Position],
        prices: dict[str, Decimal],
        as_of: datetime,
    ) -> PortfolioState:
        nav = cash
        for symbol, position in positions.items():
            mark = prices.get(symbol, position.average_price)
            nav += position.quantity * mark
        return PortfolioState(
            cash=cash,
            positions=dict(positions),
            nav=nav,
            currency=self._config.currency,
            as_of=as_of,
        )

    @staticmethod
    def _instruction_allows(*, symbol: str, plan: RebalancePlan | None) -> bool:
        if plan is None:
            return True
        instruction = plan.for_symbol(symbol)
        return bool(instruction is not None and instruction.execute)

    @staticmethod
    def _clamp_cash(value: Decimal) -> Decimal:
        if value >= _ZERO:
            return value
        if value >= -_CASH_EPSILON:
            return _ZERO
        raise RuntimeError("backtest attempted to spend materially more cash than available")

    @staticmethod
    def _bar_at(bars: tuple[MarketBar, ...], timestamp: datetime) -> MarketBar | None:
        for bar in bars:
            if bar.timestamp == timestamp:
                return bar
        return None

    @staticmethod
    def _validate_history(history: dict[str, tuple[MarketBar, ...]]) -> None:
        if not history:
            raise ValueError("history must not be empty")
        for symbol, bars in history.items():
            if not symbol or not bars:
                raise ValueError("every backtest symbol must have history")
            previous: datetime | None = None
            for bar in bars:
                if previous is not None and bar.timestamp <= previous:
                    raise ValueError("backtest history must be strictly increasing")
                previous = bar.timestamp


class WalkForwardEvaluator:
    """Evaluate a strategy repeatedly on unseen test windows.

    The strategy factory is called per window so state cannot leak between windows. The optional
    economic rebalance policy is stateless and is applied identically in every window.
    """

    def __init__(
        self,
        strategy_factory: Callable[[], StrategyProvider],
        *,
        backtest_config: BacktestConfig | None = None,
        walk_forward_config: WalkForwardConfig | None = None,
        rebalance_policy: EconomicRebalancePolicy | None = None,
    ) -> None:
        self._strategy_factory = strategy_factory
        self._backtest_config = backtest_config or BacktestConfig()
        self._walk_config = walk_forward_config or WalkForwardConfig()
        self._rebalance_policy = rebalance_policy

    def evaluate(
        self,
        *,
        history: dict[str, tuple[MarketBar, ...]],
        benchmark_symbol: str,
    ) -> tuple[WalkForwardWindow, ...]:
        benchmark = history.get(benchmark_symbol, ())
        cfg = self._walk_config
        windows: list[WalkForwardWindow] = []
        start = cfg.train_bars

        while start + cfg.test_bars < len(benchmark):
            test_start = benchmark[start].timestamp
            test_end_index = start + cfg.test_bars
            test_end = benchmark[test_end_index].timestamp
            window_history = {
                symbol: tuple(bar for bar in bars if bar.timestamp <= test_end)
                for symbol, bars in history.items()
            }
            engine = BacktestEngine(
                self._strategy_factory(),
                self._backtest_config,
                rebalance_policy=self._rebalance_policy,
            )
            result = engine.run(
                history=window_history,
                benchmark_symbol=benchmark_symbol,
                evaluation_start=test_start,
            )
            windows.append(
                WalkForwardWindow(test_start=test_start, test_end=test_end, result=result)
            )
            start += cfg.step_bars

        return tuple(windows)
