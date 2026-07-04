"""Tests for core/capital_manager.py."""
import pytest
from core.capital_manager import CapitalManager
from core.mocks import MockEventBus, MockOrderManager
from core.strategy import Strategy
from core.models import Tick, Candle


class DummyStrategy(Strategy):
    def __init__(self, name, **kwargs):
        super().__init__(name=name, event_bus=MockEventBus(),
                         order_manager=MockOrderManager())

    async def on_tick(self, t: Tick): pass
    async def on_candle(self, c: Candle): pass


def test_initial_state():
    cm = CapitalManager(total_capital=100_000, max_leverage=1.0)
    assert cm.total_capital == 100_000
    assert cm.max_leverage == 1.0
    assert cm.shares == {}


def test_set_and_get_share():
    cm = CapitalManager()
    cm.set_share('strat_a', 60)
    cm.set_share('strat_b', 40)
    assert cm.get_share('strat_a') == 60
    assert cm.get_share('strat_b') == 40
    assert cm.get_share('unknown') == 0


def test_get_allocated_capital_equal_shares():
    cm = CapitalManager(total_capital=100_000)
    s1, s2 = DummyStrategy('s1'), DummyStrategy('s2')
    cm.set_strategy(s1, share=50)
    cm.set_strategy(s2, share=50)
    assert cm.get_allocated_capital('s1') == pytest.approx(50_000)
    assert cm.get_allocated_capital('s2') == pytest.approx(50_000)


def test_get_allocated_capital_unequal_shares():
    cm = CapitalManager(total_capital=100_000)
    s1, s2 = DummyStrategy('s1'), DummyStrategy('s2')
    cm.set_strategy(s1, share=75)
    cm.set_strategy(s2, share=25)
    assert cm.get_allocated_capital('s1') == pytest.approx(75_000)
    assert cm.get_allocated_capital('s2') == pytest.approx(25_000)


def test_get_allocated_capital_zero_shares():
    cm = CapitalManager(total_capital=100_000)
    assert cm.get_allocated_capital('nobody') == 0.0


def test_get_available_capital_no_positions():
    cm = CapitalManager(total_capital=100_000)
    s = DummyStrategy('s1')
    cm.set_strategy(s, share=100)
    # Нет позиций → доступный = выделенный
    avail = cm.get_available_capital('s1')
    assert avail == pytest.approx(100_000)


def test_get_available_capital_with_open_position():
    cm = CapitalManager(total_capital=100_000)
    s = DummyStrategy('s1')
    cm.set_strategy(s, share=100)
    # Симулируем открытую позицию
    s.positions['AAPL'] = 10.0
    s._last_prices['AAPL'] = 500.0   # 10 * 500 = 5000 используется
    avail = cm.get_available_capital('s1')
    assert avail == pytest.approx(95_000)


def test_remove_strategy():
    cm = CapitalManager(total_capital=100_000)
    s = DummyStrategy('s1')
    cm.set_strategy(s, share=100)
    cm.remove_strategy('s1')
    assert cm.get_share('s1') == 0
    assert cm.get_allocated_capital('s1') == 0.0


def test_save_and_load_state():
    cm = CapitalManager(total_capital=250_000, max_leverage=2.5)
    cm.shares = {'sa': 3, 'sb': 1}
    state = cm.save_state()

    cm2 = CapitalManager()
    cm2.load_state(state)
    assert cm2.total_capital == 250_000
    assert cm2.max_leverage == 2.5
    assert cm2.shares == {'sa': 3, 'sb': 1}


# ── Leverage tests ────────────────────────────────────────────────────────────

def test_default_leverage_one():
    """Стратегия с leverage=1.0 (дефолт) получает ровно allocated."""
    cm = CapitalManager(total_capital=100_000, max_leverage=5.0)
    s = DummyStrategy('s1')
    s.leverage = 1.0
    cm.set_strategy(s, share=100)
    assert cm.get_available_capital('s1') == pytest.approx(100_000)


def test_leverage_doubles_available():
    """leverage=2.0 → доступный капитал вдвое больше выделенного."""
    cm = CapitalManager(total_capital=100_000, max_leverage=5.0)
    s = DummyStrategy('s1')
    s.leverage = 2.0
    cm.set_strategy(s, share=100)
    assert cm.get_available_capital('s1') == pytest.approx(200_000)


def test_leverage_capped_by_max_leverage():
    """leverage превышает max_leverage → ограничивается max_leverage."""
    cm = CapitalManager(total_capital=100_000, max_leverage=3.0)
    s = DummyStrategy('s1')
    s.leverage = 10.0
    cm.set_strategy(s, share=100)
    # Ограничено max_leverage=3 → 100_000 * 3
    assert cm.get_available_capital('s1') == pytest.approx(300_000)


def test_leverage_conservative():
    """leverage=0.5 → стратегия получает только половину выделенного."""
    cm = CapitalManager(total_capital=100_000, max_leverage=5.0)
    s = DummyStrategy('s1')
    s.leverage = 0.5
    cm.set_strategy(s, share=100)
    assert cm.get_available_capital('s1') == pytest.approx(50_000)


def test_leverage_with_open_position():
    """leverage=2.0, открытая позиция вычитается из effective_capital."""
    cm = CapitalManager(total_capital=100_000, max_leverage=5.0)
    s = DummyStrategy('s1')
    s.leverage = 2.0
    cm.set_strategy(s, share=100)
    # effective = 200_000; position = 10 * 500 = 5_000
    s.positions['AAPL'] = 10.0
    s._last_prices['AAPL'] = 500.0
    assert cm.get_available_capital('s1') == pytest.approx(195_000)


def test_leverage_two_strategies_different_leverages():
    """Несколько стратегий с разными плечами."""
    cm = CapitalManager(total_capital=100_000, max_leverage=5.0)
    s1, s2 = DummyStrategy('s1'), DummyStrategy('s2')
    s1.leverage = 1.0
    s2.leverage = 3.0
    cm.set_strategy(s1, share=50)
    cm.set_strategy(s2, share=50)
    # s1: allocated=50_000, leverage=1 → 50_000
    # s2: allocated=50_000, leverage=3 → 150_000
    assert cm.get_available_capital('s1') == pytest.approx(50_000)
    assert cm.get_available_capital('s2') == pytest.approx(150_000)


def test_strategy_leverage_saved_and_loaded():
    """leverage должен сохраняться и восстанавливаться через save/load_state."""
    from core.mocks import MockEventBus, MockOrderManager
    from core.strategy import Strategy
    from core.models import Tick, Candle as CandleM

    class DS(Strategy):
        async def on_tick(self, t: Tick): pass
        async def on_candle(self, c: CandleM): pass

    s = DS(name='test', event_bus=MockEventBus(), order_manager=MockOrderManager())
    s.leverage = 2.5
    state = s.save_state()

    s2 = DS(name='test', event_bus=MockEventBus(), order_manager=MockOrderManager())
    s2.load_state(state)
    assert s2.leverage == pytest.approx(2.5)
