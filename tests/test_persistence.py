"""Tests for state persistence: StateStore, OrderManager, CapitalManager."""
import pytest
import asyncio
import tempfile
from datetime import datetime

from core.state_store import JsonStateStore
from core.capital_manager import CapitalManager
from core.order_manager import OrderManager
from core.events import EventBus
from core.risk_manager import RiskManager
from core.commission import FixedCommission
from core.models import Order, OrderSide, OrderType, OrderStatus
from unittest.mock import AsyncMock


@pytest.fixture
def tmp_store(tmp_path):
    return JsonStateStore(base_path=str(tmp_path / "states"))


# ── JsonStateStore ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_and_load_strategy_state(tmp_store):
    state = {'positions': {'AAPL': 5.0}, 'current_equity': 99_000.0}
    await tmp_store.save_strategy_state('my_strat', state)
    loaded = await tmp_store.load_strategy_state('my_strat')
    assert loaded == state


@pytest.mark.asyncio
async def test_load_nonexistent_strategy_state_returns_none(tmp_store):
    loaded = await tmp_store.load_strategy_state('ghost')
    assert loaded is None


@pytest.mark.asyncio
async def test_delete_strategy_state_renames_file(tmp_store, tmp_path):
    await tmp_store.save_strategy_state('to_delete', {'x': 1})
    await tmp_store.delete_strategy_state('to_delete')
    # Original file should be gone, renamed to *_removed.json
    original = tmp_path / 'states' / 'to_delete.json'
    renamed = tmp_path / 'states' / 'to_delete_removed.json'
    assert not original.exists()
    assert renamed.exists()


@pytest.mark.asyncio
async def test_save_and_load_strategies_list(tmp_store):
    lst = [{'name': 's1', 'class_name': 'SMACrossoverStrategy'}]
    await tmp_store.save_strategies_list(lst)
    loaded = await tmp_store.load_strategies_list()
    assert loaded == lst


@pytest.mark.asyncio
async def test_load_empty_strategies_list(tmp_store):
    loaded = await tmp_store.load_strategies_list()
    assert loaded == []


@pytest.mark.asyncio
async def test_save_and_load_component_state(tmp_store):
    state = {'total_capital': 500_000, 'shares': {'a': 1, 'b': 3}}
    await tmp_store.save_component_state('capital_manager', state)
    loaded = await tmp_store.load_component_state('capital_manager')
    assert loaded == state


@pytest.mark.asyncio
async def test_load_nonexistent_component_state_returns_none(tmp_store):
    loaded = await tmp_store.load_component_state('nonexistent_component')
    assert loaded is None


# ── CapitalManager persistence ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_capital_manager_full_persistence_cycle(tmp_store):
    cm = CapitalManager(total_capital=300_000, max_leverage=1.5)
    cm.shares = {'alpha': 70, 'beta': 30}

    state = cm.save_state()
    await tmp_store.save_component_state('capital_manager', state)

    # Simulate new session
    cm2 = CapitalManager()
    raw = await tmp_store.load_component_state('capital_manager')
    cm2.load_state(raw)

    assert cm2.total_capital == 300_000
    assert cm2.max_leverage == 1.5
    assert cm2.get_share('alpha') == 70
    assert cm2.get_share('beta') == 30


# ── OrderManager persistence ──────────────────────────────────────────────────

@pytest.fixture
def order_manager():
    gw = AsyncMock()
    gw.send_order.return_value = 'gw-1'
    return OrderManager(EventBus(), gw, RiskManager(), FixedCommission(0.0))


@pytest.mark.asyncio
async def test_order_manager_history_persists(tmp_store, order_manager):
    # Manually add a filled order to history
    filled = Order(
        client_order_id='hist-1',
        strategy_name='s1',
        symbol='SBER',
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        volume=100,
        status=OrderStatus.FILLED,
        filled_volume=100,
        average_fill_price=280.5,
    )
    order_manager._order_history.append(filled)

    state = order_manager.save_state()
    await tmp_store.save_component_state('order_manager', state)

    # New session
    om2 = OrderManager(EventBus(), AsyncMock(), RiskManager(), FixedCommission(0.0))
    raw = await tmp_store.load_component_state('order_manager')
    om2.load_state(raw)

    assert len(om2._order_history) == 1
    assert om2._order_history[0].client_order_id == 'hist-1'
    assert om2._order_history[0].symbol == 'SBER'


@pytest.mark.asyncio
async def test_active_orders_at_shutdown_become_cancelled(tmp_store, order_manager):
    """Активные ордера при сохранении должны быть помечены как CANCELLED при восстановлении."""
    active = Order(
        client_order_id='active-1',
        strategy_name='s1',
        symbol='GAZP',
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        price=200.0,
        volume=50,
        status=OrderStatus.ACTIVE,
    )
    order_manager._active_orders['active-1'] = active

    state = order_manager.save_state()
    await tmp_store.save_component_state('order_manager', state)

    om2 = OrderManager(EventBus(), AsyncMock(), RiskManager(), FixedCommission(0.0))
    raw = await tmp_store.load_component_state('order_manager')
    om2.load_state(raw)

    restored = [o for o in om2._order_history if o.client_order_id == 'active-1']
    assert len(restored) == 1
    assert restored[0].status == OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_empty_order_manager_state(tmp_store, order_manager):
    state = order_manager.save_state()
    assert state['active_orders'] == []
    assert state['order_history'] == []

    await tmp_store.save_component_state('order_manager', state)
    raw = await tmp_store.load_component_state('order_manager')

    om2 = OrderManager(EventBus(), AsyncMock(), RiskManager(), FixedCommission(0.0))
    om2.load_state(raw)
    assert om2._order_history == []
