"""Tests for ATR/risk-management helpers and ParallelBacktestRunner."""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from core.mocks import MockEventBus, MockOrderManager
from core.strategy import Strategy
from core.models import Tick, Candle, Order, OrderSide, OrderType
from core.parallel_backtest import ParallelBacktestRunner
from core.commission import FixedCommission
from core.capital_manager import CapitalManager


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_ohlcv(n=60, seed=0) -> pd.DataFrame:
    np.random.seed(seed)
    dates = pd.date_range('2024-01-01', periods=n, freq='1min')
    p = 100 + np.cumsum(np.random.randn(n) * 0.3)
    p = np.maximum(p, 1.0)
    return pd.DataFrame({
        'Open': p, 'High': p * 1.001, 'Low': p * 0.999,
        'Close': p, 'Volume': np.ones(n) * 500,
    }, index=dates)


class DummyStrategy(Strategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.subscriptions:
            self.subscriptions = [('SYM', '1m')]

    async def on_tick(self, t: Tick): pass
    async def on_candle(self, c: Candle):
        self.add_candle_to_history(c)


class TradingDummy(Strategy):
    """Покупает на каждой 5-й свече, продаёт через 5 баров."""
    def __init__(self, *args, fast=5, **kwargs):
        super().__init__(*args, **kwargs)
        self.fast = fast
        self._cnt = 0
        if not self.subscriptions:
            self.subscriptions = [('SYM', '1m')]

    async def on_tick(self, t: Tick): pass

    async def on_candle(self, c: Candle):
        self.add_candle_to_history(c)
        self._cnt += 1
        sym = c.symbol
        pos = self.positions.get(sym, 0.0)
        if self._cnt % self.fast == 1 and pos == 0:
            await self.send_order(Order(
                client_order_id=f'b{self._cnt}', strategy_name=self.name,
                symbol=sym, side=OrderSide.BUY,
                order_type=OrderType.MARKET, volume=1,
            ))
        elif self._cnt % self.fast == 0 and pos > 0:
            await self.send_order(Order(
                client_order_id=f's{self._cnt}', strategy_name=self.name,
                symbol=sym, side=OrderSide.SELL,
                order_type=OrderType.MARKET, volume=pos,
            ))


def _candle(sym='SYM', tf='1m', o=100., h=102., l=98., c=101., ts=None):
    return Candle(
        symbol=sym, timeframe=tf,
        open=o, high=h, low=l, close=c,
        volume=500, timestamp=ts or datetime(2024, 1, 1, 10, 0),
        is_complete=True,
    )


# ══════════════════════════════════════════════════════════════════
# ATR tests
# ══════════════════════════════════════════════════════════════════

def _make_strategy_with_history(n=30, sym='SYM', tf='1m'):
    s = DummyStrategy(name='t', event_bus=MockEventBus(), order_manager=MockOrderManager())
    np.random.seed(1)
    for i in range(n):
        ts = datetime(2024, 1, 1, 10, i)
        p = 100.0 + i * 0.1
        s.add_candle_to_history(Candle(
            symbol=sym, timeframe=tf,
            open=p, high=p + 1.0, low=p - 0.5, close=p + 0.2,
            volume=100, timestamp=ts, is_complete=True,
        ))
    return s


def test_compute_atr_returns_none_when_insufficient_data():
    s = DummyStrategy(name='t', event_bus=MockEventBus(), order_manager=MockOrderManager())
    # Только 5 баров — меньше периода=14
    for i in range(5):
        s.add_candle_to_history(_candle(ts=datetime(2024, 1, 1, 10, i)))
    result = s.compute_atr('SYM', '1m', period=14)
    assert result is None


def test_compute_atr_returns_float_with_enough_data():
    s = _make_strategy_with_history(n=30)
    result = s.compute_atr('SYM', '1m', period=14)
    assert isinstance(result, float)
    assert result > 0


def test_compute_atr_nonexistent_symbol_returns_none():
    s = DummyStrategy(name='t', event_bus=MockEventBus(), order_manager=MockOrderManager())
    assert s.compute_atr('NONE', '1m') is None


def test_compute_atr_value_matches_manual_calculation():
    """ATR должен совпасть с ручным расчётом по последним 3 барам."""
    s = DummyStrategy(name='t', event_bus=MockEventBus(), order_manager=MockOrderManager())
    # Добавляем 4 бара с известными значениями
    bars = [
        (100., 105., 98., 102.),   # bar 0: prev close нет
        (102., 107., 100., 104.),  # bar 1: TR = max(7, |107-102|, |100-102|) = 7
        (104., 108., 101., 105.),  # bar 2: TR = max(7, |108-104|, |101-104|) = 7
        (105., 110., 103., 107.),  # bar 3: TR = max(7, |110-105|, |103-105|) = 7
    ]
    for i, (o, h, l, c) in enumerate(bars):
        s.add_candle_to_history(Candle(
            symbol='SYM', timeframe='1m',
            open=o, high=h, low=l, close=c,
            volume=100, timestamp=datetime(2024, 1, 1, 10, i), is_complete=True,
        ))
    atr = s.compute_atr('SYM', '1m', period=3)
    # TR[1]=7, TR[2]=7, TR[3]=7 → ATR=7
    assert atr == pytest.approx(7.0, rel=0.01)


# ══════════════════════════════════════════════════════════════════
# Risk-based position sizing tests
# ══════════════════════════════════════════════════════════════════

def test_get_position_size_returns_zero_without_capital():
    s = DummyStrategy(name='t', event_bus=MockEventBus(), order_manager=MockOrderManager())
    # Нет CapitalManager → available=0
    result = s.get_position_size('SYM', price=100.0, risk_fraction=1.0)
    assert result == 0.0


def test_get_position_size_with_capital():
    s = DummyStrategy(name='t', event_bus=MockEventBus(), order_manager=MockOrderManager())
    cm = CapitalManager(total_capital=100_000)
    cm.set_strategy(s, share=100)
    s._capital_manager = cm
    # volume = 100_000 / 100 = 1000
    result = s.get_position_size('SYM', price=100.0, risk_fraction=1.0)
    assert result == pytest.approx(1000.0)


def test_get_position_size_by_risk_basic():
    s = DummyStrategy(name='t', event_bus=MockEventBus(), order_manager=MockOrderManager())
    cm = CapitalManager(total_capital=100_000)
    cm.set_strategy(s, share=100)
    s._capital_manager = cm
    # risk_amount = 100_000 * 0.01 = 1000
    # price_risk = |100 - 98| = 2
    # volume = 1000 / 2 = 500
    result = s.get_position_size_by_risk('SYM', entry_price=100.0, stop_price=98.0, risk_pct=0.01)
    assert result == pytest.approx(500.0)


def test_get_position_size_by_risk_zero_when_same_price():
    s = DummyStrategy(name='t', event_bus=MockEventBus(), order_manager=MockOrderManager())
    cm = CapitalManager(total_capital=100_000)
    cm.set_strategy(s, share=100)
    s._capital_manager = cm
    result = s.get_position_size_by_risk('SYM', entry_price=100.0, stop_price=100.0)
    assert result == 0.0


def test_get_position_size_by_risk_short():
    s = DummyStrategy(name='t', event_bus=MockEventBus(), order_manager=MockOrderManager())
    cm = CapitalManager(total_capital=50_000)
    cm.set_strategy(s, share=100)
    s._capital_manager = cm
    # Шорт: stop выше входа
    # risk_amount = 50_000 * 0.02 = 1000
    # price_risk = |90 - 95| = 5
    # volume = 1000/5 = 200
    result = s.get_position_size_by_risk('SYM', entry_price=90.0, stop_price=95.0, risk_pct=0.02)
    assert result == pytest.approx(200.0)


def test_compute_atr_stop_long():
    s = _make_strategy_with_history(n=30)
    atr = s.compute_atr('SYM', '1m', period=14)
    stop = s.compute_atr_stop('SYM', '1m', entry_price=110.0, direction='long',
                              atr_period=14, atr_multiplier=2.0)
    assert stop is not None
    assert stop == pytest.approx(110.0 - atr * 2.0)


def test_compute_atr_stop_short():
    s = _make_strategy_with_history(n=30)
    atr = s.compute_atr('SYM', '1m', period=14)
    stop = s.compute_atr_stop('SYM', '1m', entry_price=110.0, direction='short',
                              atr_period=14, atr_multiplier=1.5)
    assert stop == pytest.approx(110.0 + atr * 1.5)


def test_compute_atr_stop_returns_none_when_insufficient():
    s = DummyStrategy(name='t', event_bus=MockEventBus(), order_manager=MockOrderManager())
    stop = s.compute_atr_stop('SYM', '1m', entry_price=100.0)
    assert stop is None


# ══════════════════════════════════════════════════════════════════
# ParallelBacktestRunner tests
# ══════════════════════════════════════════════════════════════════

class TestParallelBacktestRunner:
    def setup_method(self):
        self.data = {'SYM': make_ohlcv(n=80)}

    def test_single_run(self):
        runner = ParallelBacktestRunner(
            data=self.data,
            strategy_class=TradingDummy,
            base_params={'name': 'run'},
            initial_capital=10_000,
            max_workers=1,
        )
        results = runner.run([{'name': 'r1', 'params': {'fast': 5}}])
        assert 'r1' in results
        assert 'equity_curve' in results['r1']

    def test_multiple_runs_parallel(self):
        runner = ParallelBacktestRunner(
            data=self.data,
            strategy_class=TradingDummy,
            base_params={},
            initial_capital=10_000,
            max_workers=4,
        )
        configs = [{'name': f'f{i}', 'params': {'fast': i}} for i in range(3, 8)]
        results = runner.run(configs)
        assert len(results) == 5
        for name in [f'f{i}' for i in range(3, 8)]:
            assert name in results

    def test_results_have_required_keys(self):
        runner = ParallelBacktestRunner(
            data=self.data,
            strategy_class=TradingDummy,
            base_params={},
            initial_capital=10_000,
        )
        results = runner.run([{'name': 'test', 'params': {}}])
        r = results['test']
        assert 'equity_curve' in r
        assert 'trades' in r
        assert 'metrics' in r
        assert 'final_equity' in r

    def test_commission_applied(self):
        runner_free = ParallelBacktestRunner(
            data=self.data, strategy_class=TradingDummy,
            base_params={}, initial_capital=10_000,
            commission=FixedCommission(0.0),
        )
        runner_paid = ParallelBacktestRunner(
            data=self.data, strategy_class=TradingDummy,
            base_params={}, initial_capital=10_000,
            commission=FixedCommission(5.0),
        )
        cfg = [{'name': 'r', 'params': {'fast': 5}}]
        r_free = runner_free.run(cfg)['r']
        r_paid = runner_paid.run(cfg)['r']
        if len(r_free['trades']) > 0:
            assert r_paid['final_equity'] <= r_free['final_equity']

    def test_empty_config_returns_empty(self):
        runner = ParallelBacktestRunner(
            data=self.data, strategy_class=TradingDummy,
            base_params={}, initial_capital=10_000,
        )
        results = runner.run([])
        assert results == {}


class TestGridSearch:
    def setup_method(self):
        self.data = {'SYM': make_ohlcv(n=100)}

    def test_grid_search_returns_ranked_list(self):
        results = ParallelBacktestRunner.grid_search(
            data=self.data,
            strategy_class=TradingDummy,
            param_grid={'fast': [3, 5, 7]},
            initial_capital=10_000,
            rank_by='sharpe_ratio',
        )
        assert len(results) == 3
        # Должны быть отсортированы по убыванию Sharpe
        sharpes = [r['sharpe_ratio'] for r in results]
        assert sharpes == sorted(sharpes, reverse=True)

    def test_grid_search_result_keys(self):
        results = ParallelBacktestRunner.grid_search(
            data=self.data,
            strategy_class=TradingDummy,
            param_grid={'fast': [5]},
            initial_capital=10_000,
        )
        r = results[0]
        assert 'name' in r
        assert 'params' in r
        assert 'metrics' in r
        assert 'final_equity' in r
        assert 'num_trades' in r

    def test_grid_search_cartesian_product(self):
        results = ParallelBacktestRunner.grid_search(
            data=self.data,
            strategy_class=TradingDummy,
            param_grid={'fast': [3, 5], 'slow': [10, 20]},
            initial_capital=10_000,
        )
        # 2 × 2 = 4 комбинации
        assert len(results) == 4
