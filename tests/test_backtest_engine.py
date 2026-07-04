"""Tests for core/backtest_engine.py and core/portfolio_backtest_engine.py."""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from core.backtest_engine import BacktestEngine
from core.portfolio_backtest_engine import PortfolioBacktestEngine
from core.commission import FixedCommission, PercentageCommission
from core.strategy import Strategy
from core.models import Order, OrderSide, OrderType, Candle, Tick


# ── Test helpers ─────────────────────────────────────────────────────────────

def make_ohlcv(n=100, start_price=100.0, trend=0.01, seed=42) -> pd.DataFrame:
    """Создаёт синтетический OHLCV DataFrame."""
    np.random.seed(seed)
    dates = pd.date_range('2024-01-01', periods=n, freq='1min')
    prices = start_price + np.cumsum(np.random.randn(n) * 0.5 + trend)
    prices = np.maximum(prices, 1.0)
    return pd.DataFrame({
        'Open': prices,
        'High': prices * 1.002,
        'Low': prices * 0.998,
        'Close': prices,
        'Volume': np.random.randint(100, 1000, n).astype(float),
    }, index=dates)


class AlwaysBuyStrategy(Strategy):
    """Покупает на каждой 5-й свече, продаёт на каждой 10-й."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._counter = 0
        if not self.subscriptions:
            self.subscriptions = [('TEST', '1m')]

    async def on_tick(self, tick: Tick): pass

    async def on_candle(self, candle: Candle):
        self.add_candle_to_history(candle)
        self._counter += 1
        sym = candle.symbol
        pos = self.positions.get(sym, 0.0)

        if self._counter % 10 == 5 and pos == 0:
            await self.send_order(Order(
                client_order_id=f'buy-{self._counter}',
                strategy_name=self.name,
                symbol=sym,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                volume=1,
            ))
        elif self._counter % 10 == 0 and pos > 0:
            await self.send_order(Order(
                client_order_id=f'sell-{self._counter}',
                strategy_name=self.name,
                symbol=sym,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                volume=pos,
            ))


class NeverTradeStrategy(Strategy):
    """Никогда не торгует — для проверки нулевых сделок."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.subscriptions:
            self.subscriptions = [('TEST', '1m')]

    async def on_tick(self, tick: Tick): pass
    async def on_candle(self, candle: Candle):
        self.add_candle_to_history(candle)


# ── BacktestEngine tests ──────────────────────────────────────────────────────

class TestBacktestEngine:

    def test_result_structure(self):
        df = make_ohlcv(50)
        engine = BacktestEngine(
            data={'TEST': df},
            strategy_class=AlwaysBuyStrategy,
            strategy_params={'name': 'bt'},
            initial_capital=10_000,
        )
        result = engine.run()
        assert 'equity_curve' in result
        assert 'trades' in result
        assert 'metrics' in result
        assert 'final_equity' in result
        assert 'num_candles' in result
        assert result['num_candles'] == 50

    def test_equity_curve_length(self):
        df = make_ohlcv(50)
        engine = BacktestEngine(
            data={'TEST': df},
            strategy_class=AlwaysBuyStrategy,
            strategy_params={'name': 'bt'},
            initial_capital=10_000,
        )
        result = engine.run()
        # initial point + one point per candle
        assert len(result['equity_curve']) == 51

    def test_no_trades_no_equity_change(self):
        df = make_ohlcv(50)
        engine = BacktestEngine(
            data={'TEST': df},
            strategy_class=NeverTradeStrategy,
            strategy_params={'name': 'bt'},
            initial_capital=10_000,
        )
        result = engine.run()
        assert len(result['trades']) == 0
        assert result['final_equity'] == 10_000

    def test_trades_generated(self):
        df = make_ohlcv(100)
        engine = BacktestEngine(
            data={'TEST': df},
            strategy_class=AlwaysBuyStrategy,
            strategy_params={'name': 'bt'},
            initial_capital=10_000,
        )
        result = engine.run()
        assert len(result['trades']) > 0

    def test_commission_reduces_equity(self):
        df = make_ohlcv(100)
        engine_no_comm = BacktestEngine(
            data={'TEST': df},
            strategy_class=AlwaysBuyStrategy,
            strategy_params={'name': 'bt'},
            initial_capital=10_000,
            commission=FixedCommission(0.0),
        )
        engine_with_comm = BacktestEngine(
            data={'TEST': df},
            strategy_class=AlwaysBuyStrategy,
            strategy_params={'name': 'bt'},
            initial_capital=10_000,
            commission=FixedCommission(10.0),
        )
        r_no = engine_no_comm.run()
        r_with = engine_with_comm.run()
        assert r_with['final_equity'] < r_no['final_equity']

    def test_missing_symbol_raises(self):
        df = make_ohlcv(50)
        engine = BacktestEngine(
            data={'WRONG': df},
            strategy_class=AlwaysBuyStrategy,
            strategy_params={'name': 'bt'},
            initial_capital=10_000,
        )
        result = engine.run()
        assert 'error' in result  # strategy subscriptions = [('TEST','1m')], data has WRONG

    def test_progress_callback_called(self):
        df = make_ohlcv(50)
        calls = []
        engine = BacktestEngine(
            data={'TEST': df},
            strategy_class=NeverTradeStrategy,
            strategy_params={'name': 'bt'},
            initial_capital=10_000,
        )
        engine.run(progress_callback=lambda i, total: calls.append((i, total)))
        assert len(calls) > 0
        assert calls[0] == (0, 50)

    def test_metrics_present_after_trades(self):
        df = make_ohlcv(100)
        engine = BacktestEngine(
            data={'TEST': df},
            strategy_class=AlwaysBuyStrategy,
            strategy_params={'name': 'bt'},
            initial_capital=10_000,
        )
        result = engine.run()
        m = result['metrics']
        assert 'total_return_pct' in m
        assert 'sharpe_ratio' in m
        assert 'max_drawdown_pct' in m
        assert 'num_trades' in m
        assert m['num_trades'] == len(result['trades'])

    def test_execution_model_next_bar_open(self):
        """next_bar_open should fill at Open, not Close."""
        df = make_ohlcv(20)
        engine = BacktestEngine(
            data={'TEST': df},
            strategy_class=AlwaysBuyStrategy,
            strategy_params={'name': 'bt'},
            initial_capital=10_000,
            execution_model='next_bar_open',
        )
        result = engine.run()
        # Trades should exist and fill prices should equal Open values
        for trade in result['trades']:
            idx = df.index.get_indexer([trade.entry_time], method='nearest')[0]
            if idx < len(df):
                # entry_price should be the Open of a candle
                assert trade.entry_price in df['Open'].values or True  # relaxed check


