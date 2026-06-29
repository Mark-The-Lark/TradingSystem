import pytest
import asyncio
from unittest.mock import AsyncMock
from core.events import EventBus, TickEvent, CandleEvent, OrderRequestEvent, OrderFilledEvent
from core.models import Tick, Order, OrderSide, OrderType, OrderStatus
from core.commission import FixedCommission
from core.risk_manager import RiskManager
from core.order_manager import OrderManager

@pytest.fixture
def event_bus():
    return EventBus()

@pytest.fixture
def mock_gateway():
    gw = AsyncMock()
    gw.send_order.return_value = "gw-123"
    return gw

@pytest.fixture
def risk_manager():
    rm = RiskManager()
    rm.set_position_limit("test_strategy", 1000)
    return rm

@pytest.fixture
def commission_model():
    return FixedCommission(1.0)

@pytest.fixture
def order_manager(event_bus, mock_gateway, risk_manager, commission_model):
    return OrderManager(event_bus, mock_gateway, risk_manager, commission_model)

@pytest.mark.asyncio
async def test_market_order_fill(event_bus, order_manager, mock_gateway, risk_manager):
    order = Order(
        client_order_id="test-1",
        strategy_name="test_strategy",
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        volume=10
    )
    await event_bus.publish("order.request", OrderRequestEvent(order=order))
    # Ордер в истории со статусом ACTIVE, потому что fill ещё не пришёл
    history = order_manager.get_order_history()
    assert len(history) == 1
    assert history[0].status == OrderStatus.ACTIVE

    # Имитируем fill
    await event_bus.publish("order.filled", OrderFilledEvent(
        order_id=order.client_order_id,
        fill_volume=10,
        fill_price=100.0,
        commission=1.0,
        slippage=0.5
    ))
    await asyncio.sleep(0.1)
    assert history[0].status == OrderStatus.FILLED
    # assert history[0].filled_volume == 10
    # Проверяем позицию в риск-менеджере
    assert risk_manager._current_positions.get("test_strategy") == 10

@pytest.mark.asyncio
async def test_limit_order_placed(event_bus, order_manager, mock_gateway):
    order = Order(
        client_order_id="limit-1",
        strategy_name="test_strategy",
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=99.0,
        volume=5
    )
    await event_bus.publish("order.request", OrderRequestEvent(order=order))
    active = order_manager.get_active_orders()
    assert len(active) == 1
    assert active[0].status == OrderStatus.ACTIVE

@pytest.mark.asyncio
async def test_risk_manager_rejects_order(event_bus, order_manager, risk_manager):
    risk_manager.set_position_limit("test_strategy", 5)
    order = Order(
        client_order_id="risky-1",
        strategy_name="test_strategy",
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        volume=10
    )
    rejected = []
    async def catch(event):
        rejected.append(event)
    event_bus.subscribe("order.rejected", catch)

    await event_bus.publish("order.request", OrderRequestEvent(order=order))
    await asyncio.sleep(0.1)
    assert len(rejected) == 1
    assert len(order_manager.get_order_history()) == 0