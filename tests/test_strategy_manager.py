"""Tests for core/strategy_manager.py — using the NEW multi-symbol API."""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

from core.events import EventBus, CandleEvent, TickEvent
from core.models import Order, OrderSide, OrderType, Tick, Candle, OrderStatus
from core.commission import FixedCommission
from core.risk_manager import RiskManager
from core.order_manager import OrderManager
from core.strategy import Strategy
from core.strategy_manager import StrategyManager
from core.state_store import JsonStateStore
from core.capital_manager import CapitalManager


# ── Helpers ───────────────────────────────────────────────────────────────────

class SimpleTestStrategy(Strategy):
    """Стратегия-заглушка с минимальной реализацией, использующая новый API."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.subscriptions:
            self.subscriptions = [('TEST', '1m')]
        self.candles_seen = []
        self.ticks_seen = []

    async def on_tick(self, tick: Tick):
        self.ticks_seen.append(tick)

    async def on_candle(self, candle: Candle):
        self.add_candle_to_history(candle)
        self.candles_seen.append(candle)


def make_candle(symbol='TEST', tf='1m', close=100.0):
    return Candle(
        symbol=symbol, timeframe=tf,
        open=close, high=close + 1, low=close - 1, close=close,
        volume=500, timestamp=datetime(2024, 1, 1, 10, 0), is_complete=True,
    )


def make_tick(symbol='TEST', last=100.0):
    return Tick(
        timestamp=datetime(2024, 1, 1, 10, 0),
        symbol=symbol, bid=last - 0.1, ask=last + 0.1,
        last=last, volume=10,
    )


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def mock_gateway():
    gw = AsyncMock()
    gw.send_order.return_value = 'gw-1'
    gw.get_history.return_value = []
    return gw


@pytest.fixture
def risk_manager():
    rm = RiskManager()
    rm.set_position_limit('test_strategy', 10_000)
    return rm


@pytest.fixture
def order_manager(event_bus, mock_gateway, risk_manager):
    return OrderManager(event_bus, mock_gateway, risk_manager, FixedCommission(0.0))


@pytest.fixture
def state_store(tmp_path):
    return JsonStateStore(base_path=str(tmp_path / "states"))


@pytest.fixture
def capital_manager():
    return CapitalManager(total_capital=100_000)


@pytest.fixture
def strategy_manager(event_bus, mock_gateway, order_manager, state_store, capital_manager):
    return StrategyManager(event_bus, mock_gateway, order_manager, state_store, capital_manager)


# ── Tests: add/remove ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_strategy(strategy_manager):
    s = SimpleTestStrategy(
        name='s1',
        event_bus=strategy_manager.event_bus,
        order_manager=strategy_manager.order_manager,
    )
    await strategy_manager.add_strategy(s)
    assert 's1' in strategy_manager._strategies


@pytest.mark.asyncio
async def test_add_duplicate_strategy_raises(strategy_manager):
    s = SimpleTestStrategy(
        name='s1',
        event_bus=strategy_manager.event_bus,
        order_manager=strategy_manager.order_manager,
    )
    await strategy_manager.add_strategy(s)
    with pytest.raises(ValueError, match='s1'):
        await strategy_manager.add_strategy(s)


@pytest.mark.asyncio
async def test_remove_strategy(strategy_manager):
    s = SimpleTestStrategy(
        name='s1',
        event_bus=strategy_manager.event_bus,
        order_manager=strategy_manager.order_manager,
    )
    await strategy_manager.add_strategy(s)
    await strategy_manager.remove_strategy('s1')
    assert 's1' not in strategy_manager._strategies


@pytest.mark.asyncio
async def test_remove_nonexistent_strategy_is_safe(strategy_manager):
    await strategy_manager.remove_strategy('ghost')  # should not raise


# ── Tests: capital allocation ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_equal_allocation_two_strategies(strategy_manager, capital_manager):
    for name in ('s1', 's2'):
        s = SimpleTestStrategy(
            name=name,
            event_bus=strategy_manager.event_bus,
            order_manager=strategy_manager.order_manager,
        )
        await strategy_manager.add_strategy(s)
    # Each should get 50%
    assert capital_manager.get_allocated_capital('s1') == pytest.approx(50_000)
    assert capital_manager.get_allocated_capital('s2') == pytest.approx(50_000)


@pytest.mark.asyncio
async def test_rebalance_after_remove(strategy_manager, capital_manager):
    for name in ('a', 'b', 'c'):
        s = SimpleTestStrategy(
            name=name,
            event_bus=strategy_manager.event_bus,
            order_manager=strategy_manager.order_manager,
        )
        await strategy_manager.add_strategy(s)
    await strategy_manager.remove_strategy('c')
    # After removing 'c', 'a' and 'b' should each get 50%
    assert capital_manager.get_allocated_capital('a') == pytest.approx(50_000)
    assert capital_manager.get_allocated_capital('b') == pytest.approx(50_000)


# ── Tests: event routing ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_strategy_receives_candle_event(strategy_manager, event_bus):
    s = SimpleTestStrategy(
        name='s1',
        event_bus=strategy_manager.event_bus,
        order_manager=strategy_manager.order_manager,
    )
    await strategy_manager.add_strategy(s)

    candle = make_candle()
    await event_bus.publish('market.candle.TEST.1m', CandleEvent(candle=candle))

    assert len(s.candles_seen) == 1
    assert s.candles_seen[0].symbol == 'TEST'


@pytest.mark.asyncio
async def test_strategy_receives_tick_event(strategy_manager, event_bus):
    s = SimpleTestStrategy(
        name='s1',
        event_bus=strategy_manager.event_bus,
        order_manager=strategy_manager.order_manager,
    )
    s.subscriptions = [('TEST', 'tick')]
    await strategy_manager.add_strategy(s)

    tick = make_tick()
    await event_bus.publish('market.tick.TEST', TickEvent(tick=tick))

    assert len(s.ticks_seen) == 1


@pytest.mark.asyncio
async def test_unsubscribed_strategy_does_not_receive_events(strategy_manager, event_bus):
    s = SimpleTestStrategy(
        name='s1',
        event_bus=strategy_manager.event_bus,
        order_manager=strategy_manager.order_manager,
    )
    await strategy_manager.add_strategy(s)
    await strategy_manager.remove_strategy('s1')

    candle = make_candle()
    await event_bus.publish('market.candle.TEST.1m', CandleEvent(candle=candle))

    assert len(s.candles_seen) == 0


# ── Tests: start / stop ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_strategy_sets_running(strategy_manager):
    s = SimpleTestStrategy(
        name='s1',
        event_bus=strategy_manager.event_bus,
        order_manager=strategy_manager.order_manager,
    )
    await strategy_manager.add_strategy(s)
    await strategy_manager.start_strategy('s1')
    assert s._status == 'RUNNING'


@pytest.mark.asyncio
async def test_stop_strategy_sets_stopped_and_saves_state(strategy_manager, state_store):
    s = SimpleTestStrategy(
        name='s1',
        event_bus=strategy_manager.event_bus,
        order_manager=strategy_manager.order_manager,
    )
    await strategy_manager.add_strategy(s)
    await strategy_manager.start_strategy('s1')
    await strategy_manager.stop_strategy('s1')
    assert s._status == 'STOPPED'
    # State should be saved
    saved = await state_store.load_strategy_state('s1')
    assert saved is not None


@pytest.mark.asyncio
async def test_start_nonexistent_strategy_is_safe(strategy_manager):
    await strategy_manager.start_strategy('ghost')  # should not raise


# ── Tests: snapshots ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_all_snapshots(strategy_manager):
    for name in ('s1', 's2'):
        s = SimpleTestStrategy(
            name=name,
            event_bus=strategy_manager.event_bus,
            order_manager=strategy_manager.order_manager,
        )
        await strategy_manager.add_strategy(s)

    snaps = strategy_manager.get_all_snapshots()
    assert len(snaps) == 2
    names = {snap['name'] for snap in snaps}
    assert names == {'s1', 's2'}


@pytest.mark.asyncio
async def test_get_strategy_snapshot(strategy_manager):
    s = SimpleTestStrategy(
        name='s1',
        event_bus=strategy_manager.event_bus,
        order_manager=strategy_manager.order_manager,
    )
    await strategy_manager.add_strategy(s)
    snap = strategy_manager.get_strategy_snapshot('s1')
    assert snap is not None
    assert snap['name'] == 's1'


# ── Tests: state persistence ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_strategy_state_persists_across_add(strategy_manager, state_store):
    """Сохранённое состояние должно загружаться при add_strategy."""
    saved_state = {'positions': {'TEST': 5.0}, 'current_equity': 55_000.0,
                   'entry_prices': {'TEST': 98.0}, 'weight': 1.0,
                   'price_history': {}, 'equity_history': []}
    await state_store.save_strategy_state('s1', saved_state)

    s = SimpleTestStrategy(
        name='s1',
        event_bus=strategy_manager.event_bus,
        order_manager=strategy_manager.order_manager,
    )
    await strategy_manager.add_strategy(s)
    assert s.positions.get('TEST') == 5.0
    assert s.current_equity == 55_000.0


# ── Tests: save_strategies_list ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_strategies_list_saved_on_add(strategy_manager, state_store):
    s = SimpleTestStrategy(
        name='s1',
        event_bus=strategy_manager.event_bus,
        order_manager=strategy_manager.order_manager,
    )
    await strategy_manager.add_strategy(s)
    lst = await state_store.load_strategies_list()
    assert len(lst) == 1
    assert lst[0]['name'] == 's1'


@pytest.mark.asyncio
async def test_strategies_list_updated_on_remove(strategy_manager, state_store):
    for name in ('s1', 's2'):
        s = SimpleTestStrategy(
            name=name,
            event_bus=strategy_manager.event_bus,
            order_manager=strategy_manager.order_manager,
        )
        await strategy_manager.add_strategy(s)
    await strategy_manager.remove_strategy('s1')
    lst = await state_store.load_strategies_list()
    assert len(lst) == 1
    assert lst[0]['name'] == 's2'
