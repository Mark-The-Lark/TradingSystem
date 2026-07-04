"""
Tests for core/quik_gateway.py.

QuikPy не устанавливается на Linux, поэтому мокируем его импорт через
unittest.mock.patch. Тесты проверяют логику шлюза, не само соединение с QUIK.
"""
import asyncio
import sys
import types
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from core.events import (
    EventBus, OrderFilledEvent, OrderCancelledEvent, ConnectionStateEvent,
    CandleEvent, TickEvent,
)
from core.models import Order, OrderSide, OrderType, Candle


# ── Mock QuikPy module ────────────────────────────────────────────────────────

def _make_quikpy_mock():
    """Создаёт mock-объект QuikPy-инстанса."""
    qp = MagicMock()
    qp.isConnected.return_value = {'data': 1}
    qp.sendTransaction.return_value = {'result': True, 'message': 'OK'}
    qp.getCandles.return_value = {'data': []}
    qp.CreateDataSource.return_value = MagicMock()
    return qp


def _patch_quikpy(qp_instance):
    """
    Контекстный менеджер: подставляет фиктивный модуль QuikPy в sys.modules.
    """
    fake_module = types.ModuleType('QuikPy')
    fake_module.QuikPy = MagicMock(return_value=qp_instance)
    return patch.dict(sys.modules, {'QuikPy': fake_module})


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def qp():
    return _make_quikpy_mock()


@pytest.fixture
async def gateway(qp):
    """Полностью подключённый QuikGateway с замоканным QuikPy."""
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    loop = asyncio.get_event_loop()
    gw = QuikGateway(
        event_bus=bus,
        asyncio_loop=loop,
        class_code_map={'SBER': 'TQBR', 'GAZP': 'TQBR', 'Si-9.25': 'SPBFUT'},
        account='L01-00000F00',
    )
    with _patch_quikpy(qp):
        await gw.connect()
    return gw, bus


# ── _parse_datetime tests ─────────────────────────────────────────────────────

def test_parse_datetime_from_dict():
    from core.quik_gateway import QuikGateway
    data = {'year': 2024, 'month': 3, 'day': 15, 'hour': 10, 'min': 30, 'sec': 45}
    result = QuikGateway._parse_datetime(data)
    assert result == datetime(2024, 3, 15, 10, 30, 45)


def test_parse_datetime_from_string_compact():
    from core.quik_gateway import QuikGateway
    result = QuikGateway._parse_datetime('20240315103045')
    assert result == datetime(2024, 3, 15, 10, 30, 45)


def test_parse_datetime_from_string_readable():
    from core.quik_gateway import QuikGateway
    result = QuikGateway._parse_datetime('15.03.2024 10:30:45')
    assert result == datetime(2024, 3, 15, 10, 30, 45)


def test_parse_datetime_fallback_on_none():
    from core.quik_gateway import QuikGateway
    result = QuikGateway._parse_datetime(None)
    assert isinstance(result, datetime)


def test_parse_datetime_fallback_on_invalid_string():
    from core.quik_gateway import QuikGateway
    result = QuikGateway._parse_datetime('not-a-date')
    assert isinstance(result, datetime)


# ── _get_class_code tests ─────────────────────────────────────────────────────

def test_get_class_code_known_symbol():
    from core.quik_gateway import QuikGateway
    gw = QuikGateway(
        event_bus=EventBus(),
        asyncio_loop=asyncio.new_event_loop(),
        class_code_map={'SBER': 'TQBR'},
        account='TEST',
    )
    assert gw._get_class_code('SBER') == 'TQBR'


def test_get_class_code_unknown_symbol_raises():
    from core.quik_gateway import QuikGateway
    gw = QuikGateway(
        event_bus=EventBus(),
        asyncio_loop=asyncio.new_event_loop(),
        class_code_map={'SBER': 'TQBR'},
        account='TEST',
    )
    with pytest.raises(KeyError, match='GAZP'):
        gw._get_class_code('GAZP')


