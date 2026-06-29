# # strategies/test_strategy.py
# from datetime import datetime
# import pandas as pd
# from core.strategy import Strategy
# from core.models import Order, OrderSide, OrderType, Tick, Candle

# class TestStrategy(Strategy):
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self._counter = 0
#         self.indicators = {}

#     async def on_tick(self, tick: Tick):
#         self._counter += 1
#         if self._counter % 10 == 0:
#             order = Order(
#                 client_order_id=f"auto-{datetime.utcnow().timestamp()}",
#                 strategy_name=self.name,
#                 symbol=self.symbol,
#                 side=OrderSide.BUY,
#                 order_type=OrderType.MARKET,
#                 volume=1
#             )
#             await self.send_order(order)

#     async def on_candle(self, candle: Candle):
#         self.add_candle_to_history(candle)
#         df = self.price_history.get(candle.timeframe)
#         if df is not None and len(df) >= 14:
#             # Устанавливаем индекс timestamp, чтобы SMA имел временной индекс
#             sma = df.set_index('timestamp')['close'].rolling(window=14).mean()
#             self.indicators['sma'] = sma

#     async def _on_fill(self, event):
#         await super()._on_fill(event)   # если определён в Strategy
#         self.update_equity_snapshot()

#     def save_state(self) -> dict:
#         state = super().save_state()
#         state['counter'] = self._counter
#         return state

#     def load_state(self, state: dict):
#         super().load_state(state)
#         self._counter = state.get('counter', 0)
#         # Пересчитываем SMA по загруженной истории
#         df = self.price_history.get('1m')
#         if df is not None and len(df) >= 14:
#             self.indicators['sma'] = df.set_index('timestamp')['close'].rolling(window=14).mean()

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