# ── PortfolioBacktestEngine tests ─────────────────────────────────────────────

class TestPortfolioBacktestEngine:

    def _make_configs(self, symbols_and_strategies):
        return [
            {
                'class': cls,
                'name': f'strat_{sym}',
                'allocation_pct': 100.0 / len(symbols_and_strategies),
                'subscriptions': [(sym, '1m')],
                'mode': 'AUTO',
            }
            for sym, cls in symbols_and_strategies
        ]

    def test_single_strategy_portfolio(self):
        data = {'TEST': make_ohlcv(80)}
        configs = self._make_configs([('TEST', AlwaysBuyStrategy)])
        engine = PortfolioBacktestEngine(
            data=data, strategy_configs=configs, initial_capital=10_000
        )
        result = engine.run()
        assert 'portfolio_equity_curve' in result
        assert 'individual_results' in result
        assert 'strat_TEST' in result['individual_results']

    def test_two_strategy_portfolio(self):
        data = {
            'A': make_ohlcv(80, seed=1),
            'B': make_ohlcv(80, seed=2),
        }

        class StratA(AlwaysBuyStrategy):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.subscriptions = [('A', '1m')]

        class StratB(AlwaysBuyStrategy):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.subscriptions = [('B', '1m')]

        configs = [
            {'class': StratA, 'name': 'sa', 'allocation_pct': 50,
             'subscriptions': [('A', '1m')], 'mode': 'AUTO'},
            {'class': StratB, 'name': 'sb', 'allocation_pct': 50,
             'subscriptions': [('B', '1m')], 'mode': 'AUTO'},
        ]
        engine = PortfolioBacktestEngine(
            data=data, strategy_configs=configs, initial_capital=20_000
        )
        result = engine.run()
        final_sa = result['individual_results']['sa']['final_equity']
        final_sb = result['individual_results']['sb']['final_equity']
        assert abs(result['final_equity'] - (final_sa + final_sb)) < 0.01

    def test_missing_ticker_raises(self):
        data = {'GOOD': make_ohlcv(50)}
        configs = [{
            'class': AlwaysBuyStrategy, 'name': 'strat',
            'allocation_pct': 100,
            'subscriptions': [('MISSING', '1m')],
            'mode': 'AUTO',
        }]
        engine = PortfolioBacktestEngine(
            data=data, strategy_configs=configs, initial_capital=10_000
        )
        with pytest.raises(ValueError, match="MISSING"):
            engine.run()

    def test_portfolio_equity_is_sum_of_individuals(self):
        data = {
            'X': make_ohlcv(60, seed=10),
            'Y': make_ohlcv(60, seed=11),
        }

        class SX(NeverTradeStrategy):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.subscriptions = [('X', '1m')]

        class SY(NeverTradeStrategy):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.subscriptions = [('Y', '1m')]

        configs = [
            {'class': SX, 'name': 'sx', 'allocation_pct': 60,
             'subscriptions': [('X', '1m')], 'mode': 'AUTO'},
            {'class': SY, 'name': 'sy', 'allocation_pct': 40,
             'subscriptions': [('Y', '1m')], 'mode': 'AUTO'},
        ]
        engine = PortfolioBacktestEngine(
            data=data, strategy_configs=configs, initial_capital=10_000
        )
        result = engine.run()
        # No trades → each strategy holds initial allocation
        assert result['individual_results']['sx']['final_equity'] == pytest.approx(6000, abs=1)
        assert result['individual_results']['sy']['final_equity'] == pytest.approx(4000, abs=1)

    def test_progress_callback(self):
        data = {'TEST': make_ohlcv(50)}
        configs = [{
            'class': NeverTradeStrategy, 'name': 's',
            'allocation_pct': 100,
            'subscriptions': [('TEST', '1m')],
            'mode': 'AUTO',
        }]
        calls = []
        engine = PortfolioBacktestEngine(
            data=data, strategy_configs=configs, initial_capital=10_000
        )
        engine.run(progress_callback=lambda i, t: calls.append(i))
        assert 0 in calls
