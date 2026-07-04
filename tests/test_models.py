import pytest
from datetime import datetime
from core.models import Order, OrderSide, OrderType, OrderStatus, Tick, Candle

def test_order_defaults():
    order = Order(
        client_order_id="test-1",
        strategy_name="test",
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        volume=10
    )
    assert order.status == OrderStatus.PENDING
    assert order.filled_volume == 0.0
    assert order.price is None

def test_order_validation():
    with pytest.raises(ValueError):
        Order(client_order_id="x", strategy_name="s", symbol="A", side=OrderSide.BUY, order_type=OrderType.MARKET, volume=-1)

def test_tick_creation():
    tick = Tick(timestamp=datetime(2023,1,1), symbol="EURUSD", bid=1.05, ask=1.06, last=1.055, volume=1000)
    assert tick.bid == 1.05
