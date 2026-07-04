from core.strategy import Strategy
from core.models import Order, OrderSide, OrderType, Tick, Candle
from datetime import datetime

class TestStrategy(Strategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.subscriptions:
            self.subscriptions = [('AAPL', '1m')]
        self._counter = 0

    async def on_tick(self, tick: Tick):
        pass

    async def on_candle(self, candle: Candle):
        self.add_candle_to_history(candle)
        self._counter += 1
        if self._counter % 10 == 0:
            order = Order(
                client_order_id=f"test-{candle.timestamp.timestamp()}",
                strategy_name=self.name,
                symbol=candle.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                volume=1
            )
            await self.send_order(order)
