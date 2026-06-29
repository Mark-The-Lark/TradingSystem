# tests/test_strategy_manager.py
import pytest
import asyncio
from datetime import datetime
from core.events import EventBus, TickEvent, CandleEvent, OrderRequestEvent, OrderFilledEvent
from core.models import Order, OrderSide, OrderType, Tick, OrderStatus
from core.simulation_gateway import SimulationGateway
from core.time_provider import SimulatedTimeProvider
from core.commission import FixedCommission
from core.risk_manager import RiskManager
from core.order_manager import OrderManager
from core.strategy import Strategy
from core.strategy_manager import StrategyManager
from core.state_store import JsonStateStore

class MockStrategy(Strategy):
    async def on_tick(self, tick: Tick):
        order = Order(
            client_order_id=f"test-{datetime.utcnow().timestamp()}",
            strategy_name=self.name,
            symbol=self.symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            volume=1
        )
        await self.send_order(order)

    async def on_candle(self, candle):
        pass

    def save_state(self) -> dict:
        return {'position': self.position}

    def load_state(self, state: dict):
        self.position = state.get('position', 0.0)

@pytest.fixture
def event_bus():
    return EventBus()

@pytest.fixture
def time_provider():
    return SimulatedTimeProvider(datetime(2023,1,1))

@pytest.fixture
def gateway(event_bus, time_provider):
    return SimulationGateway(event_bus, time_provider, base_prices={"TEST": 100.0})

@pytest.fixture
def risk_manager():
    rm = RiskManager()
    rm.set_position_limit("test_strategy", 1000)
    return rm

@pytest.fixture
def commission_model():
    return FixedCommission(1.0)

@pytest.fixture
def order_manager(event_bus, gateway, risk_manager, commission_model):
    return OrderManager(event_bus, gateway, risk_manager, commission_model)

@pytest.fixture
def state_store(tmp_path):
    return JsonStateStore(base_path=str(tmp_path / "states"))

@pytest.fixture
def strategy_manager(event_bus, gateway, order_manager, state_store):
    return StrategyManager(event_bus, gateway, order_manager, state_store)

# tests/test_strategy_manager.py
# tests/test_strategy_manager.py
@pytest.mark.asyncio
async def test_strategy_receives_tick_and_sends_order(event_bus, order_manager, strategy_manager):
    strategy = MockStrategy("test_strategy", "TEST", event_bus, order_manager, mode='AUTO')
    await strategy_manager.add_strategy(strategy)
    await strategy_manager.start_strategy("test_strategy")

    # Отправляем тик вручную
    tick = Tick(
        timestamp=datetime(2023,1,1,12,0,0),
        symbol="TEST",
        bid=99.0,
        ask=101.0,
        last=100.0,
        volume=10
    )
    await event_bus.publish("market.tick.TEST", TickEvent(tick=tick))
    await asyncio.sleep(0.1)

    # Ордер должен появиться в истории со статусом ACTIVE
    history = order_manager.get_order_history("test_strategy")
    assert len(history) == 1, "Order should be created from tick"
    assert history[0].status == OrderStatus.ACTIVE

    # Имитируем исполнение
    await event_bus.publish("order.filled", OrderFilledEvent(
        order_id=history[0].client_order_id,
        fill_volume=1,
        fill_price=100.0,
        commission=1.0,
        slippage=0.0
    ))
    await asyncio.sleep(0.1)

    # Теперь ордер должен стать FILLED, а позиция стратегии обновиться
    assert history[0].status == OrderStatus.FILLED
    assert strategy.position == 1