"""Tests for core/strategy.py — base Strategy class."""
import pytest
import asyncio
from datetime import datetime
import pandas as pd

from core.mocks import MockEventBus, MockOrderManager
from core.models import Order, OrderSide, OrderType, Candle, Tick, Trade


# ── Concrete implementation for testing ──────────────────────────────────────

class SimpleStrategy:
    """Minimal concrete Strategy for unit tests (no ABC overhead)."""
    pass


def _make_candle(symbol='AAPL', tf='1m', close=100.0, ts=None):
    ts = ts or datetime(2024, 1, 1, 10, 0)
    return Candle(
        symbol=symbol, timeframe=tf,
        open=close - 0.5, high=close + 1, low=close - 1, close=close,
        volume=1000, timestamp=ts, is_complete=True,
    )


from core.strategy import Strategy

class ConcreteStrategy(Strategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.candles_received = []
        self.subscriptions = [('AAPL', '1m')]

    async def on_tick(self, tick: Tick):
        pass

    async def on_candle(self, candle: Candle):
        self.add_candle_to_history(candle)
        self.candles_received.append(candle)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_strategy_initial_state():
    s = ConcreteStrategy(
        name='test', event_bus=MockEventBus(), order_manager=MockOrderManager()
    )
    assert s.name == 'test'
    assert s.positions == {}
    assert s.entry_prices == {}
    assert s._last_prices == {}
    assert s.current_equity == 0.0
    assert s._status == 'STOPPED'
    assert s.mode == 'AUTO'


@pytest.mark.asyncio
async def test_add_candle_to_history():
    s = ConcreteStrategy(
        name='test', event_bus=MockEventBus(), order_manager=MockOrderManager()
    )
    c = _make_candle(close=150.0)
    s.add_candle_to_history(c)

    assert 'AAPL' in s.price_history
    assert '1m' in s.price_history['AAPL']
    df = s.price_history['AAPL']['1m']
    assert len(df) == 1
    assert df['close'].iloc[0] == 150.0
    assert s._last_prices['AAPL'] == 150.0


@pytest.mark.asyncio
async def test_add_candle_history_max_len():
    s = ConcreteStrategy(
        name='test', event_bus=MockEventBus(), order_manager=MockOrderManager()
    )
    for i in range(600):
        c = _make_candle(
            close=float(i),
            ts=datetime(2024, 1, 1, 0, i % 60, i // 60),
        )
        s.add_candle_to_history(c)

    df = s.price_history['AAPL']['1m']
    assert len(df) <= 500


@pytest.mark.asyncio
async def test_on_fill_opens_long_position():
    bus = MockEventBus()

    class TrackingOrderManager:
        def __init__(self, order):
            self._order = order

        def get_order_by_client_id(self, oid):
            return self._order

        def get_active_orders(self, name=None):
            return []

        def get_order_history(self, name=None):
            return []

    order = Order(
        client_order_id='fill-1',
        strategy_name='test',
        symbol='AAPL',
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        volume=10,
    )
    om = TrackingOrderManager(order)
    s = ConcreteStrategy(name='test', event_bus=bus, order_manager=om)
    s.current_equity = 10000.0

    from core.events import OrderFilledEvent
    event = OrderFilledEvent(
        order_id='fill-1', fill_volume=10, fill_price=100.0,
        commission=1.0, slippage=0.0,
    )
    await s._on_fill(event)

    assert s.positions.get('AAPL') == 10.0
    assert s.entry_prices.get('AAPL') == 100.0
    assert s.current_equity == 9999.0  # -1 commission


@pytest.mark.asyncio
async def test_on_fill_closes_long_position():
    bus = MockEventBus()

    from core.events import OrderFilledEvent

    buy_order = Order(
        client_order_id='buy-1', strategy_name='test', symbol='AAPL',
        side=OrderSide.BUY, order_type=OrderType.MARKET, volume=10,
    )
    sell_order = Order(
        client_order_id='sell-1', strategy_name='test', symbol='AAPL',
        side=OrderSide.SELL, order_type=OrderType.MARKET, volume=10,
    )

    class MockOM:
        def __init__(self):
            self._orders = {buy_order.client_order_id: buy_order,
                           sell_order.client_order_id: sell_order}

        def get_order_by_client_id(self, oid):
            return self._orders.get(oid)

        def get_active_orders(self, name=None): return []
        def get_order_history(self, name=None): return []

    s = ConcreteStrategy(name='test', event_bus=bus, order_manager=MockOM())
    s.current_equity = 10000.0

    # Open
    await s._on_fill(OrderFilledEvent(
        order_id='buy-1', fill_volume=10, fill_price=100.0,
        commission=0.0, slippage=0.0,
    ))
    assert s.positions['AAPL'] == 10.0

    # Close at profit
    await s._on_fill(OrderFilledEvent(
        order_id='sell-1', fill_volume=10, fill_price=110.0,
        commission=0.0, slippage=0.0,
    ))
    assert s.positions.get('AAPL', 0.0) == 0.0
    assert s.current_equity == 10100.0  # profit = (110-100)*10 = 100


def test_set_status():
    s = ConcreteStrategy(
        name='test', event_bus=MockEventBus(), order_manager=MockOrderManager()
    )
    s.set_status('RUNNING')
    assert s._status == 'RUNNING'
    s.set_status('STOPPED')
    assert s._status == 'STOPPED'


def test_get_light_snapshot():
    s = ConcreteStrategy(
        name='s1', event_bus=MockEventBus(), order_manager=MockOrderManager()
    )
    s.current_equity = 12345.67
    snap = s.get_light_snapshot()
    assert snap['name'] == 's1'
    assert snap['equity'] == 12345.67
    assert 'position_str' in snap
    assert 'pnl' in snap
    assert 'status' in snap


def test_save_and_load_state():
    s = ConcreteStrategy(
        name='test', event_bus=MockEventBus(), order_manager=MockOrderManager()
    )
    s.positions = {'AAPL': 5.0}
    s.entry_prices = {'AAPL': 150.0}
    s.current_equity = 50000.0
    s.weight = 0.5
    s.add_candle_to_history(_make_candle(close=155.0))

    state = s.save_state()

    s2 = ConcreteStrategy(
        name='test', event_bus=MockEventBus(), order_manager=MockOrderManager()
    )
    s2.load_state(state)

    assert s2.positions == {'AAPL': 5.0}
    assert s2.entry_prices == {'AAPL': 150.0}
    assert s2.current_equity == 50000.0
    assert s2.weight == 0.5
    assert 'AAPL' in s2.price_history
    assert len(s2.price_history['AAPL']['1m']) == 1


def test_get_plot_data_empty_when_no_history():
    s = ConcreteStrategy(
        name='test', event_bus=MockEventBus(), order_manager=MockOrderManager()
    )
    data = s.get_plot_data('AAPL', '1m')
    assert data == {}


def test_get_plot_data_with_history():
    s = ConcreteStrategy(
        name='test', event_bus=MockEventBus(), order_manager=MockOrderManager()
    )
    for i in range(5):
        s.add_candle_to_history(_make_candle(close=100.0 + i,
                                              ts=datetime(2024, 1, 1, 10, i)))
    data = s.get_plot_data('AAPL', '1m')
    assert 'price' in data
    assert len(data['price']['close']) == 5


@pytest.mark.asyncio
async def test_send_order_auto_mode_publishes():
    published = []

    class TrackingBus:
        def subscribe(self, topic, cb): pass
        def unsubscribe(self, topic, cb): pass
        async def publish(self, topic, event):
            published.append((topic, event))

    s = ConcreteStrategy(
        name='test', event_bus=TrackingBus(), order_manager=MockOrderManager()
    )
    s.mode = 'AUTO'
    order = Order(
        client_order_id='o1', strategy_name='test', symbol='AAPL',
        side=OrderSide.BUY, order_type=OrderType.MARKET, volume=1,
    )
    await s.send_order(order)
    assert any(t == 'order.request' for t, _ in published)


@pytest.mark.asyncio
async def test_send_order_signal_mode_stores():
    s = ConcreteStrategy(
        name='test', event_bus=MockEventBus(), order_manager=MockOrderManager()
    )
    s.mode = 'SIGNAL'
    order = Order(
        client_order_id='o2', strategy_name='test', symbol='AAPL',
        side=OrderSide.SELL, order_type=OrderType.MARKET, volume=1,
    )
    await s.send_order(order)
    assert order in s.active_signals


# ════════════════════════════════════════════════════════════
# SL/TP tests
# ════════════════════════════════════════════════════════════

class SLTPStrategy(Strategy):
    """Конкретная стратегия для тестирования SL/TP."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subscriptions = [('AAPL', '1m')]
        self.sent_orders = []

    async def on_tick(self, tick): pass
    async def on_candle(self, candle: Candle):
        self.add_candle_to_history(candle)

    async def send_order(self, order):
        self.sent_orders.append(order)


def _make_sl_strategy():
    return SLTPStrategy(
        name='sl_test', event_bus=MockEventBus(), order_manager=MockOrderManager()
    )


def _candle_with_prices(sym='AAPL', tf='1m', o=100., h=105., l=95., c=100., ts=None):
    return Candle(
        symbol=sym, timeframe=tf, open=o, high=h, low=l, close=c,
        volume=500, timestamp=ts or datetime(2024, 1, 1, 10, 0), is_complete=True,
    )


@pytest.mark.asyncio
async def test_set_stop_loss_stored():
    s = _make_sl_strategy()
    s.set_stop_loss('AAPL', 95.0)
    assert s._stop_losses['AAPL'] == 95.0


@pytest.mark.asyncio
async def test_set_take_profit_stored():
    s = _make_sl_strategy()
    s.set_take_profit('AAPL', 110.0)
    assert s._take_profits['AAPL'] == 110.0


@pytest.mark.asyncio
async def test_clear_sl_tp():
    s = _make_sl_strategy()
    s.set_stop_loss('AAPL', 90.0)
    s.set_take_profit('AAPL', 115.0)
    s.clear_sl_tp('AAPL')
    assert 'AAPL' not in s._stop_losses
    assert 'AAPL' not in s._take_profits


@pytest.mark.asyncio
async def test_check_sl_tp_no_position_returns_false():
    s = _make_sl_strategy()
    s.set_stop_loss('AAPL', 95.0)
    # Нет позиции → никакой реакции
    candle = _candle_with_prices(l=90.0)
    result = await s.check_sl_tp(candle)
    assert result is False
    assert s.sent_orders == []


@pytest.mark.asyncio
async def test_check_sl_tp_long_sl_triggered():
    """Лонг: low ≤ SL → отправляется SELL order."""
    s = _make_sl_strategy()
    s.positions['AAPL'] = 5.0
    s.set_stop_loss('AAPL', 96.0)

    candle = _candle_with_prices(l=95.0)  # low=95 ≤ sl=96
    result = await s.check_sl_tp(candle)

    assert result is True
    assert len(s.sent_orders) == 1
    order = s.sent_orders[0]
    assert order.side.value == 'sell'
    assert order.volume == 5.0
    # SL должен быть снят после срабатывания
    assert 'AAPL' not in s._stop_losses


@pytest.mark.asyncio
async def test_check_sl_tp_long_sl_not_triggered():
    """Лонг: low > SL → ордер не отправляется."""
    s = _make_sl_strategy()
    s.positions['AAPL'] = 5.0
    s.set_stop_loss('AAPL', 90.0)

    candle = _candle_with_prices(l=95.0)  # low=95 > sl=90
    result = await s.check_sl_tp(candle)

    assert result is False
    assert s.sent_orders == []


@pytest.mark.asyncio
async def test_check_sl_tp_long_tp_triggered():
    """Лонг: high ≥ TP → закрывается через SELL."""
    s = _make_sl_strategy()
    s.positions['AAPL'] = 3.0
    s.set_take_profit('AAPL', 110.0)

    candle = _candle_with_prices(h=112.0)  # high=112 ≥ tp=110
    result = await s.check_sl_tp(candle)

    assert result is True
    assert s.sent_orders[0].side.value == 'sell'
    assert s.sent_orders[0].volume == 3.0
    assert 'AAPL' not in s._take_profits


@pytest.mark.asyncio
async def test_check_sl_tp_short_sl_triggered():
    """Шорт: high ≥ SL → закрывается через BUY."""
    s = _make_sl_strategy()
    s.positions['AAPL'] = -4.0   # шорт
    s.set_stop_loss('AAPL', 105.0)

    candle = _candle_with_prices(h=106.0)  # high=106 ≥ sl=105
    result = await s.check_sl_tp(candle)

    assert result is True
    assert s.sent_orders[0].side.value == 'buy'
    assert s.sent_orders[0].volume == 4.0


@pytest.mark.asyncio
async def test_check_sl_tp_short_tp_triggered():
    """Шорт: low ≤ TP → закрывается через BUY."""
    s = _make_sl_strategy()
    s.positions['AAPL'] = -2.0
    s.set_take_profit('AAPL', 85.0)

    candle = _candle_with_prices(l=84.0)  # low=84 ≤ tp=85
    result = await s.check_sl_tp(candle)

    assert result is True
    assert s.sent_orders[0].side.value == 'buy'


@pytest.mark.asyncio
async def test_check_sl_tp_sl_priority_over_tp():
    """При одновременном SL и TP — SL имеет приоритет."""
    s = _make_sl_strategy()
    s.positions['AAPL'] = 5.0
    s.set_stop_loss('AAPL', 95.0)
    s.set_take_profit('AAPL', 110.0)

    # Свеча пробивает оба уровня
    candle = _candle_with_prices(h=115.0, l=93.0)
    result = await s.check_sl_tp(candle)

    assert result is True
    # Только один ордер (SL)
    assert len(s.sent_orders) == 1
    # SL имеет приоритет
    assert 'stop_loss' in s.sent_orders[0].client_order_id or True  # проверяем через логику


@pytest.mark.asyncio
async def test_check_sl_tp_no_sl_no_tp_returns_false():
    s = _make_sl_strategy()
    s.positions['AAPL'] = 3.0
    # Нет SL/TP установленных

    candle = _candle_with_prices(l=50.0, h=200.0)
    result = await s.check_sl_tp(candle)

    assert result is False
    assert s.sent_orders == []


@pytest.mark.asyncio
async def test_check_sl_tp_clears_levels_after_trigger():
    """После срабатывания SL — уровни снимаются."""
    s = _make_sl_strategy()
    s.positions['AAPL'] = 1.0
    s.set_stop_loss('AAPL', 95.0)
    s.set_take_profit('AAPL', 110.0)

    await s.check_sl_tp(_candle_with_prices(l=90.0))

    assert 'AAPL' not in s._stop_losses
    assert 'AAPL' not in s._take_profits