# ── connect / disconnect tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_sets_connected_flag(qp):
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    loop = asyncio.get_event_loop()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=loop,
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
    assert gw.connected is True


@pytest.mark.asyncio
async def test_connect_publishes_connected_event(qp):
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    loop = asyncio.get_event_loop()
    received = []

    async def catch(e):
        received.append(e)

    bus.subscribe('connection', catch)

    gw = QuikGateway(
        event_bus=bus, asyncio_loop=loop,
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
    assert any(isinstance(e, ConnectionStateEvent) and e.state == 'connected'
               for e in received)


@pytest.mark.asyncio
async def test_connect_fails_when_quik_not_connected(qp):
    from core.quik_gateway import QuikGateway
    qp.isConnected.return_value = {'data': 0}   # QUIK не подключён к брокеру
    bus = EventBus()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        with pytest.raises(ConnectionError):
            await gw.connect()


@pytest.mark.asyncio
async def test_connect_fails_without_quikpy():
    from core.quik_gateway import QuikGateway
    gw = QuikGateway(
        event_bus=EventBus(), asyncio_loop=asyncio.get_event_loop(),
        class_code_map={}, account='TEST',
    )
    # Убираем QuikPy из sys.modules чтобы симулировать отсутствие библиотеки
    with patch.dict(sys.modules, {'QuikPy': None}):
        with pytest.raises((ImportError, TypeError)):
            await gw.connect()


@pytest.mark.asyncio
async def test_disconnect_clears_connected_flag(qp):
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    loop = asyncio.get_event_loop()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=loop,
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
    await gw.disconnect()
    assert gw.connected is False


@pytest.mark.asyncio
async def test_disconnect_publishes_disconnected_event(qp):
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    loop = asyncio.get_event_loop()
    received = []

    async def catch(e): received.append(e)
    bus.subscribe('connection', catch)

    gw = QuikGateway(
        event_bus=bus, asyncio_loop=loop,
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
    await gw.disconnect()
    states = [e.state for e in received if isinstance(e, ConnectionStateEvent)]
    assert 'disconnected' in states


# ── send_order tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_market_order(qp):
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    loop = asyncio.get_event_loop()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=loop,
        class_code_map={'SBER': 'TQBR'}, account='L01-00',
    )
    with _patch_quikpy(qp):
        await gw.connect()
        order = Order(
            client_order_id='ord-1', strategy_name='s', symbol='SBER',
            side=OrderSide.BUY, order_type=OrderType.MARKET, volume=10,
        )
        gw_id = await gw.send_order(order)

    assert gw_id.startswith('quik-trans-')
    # Проверяем что sendTransaction был вызван
    qp.sendTransaction.assert_called_once()
    call_args = qp.sendTransaction.call_args[0][0]
    assert call_args['OPERATION'] == 'B'
    assert call_args['TYPE'] == 'M'
    assert call_args['SECCODE'] == 'SBER'
    assert call_args['CLASSCODE'] == 'TQBR'
    assert call_args['ACCOUNT'] == 'L01-00'
    assert call_args['QUANTITY'] == '10'


@pytest.mark.asyncio
async def test_send_limit_order(qp):
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
        order = Order(
            client_order_id='lim-1', strategy_name='s', symbol='SBER',
            side=OrderSide.SELL, order_type=OrderType.LIMIT, price=280.5, volume=5,
        )
        await gw.send_order(order)

    call_args = qp.sendTransaction.call_args[0][0]
    assert call_args['OPERATION'] == 'S'
    assert call_args['TYPE'] == 'L'
    assert call_args['PRICE'] == '280.5'


@pytest.mark.asyncio
async def test_send_order_raises_on_quik_rejection(qp):
    from core.quik_gateway import QuikGateway
    qp.sendTransaction.return_value = {'result': False, 'message': 'Недостаточно средств'}
    bus = EventBus()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
        order = Order(
            client_order_id='bad-1', strategy_name='s', symbol='SBER',
            side=OrderSide.BUY, order_type=OrderType.MARKET, volume=100,
        )
        with pytest.raises(RuntimeError, match='Недостаточно средств'):
            await gw.send_order(order)


@pytest.mark.asyncio
async def test_send_order_increments_trans_id(qp):
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
        for i in range(3):
            order = Order(
                client_order_id=f'o{i}', strategy_name='s', symbol='SBER',
                side=OrderSide.BUY, order_type=OrderType.MARKET, volume=1,
            )
            await gw.send_order(order)

    assert gw._trans_id_counter == 3


@pytest.mark.asyncio
async def test_send_order_unknown_symbol_raises(qp):
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
        order = Order(
            client_order_id='o-unk', strategy_name='s', symbol='UNKNOWN',
            side=OrderSide.BUY, order_type=OrderType.MARKET, volume=1,
        )
        with pytest.raises(KeyError, match='UNKNOWN'):
            await gw.send_order(order)


# ── cancel_order tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_order_sends_kill_transaction(qp):
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
        order = Order(
            client_order_id='kill-me', strategy_name='s', symbol='SBER',
            side=OrderSide.BUY, order_type=OrderType.MARKET, volume=1,
        )
        await gw.send_order(order)
        # Симулируем получение quik_num через _on_quik_order
        gw._client_to_quik_num['kill-me'] = 123456
        gw._quik_num_to_client[123456] = 'kill-me'
        gw._client_to_symbol['kill-me'] = ('SBER', 'TQBR')

        await gw.cancel_order('kill-me')

    # Первый вызов — NEW_ORDER, второй — KILL_ORDER
    assert qp.sendTransaction.call_count == 2
    kill_call = qp.sendTransaction.call_args_list[1][0][0]
    assert kill_call['ACTION'] == 'KILL_ORDER'
    assert kill_call['ORDER_KEY'] == '123456'


@pytest.mark.asyncio
async def test_cancel_order_no_quik_num_logs_warning(qp, caplog):
    from core.quik_gateway import QuikGateway
    import logging
    bus = EventBus()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()

    with caplog.at_level(logging.WARNING):
        await gw.cancel_order('nonexistent')
    assert 'нет QUIK-номера' in caplog.text


# ── Async callback bridge tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_fill_publishes_event(qp):
    """_handle_fill должен публиковать OrderFilledEvent."""
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    loop = asyncio.get_event_loop()
    received = []

    async def catch(e): received.append(e)
    bus.subscribe('order.filled', catch)

    gw = QuikGateway(
        event_bus=bus, asyncio_loop=loop,
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()

    # Регистрируем маппинг
    gw._quik_num_to_client[999] = 'test-ord'

    await gw._handle_fill({'order_num': 999, 'qty': 10.0, 'price': 280.5})

    assert len(received) == 1
    ev = received[0]
    assert isinstance(ev, OrderFilledEvent)
    assert ev.order_id == 'test-ord'
    assert ev.fill_volume == 10.0
    assert ev.fill_price == 280.5


@pytest.mark.asyncio
async def test_handle_fill_unknown_order_ignored(qp):
    """Fill для неизвестного ордера не должен публиковать события."""
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    received = []
    async def catch(e): received.append(e)
    bus.subscribe('order.filled', catch)

    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()

    await gw._handle_fill({'order_num': 999, 'qty': 5.0, 'price': 100.0})
    assert received == []


@pytest.mark.asyncio
async def test_handle_order_update_maps_ids(qp):
    """_handle_order_update устанавливает маппинг trans_id ↔ quik_num."""
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()

    gw._trans_id_to_client[42] = 'my-order'
    await gw._handle_order_update({'order_num': 777, 'trans_id': 42, 'flags': 0})

    assert gw._client_to_quik_num['my-order'] == 777
    assert gw._quik_num_to_client[777] == 'my-order'


@pytest.mark.asyncio
async def test_handle_order_update_cancelled_publishes_event(qp):
    """flags & 0x2 (killed) → OrderCancelledEvent."""
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    received = []
    async def catch(e): received.append(e)
    bus.subscribe('order.cancelled', catch)

    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()

    gw._quik_num_to_client[888] = 'to-cancel'
    # flags=2 (0x2) = killed
    await gw._handle_order_update({'order_num': 888, 'trans_id': 0, 'flags': 2})
    assert len(received) == 1
    assert received[0].order_id == 'to-cancel'


@pytest.mark.asyncio
async def test_handle_tick_publishes_for_subscribed_symbol(qp):
    """AllTrade для подписанного символа → TickEvent."""
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    received = []
    async def catch(e): received.append(e)
    bus.subscribe('market.tick.SBER', catch)

    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()

    gw._tick_symbols.add('SBER')
    dt_data = {'year': 2024, 'month': 1, 'day': 5, 'hour': 10, 'min': 0, 'sec': 0}
    await gw._handle_tick({'sec_code': 'SBER', 'price': 280.5, 'qty': 10.0, 'datetime': dt_data})

    assert len(received) == 1
    ev = received[0]
    assert isinstance(ev, TickEvent)
    assert ev.tick.symbol == 'SBER'
    assert ev.tick.last == 280.5


@pytest.mark.asyncio
async def test_handle_tick_ignored_for_unsubscribed_symbol(qp):
    """AllTrade для символа без подписки → не публикуется."""
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    received = []
    async def catch(e): received.append(e)
    bus.subscribe('market.tick.GAZP', catch)

    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={'GAZP': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
    # Не добавляем GAZP в _tick_symbols

    await gw._handle_tick({'sec_code': 'GAZP', 'price': 100.0, 'qty': 1.0, 'datetime': {}})
    assert received == []


# ── get_history tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_history_returns_candles(qp):
    from core.quik_gateway import QuikGateway
    qp.getCandles.return_value = {'data': [
        {'datetime': {'year': 2024, 'month': 1, 'day': 5, 'hour': 10, 'min': i, 'sec': 0},
         'open': 280.0 + i, 'high': 281.0 + i, 'low': 279.0 + i,
         'close': 280.5 + i, 'volume': 1000.0}
        for i in range(5)
    ]}
    bus = EventBus()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
        candles = await gw.get_history('SBER', '1m', 5)

    assert len(candles) == 5
    assert candles[0].symbol == 'SBER'
    assert candles[0].timeframe == '1m'
    assert candles[0].open == pytest.approx(280.0)


@pytest.mark.asyncio
async def test_get_history_unknown_timeframe_returns_empty(qp):
    from core.quik_gateway import QuikGateway
    bus = EventBus()
    gw = QuikGateway(
        event_bus=bus, asyncio_loop=asyncio.get_event_loop(),
        class_code_map={'SBER': 'TQBR'}, account='TEST',
    )
    with _patch_quikpy(qp):
        await gw.connect()
        candles = await gw.get_history('SBER', '7m', 10)

    assert candles == []


# ── Timeframe mapping tests ───────────────────────────────────────────────────

def test_timeframe_mapping_completeness():
    from core.quik_gateway import _TF_TO_INTERVAL, _INTERVAL_TO_TF
    # Все поддерживаемые ТФ должны иметь обратный маппинг
    for tf, interval in _TF_TO_INTERVAL.items():
        assert interval in _INTERVAL_TO_TF
        assert _INTERVAL_TO_TF[interval] == tf


def test_key_timeframes_correct():
    from core.quik_gateway import _TF_TO_INTERVAL
    assert _TF_TO_INTERVAL['1m']  == 1
    assert _TF_TO_INTERVAL['5m']  == 5
    assert _TF_TO_INTERVAL['15m'] == 8
    assert _TF_TO_INTERVAL['1h']  == 11
    assert _TF_TO_INTERVAL['1d']  == 14
